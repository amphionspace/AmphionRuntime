import { AsrErrorCode } from './Types';
import { cryptoFramework } from '@kit.CryptoArchitectureKit';
import { util } from '@kit.ArkTS';

// Offline-license public key (X.509 SubjectPublicKeyInfo DER, base64). Empty = development/unarmed build.
// PRODUCTION key — same keypair as the Android SDK (asr/android/gradle.properties AMPHION_LICENSE_PUBLIC_KEY),
// so the shared amphion-license.lic (ASR/TTS, SN whitelist) verifies identically on Harmony and Android.
const LICENSE_PUBLIC_KEY_B64: string = 'MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEc5BCEdeeELgXa3tTXeM6i49o+2NslcH9FrgpAMn3o61kFEv1Xlv7fD/kYA5NnXi2eLM8l+w4wEUvPgsbiM9tCQ==';

export enum AmphionLicenseState {
  NOT_INITIALIZED = 'NOT_INITIALIZED',
  DEV_UNLICENSED = 'DEV_UNLICENSED',
  LICENSED = 'LICENSED',
  INVALID = 'INVALID'
}

export class AmphionLicenseStatus {
  state: AmphionLicenseState = AmphionLicenseState.NOT_INITIALIZED;
  message: string = 'license not checked';
  valid: boolean = false;
  errorCode: number = AsrErrorCode.SDK_NOT_INITIALIZED;
  licenseId: string = '';
  customer: string = '';
  applicationId: string = '';
  bundleName?: string;
  signingCertDigest?: string;
  deviceIdHashAlg: string = '';
  deviceIdSaltId: string = '';
  authorizedDeviceCount: number = 0;
  issuedAt?: string;
  maintenanceUntil?: string;
  expiresAt?: string;
  installTier: string = '';
  features: string[] = [];

  hasFeature(feature: string): boolean {
    return this.features.includes(feature);
  }

