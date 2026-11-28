/**
 * 按数量离线授权（额度证书链 amphion.quota-chain.v1）的设备端校验，鸿蒙版。
 *
 * 纯 TS、无 @kit 依赖：密码学原语与设备密钥由调用方注入（真机用 cryptoFramework + HUKS，见 QuotaDeviceKey.ets；
 * 单测用 node:crypto）。逻辑与 tools/license/quota/quota_chain.py 的 verify_chain、安卓 QuotaChainVerifier.kt
 * 逐条对齐，错误码字符串相同；三端用同一份 Python 签出的 fixtures 互测。
 *
 * 为什么自带 JSON 解析：JSON.parse 遇到重复键会静默取后一个，签发端（Python）则拒绝。同一份签名字节两端读出
 * 不同值，就可能让对账看到 seq=1、设备看到另一个值。这里重复键、浮点、NaN、尾随内容、超深嵌套一律拒绝。
 */

export const QUOTA_CHAIN_FORMAT = 'amphion.quota-chain.v1';
const ALG = 'SHA256withECDSA';
const T_QUOTA = 'amphion.quota.v1';
const T_DEVICE = 'amphion.device-license.v1';
const T_CHALLENGE = 'amphion.device-challenge.v1';
const T_ACTIVATION = 'amphion.activation-request.v1';
const T_DEACT = 'amphion.deactivation-receipt.v1';
const MAX_BYTES = 64 * 1024;
const MAX_DEVICES = 1000000;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const HEX64 = /^[0-9A-F]{64}$/;
const SALT = /^[A-Za-z0-9_-]{8,120}$/;
const ID = /^[A-Za-z0-9._-]{1,80}$/;
const SERIAL = /^[A-Z0-9]{4,64}$/;
const FEATURES = ['ASR', 'TTS'];
const ZERO_HASH = '0'.repeat(64);

export class QuotaChainError extends Error {
  readonly code: string;

  constructor(code: string, detail: string = '') {
    super(detail.length === 0 ? code : `${code}: ${detail}`);
    this.code = code;
  }
}

/** 平台密码学原语。ecdsaVerify 只接受 P-256 公钥（SPKI DER），签名为 DER。 */
export interface QuotaCrypto {
  b64decode(text: string): Uint8Array;
  b64encode(bytes: Uint8Array): string;
  utf8Encode(text: string): Uint8Array;
  utf8Decode(bytes: Uint8Array): string;
  sha256(bytes: Uint8Array): Promise<Uint8Array>;
  ecdsaVerify(spki: Uint8Array, data: Uint8Array, sig: Uint8Array): Promise<boolean>;
  /** SPKI DER 能解析且是 P-256 公钥。 */
  isP256(spki: Uint8Array): Promise<boolean>;
  randomBytes(length: number): Uint8Array;
}

/** 设备密钥：真机在 HUKS 内生成，私钥不可导出。 */
export interface QuotaDeviceKey {
  publicKeySpki(): Promise<Uint8Array>;
  sign(data: Uint8Array): Promise<Uint8Array>;
}

export interface QuotaContext {
  serial: string;
  bundleName: string;
  sdkMajor: number;
  sdkReleaseDate: string;
  requiredFeature: string;
  /** 已经过时钟水位处理的日期（见 effectiveToday）。 */
  today: string;
  deviceKey: QuotaDeviceKey;
}

export interface QuotaChainResult {
  quotaId: string;
  customer: string;
  seq: number;
  maxDevices: number;
  features: string[];
  licenseExpiresAt: string;
  maintenanceUntil: string;
  deviceIdSaltId: string;
}

type Json = null | boolean | number | string | Json[] | JsonObject;
interface JsonObject {
  [key: string]: Json;
}

// ------------------------------------------------------------------ 严格 JSON

export function strictParse(text: string): Json {
  const p = new StrictParser(text);
  p.ws();
  const v = p.value(0);
  p.ws();
  if (p.i !== text.length) {
    throw new QuotaChainError('MALFORMED', 'trailing content');
  }
  return v;
}

