import ChildProcess from '@ohos.app.ability.ChildProcess';
import type { ChildProcessArgs } from '@ohos.app.ability.ChildProcessArgs';
import { MeetingSpeakerChildService } from 'amphion_dingqiao';

export default class MeetingSpeakerChild extends ChildProcess {
  private readonly service: MeetingSpeakerChildService = new MeetingSpeakerChildService();

  onStart(args?: ChildProcessArgs): void {
    void this.service.start(args?.entryParams ?? '');
  }
}
