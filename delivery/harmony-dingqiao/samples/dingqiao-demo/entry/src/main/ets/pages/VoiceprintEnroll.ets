import { abilityAccessCtrl, common, Permissions } from '@kit.AbilityKit';
import { promptAction, router } from '@kit.ArkUI';
import {
  AudioInfo,
  DINGQIAO_VOICEPRINT_MAX_SEC,
  DINGQIAO_VOICEPRINT_MIN_SAMPLES,
  DINGQIAO_VOICEPRINT_MIN_SEC,
  SpeechRecognizeSdk,
  VoiceprintRegisterParams
} from 'amphion_dingqiao';
import { AudioRecorder } from '../util/AudioRecorder';
import { EnrollSampleStore } from '../util/EnrollSampleStore';
import { PcmPlayer } from '../util/PcmPlayer';
import { WavIo } from '../util/WavIo';
import { DemoPrefs } from '../util/DemoPrefs';

const BRAND_ACCENT = '#2E6BE6';

/** Voiceprint enrollment: record one or more 3~8 s segments, then register their merged embedding. */
@Entry
@Component
struct VoiceprintEnroll {
  @State samples: string[] = [];
  @State recording: boolean = false;
  @State registering: boolean = false;
  @State status: string = '';
  @State registeredId: string = '';

  private store?: EnrollSampleStore;
  private recorder?: AudioRecorder;
  private recChunks: Int16Array[] = [];
  private player: PcmPlayer = new PcmPlayer();
  private workPath: string = '';

  aboutToAppear(): void {
    this.workPath = SpeechRecognizeSdk.getWorkPath();
    this.store = new EnrollSampleStore(`${this.workPath}/enroll_samples`);
    this.requestMicPermission();
    this.reload();
  }

  aboutToDisappear(): void {
    this.recorder?.stop();
    this.player.stop();
  }

  private async requestMicPermission(): Promise<void> {
    const ctx = getContext(this) as common.UIAbilityContext;
    const atManager = abilityAccessCtrl.createAtManager();
    const permissions: Permissions[] = ['ohos.permission.MICROPHONE'];
    try {
      await atManager.requestPermissionsFromUser(ctx, permissions);
    } catch (e) {
      this.toast('没有录音权限');
    }
  }

  private reload(): void {
    const store = this.store;
    if (store === undefined) return;
    this.samples = store.listSamples();
    const ctx = getContext(this) as common.UIAbilityContext;
    this.registeredId = DemoPrefs.getVoiceprintId(ctx);
    const missing = Math.max(0, DINGQIAO_VOICEPRINT_MIN_SAMPLES - this.samples.length);
    this.status = missing > 0 ?
      `已录制 ${this.samples.length} 段，还需 ${missing} 段` :
      `已录制 ${this.samples.length} 段，可注册声纹`;
  }

  private startRecord(): void {
    this.recording = true;
    this.recChunks = [];
    this.status = '录音中…正常说 3~8 秒后结束';
    const recorder = new AudioRecorder(
      (samples: Int16Array): void => { this.recChunks.push(samples); },
      (msg: string): void => { this.toast(msg); }
    );
    this.recorder = recorder;
    recorder.start();
  }

  private async stopRecord(): Promise<void> {
    this.recording = false;
    await this.recorder?.stop();
    this.recorder = undefined;
    const pcm = this.merge(this.recChunks);
    this.recChunks = [];
    if (pcm.length === 0) {
      this.reload();
      return;
    }
    this.store?.addSample(pcm);
    this.reload();
  }

  private onPlay(index: number): void {
    const store = this.store;
    if (store === undefined || index < 0 || index >= this.samples.length) return;
    const pcm = store.readPcm(this.samples[index]);
    this.player.play(pcm, (): void => {});
  }

  private onDelete(index: number): void {
    if (index < 0 || index >= this.samples.length) return;
    const path = this.samples[index];
    AlertDialog.show({
      title: '删除样本？',
      message: '删除后需重新注册声纹。',
      primaryButton: { value: '删除', fontColor: '#E5533C', action: (): void => this.doDeleteSample(path) },
      secondaryButton: { value: '取消', action: (): void => {} }
    });
  }

