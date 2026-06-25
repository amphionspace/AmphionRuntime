import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { window } from '@kit.ArkUI';
import hilog from '@ohos.hilog';
import { SpeechRecognizeSdk } from 'amphion_dingqiao';

export default class EntryAbility extends UIAbility {
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
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    windowStage.loadContent('pages/Index', (err: BusinessError) => {
      if (err.code !== 0) {
        hilog.error(0x0000, 'DingqiaoDemo', 'Failed to load pages/Index. Cause: %{public}s', JSON.stringify(err));
        return;
      }
      hilog.info(0x0000, 'DingqiaoDemo', 'Succeeded in loading pages/Index.');
    });
  }
}
