import { AsrErrorCode } from './Types';
import { cryptoFramework } from '@kit.CryptoArchitectureKit';
import { util } from '@kit.ArkTS';
import { hilog } from '@kit.PerformanceAnalysisKit';

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
   * License 字段与 Android 对齐；applicationId / bundleName 仅作记录，正式授权边界由设备 SN 白名单决定。
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

    const boundCert = HarmonyLicenseVerifier.normalizeHex(HarmonyLicenseVerifier.stringValue(claims, 'signingCertDigest'));
    const hostCert = HarmonyLicenseVerifier.normalizeHex(signingCertDigest ?? '');
    if (boundCert.length > 0 && hostCert.length === 0) {
      status.state = AmphionLicenseState.INVALID;
      status.errorCode = AsrErrorCode.LICENSE_CERT_MISMATCH;
      status.message = 'host signing certificate fingerprint unavailable';
      return status;
    }
    if (boundCert.length > 0 && boundCert !== hostCert) {
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
    if (sdkMajor > 0 && claimSdkMajor !== sdkMajor) {
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

  /**
   * 单次解析快速路径(核心鉴权用)。把 envelope + payload 只解码/解析一遍,复用给「结构校验 + ECDSA 验签 +
   * SN 白名单」三段——消除旧 evaluateLicense 里 verify()/verifySignature()/deviceHashOk() 各自重复解析同一份
   * 4MB payload(原先:base64 解码 3 次、其中 2 次走按字节手搓的 decodeBase64Utf8/decodeUtf8 逐字符拼接、
   * payload JSON 解析 2 次、6万条设备数组重建 3 次)。本方法:native base64 解码 1 次、native UTF-8 解码 1 次、
   * JSON.parse 1 次、白名单单遍扫描。行为、错误码、门禁顺序与旧三段式严格等价(fail-closed)。
   * 旧 verify()/verifySignature()/deviceHashOk() 保留供交付 wrapper 前置门与单测,未改。
   */
  static async evaluate(
    licenseText: string | undefined,
    bundleName: string | undefined,
    signingCertDigest: string | undefined,
    deviceSerial: string | undefined,
    publicKeyB64: string = '',
    sdkMajor: number = 0,
    sdkReleaseDate: string = ''
  ): Promise<AmphionLicenseStatus> {
    const status = new AmphionLicenseStatus();
    status.bundleName = bundleName;
    const armed = publicKeyB64.trim().length > 0;
    const hasLicense = licenseText !== undefined && licenseText.trim().length > 0;

    // 与 verify() 一致:未武装且无 license = 开发态放行;有公钥但无 license = LICENSE_MISSING。
    if (!armed && !hasLicense) {
      status.state = AmphionLicenseState.DEV_UNLICENSED;
      status.valid = true;
      status.errorCode = AsrErrorCode.OK;
      status.message = 'license public key is not injected; development build is unlicensed';
      return status;
    }
    if (!hasLicense) {
      return HarmonyLicenseVerifier.fail(status, AsrErrorCode.LICENSE_MISSING, 'license missing');
    }

    // ---- 单次解析:envelope 一次 → native base64 解 payload 一次(bytes 同时喂 ECDSA)→ native UTF-8 → claims 一次 ----
    let payloadBytes: Uint8Array | undefined;
    let sigBytes: Uint8Array | undefined;
    let claims: Record<string, Object> | undefined;
    try {
      const envelope = JSON.parse(licenseText as string) as Record<string, Object>;
      if (envelope['payload'] !== undefined) {
        // 安全:claims 只取自签名覆盖的 payload_b64;绝不接受未签名的顶层 payload(否则可附伪造 claims 绕过绑定)。
        hilog.warn(0x0000, 'AmphionLicense', '%{public}s',
          'SECURITY: ignoring UNSIGNED top-level "payload"; claims are taken only from signed payload_b64');
      }
      const payloadB64 = envelope['payload_b64'];
      const sigB64 = envelope['sig_b64'];
      if (typeof payloadB64 === 'string' && typeof sigB64 === 'string') {
        payloadBytes = HarmonyLicenseVerifier.base64ToBytes(payloadB64 as string);
        sigBytes = HarmonyLicenseVerifier.base64ToBytes(sigB64 as string);
        claims = JSON.parse(HarmonyLicenseVerifier.bytesToUtf8(payloadBytes)) as Record<string, Object>;
      }
    } catch (_e) {
      claims = undefined;
    }
    if (claims === undefined || payloadBytes === undefined || sigBytes === undefined) {
      return HarmonyLicenseVerifier.fail(status, AsrErrorCode.LICENSE_MALFORMED, 'license payload missing or unsupported');
    }

    // ---- 字段填充(与 verify() 逐字段一致) ----
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
    const deviceHashes = HarmonyLicenseVerifier.stringArray(claims, 'authorizedDeviceHashes');
    status.authorizedDeviceCount = deviceHashes.length;

    // ---- 结构校验(顺序/错误码/消息与 verify() 逐条对齐) ----
    const boundCert = HarmonyLicenseVerifier.normalizeHex(status.signingCertDigest ?? '');
    const hostCert = HarmonyLicenseVerifier.normalizeHex(signingCertDigest ?? '');
    if (boundCert.length > 0 && hostCert.length === 0) {
      return HarmonyLicenseVerifier.fail(status, AsrErrorCode.LICENSE_CERT_MISMATCH,
        'host signing certificate fingerprint unavailable');
    }
    if (boundCert.length > 0 && boundCert !== hostCert) {
      return HarmonyLicenseVerifier.fail(status, AsrErrorCode.LICENSE_CERT_MISMATCH, 'license signingCertDigest mismatch');
    }
    const normalizedFeatures = status.features.map((feature: string): string => feature.trim().toUpperCase());
    if (!normalizedFeatures.includes('ASR')) {
      return HarmonyLicenseVerifier.fail(status, AsrErrorCode.LICENSE_FEATURE_MISSING, 'license feature ASR missing');
    }
    if (status.authorizedDeviceCount > 0 && (deviceSerial === undefined || deviceSerial.trim().length === 0)) {
      return HarmonyLicenseVerifier.fail(status, AsrErrorCode.LICENSE_DEVICE_MISMATCH, 'device SN unavailable');
    }
    const claimSdkMajor = HarmonyLicenseVerifier.numberValue(claims, 'sdkMajor');
    if (sdkMajor > 0 && claimSdkMajor !== sdkMajor) {
      return HarmonyLicenseVerifier.fail(status, AsrErrorCode.LICENSE_SDK_MAJOR_MISMATCH,
        `license sdkMajor=${claimSdkMajor} runtime=${sdkMajor}`);
    }
    const maintenanceUntil = status.maintenanceUntil ?? '';
    if (sdkReleaseDate.length > 0 && maintenanceUntil.length > 0 && sdkReleaseDate > maintenanceUntil) {
      return HarmonyLicenseVerifier.fail(status, AsrErrorCode.LICENSE_MAINTENANCE_EXPIRED,
        `license maintenanceUntil=${maintenanceUntil} runtimeRelease=${sdkReleaseDate}`);
    }
    const expiresAt = status.expiresAt ?? '';
    if (expiresAt.length > 0 && HarmonyLicenseVerifier.today() > expiresAt) {
      return HarmonyLicenseVerifier.fail(status, AsrErrorCode.LICENSE_EXPIRED, `license expired at ${expiresAt}`);
    }

    // ---- armed 且带 license:强制 ECDSA(复用已解码的 payloadBytes)+ SN 白名单单遍扫描 ----
    // 与旧 evaluateLicense 第二段(verifySignature → deviceHashOk)语义一致;未武装(公钥空)时跳过,同旧逻辑。
    if (armed) {
      const signatureOk = await HarmonyLicenseVerifier.verifyBytes(payloadBytes, sigBytes, publicKeyB64);
      if (!signatureOk) {
        return HarmonyLicenseVerifier.fail(status, AsrErrorCode.LICENSE_SIGNATURE_INVALID, 'license signature verification failed');
      }
      if (deviceHashes.length > 0) {
        if (deviceSerial === undefined || deviceSerial.trim().length === 0) {
          return HarmonyLicenseVerifier.fail(status, AsrErrorCode.LICENSE_DEVICE_MISMATCH, 'device SN not in license whitelist');
        }
        const saltId = HarmonyLicenseVerifier.stringValue(claims, 'deviceIdSaltId');
        const have = await HarmonyLicenseVerifier.deviceFingerprint(deviceSerial, saltId);
        let found = false;
        // 单遍扫描,归一化边扫边比——不再 .map 出第二个 6万数组。
        for (let i = 0; i < deviceHashes.length; i++) {
          if (HarmonyLicenseVerifier.normalizeHex(deviceHashes[i]) === have) {
            found = true;
            break;
          }
        }
        if (!found) {
          return HarmonyLicenseVerifier.fail(status, AsrErrorCode.LICENSE_DEVICE_MISMATCH, 'device SN not in license whitelist');
        }
      }
    }

    status.state = armed ? AmphionLicenseState.LICENSED : AmphionLicenseState.DEV_UNLICENSED;
    status.valid = true;
    status.errorCode = AsrErrorCode.OK;
    status.message = armed
      ? 'license accepted; signature and SN whitelist verified'
      : 'license parsed without signature verification; public key is not injected';
    return status;
  }

  private static fail(status: AmphionLicenseStatus, code: number, message: string): AmphionLicenseStatus {
    status.state = AmphionLicenseState.INVALID;
    status.valid = false;
    status.errorCode = code;
    status.message = message;
    return status;
  }

  /** ECDSA P-256(ECC256|SHA256)验签,输入为已解码的 payload/sig 字节(避免重复 base64 解码)。 */
  private static async verifyBytes(payloadBytes: Uint8Array, sigBytes: Uint8Array, publicKeyB64: string): Promise<boolean> {
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

  /** native UTF-8 解码。替代按字节手搓的 decodeBase64Utf8/decodeUtf8(4MB 逐字符 String.fromCharCode 拼接,真机极慢)。 */
  private static bytesToUtf8(bytes: Uint8Array): string {
    return util.TextDecoder.create('utf-8').decodeToString(bytes);
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
    // UTF-8 编码,与签发端 issue_license.py 及安卓 DeviceLicenseFingerprint 逐字节一致。
    // 旧实现用 charCodeAt & 0xff(非 UTF-8):非 ASCII SN 会与签发端分叉,导致合法 SN license 在鸿蒙被误拒。
    const bytes = new util.TextEncoder().encodeInto(raw);
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
      // 安全:claims 只能取自「签名覆盖的」payload_b64 解码结果。绝不接受未签名的顶层 payload
      // 或其他顶层字段——否则攻击者可保留一张合法签名,另附未签名 claims,绕过设备/有效期/特征绑定。
      if (parsed['payload'] !== undefined) {
        hilog.warn(0x0000, 'AmphionLicense', '%{public}s',
          'SECURITY: ignoring UNSIGNED top-level "payload"; claims are taken only from signed payload_b64');
      }
      const payloadB64 = parsed['payload_b64'];
      if (typeof payloadB64 !== 'string') {
        hilog.error(0x0000, 'AmphionLicense', '%{public}s', 'license missing payload_b64 (malformed)');
        return undefined;
      }
      const payloadJson = HarmonyLicenseVerifier.decodeBase64Utf8(payloadB64);
      const claims = JSON.parse(payloadJson) as Record<string, Object>;
      hilog.info(0x0000, 'AmphionLicense', 'claims(signed): features=%{public}s expiresAt=%{public}s devices=%{public}s',
        JSON.stringify(claims['features'] ?? []), `${claims['expiresAt'] ?? ''}`,
        JSON.stringify(claims['authorizedDeviceHashes'] ?? []));
      return claims;
    } catch (e) {
      hilog.error(0x0000, 'AmphionLicense', 'parseClaims failed: %{public}s', `${e}`);
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
    // BundleManager returns the host certificate SHA-256 fingerprint. Accept both its plain/colon
    // form and the conventional "SHA256:" prefix used by some signing tools and license issuers.
    return value.trim().replace(/^SHA-?256\s*[:=]?\s*/i, '').replace(/[:\s]/g, '').toUpperCase();
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