  private doDeleteSample(path: string): void {
    this.store?.deleteSample(path);
    this.deleteRegisteredIfAny();
    this.reload();
  }

  private register(): void {
    if (this.samples.length < DINGQIAO_VOICEPRINT_MIN_SAMPLES) return;
    const invalid = this.firstInvalidSample();
    if (invalid.length > 0) {
      this.status = invalid;
      this.toast(invalid);
      return;
    }
    this.registering = true;
    this.status = '正在注册声纹…';
    // Defer the blocking SDK call one tick so the "registering" status renders first.
    setTimeout((): void => this.doRegister(), 50);
  }

  private doRegister(): void {
    const ctx = getContext(this) as common.UIAbilityContext;
    try {
      this.deleteRegisteredIfAny();
      const params = new VoiceprintRegisterParams();
      params.voiceprintId = '';
      params.samplePaths = this.samples;
      params.audioInfo = new AudioInfo();
      const result = SpeechRecognizeSdk.registerVoiceprint(params);
      this.registering = false;
      if (result.status === 0) {
        const ids = Object.keys(result.voiceprintId);
        const id = ids.length > 0 ? ids[0] : '';
        DemoPrefs.setVoiceprintId(ctx, id);
        this.toast(`注册成功：${id}`);
        router.back();
      } else {
        this.status = `注册失败：${result.message}`;
        this.toast(`注册失败：${result.message}`);
        this.reload();
      }
    } catch (e) {
      this.registering = false;
      this.status = `注册失败：${e}`;
      this.toast(`注册失败：${e}`);
      this.reload();
    }
  }

  private confirmDeleteVoiceprint(): void {
    if (this.registeredId.length === 0) return;
    AlertDialog.show({
      title: '删除已注册声纹？',
      message: `将删除 SDK 工作目录中的声纹特征。\n\n${this.registeredId}`,
      primaryButton: { value: '删除', fontColor: '#E5533C', action: (): void => this.deleteVoiceprintNow() },
      secondaryButton: { value: '取消', action: (): void => {} }
    });
  }

  private deleteVoiceprintNow(): void {
    const ctx = getContext(this) as common.UIAbilityContext;
    const id = this.registeredId;
    try {
      if (SpeechRecognizeSdk.deleteVoiceprint(id)) {
        DemoPrefs.setVoiceprintId(ctx, '');
        this.toast(`已删除声纹：${id}`);
      } else {
        this.toast(`删除失败，未找到声纹：${id}`);
      }
    } catch (e) {
      this.toast(`删除失败：${e}`);
    }
    this.reload();
  }

  private deleteRegisteredIfAny(): void {
    const ctx = getContext(this) as common.UIAbilityContext;
    const id = DemoPrefs.getVoiceprintId(ctx);
    if (id.length === 0) return;
    try {
      SpeechRecognizeSdk.deleteVoiceprint(id);
    } catch (e) {
      // old id may already be gone; continue
    }
    DemoPrefs.setVoiceprintId(ctx, '');
  }

  private firstInvalidSample(): string {
    const store = this.store;
    if (store === undefined) return '';
    for (let i = 0; i < this.samples.length; i++) {
      const sec = WavIo.durationSecFromBytes(store.fileSize(this.samples[i]));
      if (sec < DINGQIAO_VOICEPRINT_MIN_SEC || sec > DINGQIAO_VOICEPRINT_MAX_SEC) {
        return `样本 ${i + 1} 时长 ${sec.toFixed(1)} 秒，不在 ` +
          `${DINGQIAO_VOICEPRINT_MIN_SEC}–${DINGQIAO_VOICEPRINT_MAX_SEC} 秒范围内`;
      }
    }
    return '';
  }

