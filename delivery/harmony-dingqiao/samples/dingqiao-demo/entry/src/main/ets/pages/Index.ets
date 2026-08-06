import { abilityAccessCtrl, common, Permissions } from '@kit.AbilityKit';
import { promptAction, router } from '@kit.ArkUI';
import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import hilog from '@ohos.hilog';
import {
  AudioInfo,
  CreateEngineCallback,
  CreateEngineParams,
  DingqiaoEventCode,
  LicenseActivationCallback,
  LicenseActivationResult,
  PrepareRuntimeCallback,
  RecognitionListener,
  SpeechRecognitionEngine,
  SpeechRecognitionResult,
  SpeechRecognizeSdk,
  StartParams
} from 'amphion_dingqiao';
import { AudioRecorder, AudioRecorderStats } from '../util/AudioRecorder';
import { PcmPlayer } from '../util/PcmPlayer';
import { PcmFrameWriter } from '../util/PcmFrameWriter';
import { DemoPrefs } from '../util/DemoPrefs';
import { DemoErrorCleanupGate } from '../util/DemoErrorCleanupGate';
import { DemoSessionDebug } from '../util/DemoSessionDebug';
import {
  applySpeakerPipelineConfig,
  captureSpeakerPipelineConfig,
  SpeakerPipelineConfig
} from '../util/SpeakerPipelineConfig';
import { WavIo } from '../util/WavIo';

const SESSION_MAX_AUDIO_MS = 60000;
const SESSION_ROTATE_AUDIO_MS = 55000;
const FRAME_AUDIO_MS = 20;
const SDK_FRAME_BYTES = 640;
const SDK_CAPTURE_MAX_FRAMES = SESSION_ROTATE_AUDIO_MS / FRAME_AUDIO_MS;
const SDK_CAPTURE_WAV = 'last_sdk_input.wav';
const SDK_CAPTURE_META = 'last_sdk_input.json';
const SDK_CAPTURE_EXPORT_WAV = '/data/storage/el2/base/files/last_sdk_input.wav';
const SDK_CAPTURE_EXPORT_META = '/data/storage/el2/base/files/last_sdk_input.json';
const REPLAY_YIELD_EVERY_FRAMES = 50;
// pre-roll 缓存上限:模型冷加载 ~0.5s,正常只缓存 ~25 帧;给 10s(500 帧)裕量防加载异常久时无界增长。
const MAX_PREROLL_FRAMES = 500;
const BRAND_ACCENT = '#2E6BE6';

class FinalSegment {
  text: string;
  score?: number;
  targetSpeakerEnhancementApplied: boolean;

  constructor(text: string, score?: number, targetSpeakerEnhancementApplied: boolean = false) {
    this.text = text;
    this.score = score;
    this.targetSpeakerEnhancementApplied = targetSpeakerEnhancementApplied;
  }
}

@Entry
@Component
struct Index {
  @State status: string = '正在初始化运行时…';
  @State partialText: string = '';
  @State finalSegments: FinalSegment[] = [];
  @State listening: boolean = false;
  // 两级加载工况:runtimeReady=L1 运行时就绪(常驻、未加载模型);engineReady=L2 模型已在内存。
  @State runtimeReady: boolean = false;
  @State engineReady: boolean = false;
  @State loading: boolean = true;
  @State loadingHint: string = '正在初始化运行时…';
  @State voiceprintInfo: string = '';
  @State voiceprintId: string = '';
  @State voiceprintVerifyDesired: boolean = false;
  @State speakerVadDesired: boolean = false;
  @State targetSpeakerEnhancementDesired: boolean = false;
  @State policeEnhancementDesired: boolean = true;
  @State captureReady: boolean = false;
  @State captureInfo: string = '尚未保存 SDK 输入 PCM';
  @State replaying: boolean = false;
  @State replayHasCompleted: boolean = false;
  @State playingCapture: boolean = false;
  @State liveHasCompleted: boolean = false;
  @State liveCompareText: string = '';
  @State replayCompareText: string = '';
  @State compareInfo: string = '';
  @State debugExpanded: boolean = false;
  @State debugSummary: string = '尚未开始识别';
  @State debugTrace: string = '';
  @State errorCleanupInProgress: boolean = false;

  private engine?: SpeechRecognitionEngine;
  private recorder?: AudioRecorder;
  private capturePlayer: PcmPlayer = new PcmPlayer();
  private frameWriter?: PcmFrameWriter;
  private sessionId: string = '';
  private sessionAudioMs: number = 0;
  private rotatingSession: boolean = false;
  private stoppingListening: boolean = false;
  private workPath: string = '';
  private appliedHotwordsKey: string = '';
  // 用户点了「开始识别」触发按需加载,加载完成后才真正开录;导航离开则丢弃这次加载。
  private startPending: boolean = false;
  private active: boolean = true;
  // 点击即开麦 + 模型异步加载:加载期间麦克风帧进 pre-roll 缓存,模型就绪后回灌再转 live(一帧不丢)。
  private modelReady: boolean = false;
  private preRoll: ArrayBuffer[] = [];
  private preRollDroppedFrames: number = 0;
  private micFirstFrameLogged: boolean = false;
  private startTapMs: number = 0;
  // 两级加载内存埋点(/proc 权威):运行时就绪时的私有 anon 地板 + 本轮推理峰值,供卸载前后对照。
  private runtimeAnonMb: number = -1;
  private peakAnonMb: number = 0;
  private peakVmRssMb: number = 0;
  // Debug capture is taken at the public SDK writeAudio boundary. It therefore includes pre-roll
  // replay and PcmFrameWriter's zero-padded last frame, but intentionally excludes Runtime.stop's
  // synthetic 1280 ms right context (live and replay each add that exactly once in finish()).
  private sdkCaptureFrames: ArrayBuffer[] = [];
  private sdkCaptureTruncated: boolean = false;
  private sdkCaptureBytes: number = 0;
  private sdkCaptureRmsDbfs: number = -120;
  private sdkCapturePeak: number = 0;
  private sdkCaptureClipSamples: number = 0;
  private recorderStats: AudioRecorderStats = new AudioRecorderStats();
  private replaySessionId: string = '';
  private capturedHotwords: string[] = [];
  private capturedVoiceprintId: string = '';
  private capturedVoiceprintVerify: boolean = false;
  private capturedSpeakerVad: boolean = false;
  private capturedTargetSpeakerEnhancement: boolean = false;
  private capturedPoliceEnhancement: boolean = true;
  private capturedSpeakerPipeline: SpeakerPipelineConfig = new SpeakerPipelineConfig();
  private sessionDebug: DemoSessionDebug = new DemoSessionDebug();
  private errorCleanupGate: DemoErrorCleanupGate = new DemoErrorCleanupGate();

