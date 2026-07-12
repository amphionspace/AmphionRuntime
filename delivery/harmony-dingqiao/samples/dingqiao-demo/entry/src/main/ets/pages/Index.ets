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
import { AudioRecorder } from '../util/AudioRecorder';
import { PcmFrameWriter } from '../util/PcmFrameWriter';
import { DemoPrefs } from '../util/DemoPrefs';
import { VoiceprintModelHelper } from '../util/VoiceprintModelHelper';

const SESSION_MAX_AUDIO_MS = 60000;
const SESSION_ROTATE_AUDIO_MS = 55000;
const FRAME_AUDIO_MS = 20;
// pre-roll 缓存上限:模型冷加载 ~0.5s,正常只缓存 ~25 帧;给 10s(500 帧)裕量防加载异常久时无界增长。
const MAX_PREROLL_FRAMES = 500;
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
    this.active = false;
    this.startPending = false;
    this.stopListening();
    this.releaseModel('');
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

  // L1:启动时只把运行时框架拉起来常驻(~15-20MB,不含模型),等用户点开始识别再按需加载模型。
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
    if (!this.active || !this.listening) {
      // 加载途中用户已离开本页 / 已点停止:直接释放,避免残留会话与内存。
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
    // 麦克风点击时已开始录音,模型就绪 → 建会话并把 pre-roll 缓存回灌,转 live。
    this.startSessionAndFlush();
  }

  onEngineCreateFailed(errorCode: number, message: string): void {
    this.loading = false;
    this.engineReady = false;
    this.startPending = false;
    this.status = `模型加载失败：${errorCode} ${message}`;
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
    // 关 prepack:按需加载工况下每次「开始识别」都冷加载模型,关掉 INT8 权重 prepack 可省 ~91-156ms
    // 冷加载并降低峰值内存(交付方向 = prepack off,详见两级加载 A/B)。
    extra['disablePrepack'] = true;
    params.extraParams = extra;
    return params;
  }

  private hotwordsKey(): string {
    return DemoPrefs.getUserHotwords(getContext(this) as common.UIAbilityContext).join('\n');
  }

  private reloadEngine(): void {
    // 按需加载模型:热词变了只需卸掉当前模型,下次「开始识别」会用新热词冷加载。
    this.stopListening();
    this.releaseModel('热词已更新 · 下次识别将按新热词加载');
    this.toast('热词已更新，下次识别按新热词加载');
  }

  // ---- recognition lifecycle ----

  private startListening(): void {
    if (!this.runtimeReady) return;
    if (this.listening) return;
    this.startTapMs = Date.now();
    this.finalSegments = [];
    this.partialText = '';
    this.preRoll = [];
    this.preRollDroppedFrames = 0;
    this.micFirstFrameLogged = false;
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
      SpeechRecognizeSdk.createEngineAsync(this.buildCreateEngineParams(), new DemoCreateEngineCallback(this));
    }
  }

  // 建会话 → 把加载期间缓存的 pre-roll 帧按序回灌 → 转 live。模型就绪(冷加载完 or 已在内存)后调用。
  private startSessionAndFlush(): void {
    this.startRecognitionSession();                // 设 sessionId + engine.startListening(同步 busy=true)+ onStart
    const buffered = this.preRoll;
    this.preRoll = [];
    this.modelReady = true;
    for (let i = 0; i < buffered.length; i++) {
      this.feedFrameLive(buffered[i]);
    }
    this.loading = false;
    this.status = '识别中…（再次点击结束）';
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
      this.engine?.finish(sid);
    } else {
      this.sessionAudioMs += FRAME_AUDIO_MS;
      this.engine?.writeAudio(this.sessionId, frame);
    }
  }

  private logStartTiming(label: string): void {
    if (this.startTapMs <= 0) return;
    hilog.info(0x0000, 'StartTiming', 'sinceTapMs=%{public}d | %{public}s', Date.now() - this.startTapMs, label);
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
    } finally {
      this.listening = false;
      this.modelReady = false;
      this.preRoll = [];
      this.sessionId = '';
      this.stoppingListening = false;
    }
    if (sid.length > 0) {
      this.engine?.finish(sid);
    } else if (this.startPending) {
      // 模型还没加载完就点了停止:没有 session 可 finish。标记取消,
      // onEngineCreated 会因 !listening 释放刚加载好的模型(不残留内存)。
      this.startPending = false;
      this.loading = false;
      this.status = '已取消（模型未加载完成）';
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

  private async stopCapture(): Promise<void> {
    // 先 await recorder.stop()(其内部重排为先冲出已缓冲的 readData 帧再 off),再补齐并吐出不足 640B 的尾帧。
    await this.recorder?.stop();
    this.recorder = undefined;
    this.frameWriter?.flushFinalFrame();
    this.frameWriter = undefined;
  }

  // ---- listener bridge (called by DemoRecognitionListener) ----

  handleStart(): void {
    this.startCapture();
    this.status = '识别中…（再次点击结束）';
  }

  handleResult(result: SpeechRecognitionResult): void {
    this.trackPeak();
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
      // 连续场景的会话轮转(逼近 55s 上限):模型保持在内存,立即重开新会话,体验不中断。
      this.rotatingSession = false;
      this.startRecognitionSession();
    } else {
      // 用户点了结束识别、最终结果已下发:按甲方工况「用完即卸」,当场释放模型(L2),运行时(L1)常驻。
      this.stopCapture();
      this.sessionId = '';
      this.releaseModel('模型已卸载 · 运行时常驻 · 点击开始识别按需加载');
    }
  }

  handleError(errorCode: number, message: string): void {
    this.stopCapture();
    this.listening = false;
    this.modelReady = false;
    this.preRoll = [];
    this.sessionId = '';
    this.startPending = false;
    // 出错后引擎状态可能不可靠:卸掉模型,下次开始识别干净重载。
    this.releaseModel(`错误 ${errorCode}：${message}`);
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
    if (checked) {
      // Warm the ~38 MB eres2net extractor now (usually already warm from registration) so the first
      // 开始识别 with 声纹校验 doesn't block. No-op if pooled; only the app-restart case pays here.
      SpeechRecognizeSdk.preloadVoiceprintModel();
    }
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
        .enabled(this.runtimeReady)
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