class StrictParser {
  readonly s: string;
  i: number = 0;

  constructor(s: string) {
    this.s = s;
  }

  ws(): void {
    while (this.i < this.s.length) {
      const c = this.s.charAt(this.i);
      if (c !== ' ' && c !== '\n' && c !== '\r' && c !== '\t') {
        break;
      }
      this.i++;
    }
  }

  fail(why: string): QuotaChainError {
    return new QuotaChainError('MALFORMED', why);
  }

  value(depth: number): Json {
    if (depth > 16) {
      throw this.fail('too deep');
    }
    if (this.i >= this.s.length) {
      throw this.fail('unexpected end');
    }
    const c = this.s.charAt(this.i);
    if (c === '{') {
      return this.obj(depth);
    }
    if (c === '[') {
      return this.arr(depth);
    }
    if (c === '"') {
      return this.str();
    }
    if (c === 't') {
      return this.lit('true', true);
    }
    if (c === 'f') {
      return this.lit('false', false);
    }
    if (c === 'n') {
      return this.lit('null', null);
    }
    return this.num();
  }

  lit(word: string, v: Json): Json {
    if (!this.s.startsWith(word, this.i)) {
      throw this.fail('bad literal');
    }
    this.i += word.length;
    return v;
  }

  obj(depth: number): JsonObject {
    const out: JsonObject = {};
    const seen = new Set<string>();
    this.i++;
    this.ws();
    if (this.s.charAt(this.i) === '}') {
      this.i++;
      return out;
    }
    for (;;) {
      this.ws();
      if (this.s.charAt(this.i) !== '"') {
        throw this.fail('expected key');
      }
      const k = this.str();
      this.ws();
      if (this.s.charAt(this.i) !== ':') {
        throw this.fail('expected colon');
      }
      this.i++;
      this.ws();
      if (seen.has(k)) {
        throw this.fail('duplicate key');
      }
      seen.add(k);
      // defineProperty：键名为 __proto__ 时也只是普通字段，不改原型。
      Object.defineProperty(out, k, { value: this.value(depth + 1), enumerable: true, writable: true, configurable: true });
      this.ws();
      const c = this.s.charAt(this.i);
      this.i++;
      if (c === '}') {
        return out;
      }
      if (c !== ',') {
        throw this.fail('expected , or }');
      }
    }
  }

  arr(depth: number): Json[] {
    const out: Json[] = [];
    this.i++;
    this.ws();
    if (this.s.charAt(this.i) === ']') {
      this.i++;
      return out;
    }
    for (;;) {
      this.ws();
      out.push(this.value(depth + 1));
      this.ws();
      const c = this.s.charAt(this.i);
      this.i++;
      if (c === ']') {
        return out;
      }
      if (c !== ',') {
        throw this.fail('expected , or ]');
      }
    }
  }

  str(): string {
    this.i++;
    let out = '';
    for (;;) {
      if (this.i >= this.s.length) {
        throw this.fail('unterminated string');
      }
      const c = this.s.charAt(this.i++);
      if (c === '"') {
        return out;
      }
      if (c === '\\') {
        const e = this.s.charAt(this.i++);
        if (e === '"' || e === '\\' || e === '/') {
          out += e;
        } else if (e === 'b') {
          out += '\b';
        } else if (e === 'f') {
          out += '\f';
        } else if (e === 'n') {
          out += '\n';
        } else if (e === 'r') {
          out += '\r';
        } else if (e === 't') {
          out += '\t';
        } else if (e === 'u') {
          const hex = this.s.substring(this.i, this.i + 4);
          if (!/^[0-9A-Fa-f]{4}$/.test(hex)) {
            throw this.fail('bad unicode escape');
          }
          out += String.fromCharCode(parseInt(hex, 16));
          this.i += 4;
        } else {
          throw this.fail('bad escape');
        }
      } else if (c < ' ') {
        throw this.fail('control char in string');
      } else {
        out += c;
      }
    }
  }

