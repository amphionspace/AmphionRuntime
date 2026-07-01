import { abilityAccessCtrl, common, Permissions } from '@kit.AbilityKit';
import { promptAction, router } from '@kit.ArkUI';
import { fileIo as fs } from '@kit.CoreFileKit';
import {
  AudioInfo,
  CreateEngineCallback,
  CreateEngineParams,
  DingqiaoEventCode,
  LicenseActivationCallback,
  LicenseActivationResult,
  RecognitionListener,
  SpeechRecognitionEngine,
  SpeechRecognitionResult,
  SpeechRecognizeSdk,
  StartParams
} from 'amphion_dingqiao';
import { AudioRecorder } from '../util/AudioRecorder';
import { PcmFrameWriter } from '../util/PcmFrameWriter';
import { DemoPrefs } from '../util/DemoPrefs';
import { VoiceprintModelHelper } from '../util/VoiceprintModelHelper';

const SESSION_MAX_AUDIO_MS = 60000;
const SESSION_ROTATE_AUDIO_MS = 55000;
const FRAME_AUDIO_MS = 20;
const SPEAKER_VAD_THRESHOLD = 0.40;
const SPEAKER_VAD_WINDOW_MS = 1000;
const SPEAKER_VAD_HOP_MS = 300;
const SPEAKER_VAD_CONSECUTIVE_BELOW = 2;
const BRAND_ACCENT = '#2E6BE6';

class FinalSegment {
  text: string;
  score?: number;

  constructor(text: string, score?: number) {
    this.text = text;
    this.score = score;
  }
}

@Entry
@Component
struct Index {
  @State status: string = '正在初始化引擎…';
  @State partialText: string = '';
  @State finalSegments: FinalSegment[] = [];
  @State listening: boolean = false;
  @State engineReady: boolean = false;
  @State loading: boolean = true;
  @State voiceprintInfo: string = '';
  @State voiceprintModelReady: boolean = false;
  @State voiceprintId: string = '';
  @State voiceprintVerifyDesired: boolean = false;
  @State speakerVadDesired: boolean = false;

  private engine?: SpeechRecognitionEngine;
  private recorder?: AudioRecorder;
  private frameWriter?: PcmFrameWriter;
  private sessionId: string = '';
  private sessionAudioMs: number = 0;
  private rotatingSession: boolean = false;
  private workPath: string = '';
  private appliedHotwordsKey: string = '';

  aboutToAppear(): void {
    this.workPath = SpeechRecognizeSdk.getWorkPath();
    this.initWithPermission();
  }

  onPageShow(): void {
    this.refreshVoiceprintUi();
    // Hotwords edited on the sub-page change sysGeneralLexicon -> rebuild the engine on return.
    if (this.engine !== undefined && this.hotwordsKey() !== this.appliedHotwordsKey) {
      this.reloadEngine();
    }
  }

  aboutToDisappear(): void {
    this.stopListening();
    this.engine?.shutdown();
    this.engine = undefined;
  }

  private async initWithPermission(): Promise<void> {
    const granted = await this.requestMicPermission();
    if (!granted) {
      this.loading = false;
      this.status = '没有录音权限，无法识别';
      this.refreshVoiceprintUi();
      return;
    }
    this.activateLicenseThenInit();
    this.refreshVoiceprintUi();
  }

  // ---- license activation (armed build requires a valid signed license before createEngine) ----

  private activateLicenseThenInit(): void {
    this.loading = true;
    this.engineReady = false;
    this.status = '正在校验授权…';
    let licPath = '';
    try {
      licPath = this.prepareLicenseFile();
    } catch (e) {
      this.loading = false;
      this.status = `授权文件准备失败：${e}`;
      return;
    }
    SpeechRecognizeSdk.setLicense(licPath, new DemoLicenseCallback(this));
  }

