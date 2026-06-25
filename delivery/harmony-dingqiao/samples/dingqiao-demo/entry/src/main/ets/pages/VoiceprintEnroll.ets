import { abilityAccessCtrl, common, Permissions } from '@kit.AbilityKit';
import { promptAction, router } from '@kit.ArkUI';
import { AudioInfo, SpeechRecognizeSdk, VoiceprintRegisterParams } from 'amphion_dingqiao';
import { AudioRecorder } from '../util/AudioRecorder';
import { EnrollSampleStore } from '../util/EnrollSampleStore';
import { PcmPlayer } from '../util/PcmPlayer';
import { WavIo } from '../util/WavIo';
import { DemoPrefs } from '../util/DemoPrefs';
import { VoiceprintModelHelper } from '../util/VoiceprintModelHelper';

const MIN_SAMPLES = 3;
const MAX_SAMPLES = 5;
const MIN_SEC = 3;
const MAX_SEC = 8;
const BRAND_ACCENT = '#2E6BE6';

/** Voiceprint enrollment: record 3~5 segments of 3~8 s, then call SpeechRecognizeSdk.registerVoiceprint. */
@Entry
@Component
struct VoiceprintEnroll {
  @State samples: string[] = [];
  @State recording: boolean = false;
  @State registering: boolean = false;
  @State status: string = '';
  @State registeredId: string = '';
  @State modelReady: boolean = false;

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
    this.registeredId = DemoPrefs.getVoiceprintId(getContext(this) as common.UIAbilityContext);
    this.modelReady = VoiceprintModelHelper.isReady(this.workPath);
    this.status = `已录制 ${this.samples.length} 段（需要 3~5 段）`;
  }

  private startRecord(): void {
    if (this.samples.length >= MAX_SAMPLES) {
      this.toast(`最多 ${MAX_SAMPLES} 段`);
      return;
    }
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
    if (this.samples.length < MIN_SAMPLES || this.samples.length > MAX_SAMPLES) return;
    if (!this.modelReady) {
      this.toast('未找到声纹模型，请先导入 eres2net.onnx');
      return;
    }
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
        DemoPrefs.setVoiceprintId(ctx, result.voiceprintId);
        this.toast(`注册成功：${result.voiceprintId}`);
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

  private async importModel(): Promise<void> {
    const ctx = getContext(this) as common.UIAbilityContext;
    const ok = await VoiceprintModelHelper.importViaPicker(ctx, this.workPath);
    if (ok) {
      this.toast('声纹模型已导入');
    } else {
      this.toast('导入失败，请确认选择的是 eres2net.onnx（约 38 MB）');
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
      if (sec < MIN_SEC || sec > MAX_SEC) {
        return `样本 ${i + 1} 时长 ${sec.toFixed(1)} 秒，不在 ${MIN_SEC}–${MAX_SEC} 秒范围内`;
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

      Text('录制 3~5 段语音，每段 3~8 秒，覆盖远/中/近距离。注册前须先导入声纹模型 eres2net.onnx。')
        .fontSize(12)
        .fontColor(Color.Gray)
        .width('100%')

      Row({ space: 8 }) {
        Button('导入声纹模型').layoutWeight(1).onClick((): void => { this.importModel(); })
        if (this.registeredId.length > 0) {
          Button('删除已注册声纹')
            .layoutWeight(1)
            .backgroundColor('#E5533C')
            .onClick((): void => this.confirmDeleteVoiceprint())
        }
      }
      .width('100%')

      if (this.registeredId.length > 0) {
        Text(`当前已注册：${this.registeredId}`).fontSize(12).fontColor(BRAND_ACCENT).width('100%')
      }

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

      Button(this.registering ? '正在注册声纹…' : '注册声纹')
        .width('100%')
        .height(46)
        .enabled(!this.recording && !this.registering &&
          this.samples.length >= MIN_SAMPLES && this.samples.length <= MAX_SAMPLES)
        .onClick((): void => this.register())
    }
    .padding(20)
    .width('100%')
    .height('100%')
    .alignItems(HorizontalAlign.Start)
  }
}