  num(): number {
    const start = this.i;
    if (this.s.charAt(this.i) === '-') {
      this.i++;
    }
    const digits = this.i;
    while (this.i < this.s.length && this.s.charAt(this.i) >= '0' && this.s.charAt(this.i) <= '9') {
      this.i++;
    }
    if (this.i === digits) {
      throw this.fail('bad number');
    }
    if (this.s.charAt(digits) === '0' && this.i - digits > 1) {
      throw this.fail('leading zero');
    }
    const next = this.s.charAt(this.i);
    if (next === '.' || next === 'e' || next === 'E') {
      throw this.fail('only integers allowed');
    }
    const v = Number(this.s.substring(start, this.i));
    if (!Number.isSafeInteger(v)) {
      throw this.fail('integer overflow');
    }
    return v;
  }
}

// ------------------------------------------------------------------ 校验

export function isQuotaChain(text: string | undefined): boolean {
  if (text === undefined) {
    return false;
  }
  try {
    const top = strictParse(text);
    return isObject(top) && (top as JsonObject)['format'] === QUOTA_CHAIN_FORMAT;
  } catch (_e) {
    return false;
  }
}

/**
 * 时钟水位：取设备时钟与已见最大日期中较晚者。离线设备调回时钟不能让已过期的授权复活。
 * 调用方在校验通过后把返回值存回本地（只增不减）。
 */
export function effectiveToday(deviceToday: string, watermark: string): string {
  if (!DATE.test(watermark)) {
    return deviceToday;
  }
  return watermark > deviceToday ? watermark : deviceToday;
}

