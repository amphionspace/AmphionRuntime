import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import hilog from '@ohos.hilog';
import deviceInfo from '@ohos.deviceInfo';
import BuildProfile from 'BuildProfile';
import { AmphionLogLevel, LicenseDeviceIdProvider, SpeechRecognizeSdk } from 'amphion_dingqiao';

const TAG = 'AmphionVoice';

class AppDeviceIdProvider implements LicenseDeviceIdProvider {
  getDeviceSerial(_context: Context): string | undefined {
    // Third-party apps cannot read the hardware serial; ODID is stable per developer and device.
    const id = deviceInfo.ODID;
    return id.length > 0 ? id : undefined;
  }
}

export default class EntryAbility extends UIAbility {
  onCreate(want: Want, _launchParam: AbilityConstant.LaunchParam): void {
    this.acceptReplay(want);
    try {
      SpeechRecognizeSdk.setLogLevel(BuildProfile.DEBUG ? AmphionLogLevel.INFO : AmphionLogLevel.WARN);
      SpeechRecognizeSdk.init(this.context, new AppDeviceIdProvider());
      SpeechRecognizeSdk.setWorkPath(`${this.context.filesDir}/amphion_asr_work`);
      if (BuildProfile.DEBUG) {
        // Debug builds print the license device identity so an internal license can be issued.
        hilog.info(0x0000, TAG, 'license device id: %{public}s', deviceInfo.ODID);
      }
    } catch (e) {
      hilog.error(0x0000, TAG, 'sdk init failed: %{public}s', `${e}`);
    }
  }

  onNewWant(want: Want, _launchParam: AbilityConstant.LaunchParam): void {
    this.acceptReplay(want);
  }

  /** Debug builds only: `--ps replay <wav> --ps engine local|cloud` queues a file replay for acceptance. */
  private acceptReplay(want: Want): void {
    if (!BuildProfile.DEBUG) return;
    const file = want.parameters?.['replay'];
    if (typeof file !== 'string' || file.length === 0) return;
    const engine = want.parameters?.['engine'];
    AppStorage.setOrCreate<string>('debugReplayEngine', typeof engine === 'string' ? engine : 'local');
    AppStorage.setOrCreate<string>('debugReplay', file);
    hilog.info(0x0000, TAG, 'debug replay queued: %{public}s', file);
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    windowStage.loadContent('pages/Index', (err): void => {
      if (err.code) {
        hilog.error(0x0000, TAG, 'loadContent failed: %{public}s', JSON.stringify(err));
        return;
      }
      try {
        const main = windowStage.getMainWindowSync();
        main.setWindowLayoutFullScreen(true);
        // Light status-bar content over the dark header.
        main.setWindowSystemBarProperties({ statusBarContentColor: '#FFFFFF', navigationBarContentColor: '#000000' });
        const top = main.getWindowAvoidArea(window.AvoidAreaType.TYPE_SYSTEM).topRect.height;
        const bottom = main.getWindowAvoidArea(window.AvoidAreaType.TYPE_NAVIGATION_INDICATOR).bottomRect.height;
        AppStorage.setOrCreate<number>('insetTopPx', top);
        AppStorage.setOrCreate<number>('insetBottomPx', bottom);
      } catch (e) {
        hilog.warn(0x0000, TAG, 'window style: %{public}s', `${e}`);
      }
    });
  }
}
