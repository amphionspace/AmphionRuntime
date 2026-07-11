import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { window } from '@kit.ArkUI';
import hilog from '@ohos.hilog';
import deviceInfo from '@ohos.deviceInfo';
import { LicenseDeviceIdProvider, SpeechRecognizeSdk } from 'amphion_dingqiao';
import { DeviceStressOptions, runDeviceStress } from '../util/DeviceStressTest';
import { runSdkSelfTest } from '../util/SdkSelfTest';

class DemoDeviceIdProvider implements LicenseDeviceIdProvider {
  getDeviceSerial(_context: Context): string | undefined {
    // Normal apps cannot request ACCESS_UDID; ODID remains scoped to this developer and device.
    const deviceId = deviceInfo.ODID;
    return deviceId.length > 0 ? deviceId : undefined;
  }
}

export default class EntryAbility extends UIAbility {
  private selfTest: boolean = false;
  private stressTest: boolean = false;

  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    // Process-level SDK init + work directory live here (mirrors Android DingqiaoApp) so every page
    // shares one SpeechRecognizeSdk instance and the same {filesDir}/dingqiao_work path.
    try {
      const workPath = `${this.context.filesDir}/dingqiao_work`;
      const deviceIdProvider = new DemoDeviceIdProvider();
      SpeechRecognizeSdk.init(this.context, deviceIdProvider);
      SpeechRecognizeSdk.setWorkPath(workPath);
      hilog.info(0x0000, 'DingqiaoDemo', 'SpeechRecognizeSdk init done, workPath=%{public}s', workPath);
    } catch (e) {
      hilog.error(0x0000, 'DingqiaoDemo', 'SpeechRecognizeSdk init failed: %{public}s', `${e}`);
    }
    // Headless SDK contract self-test: `aa start ... --ps selftest true`. Runs every public API and
    // logs a PASS/FAIL matrix under tag SdkSelfTest, without loading the UI.
    const params = want.parameters;
    this.selfTest = params !== undefined && params['selftest'] === 'true';
    this.stressTest = params !== undefined && params['stress'] === 'true';
    if (this.selfTest) {
      runSdkSelfTest(this.context).catch((e: Object): void => {
        hilog.error(0x0000, 'SdkSelfTest', 'self-test crashed: %{public}s', `${e}`);
      });
    } else if (this.stressTest) {
      const options = new DeviceStressOptions();
      options.runId = this.stringParameter(want, 'stressRunId', 'manual');
      options.manifestPath = this.stringParameter(want, 'stressManifest', '');
      options.resultPath = this.stringParameter(want, 'stressResult', '');
      options.mode = this.stringParameter(want, 'stressMode', 'burst');
      options.cycles = this.numberParameter(want, 'stressCycles', 1);
      options.settleMs = this.numberParameter(want, 'stressSettleMs', 0);
      options.paceMs = this.numberParameter(want, 'stressPaceMs', 20);
      runDeviceStress(this.context, options).catch((e: Object): void => {
        hilog.error(0x0000, 'DeviceStressTest', 'stress test crashed: %{public}s', `${e}`);
      });
    }
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    if (this.selfTest || this.stressTest) {
      hilog.info(0x0000, 'DingqiaoDemo', 'headless test mode: skipping UI');
      return;
    }
    windowStage.loadContent('pages/Index', (err: BusinessError) => {
      if (err.code !== 0) {
        hilog.error(0x0000, 'DingqiaoDemo', 'Failed to load pages/Index. Cause: %{public}s', JSON.stringify(err));
        return;
      }
      hilog.info(0x0000, 'DingqiaoDemo', 'Succeeded in loading pages/Index.');
    });
  }

  private stringParameter(want: Want, key: string, fallback: string): string {
    const value = want.parameters?.[key];
    return typeof value === 'string' && value.length > 0 ? value : fallback;
  }

  private numberParameter(want: Want, key: string, fallback: number): number {
    const value = want.parameters?.[key];
    if (typeof value === 'number' && Number.isFinite(value)) return Math.max(0, Math.floor(value));
    if (typeof value === 'string') {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return Math.max(0, Math.floor(parsed));
    }
    return fallback;
  }
}