export async function verifyQuotaChain(text: string, trustedRootsB64: string, ctx: QuotaContext,
  crypto: QuotaCrypto): Promise<QuotaChainResult> {
  const roots = trustedRootsB64.split(',').map((r: string): string => r.trim()).filter((r: string): boolean => r.length > 0);
  if (roots.length === 0) {
    throw new QuotaChainError('NOT_ARMED');
  }
  if (crypto.utf8Encode(text).length > MAX_BYTES * 3) {
    throw new QuotaChainError('MALFORMED', 'too large');
  }
  const top = exact(strictParse(text), ['format', 'quota', 'device'], 'chain');
  if (top['format'] !== QUOTA_CHAIN_FORMAT) {
    throw new QuotaChainError('MALFORMED', 'format');
  }

  // 1. 额度证书只认内置根公钥。
  const rootKeys = roots.map((r: string): Uint8Array => decode(r, crypto));
  for (const k of rootKeys) {
    await requireP256(k, crypto);
  }
  const q = await openEnvelope(top['quota'], rootKeys, T_QUOTA, 'QUOTA_SIGNATURE_INVALID', crypto);
  const quota = q.claims;
  validateQuota(quota);
  const site = obj(quota, 'site');
  const sitePk = decode(str(site, 'publicKey'), crypto);
  await requireP256(sitePk, crypto);
  if (str(site, 'keyId') !== hex(await crypto.sha256(sitePk))) {
    throw new QuotaChainError('MALFORMED', 'site keyId');
  }
  const qSha = hex(await crypto.sha256(q.payload));

  // 2. 设备授权只认额度证书里写明的签发点公钥。
  const d = await openEnvelope(top['device'], [sitePk], T_DEVICE, 'DEVICE_SIGNATURE_INVALID', crypto);
  const dev = d.claims;
  validateDevice(dev);
  if (str(dev, 'quotaSha256') !== qSha || str(dev, 'quotaId') !== str(quota, 'quotaId')) {
    throw new QuotaChainError('QUOTA_MISMATCH', 'device license references another quota');
  }
  if (str(dev, 'siteKeyId') !== str(site, 'keyId')) {
    throw new QuotaChainError('QUOTA_MISMATCH', 'site key id');
  }

  // 3. 数量上限。
  const seq = int(dev, 'seq');
  const max = int(quota, 'maxDevices');
  if (seq < 1 || seq > max) {
    throw new QuotaChainError('SEQ_OUT_OF_RANGE', `seq=${seq} max=${max}`);
  }

  // 4. 签发点不能放大权限。
  const qFeatures = strList(quota, 'features');
  const dFeatures = strList(dev, 'features');
  if (dFeatures.length === 0 || dFeatures.some((f: string): boolean => !qFeatures.includes(f))) {
    throw new QuotaChainError('FEATURE_ESCALATION');
  }
  if (!dFeatures.includes(ctx.requiredFeature)) {
    throw new QuotaChainError('FEATURE_MISSING', ctx.requiredFeature);
  }
  const issued = str(dev, 'issuedAt');
  if (issued < str(quota, 'issuedAt') || issued > str(quota, 'issueNotAfter')) {
    throw new QuotaChainError('ISSUE_WINDOW');
  }
  const qExp = str(quota, 'licenseExpiresAt');
  const dExp = str(dev, 'licenseExpiresAt');
  if (qExp.length > 0 && (dExp.length === 0 || dExp > qExp)) {
    throw new QuotaChainError('EXPIRY_ESCALATION');
  }
  if (str(dev, 'deviceIdSaltId') !== str(quota, 'deviceIdSaltId')) {
    throw new QuotaChainError('QUOTA_MISMATCH', 'salt');
  }

  // 5. 运行期限 / 版本 / 维护期 / 应用包（策略只取自根签的额度证书）。
  if (dExp.length > 0 && ctx.today > dExp) {
    throw new QuotaChainError('EXPIRED', dExp);
  }
  const major = int(quota, 'sdkMajor');
  if (major > 0 && major !== ctx.sdkMajor) {
    throw new QuotaChainError('SDK_MAJOR_MISMATCH');
  }
  const maint = str(quota, 'maintenanceUntil');
  if (maint.length > 0 && ctx.sdkReleaseDate.length > 0 && ctx.sdkReleaseDate > maint) {
    throw new QuotaChainError('MAINTENANCE_EXPIRED', maint);
  }
  if (str(quota, 'applicationBindingMode') === 'allowlist' &&
    !strList(quota, 'bundleNames').concat(strList(quota, 'applicationIds')).includes(ctx.bundleName)) {
    throw new QuotaChainError('APP_MISMATCH');
  }

  // 6. 设备绑定：SN 哈希 + 设备密钥持有证明（每次新随机挑战）。
  const normalized = ctx.serial.trim().toUpperCase();
  if (!SERIAL.test(normalized)) {
    throw new QuotaChainError('DEVICE_ID_INVALID');
  }
  const snHash = hex(await crypto.sha256(crypto.utf8Encode(normalized + str(quota, 'deviceIdSaltId'))));
  if (snHash !== str(dev, 'snHash')) {
    throw new QuotaChainError('DEVICE_MISMATCH', 'SN');
  }
  let spki: Uint8Array;
  try {
    spki = await ctx.deviceKey.publicKeySpki();
  } catch (_e) {
    throw new QuotaChainError('DEVICE_KEY_MISMATCH', 'device key unavailable');
  }
  if (hex(await crypto.sha256(spki)) !== str(dev, 'devicePublicKeySha256')) {
    throw new QuotaChainError('DEVICE_KEY_MISMATCH');
  }
  const challenge = crypto.utf8Encode(`${T_CHALLENGE}|${hex(crypto.randomBytes(16)).toLowerCase()}`);
  let proven = false;
  try {
    proven = await crypto.ecdsaVerify(spki, challenge, await ctx.deviceKey.sign(challenge));
  } catch (_e) {
    proven = false;
  }
  if (!proven) {
    throw new QuotaChainError('DEVICE_KEY_MISMATCH', 'challenge signature');
  }
  return {
    quotaId: str(quota, 'quotaId'), customer: str(quota, 'customer'), seq, maxDevices: max, features: dFeatures,
    licenseExpiresAt: dExp, maintenanceUntil: maint, deviceIdSaltId: str(quota, 'deviceIdSaltId')
  };
}

// ------------------------------------------------------------------ 激活请求 / 注销回执（设备密钥签名）