  // Copies the bundled signed license out of rawfile into the SDK work path (setLicense needs a real fs path).
  private prepareLicenseFile(): string {
    const ctx = getContext(this) as common.UIAbilityContext;
    const data = ctx.resourceManager.getRawFileContentSync('amphion-license.lic');
    if (!fs.accessSync(this.workPath)) fs.mkdirSync(this.workPath);
    const dest = `${this.workPath}/amphion-license.lic`;
    const dst = fs.openSync(dest, fs.OpenMode.READ_WRITE | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
    try {
      fs.writeSync(dst.fd, data.buffer);
    } finally {
      fs.closeSync(dst);
    }
    return dest;
  }

  onLicenseActivated(): void {
    this.status = '授权通过，正在初始化引擎…';
    this.initEngine();
  }

  onLicenseFailed(errorCode: number, message: string): void {
    this.loading = false;
    this.engineReady = false;
    this.status = `授权失败：${errorCode} ${message}`;
  }

  private async requestMicPermission(): Promise<boolean> {
    const ctx = getContext(this) as common.UIAbilityContext;
    const atManager = abilityAccessCtrl.createAtManager();
    const permissions: Permissions[] = ['ohos.permission.MICROPHONE'];
    try {
      const result = await atManager.requestPermissionsFromUser(ctx, permissions);
      return result.authResults.length > 0 && result.authResults[0] === 0;
    } catch (e) {
      return false;
    }
  }

  private initEngine(): void {
    this.loading = true;
    this.engineReady = false;
    this.status = '正在初始化引擎…';
    SpeechRecognizeSdk.createEngineAsync(this.buildCreateEngineParams(), new DemoCreateEngineCallback(this));
  }

  onEngineCreated(engine: SpeechRecognitionEngine): void {
    this.engine = engine;
    engine.setListener(new DemoRecognitionListener(this));
    this.loading = false;
    this.engineReady = true;
    this.status = '引擎就绪，点击开始识别';
    this.refreshVoiceprintUi();
  }

  onEngineCreateFailed(errorCode: number, message: string): void {
    this.loading = false;
    this.engineReady = false;
    this.status = `引擎初始化失败：${errorCode} ${message}`;
  }

  private buildCreateEngineParams(): CreateEngineParams {
    const params = new CreateEngineParams();
    params.language = 'zh-CN';
    params.online = 1; // DingqiaoOnlineMode.OFFLINE
    const hotwords = DemoPrefs.getUserHotwords(getContext(this) as common.UIAbilityContext);
    this.appliedHotwordsKey = hotwords.join('\n');
    const extra: Record<string, Object> = {};
    if (hotwords.length > 0) {
      extra['sysGeneralLexicon'] = hotwords;
    }
    params.extraParams = extra;
    return params;
  }

  private hotwordsKey(): string {
    return DemoPrefs.getUserHotwords(getContext(this) as common.UIAbilityContext).join('\n');
  }

  private reloadEngine(): void {
    this.stopListening();
    this.engine?.shutdown();
    this.engine = undefined;
    this.toast('热词已更新，正在重建引擎…');
    this.initEngine();
  }

  // ---- recognition lifecycle ----

  private startListening(): void {
    if (!this.engineReady || this.engine === undefined) return;
    if (this.listening) return;
    this.listening = true;
    this.finalSegments = [];
    this.partialText = '';
    this.startRecognitionSession();
  }

  private startRecognitionSession(): void {
    const engine = this.engine;
    if (engine === undefined) return;
    const sid = `demo-${Date.now()}`;
    this.sessionId = sid;
    this.sessionAudioMs = 0;
    this.frameWriter?.reset();

    const ctx = getContext(this) as common.UIAbilityContext;
    const id = DemoPrefs.getVoiceprintId(ctx);
    const hasVoiceprint = id.length > 0;
    const verify = this.voiceprintVerifyDesired && hasVoiceprint;
    const speakerVad = this.speakerVadDesired && hasVoiceprint;

    const extra: Record<string, Object> = {};
    extra['enablePartialResult'] = true;
    extra['maxAudioDuration'] = SESSION_MAX_AUDIO_MS;
    if (verify) {
      extra['enableVoiceprintVerification'] = true;
    }
    if (speakerVad) {
      extra['enableSpeakerVad'] = true;
      extra['speakerVadThreshold'] = SPEAKER_VAD_THRESHOLD;
      extra['speakerVadWindowMs'] = SPEAKER_VAD_WINDOW_MS;
      extra['speakerVadHopMs'] = SPEAKER_VAD_HOP_MS;
      extra['speakerVadConsecutiveBelow'] = SPEAKER_VAD_CONSECUTIVE_BELOW;
    }
    if (hasVoiceprint) {
      extra['voiceprintIds'] = [id];
    }

    const startParams = new StartParams();
    startParams.sessionId = sid;
    startParams.audioInfo = new AudioInfo();
    startParams.extraParams = extra;
    engine.startListening(startParams);
  }

  private writeFrameToCurrentSession(frame: ArrayBuffer): void {
    if (!this.listening || this.sessionId.length === 0) return;
    if (this.sessionAudioMs >= SESSION_ROTATE_AUDIO_MS && !this.rotatingSession) {
      // Proactively rotate before the 60 s SDK cap; onComplete restarts a fresh session.
      this.rotatingSession = true;
      const sid = this.sessionId;
      this.sessionId = '';
      this.sessionAudioMs = 0;
      this.engine?.finish(sid);
    } else {
      this.sessionAudioMs += FRAME_AUDIO_MS;
      this.engine?.writeAudio(this.sessionId, frame);
    }
  }

  private stopListening(): void {
    if (!this.listening) return;
    this.listening = false;
    this.stopCapture();
    const sid = this.sessionId;
    this.sessionId = '';
    this.rotatingSession = false;
    this.sessionAudioMs = 0;
    if (sid.length > 0) {
      this.engine?.finish(sid);
    }
  }

  private startCapture(): void {
    if (this.recorder !== undefined) return;
    const writer = new PcmFrameWriter((frame: ArrayBuffer): void => this.writeFrameToCurrentSession(frame));
    this.frameWriter = writer;
    const recorder = new AudioRecorder(
      (samples: Int16Array): void => writer.accept(samples),
      (msg: string): void => {
        this.stopCapture();
        this.listening = false;
        this.sessionId = '';
        this.engineReady = this.engine !== undefined;
        this.status = `录音错误：${msg}`;
      }
    );
    this.recorder = recorder;
    recorder.start();
  }

  private stopCapture(): void {
    this.recorder?.stop();
    this.recorder = undefined;
    this.frameWriter?.reset();
    this.frameWriter = undefined;
  }

  // ---- listener bridge (called by DemoRecognitionListener) ----

  handleStart(): void {
    this.startCapture();
    this.status = '识别中…（再次点击结束）';
  }

  handleResult(result: SpeechRecognitionResult): void {
    if (result.isFinal) {
      this.appendFinal(result);
      this.partialText = '';
    } else {
      this.partialText = result.result;
    }
  }

  handleEvent(eventCode: number, message: string): void {
    if (eventCode === DingqiaoEventCode.SPEAKER_VAD_REJECTED) {
      this.status = '说话人 VAD：检测到非目标说话人，已截断';
    }
  }

  handleComplete(): void {
    if (this.listening) {
      // Session rotation: relaunch immediately for an uninterrupted listening experience.
      this.rotatingSession = false;
      this.startRecognitionSession();
    } else {
      this.stopCapture();
      this.sessionId = '';
      this.status = '引擎就绪，点击开始识别';
    }
  }

  handleError(errorCode: number, message: string): void {
    this.stopCapture();
    this.status = `错误 ${errorCode}：${message}`;
    this.listening = false;
    this.sessionId = '';
  }

  private appendFinal(result: SpeechRecognitionResult): void {
    if (result.result.length === 0) return;
    const next = this.finalSegments.slice();
    next.push(new FinalSegment(result.result, result.speakerSimilarity));
    this.finalSegments = next;
  }

  // ---- voiceprint UI ----

  private refreshVoiceprintUi(): void {
    const ctx = getContext(this) as common.UIAbilityContext;
    this.voiceprintModelReady = VoiceprintModelHelper.isReady(this.workPath);
    this.voiceprintId = DemoPrefs.getVoiceprintId(ctx);
    if (!this.voiceprintModelReady) {
      this.voiceprintInfo = '未找到声纹模型，请导入 eres2net.onnx';
    } else if (this.voiceprintId.length === 0) {
      this.voiceprintInfo = '未注册声纹';
    } else {
      this.voiceprintInfo = `已注册声纹：${this.voiceprintId}`;
    }
    if (this.voiceprintId.length === 0) {
      this.voiceprintVerifyDesired = false;
      this.speakerVadDesired = false;
    }
  }

  private onVoiceprintSwitch(checked: boolean): void {
    if (checked && this.voiceprintId.length === 0) {
      this.voiceprintVerifyDesired = false;
      this.toast('请先注册声纹');
      return;
    }
    this.voiceprintVerifyDesired = checked;
  }

  private onSpeakerVadSwitch(checked: boolean): void {
    if (checked && this.voiceprintId.length === 0) {
      this.speakerVadDesired = false;
      this.toast('请先注册声纹');
      return;
    }
    this.speakerVadDesired = checked;
    if (this.listening) {
      this.engine?.setSpeakerVadEnabled(checked);
    }
    this.toast(checked ? '说话人 VAD 已开启' : '说话人 VAD 已关闭');
  }

  // ---- menu actions ----

  private openHotwords(): void {
    router.pushUrl({ url: 'pages/Hotwords' }).catch((err: Object): void => {
      this.toast(`打开热词页失败：${err}`);
    });
  }

  private openEnroll(): void {
    router.pushUrl({ url: 'pages/VoiceprintEnroll' }).catch((err: Object): void => {
      this.toast(`打开声纹注册页失败：${err}`);
    });
  }

  private async importModel(): Promise<void> {
    const ctx = getContext(this) as common.UIAbilityContext;
    const ok = await VoiceprintModelHelper.importViaPicker(ctx, this.workPath);
    if (ok) {
      this.toast('声纹模型已导入');
      this.refreshVoiceprintUi();
    } else {
      this.toast('导入失败，请确认选择的是 eres2net.onnx（约 38 MB）');
    }
  }

  private confirmDeleteVoiceprint(): void {
    const ctx = getContext(this) as common.UIAbilityContext;
    const id = DemoPrefs.getVoiceprintId(ctx);
    if (id.length === 0) {
      this.toast('当前没有已注册声纹');
      return;
    }
    SpeechRecognizeSdk.deleteVoiceprint(id);
    DemoPrefs.setVoiceprintId(ctx, '');
    this.voiceprintVerifyDesired = false;
    this.speakerVadDesired = false;
    this.refreshVoiceprintUi();
    this.toast(`已删除声纹：${id}`);
  }

  private toast(message: string): void {
    promptAction.showToast({ message: message, duration: 2000 });
  }

  build() {
    Column({ space: 12 }) {
      Row() {
        Text('鼎桥离线语音识别')
          .fontSize(22)
          .fontWeight(FontWeight.Bold)
          .layoutWeight(1)
        Text('⋮')
          .fontSize(28)
          .fontWeight(FontWeight.Bold)
          .padding({ left: 12, right: 4 })
          .bindMenu([
            { value: '自定义热词', action: (): void => this.openHotwords() },
            { value: '声纹注册', action: (): void => this.openEnroll() },
            { value: '导入声纹模型', action: (): void => { this.importModel(); } },
            { value: '删除声纹', action: (): void => this.confirmDeleteVoiceprint() }
          ])
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Row({ space: 8 }) {
        Circle({ width: 10, height: 10 }).fill(this.listening ? '#2ECC71' : '#BDBDBD')
        Text(this.status).fontSize(13).fontColor(Color.Gray).layoutWeight(1)
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Row() {
        Text('声纹校验').fontSize(15).layoutWeight(1)
        Toggle({ type: ToggleType.Switch, isOn: this.voiceprintVerifyDesired })
          .enabled(this.voiceprintModelReady && this.voiceprintId.length > 0)
          .onChange((isOn: boolean): void => this.onVoiceprintSwitch(isOn))
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Row() {
        Column() {
          Text('说话人 VAD').fontSize(15)
          Text('目标说话人离开时提前截断当前句').fontSize(12).fontColor(Color.Gray)
        }
        .layoutWeight(1)
        .alignItems(HorizontalAlign.Start)
        Toggle({ type: ToggleType.Switch, isOn: this.speakerVadDesired })
          .enabled(this.voiceprintModelReady && this.voiceprintId.length > 0)
          .onChange((isOn: boolean): void => this.onSpeakerVadSwitch(isOn))
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text(this.voiceprintInfo).fontSize(12).fontColor(BRAND_ACCENT).width('100%')

      if (this.loading) {
        Row({ space: 8 }) {
          LoadingProgress().width(22).height(22)
          Text('模型加载中…').fontSize(13).fontColor(Color.Gray)
        }
        .width('100%')
      }

      Text('中间结果').fontSize(14).fontWeight(FontWeight.Medium).width('100%')
      Text(this.partialText.length > 0 ? this.partialText : '等待语音输入…')
        .width('100%')
        .height(56)
        .fontColor(this.partialText.length > 0 ? Color.Black : Color.Gray)
        .backgroundColor('#f5f5f5')
        .borderRadius(8)
        .padding(12)

      Text('最终结果').fontSize(14).fontWeight(FontWeight.Medium).width('100%')
      Scroll() {
        Column({ space: 6 }) {
          if (this.finalSegments.length === 0) {
            Text('识别结果（警务增强）将累积显示在这里。').fontSize(14).fontColor(Color.Gray).width('100%')
          }
          ForEach(this.finalSegments, (item: FinalSegment, index: number) => {
            Text() {
              if (item.score !== undefined) {
                Span(`[声纹相似度 ${item.score.toFixed(2)}] `).fontColor(BRAND_ACCENT).fontWeight(FontWeight.Bold)
              }
              Span(item.text)
            }
            .width('100%')
            .fontSize(16)
          }, (item: FinalSegment, index: number) => `${index}-${item.text}`)
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

      Button(this.listening ? '停止识别' : '开始识别')
        .width('100%')
        .height(48)
        .enabled(this.engineReady)
        .backgroundColor(this.listening ? '#E5533C' : BRAND_ACCENT)
        .onClick((): void => {
          if (this.listening) {
            this.stopListening();
          } else {
            this.startListening();
          }
        })
    }
    .padding(20)
    .width('100%')
    .height('100%')
    .alignItems(HorizontalAlign.Start)
  }
}

class DemoRecognitionListener implements RecognitionListener {
  private owner: Index;

  constructor(owner: Index) {
    this.owner = owner;
  }

  onStart(_sessionId: string, _eventMessage: string): void {
    this.owner.handleStart();
  }

  onEvent(_sessionId: string, eventCode: number, message: string): void {
    this.owner.handleEvent(eventCode, message);
  }

  onResult(_sessionId: string, result: SpeechRecognitionResult): void {
    this.owner.handleResult(result);
  }

  onComplete(_sessionId: string, _eventMessage: string): void {
    this.owner.handleComplete();
  }

  onError(_sessionId: string, errorCode: number, message: string): void {
    this.owner.handleError(errorCode, message);
  }
}

class DemoCreateEngineCallback implements CreateEngineCallback {
  private owner: Index;

  constructor(owner: Index) {
    this.owner = owner;
  }

  onSuccess(engine: SpeechRecognitionEngine): void {
    this.owner.onEngineCreated(engine);
  }

  onError(errorCode: number, message: string): void {
    this.owner.onEngineCreateFailed(errorCode, message);
  }
}

class DemoLicenseCallback implements LicenseActivationCallback {
  private owner: Index;

  constructor(owner: Index) {
    this.owner = owner;
  }

  onResult(result: LicenseActivationResult): void {
    if (result.errorCode === 0) {
      this.owner.onLicenseActivated();
    } else {
      this.owner.onLicenseFailed(result.errorCode, result.message);
    }
  }

  onError(errorCode: number, message: string): void {
    this.owner.onLicenseFailed(errorCode, message);
  }
}