  static notInitialized(): AmphionLicenseStatus {
    return new AmphionLicenseStatus();
  }
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
    deviceSerial: string | undefined,
    publicKeyB64: string = '',
    sdkMajor: number = 0,
    sdkReleaseDate: string = ''
  ): AmphionLicenseStatus {
    const status = new AmphionLicenseStatus();
    status.bundleName = bundleName;
    if (publicKeyB64.trim().length === 0 && (licenseText === undefined || licenseText.trim().length === 0)) {
      status.state = AmphionLicenseState.DEV_UNLICENSED;
      status.valid = true;
      status.errorCode = AsrErrorCode.OK;
      status.message = 'license public key is not injected; development build is unlicensed';
      return status;
    }
    if (licenseText === undefined || licenseText.trim().length === 0) {
      status.state = AmphionLicenseState.INVALID;
      status.errorCode = AsrErrorCode.LICENSE_MISSING;
      status.message = 'license missing';
      return status;
    }
    const claims = HarmonyLicenseVerifier.parseClaims(licenseText);
    if (claims === undefined) {
      status.state = AmphionLicenseState.INVALID;
      status.errorCode = AsrErrorCode.LICENSE_MALFORMED;
      status.message = 'license payload missing or unsupported';
      return status;
    }
    status.licenseId = HarmonyLicenseVerifier.stringValue(claims, 'licenseId');
    status.customer = HarmonyLicenseVerifier.stringValue(claims, 'customer');
    status.applicationId = HarmonyLicenseVerifier.stringValue(claims, 'applicationId');
    status.bundleName = HarmonyLicenseVerifier.stringValue(claims, 'bundleName') || bundleName;
    status.signingCertDigest = HarmonyLicenseVerifier.stringValue(claims, 'signingCertDigest');
    status.deviceIdHashAlg = HarmonyLicenseVerifier.stringValue(claims, 'deviceIdHashAlg');
    status.deviceIdSaltId = HarmonyLicenseVerifier.stringValue(claims, 'deviceIdSaltId');
    status.issuedAt = HarmonyLicenseVerifier.stringValue(claims, 'issuedAt');
    status.maintenanceUntil = HarmonyLicenseVerifier.stringValue(claims, 'maintenanceUntil');
    status.expiresAt = HarmonyLicenseVerifier.stringValue(claims, 'expiresAt');
    status.installTier = HarmonyLicenseVerifier.stringValue(claims, 'installTier');
    status.features = HarmonyLicenseVerifier.stringArray(claims, 'features');
    status.authorizedDeviceCount = HarmonyLicenseVerifier.stringArray(claims, 'authorizedDeviceHashes').length;

    const boundBundle = HarmonyLicenseVerifier.stringValue(claims, 'bundleName');
    if (bundleName !== undefined && boundBundle.length > 0 && boundBundle !== bundleName) {
      status.state = AmphionLicenseState.INVALID;
      status.errorCode = AsrErrorCode.LICENSE_APP_MISMATCH;
      status.message = `license bundleName=${boundBundle} host=${bundleName}`;
      return status;
    }
    const boundCert = HarmonyLicenseVerifier.normalizeHex(HarmonyLicenseVerifier.stringValue(claims, 'signingCertDigest'));
    const hostCert = HarmonyLicenseVerifier.normalizeHex(signingCertDigest ?? '');
    if (boundCert.length > 0 && hostCert.length > 0 && boundCert !== hostCert) {
      status.state = AmphionLicenseState.INVALID;
      status.errorCode = AsrErrorCode.LICENSE_CERT_MISMATCH;
      status.message = 'license signingCertDigest mismatch';
      return status;
    }
    const normalizedFeatures = status.features.map((feature: string): string => feature.trim().toUpperCase());
    if (!normalizedFeatures.includes('ASR')) {
      status.state = AmphionLicenseState.INVALID;
      status.errorCode = AsrErrorCode.LICENSE_FEATURE_MISSING;
      status.message = 'license feature ASR missing';
      return status;
    }
    if (status.authorizedDeviceCount > 0 && (deviceSerial === undefined || deviceSerial.trim().length === 0)) {
      status.state = AmphionLicenseState.INVALID;
      status.errorCode = AsrErrorCode.LICENSE_DEVICE_MISMATCH;
      status.message = 'device SN unavailable';
      return status;
    }
    const claimSdkMajor = HarmonyLicenseVerifier.numberValue(claims, 'sdkMajor');
    if (claimSdkMajor > 0 && sdkMajor > 0 && claimSdkMajor !== sdkMajor) {
      status.state = AmphionLicenseState.INVALID;
      status.errorCode = AsrErrorCode.LICENSE_SDK_MAJOR_MISMATCH;
      status.message = `license sdkMajor=${claimSdkMajor} runtime=${sdkMajor}`;
      return status;
    }
    const maintenanceUntil = status.maintenanceUntil ?? '';
    if (sdkReleaseDate.length > 0 && maintenanceUntil.length > 0 && sdkReleaseDate > maintenanceUntil) {
      status.state = AmphionLicenseState.INVALID;
      status.errorCode = AsrErrorCode.LICENSE_MAINTENANCE_EXPIRED;
      status.message = `license maintenanceUntil=${maintenanceUntil} runtimeRelease=${sdkReleaseDate}`;
      return status;
    }
    const expiresAt = status.expiresAt ?? '';
    if (expiresAt.length > 0 && HarmonyLicenseVerifier.today() > expiresAt) {
      status.state = AmphionLicenseState.INVALID;
      status.errorCode = AsrErrorCode.LICENSE_EXPIRED;
      status.message = `license expired at ${expiresAt}`;
      return status;
    }
    status.state = publicKeyB64.trim().length === 0
      ? AmphionLicenseState.DEV_UNLICENSED
      : AmphionLicenseState.LICENSED;
    status.valid = true;
    status.errorCode = AsrErrorCode.OK;
    status.message = publicKeyB64.trim().length === 0
      ? 'license parsed without signature verification; public key is not injected'
      : 'license accepted; signature verification is expected in delivery build';
    return status;
  }

  /** Injected offline-license public key (empty on a development/unarmed build). */
  static publicKey(): string {
    return LICENSE_PUBLIC_KEY_B64;
  }

  /**
   * Real ECDSA P-256 (ECC256|SHA256) signature verification over the raw license payload bytes.
   * Mirrors tools/license/issue_license.py (SHA256withECDSA over the decoded UTF-8 payload) and the TTS
   * Harmony verifier. Returns true on an unarmed build (empty public key) so development keeps working;
   * otherwise a forged or tampered license (e.g. an edited expiresAt) fails signature verification here.
   */
  static async verifySignature(licenseText: string | undefined, publicKeyB64: string): Promise<boolean> {
    if (publicKeyB64.trim().length === 0) {
      return true;
    }
    if (licenseText === undefined || licenseText.trim().length === 0) {
      return false;
    }
    let payloadBytes: Uint8Array;
    let sigBytes: Uint8Array;
    try {
      const envelope = JSON.parse(licenseText) as Record<string, Object>;
      const payloadB64 = envelope['payload_b64'];
      const sigB64 = envelope['sig_b64'];
      if (typeof payloadB64 !== 'string' || typeof sigB64 !== 'string') {
        return false;
      }
      payloadBytes = HarmonyLicenseVerifier.base64ToBytes(payloadB64 as string);
      sigBytes = HarmonyLicenseVerifier.base64ToBytes(sigB64 as string);
    } catch (_e) {
      return false;
    }
    try {
      const keyGenerator = cryptoFramework.createAsyKeyGenerator('ECC256');
      const keyPair = await keyGenerator.convertKey({ data: HarmonyLicenseVerifier.base64ToBytes(publicKeyB64) }, null);
      const verifier = cryptoFramework.createVerify('ECC256|SHA256');
      await verifier.init(keyPair.pubKey);
      await verifier.update({ data: payloadBytes });
      return await verifier.verify(null, { data: sigBytes });
    } catch (_e) {
      return false;
    }
  }

  private static base64ToBytes(b64: string): Uint8Array {
    return new util.Base64Helper().decodeSync(b64.replace(/[\r\n\t ]/g, ''));
  }

  /**
   * SN 白名单校验（对齐 Android LicenseVerifier + DeviceLicenseFingerprint）。
   * 指纹 = SHA-256( 大写去空(SN) + deviceIdSaltId )，大写 hex，对 authorizedDeviceHashes 取成员判定。
   * 返回 true = 未绑 SN 或 SN 在白名单内；false = 需要 SN 但缺失 / 不在白名单。
   */
  static async deviceHashOk(licenseText: string | undefined, deviceSerial: string | undefined): Promise<boolean> {
    if (licenseText === undefined || licenseText.trim().length === 0) {
      return true;
    }
    const claims = HarmonyLicenseVerifier.parseClaims(licenseText);
    if (claims === undefined) {
      return true;
    }
    const hashes = HarmonyLicenseVerifier.stringArray(claims, 'authorizedDeviceHashes')
      .map((h: string): string => HarmonyLicenseVerifier.normalizeHex(h));
    if (hashes.length === 0) {
      return true;
    }
    if (deviceSerial === undefined || deviceSerial.trim().length === 0) {
      return false;
    }
    const saltId = HarmonyLicenseVerifier.stringValue(claims, 'deviceIdSaltId');
    const have = await HarmonyLicenseVerifier.deviceFingerprint(deviceSerial, saltId);
    return hashes.includes(have);
  }

  static async deviceFingerprint(deviceSerial: string, saltId: string): Promise<string> {
    const raw = deviceSerial.trim().toUpperCase() + saltId;
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) {
      bytes[i] = raw.charCodeAt(i) & 0xff;
    }
    const md = cryptoFramework.createMd('SHA256');
    await md.update({ data: bytes });
    const digest = await md.digest();
    return HarmonyLicenseVerifier.bytesToHexUpper(digest.data);
  }

  private static bytesToHexUpper(bytes: Uint8Array): string {
    let out = '';
    for (let i = 0; i < bytes.length; i++) {
      const h = bytes[i].toString(16).toUpperCase();
      out += h.length === 1 ? `0${h}` : h;
    }
    return out;
  }

  private static parseClaims(licenseText: string): Record<string, Object> | undefined {
    try {
      const parsed = JSON.parse(licenseText) as Record<string, Object>;
      const payload = parsed['payload'];
      if (typeof payload === 'object' && payload !== null) {
        return payload as Record<string, Object>;
      }
      const payloadB64 = parsed['payload_b64'];
      if (typeof payloadB64 === 'string') {
        const payloadJson = HarmonyLicenseVerifier.decodeBase64Utf8(payloadB64);
        return JSON.parse(payloadJson) as Record<string, Object>;
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

  private static numberValue(claims: Record<string, Object>, key: string): number {
    const value = claims[key];
    if (typeof value === 'number') return value;
    if (typeof value === 'string') {
      const parsed = Number(value);
      return Number.isNaN(parsed) ? 0 : parsed;
    }
    return 0;
  }

  private static normalizeHex(value: string): string {
    return value.replace(/[: ]/g, '').toUpperCase();
  }

  private static today(): string {
    return new Date().toISOString().substring(0, 10);
  }

  private static decodeBase64Utf8(value: string): string {
    const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
    const clean = value.replace(/[\r\n\t ]/g, '');
    const bytes: number[] = [];
    for (let i = 0; i < clean.length; i += 4) {
      const c0 = alphabet.indexOf(clean.charAt(i));
      const c1 = alphabet.indexOf(clean.charAt(i + 1));
      const c2 = clean.charAt(i + 2) === '=' ? -1 : alphabet.indexOf(clean.charAt(i + 2));
      const c3 = clean.charAt(i + 3) === '=' ? -1 : alphabet.indexOf(clean.charAt(i + 3));
      if (c0 < 0 || c1 < 0 || (c2 < 0 && clean.charAt(i + 2) !== '=') || (c3 < 0 && clean.charAt(i + 3) !== '=')) {
        throw new Error('invalid base64 payload');
      }
      const n = (c0 << 18) | (c1 << 12) | ((c2 < 0 ? 0 : c2) << 6) | (c3 < 0 ? 0 : c3);
      bytes.push((n >> 16) & 0xff);
      if (c2 >= 0) bytes.push((n >> 8) & 0xff);
      if (c3 >= 0) bytes.push(n & 0xff);
    }
    return HarmonyLicenseVerifier.decodeUtf8(bytes);
  }

  private static decodeUtf8(bytes: number[]): string {
    let out = '';
    for (let i = 0; i < bytes.length;) {
      const b0 = bytes[i++];
      if (b0 < 0x80) {
        out += String.fromCharCode(b0);
      } else if (b0 < 0xe0) {
        const b1 = bytes[i++] & 0x3f;
        out += String.fromCharCode(((b0 & 0x1f) << 6) | b1);
      } else if (b0 < 0xf0) {
        const b1 = bytes[i++] & 0x3f;
        const b2 = bytes[i++] & 0x3f;
        out += String.fromCharCode(((b0 & 0x0f) << 12) | (b1 << 6) | b2);
      } else {
        const b1 = bytes[i++] & 0x3f;
        const b2 = bytes[i++] & 0x3f;
        const b3 = bytes[i++] & 0x3f;
        const codePoint = ((b0 & 0x07) << 18) | (b1 << 12) | (b2 << 6) | b3;
        const high = ((codePoint - 0x10000) >> 10) + 0xd800;
        const low = ((codePoint - 0x10000) & 0x3ff) + 0xdc00;
        out += String.fromCharCode(high, low);
      }
    }
    return out;
  }
}
