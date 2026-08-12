import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { window } from '@kit.ArkUI';
import hilog from '@ohos.hilog';
import deviceInfo from '@ohos.deviceInfo';
import { LicenseDeviceIdProvider, SpeechRecognizeSdk } from 'amphion_dingqiao';
import { DeviceStressOptions, runDeviceStress } from '../util/DeviceStressTest';
import { ModelLoadBenchOptions, runModelLoadBench } from '../util/ModelLoadBench';
import { LifecycleBenchOptions, runLifecycleBench } from '../util/LifecycleBench';
import { runSdkSelfTest } from '../util/SdkSelfTest';
import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';

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
  private loadBench: boolean = false;
  private lifecycleBench: boolean = false;
  private stressWindow?: window.Window;
  private stressFinished: boolean = false;

  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    // Process-level SDK init + work directory live here (mirrors Android DingqiaoApp) so every page
    // shares one SpeechRecognizeSdk instance and the same {filesDir}/amphion_asr_work path.
    // 载体基线:任何 SDK 调用之前从 /proc 采一次 VmRSS + 私有 anon(纯宿主,无 SDK native/模型),供内存减法。
    // 用 /proc 内核账,不用 hidebug.getPss()(实测低估)。
    let carrierBaselinePss = 0;   // 实为 VmRSS,沿用字段名传给 bench
    let carrierBaselineAnon = 0;
    // /proc 文件 stat 报 size=0,fs.readTextSync 读到空;必须 openSync+readSync 读到 EOF。
    try {
      const fp = fs.openSync('/proc/self/status', fs.OpenMode.READ_ONLY);
      try {
        const buf = new ArrayBuffer(8192);
        const n = fs.readSync(fp.fd, buf);
        const st = util.TextDecoder.create('utf-8').decodeToString(new Uint8Array(buf.slice(0, n)));
        const mr = st.match(/VmRSS:\s*(\d+)\s*kB/);
        const ma = st.match(/RssAnon:\s*(\d+)\s*kB/);
        carrierBaselinePss = mr !== null ? Math.round(Number(mr[1]) / 1024) : 0;
        carrierBaselineAnon = ma !== null ? Math.round(Number(ma[1]) / 1024) : 0;
      } finally {
        fs.closeSync(fp);
      }
    } catch (e) { /* 0 */ }
    // 两级加载内存曲线的地板:纯载体(SDK.init 之前)。运行时净值 = 运行时就绪 anon − 本基线 anon(≈6-7MB)。
    hilog.info(0x0000, 'TwoLevelMem',
      'STAGE=00_carrier_baseline(纯载体_SDK_init前) | vmRssMb=%{public}d | anonMb=%{public}d',
      carrierBaselinePss, carrierBaselineAnon);
    try {
      const workPath = `${this.context.filesDir}/amphion_asr_work`;
      const deviceIdProvider = new DemoDeviceIdProvider();
      SpeechRecognizeSdk.init(this.context, deviceIdProvider);
      SpeechRecognizeSdk.setWorkPath(workPath);
      hilog.info(0x0000, 'AmphionAsrDemo', 'SpeechRecognizeSdk init done, workPath=%{public}s', workPath);
    } catch (e) {
      hilog.error(0x0000, 'AmphionAsrDemo', 'SpeechRecognizeSdk init failed: %{public}s', `${e}`);
    }
    // Headless SDK contract self-test: `aa start ... --ps selftest true`. Runs every public API and
    // logs a PASS/FAIL matrix under tag SdkSelfTest, without loading the UI.
    const params = want.parameters;
    this.selfTest = params !== undefined && params['selftest'] === 'true';
    this.stressTest = params !== undefined && params['stress'] === 'true';
    this.loadBench = params !== undefined && params['loadbench'] === 'true';
    this.lifecycleBench = params !== undefined && params['lifecycle'] === 'true';
    if (this.lifecycleBench) {
      const options = new LifecycleBenchOptions();
      options.resultPath = this.stringParameter(want, 'lifecycleResult', '');
      options.disablePrepack = this.stringParameter(want, 'prepack', 'on') === 'off';
      options.carrierBaselinePss = carrierBaselinePss;
      options.carrierBaselineAnon = carrierBaselineAnon;
      options.iters = this.numberParameter(want, 'iters', 20);
      runLifecycleBench(this.context, options).catch((e: Object): void => {
        hilog.error(0x0000, 'LifecycleBench', 'lifecycle bench crashed: %{public}s', `${e}`);
      });
    } else if (this.selfTest) {
      runSdkSelfTest(this.context).catch((e: Object): void => {
        hilog.error(0x0000, 'SdkSelfTest', 'self-test crashed: %{public}s', `${e}`);
      });
    } else if (this.loadBench) {
      const options = new ModelLoadBenchOptions();
      options.runId = this.stringParameter(want, 'loadbenchRunId', 'manual');
      options.resultPath = this.stringParameter(want, 'loadbenchResult', '');
      runModelLoadBench(this.context, options).catch((e: Object): void => {
        hilog.error(0x0000, 'ModelLoadBench', 'model load benchmark crashed: %{public}s', `${e}`);
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
      options.enrollmentCount = this.numberParameter(want, 'stressEnrollmentCount', 1);
      options.enforceTargetSpeakerBusinessText =
        this.stringParameter(want, 'stressEnforceTargetSpeakerBusinessText', 'true') === 'true';
      // `aa --ps` treats a leading '-' in the value as another option. Transport the
      // [-2, 1] test value shifted by +2, then restore it inside the carrier.
      options.speakerVadThreshold =
        this.floatParameter(want, 'stressSpeakerVadThreshold', 0) - 2;
      runDeviceStress(this.context, options).catch((e: Object): void => {
        hilog.error(0x0000, 'DeviceStressTest', 'stress test crashed: %{public}s', `${e}`);
      }).finally((): void => {
        this.stressFinished = true;
        this.setStressKeepScreenOn(false);
      });
    }
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    if (this.stressTest) {
      // A real-time corpus run lasts longer than Harmony's content-less foreground grace period.
      // Keep a minimal window attached so the event runner is not suspended between audio frames.
      this.stressWindow = windowStage.getMainWindowSync();
      if (!this.stressFinished) this.setStressKeepScreenOn(true);
      windowStage.loadContent('pages/DeviceTest', (err: BusinessError): void => {
        if (err.code !== 0) {
          hilog.error(0x0000, 'AmphionAsrDemo', 'Failed to load device test page: %{public}s', JSON.stringify(err));
        }
      });
      return;
    }
    if (this.selfTest || this.loadBench || this.lifecycleBench) {
      hilog.info(0x0000, 'AmphionAsrDemo', 'headless test mode: skipping UI');
      return;
    }
    windowStage.loadContent('pages/Index', (err: BusinessError) => {
      if (err.code !== 0) {
        hilog.error(0x0000, 'AmphionAsrDemo', 'Failed to load pages/Index. Cause: %{public}s', JSON.stringify(err));
        return;
      }
      hilog.info(0x0000, 'AmphionAsrDemo', 'Succeeded in loading pages/Index.');
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

  private floatParameter(want: Want, key: string, fallback: number): number {
    const value = want.parameters?.[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string') {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
    return fallback;
  }

  private setStressKeepScreenOn(enabled: boolean): void {
    this.stressWindow?.setWindowKeepScreenOn(enabled).catch((e: Object): void => {
      hilog.error(0x0000, 'AmphionAsrDemo', 'Failed to set test screen state: %{public}s', `${e}`);
    });
  }
}
