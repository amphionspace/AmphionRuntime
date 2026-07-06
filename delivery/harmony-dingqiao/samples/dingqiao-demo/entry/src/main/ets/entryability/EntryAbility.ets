import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { window } from '@kit.ArkUI';
import hilog from '@ohos.hilog';
import { SpeechRecognizeSdk } from 'amphion_dingqiao';
import { runSdkSelfTest } from '../util/SdkSelfTest';

export default class EntryAbility extends UIAbility {
  private selfTest: boolean = false;

  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    // Process-level SDK init + work directory live here (mirrors Android DingqiaoApp) so every page
    // shares one SpeechRecognizeSdk instance and the same {filesDir}/dingqiao_work path.
    try {
      const workPath = `${this.context.filesDir}/dingqiao_work`;
      SpeechRecognizeSdk.init(this.context);
      SpeechRecognizeSdk.setWorkPath(workPath);
      hilog.info(0x0000, 'DingqiaoDemo', 'SpeechRecognizeSdk init done, workPath=%{public}s', workPath);
    } catch (e) {
      hilog.error(0x0000, 'DingqiaoDemo', 'SpeechRecognizeSdk init failed: %{public}s', `${e}`);
    }
    // Headless SDK contract self-test: `aa start ... --ps selftest true`. Runs every public API and
    // logs a PASS/FAIL matrix under tag SdkSelfTest, without loading the UI.
    const params = want.parameters;
    this.selfTest = params !== undefined && params['selftest'] === 'true';
    if (this.selfTest) {
      runSdkSelfTest(this.context).catch((e: Object): void => {
        hilog.error(0x0000, 'SdkSelfTest', 'self-test crashed: %{public}s', `${e}`);
      });
    }
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    if (this.selfTest) {
      hilog.info(0x0000, 'DingqiaoDemo', 'self-test mode: skipping UI');
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
}