  aboutToAppear(): void {
    this.workPath = SpeechRecognizeSdk.getWorkPath();
    const context = getContext(this) as common.UIAbilityContext;
    this.policeEnhancementDesired = DemoPrefs.getPoliceEnhancementEnabled(context);
    this.targetSpeakerEnhancementDesired = DemoPrefs.getTargetSpeakerEnhancementEnabled(context);
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
    this.active = false;
    this.startPending = false;
    this.capturePlayer.stop();
    this.playingCapture = false;
    if (this.replaying) {
      const sid = this.replaySessionId;
      this.replaying = false;
      this.replaySessionId = '';
      if (sid.length > 0 && this.engine?.isBusy()) this.engine.cancel(sid);
      this.releaseModel('');
    } else if (this.listening) {
      // stopListening owns recorder drain -> capture save -> SDK finish; onComplete then unloads.
      this.stopListening();
    } else {
      this.releaseModel('');
    }
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
    this.status = '授权通过，正在拉起运行时…';
    this.prepareRuntimeStep();
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

  // L1:启动时只把运行时框架拉起来常驻(~15-20MB,不加载内存模型),等用户点开始识别再按需加载模型。
  // 甲方工况:「不占内存的运行时常驻加速;占内存的模型用时当场起、用完释放」。
  private prepareRuntimeStep(): void {
    this.loading = true;
    this.loadingHint = '正在拉起运行时…';
    this.runtimeReady = false;
    this.engineReady = false;
    this.status = '正在拉起运行时…';
    SpeechRecognizeSdk.prepareRuntime(new DemoPrepareRuntimeCallback(this));
  }

  onRuntimeReady(): void {
    this.runtimeReady = true;
    this.loading = false;
    this.engineReady = false;
    this.status = '运行时就绪（未加载模型）· 点击开始识别按需加载';
    // L1 常驻地板:记下运行时就绪时的私有 anon,后续「净值」都相对它算。
    this.runtimeAnonMb = this.sampleMemMb()[1];
    this.logMem('01_runtime_ready(L1常驻_无模型)');
    this.refreshVoiceprintUi();
  }

  onRuntimeFailed(errorCode: number, message: string): void {
    this.loading = false;
    this.runtimeReady = false;
    this.status = `运行时拉起失败：${errorCode} ${message}`;
  }

  // L2 加载完成回调(由「开始识别」触发的按需加载)。加载完直接开录。
  onEngineCreated(engine: SpeechRecognitionEngine): void {
    if (!this.active || (!this.listening && !this.replaying)) {
      // 加载途中用户已离开本页 / 已取消当前输入:直接释放,避免残留会话与内存。
      engine.shutdown();
      SpeechRecognizeSdk.unloadModel();
      this.startPending = false;
      this.loading = false;
      return;
    }
    this.engine = engine;
    engine.setListener(new DemoRecognitionListener(this));
    this.engineReady = true;
    this.startPending = false;
    // L2 冷加载完成:模型已在内存(关 prepack)。
    this.peakAnonMb = 0;
    this.peakVmRssMb = 0;
    this.logStartTiming('model_loaded(模型冷加载完成)');
    this.logMem('02_model_loaded(L2冷加载完_关prepack)');
    this.debugRecord('engine_created', this.replaySessionId,
      `replay=${this.replaying} preRollFrames=${this.preRoll.length}`);
    if (this.replaying) {
      this.loading = false;
      this.loadingHint = '';
      this.startSavedPcmReplay();
      return;
    }
    // 麦克风点击时已开始录音,模型就绪 → 建会话并把 pre-roll 缓存回灌,转 live。
    this.startSessionAndFlush();
  }

  onEngineCreateFailed(errorCode: number, message: string): void {
    this.loading = false;
    this.engineReady = false;
    this.startPending = false;
    this.debugRecord('engine_create_error', this.replaySessionId, `code=${errorCode} message=${message}`);
    if (this.replaying) {
      this.replaying = false;
      this.replaySessionId = '';
      this.compareInfo = `原样复测失败：${errorCode} ${message}`;
      this.status = this.compareInfo;
    } else {
      const errorStatus = `模型加载失败：${errorCode} ${message}`;
      this.listening = false;
      this.modelReady = false;
      this.preRoll = [];
      this.sessionId = '';
      this.releaseModel(errorStatus);
      this.saveLiveErrorArtifacts();
    }
  }

  private buildCreateEngineParams(hotwordsOverride?: string[]): CreateEngineParams {
    const params = new CreateEngineParams();
    params.language = 'zh-CN';
    params.online = 1; // DingqiaoOnlineMode.OFFLINE
    const hotwords = hotwordsOverride ??
      DemoPrefs.getUserHotwords(getContext(this) as common.UIAbilityContext);
    this.appliedHotwordsKey = hotwords.join('\n');
    const extra: Record<string, Object> = {};
    if (hotwords.length > 0) {
      extra['sysGeneralLexicon'] = hotwords;
    }
    // 关 prepack:按需加载工况下每次「开始识别」都冷加载模型,关掉 INT8 权重 prepack 可省 ~91-156ms
    // 冷加载并降低峰值内存(交付方向 = prepack off,详见两级加载 A/B)。
    extra['disablePrepack'] = true;
    params.extraParams = extra;
    return params;
  }

  private hotwordsKey(): string {
    return DemoPrefs.getUserHotwords(getContext(this) as common.UIAbilityContext).join('\n');
  }

  private async reloadEngine(): Promise<void> {
    // 按需加载模型:热词变了只需卸掉当前模型,下次「开始识别」会用新热词冷加载。
    await this.stopListening();
    this.releaseModel('热词已更新 · 下次识别将按新热词加载');
    this.toast('热词已更新，下次识别按新热词加载');
  }

  // ---- recognition lifecycle ----

  private startListening(): void {
    if (!this.runtimeReady) return;
    if (!this.errorCleanupGate.canStart()) return;
    if (this.listening || this.replaying || this.playingCapture) return;
    this.startTapMs = Date.now();
    this.finalSegments = [];
    this.partialText = '';
    this.preRoll = [];
    this.preRollDroppedFrames = 0;
    this.micFirstFrameLogged = false;
    this.resetSdkCapture();
    const ctx = getContext(this) as common.UIAbilityContext;
    this.capturedHotwords = DemoPrefs.getUserHotwords(ctx);
    this.capturedVoiceprintId = DemoPrefs.getVoiceprintId(ctx);
    this.capturedSpeakerPipeline = captureSpeakerPipelineConfig(
      this.capturedVoiceprintId,
      this.voiceprintVerifyDesired,
      this.speakerVadDesired,
      this.targetSpeakerEnhancementDesired);
    this.capturedVoiceprintVerify = this.capturedSpeakerPipeline.voiceprintVerify;
    this.capturedSpeakerVad = this.capturedSpeakerPipeline.speakerVad;
    this.capturedTargetSpeakerEnhancement = this.capturedSpeakerPipeline.targetSpeakerEnhancement;
    this.capturedPoliceEnhancement = this.policeEnhancementDesired;
    this.sessionDebug = new DemoSessionDebug(this.startTapMs);
    this.sessionDebug.configure(
      this.capturedVoiceprintId,
      this.capturedVoiceprintVerify,
      this.capturedSpeakerVad,
      this.capturedTargetSpeakerEnhancement,
      this.capturedPoliceEnhancement);
    hilog.info(0x0000, 'DemoDebug',
      'stage=config_snapshot|voiceprintIdCount=%{public}d|voiceprintVerify=%{public}s' +
      '|speakerVad=%{public}s|targetSpeakerEnhancement=%{public}s|policeEnhancement=%{public}s' +
      '|hotwordCount=%{public}d',
      this.capturedVoiceprintId.length > 0 ? 1 : 0,
      String(this.capturedVoiceprintVerify), String(this.capturedSpeakerVad),
      String(this.capturedTargetSpeakerEnhancement), String(this.capturedPoliceEnhancement),
      this.capturedHotwords.length);
    this.debugRecord('start_tap', '', `engineReady=${this.engine !== undefined}`);
    this.liveCompareText = '';
    this.liveHasCompleted = false;
    this.replayCompareText = '';
    this.replayHasCompleted = false;
    this.compareInfo = '';
    this.listening = true;                         // UI 立即进入识别态,按钮变「停止识别」
    this.modelReady = (this.engine !== undefined);
    // ① 立即开麦(与模型冷加载并行);模型没好时,麦克风帧先进 pre-roll 缓存不丢。
    this.startCapture();
    this.logStartTiming('mic_start_issued(已发起开麦)');
    if (this.engine !== undefined) {
      // 模型已在内存:直接建会话喂 live(无缓存)。
      this.startSessionAndFlush();
    } else {
      // ② 并行冷加载模型;完成后在 onEngineCreated 建会话并回灌 pre-roll。
      this.startPending = true;
      this.loading = true;
      this.loadingHint = '模型加载中（语音已在缓存,加载完立即识别）…';
      this.status = '录音中 · 模型加载中（语音已缓存,加载完立即识别）…';
      SpeechRecognizeSdk.createEngineAsync(
        this.buildCreateEngineParams(this.capturedHotwords),
        new DemoCreateEngineCallback(this));
    }
  }

  // 建会话 → 把加载期间缓存的 pre-roll 帧按序回灌 → 转 live。模型就绪(冷加载完 or 已在内存)后调用。
  private startSessionAndFlush(): void {
    if (!this.startRecognitionSession()) {
      // startListening may synchronously call onError (for example, enhancement model missing).
      // Keep that error state and never overwrite it with a false "recognizing" state.
      this.preRoll = [];
      this.modelReady = false;
      this.loading = false;
      return;
    }
    const buffered = this.preRoll;
    this.preRoll = [];
    this.modelReady = true;
    for (let i = 0; i < buffered.length; i++) {
      this.feedFrameLive(buffered[i]);
    }
    this.loading = false;
    this.status = '识别中…（再次点击结束）';
    this.debugRecord('pre_roll_flushed', this.sessionId,
      `frames=${buffered.length} dropped=${this.preRollDroppedFrames}`);
    this.logStartTiming(`session_ready(回灌 preRoll=${buffered.length} 帧, 丢=${this.preRollDroppedFrames})`);
  }

  // ---- 两级加载内存埋点(tag=TwoLevelMem,/proc 权威) ----
  // /proc 文件 stat 报 size=0,fs.readTextSync 会读到空;必须 openSync+readSync 读到 EOF(与 LifecycleBench.procMem 一致)。
  private sampleMemMb(): number[] {
    try {
      const fp = fs.openSync('/proc/self/status', fs.OpenMode.READ_ONLY);
      try {
        const buf = new ArrayBuffer(8192);
        const n = fs.readSync(fp.fd, buf);
        const text = util.TextDecoder.create('utf-8').decodeToString(new Uint8Array(buf.slice(0, n)));
        const g = (key: string): number => {
          const m = text.match(new RegExp(key + ':\\s*(\\d+)\\s*kB'));
          return m !== null ? Math.round(Number(m[1]) / 1024) : -1;
        };
        return [g('VmRSS'), g('RssAnon'), g('RssFile')];
      } finally {
        fs.closeSync(fp);
      }
    } catch (e) {
      return [-1, -1, -1];
    }
  }

  private logMem(stage: string): void {
    const m = this.sampleMemMb();
    const net = (this.runtimeAnonMb >= 0 && m[1] >= 0) ? (m[1] - this.runtimeAnonMb) : -1;
    hilog.info(0x0000, 'TwoLevelMem',
      'STAGE=%{public}s | vmRssMb=%{public}d | anonMb=%{public}d | fileMb=%{public}d | netAnonMb(减运行时)=%{public}d',
      stage, m[0], m[1], m[2], net);
  }

  // 推理期高频采样,记录本轮峰值(解码同步发生,partial 紧随其后,足够贴近峰值)。
  private trackPeak(): void {
    const m = this.sampleMemMb();
    if (m[0] > this.peakVmRssMb) this.peakVmRssMb = m[0];
    if (m[1] > this.peakAnonMb) this.peakAnonMb = m[1];
  }

  private startRecognitionSession(): boolean {
    const engine = this.engine;
    if (engine === undefined) return false;
    const sid = `demo-${Date.now()}`;
    this.sessionId = sid;
    this.sessionAudioMs = 0;
    this.debugRecord('startListening', sid,
      `targetEnhancement=${this.capturedTargetSpeakerEnhancement} speakerVad=${this.capturedSpeakerVad}`);
    engine.startListening(this.buildCapturedStartParams(sid));
    return engine.isBusy() && this.sessionId === sid;
  }

  private buildCapturedStartParams(sessionId: string): StartParams {
    const extra: Record<string, Object> = {};
    extra['enablePartialResult'] = true;
    extra['maxAudioDuration'] = SESSION_MAX_AUDIO_MS;
    extra['enablePoliceEnhancement'] = this.capturedPoliceEnhancement;
    applySpeakerPipelineConfig(extra, this.capturedSpeakerPipeline);

    const startParams = new StartParams();
    startParams.sessionId = sessionId;
    startParams.audioInfo = new AudioInfo();
    startParams.extraParams = extra;
    return startParams;
  }

  private writeFrameToCurrentSession(frame: ArrayBuffer): void {
    if (!this.listening) return;
    if (!this.micFirstFrameLogged) {
      this.micFirstFrameLogged = true;
      this.logStartTiming('first_mic_frame(麦克风冷启动完成,开始出帧)');
    }
    if (!this.modelReady) {
      // 初始模型加载期:麦克风帧进 pre-roll 缓存(一帧不丢),加载完在 startSessionAndFlush 回灌。
      if (this.preRoll.length < MAX_PREROLL_FRAMES) {
        this.preRoll.push(frame);
      } else {
        if (this.preRollDroppedFrames === 0) {
          this.debugRecord('pre_roll_full', '', `limitFrames=${MAX_PREROLL_FRAMES}`);
        }
        this.preRollDroppedFrames += 1;   // 加载异常久(>10s)才会到这;正常不会。
      }
      return;
    }
    this.feedFrameLive(frame);
  }

  // modelReady=true 后的正常喂帧(含 55s 轮转)。轮转间隙 sessionId 短暂为空,丢极少数帧(同旧行为)。
  private feedFrameLive(frame: ArrayBuffer): void {
    if (this.sessionId.length === 0) return;
    if (this.sessionAudioMs >= SESSION_ROTATE_AUDIO_MS && !this.rotatingSession) {
      // Proactively rotate before the 60 s SDK cap; onComplete restarts a fresh session.
      this.rotatingSession = true;
      const sid = this.sessionId;
      this.sessionId = '';
      this.sessionAudioMs = 0;
      this.debugRecord('finish_requested', sid, 'reason=session_rotation');
      this.engine?.finish(sid);
    } else {
      this.sessionAudioMs += FRAME_AUDIO_MS;
      // Copy before writeAudio: the public call can synchronously finish at max duration, so saving
      // afterwards could miss the final frame. This is the exact payload attempted at the SDK gate.
      this.captureSdkFrame(frame);
      this.sessionDebug.addAudioFrame(frame.byteLength);
      if (this.sessionAudioMs % 1000 === 0) {
        hilog.info(0x0000, 'DemoDebug',
          'stage=audio_progress|sessionId=%{public}s|frames=%{public}d|bytes=%{public}d' +
          '|durationMs=%{public}d|resultCallbacks=%{public}d|partialResults=%{public}d',
          this.sessionId, this.sessionDebug.audioFrameCount(), this.sessionDebug.audioByteCount(),
          Math.round(this.sessionDebug.audioByteCount() / 32),
          this.sessionDebug.resultCallbackCount(), this.sessionDebug.partialResultCount());
        this.refreshSessionDebugUi();
      }
      this.engine?.writeAudio(this.sessionId, frame);
    }
  }

  private resetSdkCapture(): void {
    this.sdkCaptureFrames = [];
    this.sdkCaptureTruncated = false;
    this.sdkCaptureBytes = 0;
    this.sdkCaptureRmsDbfs = -120;
    this.sdkCapturePeak = 0;
    this.sdkCaptureClipSamples = 0;
    this.recorderStats = new AudioRecorderStats();
    this.captureReady = false;
    this.captureInfo = '正在采集实际送入 SDK 的 PCM…';
  }

  private captureSdkFrame(frame: ArrayBuffer): void {
    if (this.replaying || frame.byteLength !== SDK_FRAME_BYTES) return;
    if (this.sdkCaptureFrames.length >= SDK_CAPTURE_MAX_FRAMES) {
      this.sdkCaptureTruncated = true;
      return;
    }
    this.sdkCaptureFrames.push(frame.slice(0));
  }

  private mergeSdkCaptureFrames(): ArrayBuffer {
    const out = new ArrayBuffer(this.sdkCaptureFrames.length * SDK_FRAME_BYTES);
    const bytes = new Uint8Array(out);
    for (let i = 0; i < this.sdkCaptureFrames.length; i++) {
      bytes.set(new Uint8Array(this.sdkCaptureFrames[i]), i * SDK_FRAME_BYTES);
    }
    return out;
  }

  private sdkCaptureWavPath(): string {
    return `${this.workPath}/${SDK_CAPTURE_WAV}`;
  }

  private sdkCaptureMetaPath(): string {
    return `${this.workPath}/${SDK_CAPTURE_META}`;
  }

  private saveSdkCapture(): void {
    if (this.sdkCaptureFrames.length === 0) {
      this.captureReady = false;
      this.captureInfo = '本轮没有任何 PCM 真正送入 SDK';
      return;
    }
    const pcm = this.mergeSdkCaptureFrames();
    WavIo.writePcmBytes(this.sdkCaptureWavPath(), pcm);
    // Debug builds can pull this mirror with `hdc file recv -b <bundle> ...` without root access.
    try {
      WavIo.writePcmBytes(SDK_CAPTURE_EXPORT_WAV, pcm);
    } catch (e) {
      hilog.warn(0x0000, 'PcmReplay', 'PCM export mirror failed: %{public}s', `${e}`);
    }
    this.sdkCaptureBytes = pcm.byteLength;
    this.measureSdkCapture(pcm);
    this.captureReady = true;
    const durationMs = Math.round(this.sdkCaptureBytes / 32);
    const suffix = this.sdkCaptureTruncated ? ' · 超过55s，仅保存首段，不可做全文对照' : '';
    this.captureInfo = `已保存 ${this.sdkCaptureFrames.length} 帧 / ${(durationMs / 1000).toFixed(2)}s` +
      ` · RMS ${this.sdkCaptureRmsDbfs.toFixed(1)} dBFS · overflow ${this.recorderStats.overflowCount}` +
      ` · maxGap ${this.recorderStats.maxCallbackGapMs}ms${suffix}`;
    hilog.info(0x0000, 'PcmReplay',
      'PCM_CAPTURE|path=%{public}s|frames=%{public}d|bytes=%{public}d|durationMs=%{public}d' +
      '|rmsDbfs=%{public}s|peak=%{public}d|clipSamples=%{public}d|truncated=%{public}s',
      this.sdkCaptureWavPath(), this.sdkCaptureFrames.length, this.sdkCaptureBytes, durationMs,
      this.sdkCaptureRmsDbfs.toFixed(2), this.sdkCapturePeak, this.sdkCaptureClipSamples,
      String(this.sdkCaptureTruncated));
    this.writeSdkCaptureMetadataBestEffort();
  }

  private measureSdkCapture(pcm: ArrayBuffer): void {
    const view = new DataView(pcm);
    const samples = Math.floor(pcm.byteLength / 2);
    let sumSquares = 0;
    let peak = 0;
    let clipped = 0;
    for (let i = 0; i < samples; i++) {
      const value = view.getInt16(i * 2, true);
      const magnitude = Math.abs(value);
      sumSquares += value * value;
      if (magnitude > peak) peak = magnitude;
      if (magnitude >= 32767) clipped += 1;
    }
    const rms = samples > 0 ? Math.sqrt(sumSquares / samples) : 0;
    this.sdkCaptureRmsDbfs = rms > 0 ? Math.max(-120, 20 * Math.log10(rms / 32768)) : -120;
    this.sdkCapturePeak = peak;
    this.sdkCaptureClipSamples = clipped;
  }

  private writeSdkCaptureMetadata(): void {
    const samples = Math.floor(this.sdkCaptureBytes / 2);
    const meta: Record<string, Object> = {};
    if (this.captureReady) {
      meta['wavPath'] = this.sdkCaptureWavPath();
      meta['hdcPullPath'] = SDK_CAPTURE_EXPORT_WAV;
    }
    meta['sampleRate'] = 16000;
    meta['channels'] = 1;
    meta['sampleFormat'] = 's16le';
    meta['audioSource'] = 'SOURCE_TYPE_MIC';
    meta['softwareGainDb'] = 0;
    meta['frameBytes'] = SDK_FRAME_BYTES;
    meta['frameCount'] = this.sdkCaptureFrames.length;
    meta['byteCount'] = this.sdkCaptureBytes;
    meta['durationMs'] = Math.round(this.sdkCaptureBytes / 32);
    meta['rmsDbfs'] = Number(this.sdkCaptureRmsDbfs.toFixed(3));
    meta['peak'] = this.sdkCapturePeak;
    meta['clipSamples'] = this.sdkCaptureClipSamples;
    meta['clipRate'] = samples > 0 ? this.sdkCaptureClipSamples / samples : 0;
    meta['truncated'] = this.sdkCaptureTruncated;
    meta['captureReady'] = this.captureReady;
    meta['captureThread'] = 'ThreadWorker';
    meta['capturerOverflowCount'] = this.recorderStats.overflowCount;
    meta['captureCallbackCount'] = this.recorderStats.callbackCount;
    meta['captureTotalBytes'] = this.recorderStats.totalBytes;
    meta['captureBufferSizeBytes'] = this.recorderStats.bufferSizeBytes;
    meta['captureMaxCallbackGapMs'] = this.recorderStats.maxCallbackGapMs;
    meta['captureLateCallbackCount'] = this.recorderStats.lateCallbackCount;
    meta['captureCallbackGapExcessMs'] = this.recorderStats.callbackGapExcessMs;
    meta['captureMaxCallbackWorkMs'] = this.recorderStats.maxCallbackWorkMs;
    meta['disablePrepack'] = true;
    meta['hotwords'] = this.capturedHotwords;
    meta['voiceprintId'] = this.capturedVoiceprintId;
    meta['voiceprintVerify'] = this.capturedVoiceprintVerify;
    meta['speakerVad'] = this.capturedSpeakerVad;
    meta['enableTargetSpeakerEnhancement'] = this.capturedTargetSpeakerEnhancement;
    meta['speakerVadInput'] = this.capturedTargetSpeakerEnhancement ?
      'target-speaker-enhanced-pcm' : 'original-pcm';
    meta['policeEnhancement'] = this.capturedPoliceEnhancement;
    meta['liveText'] = this.liveCompareText;
    meta['replayText'] = this.replayCompareText;
    meta['comparison'] = !this.replayHasCompleted ? 'pending' :
      (this.liveCompareText === this.replayCompareText ? 'exact-match' : 'different');
    meta['startExtraParams'] = this.buildCapturedStartParams('metadata-snapshot').extraParams;
    meta['sessionDebug'] = this.sessionDebug.snapshot();
    const encoded = new util.TextEncoder().encodeInto(`${JSON.stringify(meta)}\n`);
    const data = new ArrayBuffer(encoded.byteLength);
    new Uint8Array(data).set(encoded);
    this.writeDebugText(this.sdkCaptureMetaPath(), data);
    try {
      this.writeDebugText(SDK_CAPTURE_EXPORT_META, data);
    } catch (e) {
      hilog.warn(0x0000, 'PcmReplay', 'metadata export mirror failed: %{public}s', `${e}`);
    }
  }

  private writeSdkCaptureMetadataBestEffort(): void {
    try {
      this.writeSdkCaptureMetadata();
    } catch (e) {
      hilog.warn(0x0000, 'PcmReplay', 'metadata write failed: %{public}s', `${e}`);
    }
  }

  private writeDebugText(path: string, data: ArrayBuffer): void {
    const fp = fs.openSync(path,
      fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
    try {
      fs.writeSync(fp.fd, data);
    } finally {
      fs.closeSync(fp.fd);
    }
  }

  private playLastSdkCapture(): void {
    if (!this.captureReady || this.listening || this.replaying || this.loading) return;
    const pcm = WavIo.readPcm(this.sdkCaptureWavPath());
    if (pcm.length === 0) {
      this.toast('上次 SDK PCM 文件为空');
      return;
    }
    this.playingCapture = true;
    this.capturePlayer.play(pcm, (): void => {
      this.playingCapture = false;
    });
  }

  private replayLastSdkCapture(): void {
    if (!this.captureReady || this.sdkCaptureTruncated || this.listening || this.replaying ||
      this.playingCapture || this.loading) return;
    this.capturePlayer.stop();
    this.replayHasCompleted = false;
    this.replaying = true;
    this.replayCompareText = '';
    this.compareInfo = '正在加载同配置模型并原样复测…';
    this.loading = true;
    this.loadingHint = '正在加载模型以原样复测上次 SDK PCM…';
    this.status = this.compareInfo;
    this.debugRecord('replay_requested', '', `frames=${this.sdkCaptureFrames.length}`);
    SpeechRecognizeSdk.createEngineAsync(
      this.buildCreateEngineParams(this.capturedHotwords),
      new DemoCreateEngineCallback(this));
  }

  private async startSavedPcmReplay(): Promise<void> {
    const engine = this.engine;
    if (engine === undefined || !this.replaying) return;
    try {
      const pcm = WavIo.readPcmBytes(this.sdkCaptureWavPath());
      if (pcm.byteLength === 0 || pcm.byteLength % SDK_FRAME_BYTES !== 0) {
        throw new Error(`PCM 长度非法：${pcm.byteLength}B`);
      }
      const sid = `replay-${Date.now()}`;
      this.replaySessionId = sid;
      this.compareInfo = `正在原样复测 ${pcm.byteLength / SDK_FRAME_BYTES} 帧…`;
      this.status = this.compareInfo;
      this.debugRecord('replay_startListening', sid, `frames=${pcm.byteLength / SDK_FRAME_BYTES}`);
      engine.startListening(this.buildCapturedStartParams(sid));
      if (!engine.isBusy()) throw new Error('replay startListening failed');
      const frames = pcm.byteLength / SDK_FRAME_BYTES;
      for (let i = 0; i < frames; i++) {
        if (!this.replaying || this.replaySessionId !== sid) return;
        const offset = i * SDK_FRAME_BYTES;
        engine.writeAudio(sid, pcm.slice(offset, offset + SDK_FRAME_BYTES));
        if ((i + 1) % REPLAY_YIELD_EVERY_FRAMES === 0) await this.yieldReplayLoop();
      }
      if (!this.replaying || this.replaySessionId !== sid) return;
      this.debugRecord('replay_audio_written', sid, `frames=${frames} bytes=${pcm.byteLength}`);
      this.debugRecord('finish_requested', sid, 'reason=replay_complete');
      engine.finish(sid);
    } catch (e) {
      this.failSavedPcmReplay(`${e}`);
    }
  }

  private yieldReplayLoop(): Promise<void> {
    return new Promise<void>((resolve: () => void): void => {
      setTimeout((): void => resolve(), 1);
    });
  }

  private failSavedPcmReplay(message: string): void {
    const engine = this.engine;
    const sid = this.replaySessionId;
    if (engine !== undefined && sid.length > 0 && engine.isBusy()) engine.cancel(sid);
    this.replaying = false;
    this.replaySessionId = '';
    this.loading = false;
    this.compareInfo = `原样复测失败：${message}`;
    this.debugRecord('replay_failed', sid, message);
    this.writeSdkCaptureMetadataBestEffort();
    this.releaseModel(this.compareInfo);
  }

  private logStartTiming(label: string): void {
    if (this.startTapMs <= 0) return;
    hilog.info(0x0000, 'StartTiming', 'sinceTapMs=%{public}d | %{public}s', Date.now() - this.startTapMs, label);
  }

  private debugRecord(stage: string, sessionId: string, detail: string): void {
    this.sessionDebug.record(stage, sessionId, detail);
    hilog.info(0x0000, 'DemoDebug',
      'stage=%{public}s|sessionId=%{public}s|detail=%{public}s', stage, sessionId, detail);
    this.refreshSessionDebugUi();
  }

  private refreshSessionDebugUi(): void {
    this.debugSummary = this.sessionDebug.summary();
    if (this.debugExpanded) this.debugTrace = this.sessionDebug.traceText();
  }

  private async stopListening(): Promise<void> {
    if (!this.listening || this.stoppingListening) return;
    this.stoppingListening = true;
    const sid = this.sessionId;
    this.rotatingSession = false;
    this.sessionAudioMs = 0;
    // 先 await 关麦并 flush 尾帧:此时 listening/sessionId 仍有效,补出来的尾帧能写进当前会话,
    // 之后再 finish 冲最终结果(与同事 5af9778「preserve recorder tail frames」对齐)。
    try {
      await this.stopCapture();
      try {
        // stopCapture has already emitted PcmFrameWriter's zero-padded final 640B frame.
        this.saveSdkCapture();
      } catch (e) {
        this.captureReady = false;
        this.captureInfo = `SDK PCM 保存失败：${e}`;
      }
    } finally {
      this.listening = false;
      this.modelReady = false;
      this.preRoll = [];
      this.sessionId = '';
      this.stoppingListening = false;
    }
    if (sid.length > 0) {
      this.debugRecord('finish_requested', sid, 'reason=user_stop');
      this.engine?.finish(sid);
    } else if (this.startPending) {
      // 模型还没加载完就点了停止:没有 session 可 finish。标记取消,
      // onEngineCreated 会因 !listening 释放刚加载好的模型(不残留内存)。
      this.startPending = false;
      this.loading = false;
      this.status = '已取消（模型未加载完成）';
      this.debugRecord('start_cancelled', '', 'model_not_ready');
    }
  }

  private startCapture(): void {
    if (this.recorder !== undefined) return;
    const writer = new PcmFrameWriter((frame: ArrayBuffer): void => this.writeFrameToCurrentSession(frame));
    this.frameWriter = writer;
    const recorder = new AudioRecorder(
      (samples: Int16Array): void => writer.accept(samples),
      (msg: string): void => {
        const sid = this.sessionId;
        this.stopCapture();
        this.listening = false;
        this.sessionId = '';
        this.engineReady = this.engine !== undefined;
        this.status = `录音错误：${msg}`;
        this.debugRecord('capture_error', sid, msg);
      }
    );
    this.recorder = recorder;
    recorder.start();
  }

  private async stopCapture(): Promise<void> {
    // 先 await recorder.stop()(其内部重排为先冲出已缓冲的 readData 帧再 off),再补齐并吐出不足 640B 的尾帧。
    const stats = await this.recorder?.stop();
    if (stats !== undefined) {
      this.recorderStats = stats;
      hilog.info(0x0000, 'AudioCapture',
        'CAPTURE_STATS|overflow=%{public}d|callbacks=%{public}d|bytes=%{public}d|bufferBytes=%{public}d' +
        '|maxGapMs=%{public}d|lateCallbacks=%{public}d|gapExcessMs=%{public}d|maxWorkMs=%{public}d',
        stats.overflowCount, stats.callbackCount, stats.totalBytes, stats.bufferSizeBytes,
        stats.maxCallbackGapMs, stats.lateCallbackCount, stats.callbackGapExcessMs,
        stats.maxCallbackWorkMs);
    }
    this.recorder = undefined;
    this.frameWriter?.flushFinalFrame();
    this.frameWriter = undefined;
  }

  private async saveLiveErrorArtifacts(): Promise<void> {
    if (!this.errorCleanupGate.tryBeginCleanup()) return;
    this.errorCleanupInProgress = true;
    try {
      await this.stopCapture();
      if (this.sdkCaptureFrames.length > 0) {
        this.saveSdkCapture();
      } else {
        this.captureReady = false;
        this.captureInfo = '本轮没有 PCM 通过 SDK writeAudio 门口；请查看错误与 pre-roll 时间线';
        this.writeSdkCaptureMetadataBestEffort();
      }
    } catch (e) {
      hilog.warn(0x0000, 'DemoDebug',
        'stage=error_artifact_failed|detail=%{public}s', `${e}`);
      this.writeSdkCaptureMetadataBestEffort();
    } finally {
      this.errorCleanupGate.finishCleanup();
      this.errorCleanupInProgress = false;
    }
  }

  // ---- listener bridge (called by DemoRecognitionListener) ----

  handleStart(sessionId: string, eventMessage: string): void {
    this.debugRecord('onStart', sessionId, eventMessage);
    if (sessionId === this.replaySessionId) {
      this.status = '正在用上次 SDK PCM 原样复测…';
      return;
    }
    this.startCapture();
    this.status = '识别中…（再次点击结束）';
  }

  handleResult(sessionId: string, result: SpeechRecognitionResult): void {
    this.trackPeak();
    this.sessionDebug.addResult(
      sessionId,
      result.result,
      result.isFinal,
      result.isLast,
      result.speakerSimilarity,
      result.targetSpeakerEnhancementApplied === true);
    const partialCount = this.sessionDebug.partialResultCount();
    if (result.isFinal || result.isLast || partialCount === 1 || partialCount % 10 === 0) {
      const loggedText = result.result.length <= 160 ? result.result :
        `${result.result.substring(0, 160)}…(len=${result.result.length})`;
      hilog.info(0x0000, 'DemoDebug',
        'stage=result_milestone|sessionId=%{public}s|callbackCount=%{public}d|partialCount=%{public}d' +
        '|isFinal=%{public}s|isLast=%{public}s|similarity=%{public}s' +
        '|targetEnhancementApplied=%{public}s|text=%{public}s',
        sessionId, this.sessionDebug.resultCallbackCount(), partialCount,
        String(result.isFinal), String(result.isLast),
        result.speakerSimilarity === undefined ? 'undefined' : result.speakerSimilarity.toFixed(4),
        String(result.targetSpeakerEnhancementApplied === true), loggedText);
    }
    if (this.debugExpanded || result.isFinal || result.isLast) this.refreshSessionDebugUi();
    if (result.isFinal) {
      if (sessionId === this.replaySessionId) {
        this.replayCompareText += result.result;
        return;
      }
      this.liveCompareText += result.result;
      this.appendFinal(result);
      this.partialText = '';
    } else if (sessionId !== this.replaySessionId) {
      this.partialText = result.result;
    }
  }

  handleEvent(sessionId: string, eventCode: number, message: string): void {
    this.debugRecord('onEvent', sessionId, `code=${eventCode} message=${message}`);
    if (eventCode === DingqiaoEventCode.SPEAKER_VAD_REJECTED) {
      this.status = '说话人 VAD：检测到非目标说话人，已截断';
    }
  }

  handleComplete(sessionId: string, eventMessage: string): void {
    this.debugRecord('onComplete', sessionId, eventMessage);
    if (sessionId === this.replaySessionId) {
      const matched = this.liveCompareText === this.replayCompareText;
      this.replayHasCompleted = true;
      this.replaying = false;
      this.replaySessionId = '';
      this.loading = false;
      this.compareInfo = matched ? '原样复测：逐字一致' : '原样复测：结果不同，请检查实时喂帧/时序';
      hilog.info(0x0000, 'PcmReplay',
        'PCM_COMPARE|match=%{public}s|live=%{public}s|replay=%{public}s',
        String(matched), this.liveCompareText, this.replayCompareText);
      this.writeSdkCaptureMetadataBestEffort();
      this.releaseModel(`${this.compareInfo} · 模型已卸载`);
      return;
    }
    if (this.listening) {
      // 连续场景的会话轮转(逼近 55s 上限):模型保持在内存,立即重开新会话,体验不中断。
      this.rotatingSession = false;
      this.startRecognitionSession();
    } else {
      // 用户点了结束识别、最终结果已下发:按甲方工况「用完即卸」,当场释放模型(L2),运行时(L1)常驻。
      this.liveHasCompleted = true;
      this.stopCapture();
      this.sessionId = '';
      this.writeSdkCaptureMetadataBestEffort();
      const next = this.captureReady ?
        'SDK PCM 已保存 · 可试听或原样重新识别 · 模型已卸载' :
        '模型已卸载 · 运行时常驻 · 点击开始识别按需加载';
      this.releaseModel(next);
    }
  }

  handleError(sessionId: string, errorCode: number, message: string): void {
    this.debugRecord('onError', sessionId, `code=${errorCode} message=${message}`);
    if (sessionId === this.replaySessionId) {
      this.replaying = false;
      this.replaySessionId = '';
      this.loading = false;
      this.compareInfo = `原样复测失败：${errorCode} ${message}`;
      this.writeSdkCaptureMetadataBestEffort();
      this.releaseModel(this.compareInfo);
      return;
    }
    this.listening = false;
    this.modelReady = false;
    this.preRoll = [];
    this.sessionId = '';
    this.startPending = false;
    // 出错后引擎状态可能不可靠:卸掉模型,下次开始识别干净重载。
    this.releaseModel(`错误 ${errorCode}：${message}`);
    this.saveLiveErrorArtifacts();
  }

  // 释放 L2 模型:关引擎/会话(把池化 recognizer 归还)后 unloadModel 显式释放 native 权重(~283MB),
  // 保留 L1 运行时常驻。下次「开始识别」重新冷加载。
  private releaseModel(statusText: string): void {
    const engine = this.engine;
    const hadModel = engine !== undefined;
    this.engine = undefined;
    this.engineReady = false;
    if (hadModel) {
      // 卸载前:模型还在内存(≈推理态),并汇报本轮峰值。
      this.logMem('03_before_unload(模型在内存)');
      const peakNet = this.runtimeAnonMb >= 0 ? this.peakAnonMb - this.runtimeAnonMb : -1;
      hilog.info(0x0000, 'TwoLevelMem',
        'PEAK(本轮推理) | peakVmRssMb=%{public}d | peakAnonMb=%{public}d | peakNetAnonMb(减运行时=模型净占)=%{public}d',
        this.peakVmRssMb, this.peakAnonMb, peakNet);
    }
    engine?.shutdown();
    if (this.runtimeReady) {
      SpeechRecognizeSdk.unloadModel();
    }
    this.status = statusText;
    this.peakAnonMb = 0;
    this.peakVmRssMb = 0;
    if (hadModel) {
      // native 权重释放有 finalizer/GC 延迟(参考 LifecycleBench 的 400ms),延时采样回落态。
      setTimeout((): void => { this.logMem('04_after_unload(回落_L1常驻)'); }, 600);
    }
  }

  private appendFinal(result: SpeechRecognitionResult): void {
    if (result.result.length === 0) return;
    const next = this.finalSegments.slice();
    next.push(new FinalSegment(
      result.result,
      result.speakerSimilarity,
      result.targetSpeakerEnhancementApplied === true));
    this.finalSegments = next;
  }

  // ---- voiceprint UI ----

  private refreshVoiceprintUi(): void {
    const ctx = getContext(this) as common.UIAbilityContext;
    this.voiceprintId = DemoPrefs.getVoiceprintId(ctx);
    if (this.voiceprintId.length === 0) {
      this.voiceprintInfo = '未注册声纹';
    } else {
      this.voiceprintInfo = `已注册声纹：${this.voiceprintId}`;
    }
    if (this.voiceprintId.length === 0) {
      this.voiceprintVerifyDesired = false;
      this.speakerVadDesired = false;
      this.targetSpeakerEnhancementDesired = false;
      DemoPrefs.setTargetSpeakerEnhancementEnabled(ctx, false);
    } else if (this.targetSpeakerEnhancementDesired) {
      this.speakerVadDesired = true;
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
    if (!checked && this.targetSpeakerEnhancementDesired) {
      this.speakerVadDesired = true;
      this.toast('目标说话人增强依赖 Speaker VAD，请先关闭增强');
      return;
    }
    this.speakerVadDesired = checked;
    this.toast(checked ? '说话人 VAD 已开启' : '说话人 VAD 已关闭');
  }

  private onTargetSpeakerEnhancementSwitch(checked: boolean): void {
    if (checked && this.voiceprintId.length === 0) {
      this.targetSpeakerEnhancementDesired = false;
      this.toast('请先注册声纹');
      return;
    }
    this.targetSpeakerEnhancementDesired = checked;
    if (checked) this.speakerVadDesired = true;
    DemoPrefs.setTargetSpeakerEnhancementEnabled(
      getContext(this) as common.UIAbilityContext, checked);
    this.toast(checked ?
      '目标说话人增强已开启：增强音频将进入 Speaker VAD 和 ASR' :
      '目标说话人增强已关闭：Speaker VAD 和 ASR 使用原始音频');
  }

  private onPoliceEnhancementSwitch(checked: boolean): void {
    this.policeEnhancementDesired = checked;
    DemoPrefs.setPoliceEnhancementEnabled(getContext(this) as common.UIAbilityContext, checked);
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
    this.targetSpeakerEnhancementDesired = false;
    DemoPrefs.setTargetSpeakerEnhancementEnabled(ctx, false);
    this.refreshVoiceprintUi();
    this.toast(`已删除声纹：${id}`);
  }

  private toast(message: string): void {
    promptAction.showToast({ message: message, duration: 2000 });
  }

  build() {
    Column({ space: 12 }) {
      Row() {
        Text('Amphion 离线语音识别')
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
          .enabled(this.voiceprintId.length > 0 && !this.listening && !this.replaying)
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
          .enabled(this.voiceprintId.length > 0 && !this.targetSpeakerEnhancementDesired &&
            !this.listening && !this.replaying)
          .onChange((isOn: boolean): void => this.onSpeakerVadSwitch(isOn))
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Row() {
        Column() {
          Text('目标说话人增强').fontSize(15)
          Text('开启后，增强音频进入 Speaker VAD 和 ASR；默认关闭').fontSize(12).fontColor(Color.Gray)
        }
        .layoutWeight(1)
        .alignItems(HorizontalAlign.Start)
        Toggle({ type: ToggleType.Switch, isOn: this.targetSpeakerEnhancementDesired })
          .enabled(this.voiceprintId.length > 0 && !this.listening && !this.replaying)
          .onChange((isOn: boolean): void => this.onTargetSpeakerEnhancementSwitch(isOn))
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Row() {
        Column() {
          Text('警务增强').fontSize(15)
          Text('术语、车牌和派出所文本归一化').fontSize(12).fontColor(Color.Gray)
        }
        .layoutWeight(1)
        .alignItems(HorizontalAlign.Start)
        Toggle({ type: ToggleType.Switch, isOn: this.policeEnhancementDesired })
          .enabled(!this.listening && !this.replaying)
          .onChange((isOn: boolean): void => this.onPoliceEnhancementSwitch(isOn))
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text(this.voiceprintInfo).fontSize(12).fontColor(BRAND_ACCENT).width('100%')

      if (this.loading) {
        Row({ space: 8 }) {
          LoadingProgress().width(22).height(22)
          Text(this.loadingHint).fontSize(13).fontColor(Color.Gray)
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
            Text('识别结果将累积显示在这里。')
              .fontSize(14).fontColor(Color.Gray).width('100%')
          }
          ForEach(this.finalSegments, (item: FinalSegment, index: number) => {
            Text() {
              if (item.targetSpeakerEnhancementApplied) {
                Span('[目标说话人增强已应用] ').fontColor('#16803A').fontWeight(FontWeight.Bold)
              }
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

      if (this.captureReady || this.replaying) {
        Column({ space: 4 }) {
          Text('SDK 实际输入 PCM').fontSize(13).fontWeight(FontWeight.Medium).width('100%')
          Text(this.captureInfo).fontSize(11).fontColor(Color.Gray).width('100%').maxLines(2)
          if (this.liveHasCompleted) {
            Text(`实录：${this.liveCompareText.length > 0 ? this.liveCompareText : '（空）'}`)
              .fontSize(12).width('100%').maxLines(2)
          }
          if (this.replaying || this.replayHasCompleted) {
            Text(`复测：${this.replayHasCompleted ?
              (this.replayCompareText.length > 0 ? this.replayCompareText : '（空）') : '等待结果…'}`)
              .fontSize(12).width('100%').maxLines(2)
          }
          if (this.compareInfo.length > 0) {
            Text(this.compareInfo).fontSize(11)
              .fontColor(this.replayHasCompleted && this.liveCompareText === this.replayCompareText ?
                '#16803A' : Color.Gray)
              .width('100%')
          }
          Row({ space: 8 }) {
            Button(this.playingCapture ? '正在试听…' : '试听上次 PCM')
              .layoutWeight(1)
              .height(36)
              .enabled(this.captureReady && !this.listening && !this.replaying &&
                !this.playingCapture && !this.loading)
              .onClick((): void => this.playLastSdkCapture())
            Button(this.replaying ? '正在复测…' : '原样重新识别')
              .layoutWeight(1)
              .height(36)
              .enabled(this.captureReady && !this.sdkCaptureTruncated && !this.listening &&
                !this.replaying && !this.playingCapture && !this.loading)
              .onClick((): void => this.replayLastSdkCapture())
          }
          .width('100%')
        }
        .width('100%')
        .padding(8)
        .backgroundColor('#EEF4FF')
        .borderRadius(8)
      }

      Column({ space: 4 }) {
        Row() {
          Text('调试信息').fontSize(13).fontWeight(FontWeight.Medium).layoutWeight(1)
          Button(this.debugExpanded ? '收起' : '展开')
            .height(30)
            .onClick((): void => {
              this.debugExpanded = !this.debugExpanded;
              this.refreshSessionDebugUi();
            })
        }
        .width('100%')
        Text(this.debugSummary).fontSize(11).fontColor(Color.Gray).width('100%').maxLines(3)
        if (this.debugExpanded) {
          Scroll() {
            Text(this.debugTrace.length > 0 ? this.debugTrace : '暂无回调记录')
              .fontSize(10).fontColor('#3B4555').width('100%')
          }
          .height(120)
          .width('100%')
        }
      }
      .width('100%')
      .padding(8)
      .backgroundColor('#F4F6F8')
      .borderRadius(8)

      Button(this.replaying ? '正在原样复测…' : (this.listening ? '停止识别' : '开始识别'))
        .width('100%')
        .height(48)
        .enabled(this.runtimeReady && !this.replaying && !this.playingCapture &&
          !this.errorCleanupInProgress)
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

  onStart(sessionId: string, eventMessage: string): void {
    this.owner.handleStart(sessionId, eventMessage);
  }

  onEvent(sessionId: string, eventCode: number, message: string): void {
    this.owner.handleEvent(sessionId, eventCode, message);
  }

  onResult(sessionId: string, result: SpeechRecognitionResult): void {
    this.owner.handleResult(sessionId, result);
  }

  onComplete(sessionId: string, eventMessage: string): void {
    this.owner.handleComplete(sessionId, eventMessage);
  }

  onError(sessionId: string, errorCode: number, message: string): void {
    this.owner.handleError(sessionId, errorCode, message);
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

class DemoPrepareRuntimeCallback implements PrepareRuntimeCallback {
  private owner: Index;

  constructor(owner: Index) {
    this.owner = owner;
  }

  onReady(): void {
    this.owner.onRuntimeReady();
  }

  onError(errorCode: number, message: string): void {
    this.owner.onRuntimeFailed(errorCode, message);
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
      this.owner.onLicenseFailed(result.errorCode, result.errorMessage);
    }
  }

  onError(errorCode: number, message: string): void {
    this.owner.onLicenseFailed(errorCode, message);
  }
}