/** 生成交给签发点的激活请求（不含明文 SN）。platform: harmony_arm64 / android_arm64。 */
export async function buildActivationRequest(serial: string, saltId: string, platform: string, bundleName: string,
  today: string, key: QuotaDeviceKey, crypto: QuotaCrypto): Promise<string> {
  const normalized = serial.trim().toUpperCase();
  if (!SERIAL.test(normalized) || !SALT.test(saltId) || !DATE.test(today)) {
    throw new QuotaChainError('MALFORMED', 'activation input');
  }
  const claims: Record<string, string> = {
    'type': T_ACTIVATION,
    'snHash': hex(await crypto.sha256(crypto.utf8Encode(normalized + saltId))),
    'deviceIdSaltId': saltId,
    'devicePublicKey': crypto.b64encode(await key.publicKeySpki()),
    'platform': platform,
    'bundleName': bundleName,
    'createdAt': today,
    'nonce': hex(crypto.randomBytes(16)).toLowerCase()
  };
  return signEnvelope(claims, key, crypto);
}

/** 注销回执：调用方签完后必须立即销毁设备密钥和授权文件。 */
export async function buildDeactivationReceipt(licenseText: string, today: string, key: QuotaDeviceKey,
  crypto: QuotaCrypto): Promise<string> {
  const top = exact(strictParse(licenseText), ['format', 'quota', 'device'], 'chain');
  const quotaEnv = exact(top['quota'], ['alg', 'payload_b64', 'sig_b64'], 'envelope');
  const quota = strictParse(crypto.utf8Decode(decode(quotaEnv['payload_b64'], crypto)));
  const sitePk = decode(str(obj(asObject(quota, 'quota'), 'site'), 'publicKey'), crypto);
  const d = await openEnvelope(top['device'], [sitePk], T_DEVICE, 'DEVICE_SIGNATURE_INVALID', crypto);
  const claims: Record<string, string | number> = {
    'type': T_DEACT,
    'quotaId': str(d.claims, 'quotaId'),
    'seq': int(d.claims, 'seq'),
    'snHash': str(d.claims, 'snHash'),
    'licenseSha256': hex(await crypto.sha256(d.payload)),
    'devicePublicKey': crypto.b64encode(await key.publicKeySpki()),
    'createdAt': today,
    'nonce': hex(crypto.randomBytes(16)).toLowerCase()
  };
  return signEnvelope(claims, key, crypto);
}

async function signEnvelope(claims: Record<string, string | number>, key: QuotaDeviceKey,
  crypto: QuotaCrypto): Promise<string> {
  const payload = crypto.utf8Encode(JSON.stringify(claims));
  const sig = await key.sign(payload);
  return JSON.stringify({ 'payload_b64': crypto.b64encode(payload), 'alg': ALG, 'sig_b64': crypto.b64encode(sig) });
}

/** 映射到 SDK 已有错误码（数值与 Types.ets AsrErrorCode 一致），宿主 App 不需要新增分支。 */
export function quotaErrorName(code: string): string {
  switch (code) {
    case 'QUOTA_SIGNATURE_INVALID':
    case 'DEVICE_SIGNATURE_INVALID':
    case 'QUOTA_MISMATCH':
    case 'SEQ_OUT_OF_RANGE':
    case 'FEATURE_ESCALATION':
    case 'ISSUE_WINDOW':
    case 'EXPIRY_ESCALATION':
      return 'LICENSE_SIGNATURE_INVALID';
    case 'FEATURE_MISSING':
      return 'LICENSE_FEATURE_MISSING';
    case 'EXPIRED':
      return 'LICENSE_EXPIRED';
    case 'SDK_MAJOR_MISMATCH':
      return 'LICENSE_SDK_MAJOR_MISMATCH';
    case 'MAINTENANCE_EXPIRED':
      return 'LICENSE_MAINTENANCE_EXPIRED';
    case 'APP_MISMATCH':
      return 'LICENSE_APP_MISMATCH';
    case 'DEVICE_MISMATCH':
    case 'DEVICE_KEY_MISMATCH':
      return 'LICENSE_DEVICE_MISMATCH';
    default:
      return 'LICENSE_MALFORMED';
  }
}

