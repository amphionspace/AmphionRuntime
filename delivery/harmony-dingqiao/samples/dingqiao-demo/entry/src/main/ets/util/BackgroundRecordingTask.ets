import { common, wantAgent, WantAgent } from '@kit.AbilityKit';
import { backgroundTaskManager } from '@kit.BackgroundTasksKit';
import hilog from '@ohos.hilog';

/** Host-side continuous task required for recording and recognition while the screen is locked. */
export class BackgroundRecordingTask {
  private static running: boolean = false;
  private static startTask?: Promise<void>;

  static start(context: common.UIAbilityContext): Promise<void> {
    if (BackgroundRecordingTask.running) return Promise.resolve();
    if (BackgroundRecordingTask.startTask !== undefined) return BackgroundRecordingTask.startTask;
    const task = BackgroundRecordingTask.startNow(context).finally((): void => {
      BackgroundRecordingTask.startTask = undefined;
    });
    BackgroundRecordingTask.startTask = task;
    return task;
  }

  static async stop(context: common.UIAbilityContext): Promise<void> {
    const pending = BackgroundRecordingTask.startTask;
    if (pending !== undefined) await pending;
    if (!BackgroundRecordingTask.running) return;
    await backgroundTaskManager.stopBackgroundRunning(context);
    BackgroundRecordingTask.running = false;
    hilog.info(0x0000, 'BackgroundRecording', 'AUDIO_RECORDING continuous task stopped');
  }

  private static async startNow(context: common.UIAbilityContext): Promise<void> {
    const info: wantAgent.WantAgentInfo = {
      wants: [{
        bundleName: context.abilityInfo.bundleName,
        abilityName: context.abilityInfo.name
      }],
      operationType: wantAgent.OperationType.START_ABILITY,
      requestCode: 0,
      wantAgentFlags: [wantAgent.WantAgentFlags.UPDATE_PRESENT_FLAG]
    };
    const agent: WantAgent = await wantAgent.getWantAgent(info);
    await backgroundTaskManager.startBackgroundRunning(
      context, backgroundTaskManager.BackgroundMode.AUDIO_RECORDING, agent);
    BackgroundRecordingTask.running = true;
    hilog.info(0x0000, 'BackgroundRecording', 'AUDIO_RECORDING continuous task started');
  }
}
