import { preferences } from '@kit.ArkData';
import { LicenseClockWatermark } from './License';
import { buildActivationRequest, buildDeactivationReceipt } from './QuotaChain';
import { HarmonyQuotaCrypto, HuksQuotaDeviceKey } from './QuotaDeviceKey';

const CLOCK_STORE = 'amphion_license_clock';
const CLOCK_KEY = 'maxSeenDate';

/** 时钟水位存到应用私有 Preferences；只增不减。读写失败不阻断校验（退化为只用设备时钟）。 */
export class PreferencesClockWatermark implements LicenseClockWatermark {
  private readonly context: Context;

  constructor(context: Context) {
    this.context = context;
  }

  read(): string {
    try {
      const store = preferences.getPreferencesSync(this.context, { name: CLOCK_STORE });
      const v = store.getSync(CLOCK_KEY, '');
      return typeof v === 'string' ? v : '';
    } catch (_e) {
      return '';
    }
  }

  write(day: string): void {
    try {
      const store = preferences.getPreferencesSync(this.context, { name: CLOCK_STORE });
      const old = store.getSync(CLOCK_KEY, '');
      if (typeof old === 'string' && old >= day) {
        return;
      }
      store.putSync(CLOCK_KEY, day);
      store.flush();
    } catch (_e) {
      // 水位只是加固，存储不可用时不影响授权判断本身。
    }
  }
}

/**
 * 按数量离线授权的设备侧操作。激活：生成 HUKS 密钥 → 导出激活请求交给客户内网签发点 → 把返回的授权文件交给
 * AmphionOptions.license。注销（额度允许回收时）：签回执交回签发点，同时销毁密钥，旧授权随之失效。
 */
export class AmphionQuotaLicense {
  /** 激活请求（JSON 文本，含 SN 盐哈希与设备公钥，不含明文 SN）。saltId 取自客户的额度证书。 */
  static async activationRequest(deviceSerial: string, saltId: string, bundleName: string): Promise<string> {
    const key = new HuksQuotaDeviceKey();
    await key.ensure();
    return await buildActivationRequest(deviceSerial, saltId, 'harmony_arm64', bundleName,
      new Date().toISOString().substring(0, 10), key, new HarmonyQuotaCrypto());
  }

  /** 注销回执；返回后本机密钥已销毁，需删除本地授权文件。 */
  static async deactivationReceipt(licenseText: string): Promise<string> {
    const key = new HuksQuotaDeviceKey();
    const receipt = await buildDeactivationReceipt(licenseText, new Date().toISOString().substring(0, 10), key,
      new HarmonyQuotaCrypto());
    await key.destroy();
    return receipt;
  }
}