// ------------------------------------------------------------------ 信封与结构

interface Opened {
  payload: Uint8Array;
  claims: JsonObject;
}

async function openEnvelope(env: Json | undefined, keys: Uint8Array[], type: string, sigCode: string,
  crypto: QuotaCrypto): Promise<Opened> {
  const e = exact(env, ['alg', 'payload_b64', 'sig_b64'], 'envelope');
  if (e['alg'] !== ALG) {
    throw new QuotaChainError('MALFORMED', 'alg');
  }
  const payload = decode(e['payload_b64'], crypto);
  const sig = decode(e['sig_b64'], crypto);
  if (payload.length > MAX_BYTES) {
    throw new QuotaChainError('MALFORMED', 'payload too large');
  }
  let ok = false;
  for (let i = 0; i < keys.length && !ok; i++) {
    try {
      ok = await crypto.ecdsaVerify(keys[i], payload, sig);
    } catch (_e) {
      ok = false;
    }
  }
  if (!ok) {
    throw new QuotaChainError(sigCode, type);
  }
  let text: string;
  try {
    text = crypto.utf8Decode(payload);
  } catch (_e) {
    throw new QuotaChainError('MALFORMED', 'utf-8');
  }
  const claims = asObject(strictParse(text), 'claims');
  if (claims['type'] !== type) {
    throw new QuotaChainError('TYPE_MISMATCH', type);
  }
  return { payload, claims };
}

function validateQuota(q: JsonObject): void {
  exact(q, ['type', 'quotaId', 'customer', 'projectId', 'issuedAt', 'issueNotAfter', 'licenseExpiresAt',
    'maxDevices', 'features', 'sdkMajor', 'maintenanceUntil', 'deviceIdSaltId', 'applicationBindingMode',
    'bundleNames', 'applicationIds', 'site', 'enrollmentSha256', 'reassignment'], 'quota');
  str(q, 'quotaId', ID);
  str(q, 'customer');
  str(q, 'projectId', ID);
  const issued = date(q, 'issuedAt', false);
  const notAfter = date(q, 'issueNotAfter', false);
  const exp = date(q, 'licenseExpiresAt', true);
  if (notAfter < issued || (exp.length > 0 && exp < notAfter)) {
    throw new QuotaChainError('MALFORMED', 'quota dates');
  }
  int(q, 'maxDevices', 1, MAX_DEVICES);
  const f = strList(q, 'features');
  if (f.length === 0 || new Set(f).size !== f.length || f.some((x: string): boolean => !FEATURES.includes(x))) {
    throw new QuotaChainError('MALFORMED', 'features');
  }
  int(q, 'sdkMajor', 0, 1000);
  date(q, 'maintenanceUntil', true);
  str(q, 'deviceIdSaltId', SALT);
  const mode = str(q, 'applicationBindingMode');
  if (mode !== 'none' && mode !== 'allowlist') {
    throw new QuotaChainError('MALFORMED', 'applicationBindingMode');
  }
  const packages = strList(q, 'bundleNames').concat(strList(q, 'applicationIds'));
  if ((mode === 'allowlist') !== (packages.length > 0)) {
    throw new QuotaChainError('MALFORMED', 'package policy');
  }
  exact(q['site'], ['siteId', 'publicKey', 'keyId', 'hardware', 'minHardwarePresent'], 'site');
  str(q, 'enrollmentSha256', HEX64);
  exact(q['reassignment'], ['mode', 'budget'], 'reassignment');
}

