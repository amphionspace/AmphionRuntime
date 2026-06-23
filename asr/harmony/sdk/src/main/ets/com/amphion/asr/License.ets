export enum AmphionLicenseState {
  VALID = 'VALID',
  MISSING = 'MISSING',
  INVALID = 'INVALID',
  EXPIRED = 'EXPIRED',
  WARN_ONLY = 'WARN_ONLY'
}

export class AmphionLicenseStatus {
  state: AmphionLicenseState = AmphionLicenseState.MISSING;
  message: string = 'license not checked';
  valid: boolean = false;
  licenseId: string = '';
  customer: string = '';
  bundleName?: string;
  signingCertDigest?: string;
  deviceIdHashAlg: string = '';
  deviceIdSaltId: string = '';
  authorizedDeviceCount: number = 0;
  maintenanceUntil?: string;
  expiresAt?: string;
  features: string[] = [];
}

export class HarmonyLicenseVerifier {
  /**
   * 纯血鸿蒙 license 绑定字段预留为 bundleName + signingCertDigest。
   * 当前实现只解析占位字段，真正签名验签由交付期注入公钥后补齐。
   */
  static verify(
    licenseText: string | undefined,
    bundleName: string | undefined,
    signingCertDigest: string | undefined,
    deviceSerial: string | undefined
  ): AmphionLicenseStatus {
    const status = new AmphionLicenseStatus();
    status.bundleName = bundleName;
    if (licenseText === undefined || licenseText.trim().length === 0) {
      status.state = AmphionLicenseState.MISSING;
      status.message = 'license missing';
      return status;
    }
    const claims = HarmonyLicenseVerifier.parseClaims(licenseText);
    if (claims === undefined) {
      status.state = AmphionLicenseState.INVALID;
      status.message = 'license payload missing or unsupported';
      return status;
    }
    status.licenseId = HarmonyLicenseVerifier.stringValue(claims, 'licenseId');
    status.customer = HarmonyLicenseVerifier.stringValue(claims, 'customer');
    status.bundleName = HarmonyLicenseVerifier.stringValue(claims, 'bundleName') || bundleName;
    status.signingCertDigest = HarmonyLicenseVerifier.stringValue(claims, 'signingCertDigest');
    status.deviceIdHashAlg = HarmonyLicenseVerifier.stringValue(claims, 'deviceIdHashAlg');
    status.deviceIdSaltId = HarmonyLicenseVerifier.stringValue(claims, 'deviceIdSaltId');
    status.maintenanceUntil = HarmonyLicenseVerifier.stringValue(claims, 'maintenanceUntil');
    status.expiresAt = HarmonyLicenseVerifier.stringValue(claims, 'expiresAt');
    status.features = HarmonyLicenseVerifier.stringArray(claims, 'features');
    status.authorizedDeviceCount = HarmonyLicenseVerifier.stringArray(claims, 'authorizedDeviceHashes').length;

    const boundBundle = HarmonyLicenseVerifier.stringValue(claims, 'bundleName');
    if (bundleName !== undefined && boundBundle.length > 0 && boundBundle !== bundleName) {
      status.state = AmphionLicenseState.WARN_ONLY;
      status.message = `license bundleName=${boundBundle} host=${bundleName}`;
      return status;
    }
    const boundCert = HarmonyLicenseVerifier.normalizeHex(HarmonyLicenseVerifier.stringValue(claims, 'signingCertDigest'));
    const hostCert = HarmonyLicenseVerifier.normalizeHex(signingCertDigest ?? '');
    if (boundCert.length > 0 && hostCert.length > 0 && boundCert !== hostCert) {
      status.state = AmphionLicenseState.INVALID;
      status.message = 'license signingCertDigest mismatch';
      return status;
    }
    const normalizedFeatures = status.features.map((feature: string): string => feature.trim().toUpperCase());
    if (!normalizedFeatures.includes('ASR')) {
      status.state = AmphionLicenseState.INVALID;
      status.message = 'license feature ASR missing';
      return status;
    }
    if (status.authorizedDeviceCount > 0 && (deviceSerial === undefined || deviceSerial.trim().length === 0)) {
      status.state = AmphionLicenseState.INVALID;
      status.message = 'device SN unavailable';
      return status;
    }
    status.state = AmphionLicenseState.VALID;
    status.valid = true;
    status.message = 'license placeholder accepted; signature verification is injected in delivery build';
    return status;
  }

  private static parseClaims(licenseText: string): Record<string, Object> | undefined {
    try {
      const parsed = JSON.parse(licenseText) as Record<string, Object>;
      const payload = parsed['payload'];
      if (typeof payload === 'object' && payload !== null) {
        return payload as Record<string, Object>;
      }
      if (parsed['payload_b64'] !== undefined) {
        return parsed;
      }
      return parsed;
    } catch (_) {
      return undefined;
    }
  }

  private static stringValue(claims: Record<string, Object>, key: string): string {
    const value = claims[key];
    return typeof value === 'string' ? value : '';
  }

  private static stringArray(claims: Record<string, Object>, key: string): string[] {
    const value = claims[key];
    return Array.isArray(value) ? value.filter((item: Object): boolean => typeof item === 'string') as string[] : [];
  }

  private static normalizeHex(value: string): string {
    return value.replace(/[: ]/g, '').toUpperCase();
  }
}
