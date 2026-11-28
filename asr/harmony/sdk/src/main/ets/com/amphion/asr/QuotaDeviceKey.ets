import { huks } from '@kit.UniversalKeystoreKit';
import { cryptoFramework } from '@kit.CryptoArchitectureKit';
import { util } from '@kit.ArkTS';
import { QuotaCrypto, QuotaDeviceKey } from './QuotaChain';

/**
 * HUKS 内的设备密钥（ECC P-256，私钥不出 HUKS）。用于激活请求、运行时持有证明与注销回执。
 * 恢复出厂/卸载应用会删除密钥，设备需重新激活（签发点按同 SN 沿用原序号，不多占名额）。
 */
export class HuksQuotaDeviceKey implements QuotaDeviceKey {
  static readonly DEFAULT_ALIAS: string = 'amphion.quota.device.v1';
  private readonly alias: string;

  constructor(alias: string = HuksQuotaDeviceKey.DEFAULT_ALIAS) {
    this.alias = alias;
  }

  private static signProperties(): Array<huks.HuksParam> {
    const props: Array<huks.HuksParam> = [];
    props.push({ tag: huks.HuksTag.HUKS_TAG_ALGORITHM, value: huks.HuksKeyAlg.HUKS_ALG_ECC });
    props.push({ tag: huks.HuksTag.HUKS_TAG_KEY_SIZE, value: huks.HuksKeySize.HUKS_ECC_KEY_SIZE_256 });
    props.push({ tag: huks.HuksTag.HUKS_TAG_PURPOSE, value: huks.HuksKeyPurpose.HUKS_KEY_PURPOSE_SIGN });
    props.push({ tag: huks.HuksTag.HUKS_TAG_DIGEST, value: huks.HuksKeyDigest.HUKS_DIGEST_SHA256 });
    return props;
  }

  async exists(): Promise<boolean> {
    try {
      return await huks.isKeyItemExist(this.alias, { properties: [] });
    } catch (_e) {
      // 密钥不存在时部分系统版本抛 12000011 而不是返回 false。
      return false;
    }
  }

  /** 首次激活时调用；已存在则复用。 */
  async ensure(): Promise<void> {
    if (await this.exists()) {
      return;
    }
    const props: Array<huks.HuksParam> = [];
    props.push({ tag: huks.HuksTag.HUKS_TAG_ALGORITHM, value: huks.HuksKeyAlg.HUKS_ALG_ECC });
    props.push({ tag: huks.HuksTag.HUKS_TAG_KEY_SIZE, value: huks.HuksKeySize.HUKS_ECC_KEY_SIZE_256 });
    props.push({
      tag: huks.HuksTag.HUKS_TAG_PURPOSE,
      value: huks.HuksKeyPurpose.HUKS_KEY_PURPOSE_SIGN | huks.HuksKeyPurpose.HUKS_KEY_PURPOSE_VERIFY
    });
    props.push({ tag: huks.HuksTag.HUKS_TAG_DIGEST, value: huks.HuksKeyDigest.HUKS_DIGEST_SHA256 });
    await huks.generateKeyItem(this.alias, { properties: props });
  }

  /** HUKS 导出的 ECC 公钥是 X.509 SubjectPublicKeyInfo DER，与签发点要求的格式一致。 */
  async publicKeySpki(): Promise<Uint8Array> {
    const result = await huks.exportKeyItem(this.alias, { properties: [] });
    if (result.outData === undefined || result.outData.length === 0) {
      throw new Error('device key missing');
    }
    return result.outData;
  }

  /** ECDSA-SHA256，输出 DER 编码签名。 */
  async sign(data: Uint8Array): Promise<Uint8Array> {
    const options: huks.HuksOptions = { properties: HuksQuotaDeviceKey.signProperties(), inData: data };
    const session = await huks.initSession(this.alias, options);
    const result = await huks.finishSession(session.handle, options);
    if (result.outData === undefined || result.outData.length === 0) {
      throw new Error('device key sign failed');
    }
    return result.outData;
  }

  /** 注销：调用方先签好回执，再调用本方法销毁密钥。 */
  async destroy(): Promise<void> {
    if (await this.exists()) {
      await huks.deleteKeyItem(this.alias, { properties: [] });
    }
  }
}

/** cryptoFramework 实现的 QuotaCrypto。 */
export class HarmonyQuotaCrypto implements QuotaCrypto {
  b64decode(text: string): Uint8Array {
    return new util.Base64Helper().decodeSync(text);
  }

  b64encode(bytes: Uint8Array): string {
    return new util.Base64Helper().encodeToStringSync(bytes);
  }

  utf8Encode(text: string): Uint8Array {
    return new util.TextEncoder().encodeInto(text);
  }

  utf8Decode(bytes: Uint8Array): string {
    const options: util.TextDecoderOptions = { fatal: true };
    return util.TextDecoder.create('utf-8', options).decodeToString(bytes);
  }

  async sha256(bytes: Uint8Array): Promise<Uint8Array> {
    const md = cryptoFramework.createMd('SHA256');
    await md.update({ data: bytes });
    return (await md.digest()).data;
  }

  async isP256(spki: Uint8Array): Promise<boolean> {
    try {
      // ECC256 生成器只能转换 NIST P-256 公钥，其他曲线或畸形 DER 都会抛错。
      await cryptoFramework.createAsyKeyGenerator('ECC256').convertKey({ data: spki }, null);
      return true;
    } catch (_e) {
      return false;
    }
  }

  async ecdsaVerify(spki: Uint8Array, data: Uint8Array, sig: Uint8Array): Promise<boolean> {
    const keyPair = await cryptoFramework.createAsyKeyGenerator('ECC256').convertKey({ data: spki }, null);
    const verifier = cryptoFramework.createVerify('ECC256|SHA256');
    await verifier.init(keyPair.pubKey);
    await verifier.update({ data: data });
    return await verifier.verify(null, { data: sig });
  }

  randomBytes(length: number): Uint8Array {
    return cryptoFramework.createRandom().generateRandomSync(length).data;
  }
}