  private sampleLabel(index: number): string {
    const store = this.store;
    const bytes = store === undefined ? 0 : store.fileSize(this.samples[index]);
    const sec = WavIo.durationSecFromBytes(bytes);
    return `样本 ${index + 1} · ${sec.toFixed(1)}s`;
  }

  private registerButtonText(): string {
    if (this.registering) return '正在注册声纹…';
    if (this.samples.length < DINGQIAO_VOICEPRINT_MIN_SAMPLES) {
      return `还需录制 ${DINGQIAO_VOICEPRINT_MIN_SAMPLES - this.samples.length} 段`;
    }
    return '注册声纹';
  }

  private merge(chunks: Int16Array[]): Int16Array {
    let total = 0;
    for (let i = 0; i < chunks.length; i++) total += chunks[i].length;
    if (total === 0) return new Int16Array(0);
    const out = new Int16Array(total);
    let off = 0;
    for (let i = 0; i < chunks.length; i++) {
      out.set(chunks[i], off);
      off += chunks[i].length;
    }
    return out;
  }

  private toast(message: string): void {
    promptAction.showToast({ message: message, duration: 2000 });
  }

  build() {
    Column({ space: 12 }) {
      Row({ space: 8 }) {
        Text('返回').fontSize(16).fontColor(BRAND_ACCENT).onClick((): void => { router.back(); })
        Text('声纹注册').fontSize(20).fontWeight(FontWeight.Bold).layoutWeight(1)
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text('录制至少 1 段语音，每段 3~8 秒；多录几段并覆盖远/中/近距离可提升稳定性。')
        .fontSize(12)
        .fontColor(Color.Gray)
        .width('100%')

      if (this.registeredId.length > 0) {
        Row({ space: 8 }) {
          Button('删除已注册声纹')
            .layoutWeight(1)
            .backgroundColor('#E5533C')
            .onClick((): void => this.confirmDeleteVoiceprint())
        }
        .width('100%')
      }

      if (this.registeredId.length > 0) {
        Text(`当前已注册：${this.registeredId}`).fontSize(12).fontColor(BRAND_ACCENT).width('100%')
      }

      Text('声纹模型已随 SDK 内置').fontSize(12).fontColor(BRAND_ACCENT).width('100%')

      Text(this.status).fontSize(13).fontColor(Color.Gray).width('100%')

      Scroll() {
        Column({ space: 8 }) {
          if (this.samples.length === 0) {
            Text('还没有录音样本').fontSize(14).fontColor(Color.Gray).width('100%')
          }
          ForEach(this.samples, (item: string, index: number) => {
            Row({ space: 8 }) {
              Text(this.sampleLabel(index)).fontSize(15).layoutWeight(1)
              Text('播放').fontSize(14).fontColor(BRAND_ACCENT).onClick((): void => this.onPlay(index))
              Text('删除').fontSize(14).fontColor('#E5533C').onClick((): void => this.onDelete(index))
            }
            .width('100%')
            .padding({ top: 8, bottom: 8 })
            .alignItems(VerticalAlign.Center)
          }, (item: string, index: number) => `${index}-${item}`)
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      }
      .layoutWeight(1)
      .width('100%')
      .backgroundColor('#f5f5f5')
      .borderRadius(8)
      .padding(12)
      .align(Alignment.TopStart)

      Button(this.recording ? '结束本段' : '录制一段')
        .width('100%')
        .height(46)
        .enabled(!this.registering)
        .backgroundColor(this.recording ? '#E5533C' : BRAND_ACCENT)
        .onClick((): void => {
          if (this.recording) {
            this.stopRecord();
          } else {
            this.startRecord();
          }
        })

      Button(this.registerButtonText())
        .width('100%')
        .height(46)
        .enabled(!this.recording && !this.registering &&
          this.samples.length >= DINGQIAO_VOICEPRINT_MIN_SAMPLES)
        .onClick((): void => this.register())
    }
    .padding(20)
    .width('100%')
    .height('100%')
    .alignItems(HorizontalAlign.Start)
  }
}
