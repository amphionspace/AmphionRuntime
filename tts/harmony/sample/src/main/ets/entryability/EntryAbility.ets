import AbilityConstant from '@ohos.app.ability.AbilityConstant';
import hilog from '@ohos.hilog';
import UIAbility from '@ohos.app.ability.UIAbility';
import Want from '@ohos.app.ability.Want';
import window from '@ohos.window';

export default class EntryAbility extends UIAbility {
  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    hilog.info(0x0000, 'LitsTtsHarmony', 'EntryAbility onCreate');
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    windowStage.loadContent('pages/Index', (err) => {
      if (err.code) {
        hilog.error(0x0000, 'LitsTtsHarmony', 'Failed to load page: %{public}s', JSON.stringify(err));
      }
    });
  }

  onDestroy(): void {
    hilog.info(0x0000, 'LitsTtsHarmony', 'EntryAbility onDestroy');
  }
}
