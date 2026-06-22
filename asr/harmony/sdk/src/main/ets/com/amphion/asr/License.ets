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
  bundleName?: string;
  expiresAt?: string;
}

export class HarmonyLicenseVerifier {
  /**
   * 纯血鸿蒙 license 绑定字段预留为 bundleName + signingCertDigest。
   * 当前实现只解析占位字段，真正签名验签由交付期注入公钥后补齐。
   */
  static verify(licenseText: string | undefined, bundleName: string | undefined): AmphionLicenseStatus {
    const status = new AmphionLicenseStatus();
    status.bundleName = bundleName;
    if (licenseText === undefined || licenseText.trim().length === 0) {
      status.state = AmphionLicenseState.MISSING;
      status.message = 'license missing';
      return status;
    }
    if (bundleName !== undefined && licenseText.indexOf(bundleName) < 0) {
      status.state = AmphionLicenseState.WARN_ONLY;
      status.message = 'license present but bundleName is not embedded in placeholder license text';
      return status;
    }
    status.state = AmphionLicenseState.VALID;
    status.message = 'license placeholder accepted';
    return status;
  }
}
