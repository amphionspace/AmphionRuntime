import AbilityConstant from '@ohos.app.ability.AbilityConstant';
import hilog from '@ohos.hilog';
import UIAbility from '@ohos.app.ability.UIAbility';
import Want from '@ohos.app.ability.Want';
import window from '@ohos.window';
import { runTtsSelfTest } from '../util/TtsSelfTest';

export default class EntryAbility extends UIAbility {
  private selfTest: boolean = false;

  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    hilog.info(0x0000, 'LitsTtsHarmony', 'EntryAbility onCreate');
    const params = want.parameters;
    if (params && params['selftest'] === 'true') {
      this.selfTest = true;
    }
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    if (this.selfTest) {
      hilog.info(0x0000, 'LitsTtsHarmony', 'EntryAbility launching headless self-test');
      runTtsSelfTest(this.context)
        .then(() => {
          hilog.info(0x0000, 'TtsSelfTest', 'self-test finished');
        })
        .catch((err: Object) => {
          hilog.error(0x0000, 'TtsSelfTest', 'self-test crashed: %{public}s', JSON.stringify(err));
        });
      return;
    }
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
