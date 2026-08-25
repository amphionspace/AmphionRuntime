import ChildProcess from '@ohos.app.ability.ChildProcess';
import type { ChildProcessArgs } from '@ohos.app.ability.ChildProcessArgs';
import { SpeakerDiarizationChildService } from 'amphion_dingqiao';

export default class SpeakerDiarizationChild extends ChildProcess {
  private readonly service: SpeakerDiarizationChildService =
    new SpeakerDiarizationChildService();

  onStart(args?: ChildProcessArgs): void {
    void this.service.start(args?.entryParams ?? '');
  }
}