function validateDevice(d: JsonObject): void {
  exact(d, ['type', 'licenseId', 'quotaId', 'quotaSha256', 'siteKeyId', 'seq', 'snHash', 'deviceIdSaltId',
    'devicePublicKeySha256', 'features', 'licenseExpiresAt', 'issuedAt', 'logIndex', 'logPrevHash'], 'device');
  str(d, 'licenseId', ID);
  str(d, 'quotaId', ID);
  for (const k of ['quotaSha256', 'siteKeyId', 'snHash', 'devicePublicKeySha256']) {
    str(d, k, HEX64);
  }
  int(d, 'seq', -2147483648, 2147483647);
  str(d, 'deviceIdSaltId', SALT);
  const f = strList(d, 'features');
  if (new Set(f).size !== f.length) {
    throw new QuotaChainError('MALFORMED', 'features');
  }
  date(d, 'licenseExpiresAt', true);
  date(d, 'issuedAt', false);
  int(d, 'logIndex', 0, 2 ** 40);
  const prev = str(d, 'logPrevHash');
  if (prev !== ZERO_HASH && !HEX64.test(prev)) {
    throw new QuotaChainError('MALFORMED', 'logPrevHash');
  }
}

function date(m: JsonObject, k: string, allowEmpty: boolean): string {
  const v = str(m, k);
  if (allowEmpty && v.length === 0) {
    return v;
  }
  if (!DATE.test(v)) {
    throw new QuotaChainError('MALFORMED', k);
  }
  const y = Number(v.substring(0, 4));
  const mo = Number(v.substring(5, 7));
  const day = Number(v.substring(8, 10));
  const leap = (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
  const dim = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (mo < 1 || mo > 12 || day < 1 || day > dim[mo - 1]) {
    throw new QuotaChainError('MALFORMED', k);
  }
  return v;
}

function isObject(v: Json | undefined): boolean {
  return v !== null && v !== undefined && typeof v === 'object' && !Array.isArray(v);
}

function asObject(v: Json | undefined, label: string): JsonObject {
  if (!isObject(v)) {
    throw new QuotaChainError('MALFORMED', `${label} must be an object`);
  }
  return v as JsonObject;
}

function exact(v: Json | undefined, keys: string[], label: string): JsonObject {
  const m = asObject(v, label);
  const have = Object.keys(m);
  if (have.length !== keys.length || keys.some((k: string): boolean => !Object.prototype.hasOwnProperty.call(m, k))) {
    throw new QuotaChainError('MALFORMED', `${label} fields mismatch`);
  }
  return m;
}

function obj(m: JsonObject, k: string): JsonObject {
  return asObject(m[k], k);
}

function str(m: JsonObject, k: string, pattern?: RegExp): string {
  const v = m[k];
  if (typeof v !== 'string' || (pattern !== undefined && !pattern.test(v))) {
    throw new QuotaChainError('MALFORMED', k);
  }
  return v;
}

function int(m: JsonObject, k: string, lo: number = Number.MIN_SAFE_INTEGER, hi: number = Number.MAX_SAFE_INTEGER): number {
  const v = m[k];
  if (typeof v !== 'number' || !Number.isSafeInteger(v) || v < lo || v > hi) {
    throw new QuotaChainError('MALFORMED', k);
  }
  return v;
}

function strList(m: JsonObject, k: string): string[] {
  const v = m[k];
  if (!Array.isArray(v) || v.some((x: Json): boolean => typeof x !== 'string')) {
    throw new QuotaChainError('MALFORMED', k);
  }
  return v as string[];
}

function decode(v: Json | undefined, crypto: QuotaCrypto): Uint8Array {
  if (typeof v !== 'string' || !/^[A-Za-z0-9+/]*={0,2}$/.test(v) || v.length % 4 !== 0) {
    throw new QuotaChainError('MALFORMED', 'base64');
  }
  try {
    return crypto.b64decode(v);
  } catch (_e) {
    throw new QuotaChainError('MALFORMED', 'base64');
  }
}

async function requireP256(spki: Uint8Array, crypto: QuotaCrypto): Promise<void> {
  let ok = false;
  try {
    ok = await crypto.isP256(spki);
  } catch (_e) {
    ok = false;
  }
  if (!ok) {
    throw new QuotaChainError('MALFORMED', 'P-256 only');
  }
}

function hex(bytes: Uint8Array): string {
  let out = '';
  for (let i = 0; i < bytes.length; i++) {
    out += (bytes[i] < 16 ? '0' : '') + bytes[i].toString(16).toUpperCase();
  }
  return out;
}
