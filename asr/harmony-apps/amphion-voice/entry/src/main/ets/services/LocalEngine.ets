import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
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
  StartParams,
  VoiceprintRegisterParams
} from 'amphion_dingqiao';
import { RecognizerEvents, TargetRecognizer } from './Recognizer';

const TAG = 'AmphionLocal';
const LICENSE_RAWFILE = 'amphion-license.lic';
// Bounded pre-roll while the model loads: 10 s of 20 ms frames.
const MAX_PENDING_FRAMES = 500;

// Target-speaker profile: continuous long-form transcription gated by the enrolled voiceprint.
const SPEAKER_VAD_THRESHOLD = 0.35;
const SPEAKER_VAD_WINDOW_MS = 1500;
const SPEAKER_VAD_HOP_MS = 500;
const SPEAKER_VAD_CONSECUTIVE_BELOW = 2;

export type LocalState = 'idle' | 'preparing' | 'ready' | 'failed';

export type LocalStateListener = (state: LocalState, message: string) => void;

/**
 * Process-wide owner of the on-device runtime: license → runtime → one lazily created engine.
 * The engine stays resident between sessions so repeated taps start instantly.
 */
export class LocalEngine {
  private static instance?: LocalEngine;

  state: LocalState = 'idle';
  message: string = '';
  private context?: common.UIAbilityContext;
  private listeners: LocalStateListener[] = [];
  private engine?: SpeechRecognitionEngine;
  private engineLoading: boolean = false;
  private engineWaiters: ((engine?: SpeechRecognitionEngine, error?: string) => void)[] = [];

  static get(): LocalEngine {
    if (LocalEngine.instance === undefined) LocalEngine.instance = new LocalEngine();
    return LocalEngine.instance;
  }

  observe(listener: LocalStateListener): void {
    this.listeners.push(listener);
    listener(this.state, this.message);
  }

  unobserve(listener: LocalStateListener): void {
    this.listeners = this.listeners.filter((item: LocalStateListener): boolean => item !== listener);
  }

  private setState(state: LocalState, message: string): void {
    this.state = state;
    this.message = message;
    this.listeners.forEach((listener: LocalStateListener): void => listener(state, message));
  }

  prepare(context: common.UIAbilityContext): void {
    this.context = context;
    if (this.state === 'preparing' || this.state === 'ready') return;
    this.setState('preparing', '正在准备');
    let licensePath = '';
    try {
      licensePath = this.copyLicense(context);
    } catch (e) {
      hilog.error(0x0000, TAG, 'license unavailable: %{public}s', `${e}`);
      this.setState('failed', '授权缺失');
      return;
    }
    SpeechRecognizeSdk.setLicense(licensePath, new LicenseCallback(this));
  }

  onLicense(ok: boolean, code: number, message: string): void {
    if (!ok) {
      hilog.error(0x0000, TAG, 'license rejected: %{public}d %{public}s', code, message);
      this.setState('failed', '授权未通过');
      return;
    }
    SpeechRecognizeSdk.prepareRuntime(new RuntimeCallback(this));
  }

  onRuntime(ok: boolean, code: number, message: string): void {
    if (!ok) {
      hilog.error(0x0000, TAG, 'runtime failed: %{public}d %{public}s', code, message);
      this.setState('failed', '识别引擎启动失败');
      return;
    }
    this.setState('ready', '准备就绪');
    // Warm the voiceprint extractor off the critical path so the first session scores immediately.
    setTimeout((): void => {
      try {
        SpeechRecognizeSdk.preloadVoiceprintModel();
      } catch (_e) {
      }
    }, 300);
  }

  /** Registers all samples as one merged voiceprint. Returns the new id or throws with a user message. */
  register(samplePaths: string[], previousId: string): string {
    if (this.state !== 'ready') throw new Error(this.message.length > 0 ? this.message : '识别服务准备中，请稍候');
    if (previousId.length > 0) {
      try {
        SpeechRecognizeSdk.deleteVoiceprint(previousId);
      } catch (_e) {
        // Already gone; a fresh registration supersedes it either way.
      }
    }
    const params = new VoiceprintRegisterParams();
    params.voiceprintId = '';
    params.samplePaths = samplePaths;
    params.audioInfo = new AudioInfo();
    const result = SpeechRecognizeSdk.registerVoiceprint(params);
    const ids = Object.keys(result.voiceprintId);
    if (result.status !== 0 || ids.length === 0) {
      throw new Error(result.message.length > 0 ? result.message : '声纹注册失败');
    }
    return ids[0];
  }

  remove(id: string): void {
    if (id.length === 0) return;
    try {
      SpeechRecognizeSdk.deleteVoiceprint(id);
    } catch (e) {
      hilog.warn(0x0000, TAG, 'delete voiceprint: %{public}s', `${e}`);
    }
  }

  acquireEngine(callback: (engine?: SpeechRecognitionEngine, error?: string) => void): void {
    if (this.engine !== undefined) {
      callback(this.engine);
      return;
    }
    this.engineWaiters.push(callback);
    if (this.engineLoading) return;
    this.engineLoading = true;
    const params = new CreateEngineParams();
    params.language = 'zh-CN';
    params.online = 1;
    const extra: Record<string, Object> = {};
    // Must match prepareRuntime's default recognizer key so the pooled model is reused.
    extra['disablePrepack'] = true;
    params.extraParams = extra;
    SpeechRecognizeSdk.createEngineAsync(params, new EngineCallback(this));
  }

  onEngine(engine?: SpeechRecognitionEngine, error?: string): void {
    this.engineLoading = false;
    this.engine = engine;
    const waiters = this.engineWaiters;
    this.engineWaiters = [];
    waiters.forEach((waiter: (engine?: SpeechRecognitionEngine, error?: string) => void): void => waiter(engine, error));
  }

  release(): void {
    this.engine?.shutdown();
    this.engine = undefined;
  }

  private copyLicense(context: common.UIAbilityContext): string {
    const data = context.resourceManager.getRawFileContentSync(LICENSE_RAWFILE);
    const workPath = SpeechRecognizeSdk.getWorkPath();
    if (!fs.accessSync(workPath)) fs.mkdirSync(workPath, true);
    const dest = `${workPath}/${LICENSE_RAWFILE}`;
    const file = fs.openSync(dest, fs.OpenMode.READ_WRITE | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
    try {
      fs.writeSync(file.fd, data.buffer);
    } finally {
      fs.closeSync(file);
    }
    return dest;
  }
}

class LicenseCallback implements LicenseActivationCallback {
  private owner: LocalEngine;

  constructor(owner: LocalEngine) {
    this.owner = owner;
  }

  onResult(result: LicenseActivationResult): void {
    this.owner.onLicense(result.errorCode === 0, result.errorCode, result.errorMessage);
  }

  onError(errorCode: number, message: string): void {
    this.owner.onLicense(false, errorCode, message);
  }
}

class RuntimeCallback implements PrepareRuntimeCallback {
  private owner: LocalEngine;

  constructor(owner: LocalEngine) {
    this.owner = owner;
  }

  onReady(): void {
    this.owner.onRuntime(true, 0, '');
  }

  onError(errorCode: number, message: string): void {
    this.owner.onRuntime(false, errorCode, message);
  }
}

class EngineCallback implements CreateEngineCallback {
  private owner: LocalEngine;

  constructor(owner: LocalEngine) {
    this.owner = owner;
  }

  onSuccess(engine: SpeechRecognitionEngine): void {
    this.owner.onEngine(engine);
  }

  onError(errorCode: number, message: string): void {
    hilog.error(0x0000, TAG, 'createEngine failed: %{public}d %{public}s', errorCode, message);
    this.owner.onEngine(undefined, '识别模型加载失败');
  }
}

/** One on-device session: offline ASR + voiceprint verification + Speaker VAD, all on device. */
export class LocalRecognizer implements TargetRecognizer {
  private readonly voiceprintId: string;
  private events?: RecognizerEvents;
  private engine?: SpeechRecognitionEngine;
  private sessionId: string = '';
  private pending: ArrayBuffer[] = [];
  private finishRequested: boolean = false;
  private closed: boolean = false;

  private readonly speakerVad: boolean;

  /** speakerVad=false leaves every Speaker VAD parameter out of the request. */
  constructor(voiceprintId: string, speakerVad: boolean = true) {
    this.voiceprintId = voiceprintId;
    this.speakerVad = speakerVad;
  }

  start(events: RecognizerEvents): void {
    this.events = events;
    LocalEngine.get().acquireEngine((engine?: SpeechRecognitionEngine, error?: string): void => {
      if (this.closed) return;
      if (engine === undefined) {
        this.fail(error ?? '识别模型加载失败');
        return;
      }
      this.engine = engine;
      engine.setListener(new SessionListener(this));
      this.sessionId = `amphion-${Date.now()}`;
      engine.startListening(this.buildParams(this.sessionId));
    });
  }

  write(frame: ArrayBuffer): void {
    if (this.closed || this.finishRequested) return;
    if (this.engine === undefined || this.sessionId.length === 0 || !this.started) {
      if (this.pending.length < MAX_PENDING_FRAMES) this.pending.push(frame);
      return;
    }
    this.engine.writeAudio(this.sessionId, frame);
  }

  finish(): void {
    if (this.closed || this.finishRequested) return;
    this.finishRequested = true;
    if (this.started) this.engine?.finish(this.sessionId);
  }

  cancel(): void {
    if (this.closed) return;
    this.closed = true;
    try {
      if (this.engine?.isBusy() && this.sessionId.length > 0) this.engine.cancel(this.sessionId);
    } catch (_e) {
    }
  }

  private started: boolean = false;

  handleStart(sessionId: string): void {
    if (sessionId !== this.sessionId || this.closed) return;
    this.started = true;
    const buffered = this.pending;
    this.pending = [];
    buffered.forEach((frame: ArrayBuffer): void => this.engine?.writeAudio(this.sessionId, frame));
    this.events?.onListening();
    if (this.finishRequested) this.engine?.finish(this.sessionId);
  }

  handleResult(sessionId: string, result: SpeechRecognitionResult): void {
    if (sessionId !== this.sessionId || this.closed) return;
    if (!result.isFinal) {
      this.events?.onPartial(result.result);
      return;
    }
    // An empty final closes a span Speaker VAD rejected; it was already counted via the event.
    if (result.result.length > 0) this.events?.onFinal(result.result, result.speakerSimilarity);
    else this.events?.onPartial('');
  }

  handleEvent(sessionId: string, eventCode: number): void {
    if (sessionId !== this.sessionId || this.closed) return;
    if (eventCode === DingqiaoEventCode.SPEAKER_VAD_REJECTED) this.events?.onFiltered();
  }

  handleComplete(sessionId: string): void {
    if (sessionId !== this.sessionId || this.closed) return;
    this.closed = true;
    this.events?.onComplete();
  }

  handleError(sessionId: string, code: number, message: string): void {
    if (sessionId !== this.sessionId || this.closed) return;
    hilog.error(0x0000, TAG, 'session error %{public}d %{public}s', code, message);
    this.fail('识别中断，请重试');
    // The engine may be in an unknown state after an error; rebuild it on the next session.
    LocalEngine.get().release();
  }

  private fail(message: string): void {
    this.closed = true;
    this.events?.onError(message);
  }

  private buildParams(sessionId: string): StartParams {
    const params = new StartParams();
    params.sessionId = sessionId;
    params.audioInfo = new AudioInfo();
    const extra = params.extraParams;
    extra['enablePartialResult'] = true;
    // Same end-of-sentence silence as the SDK meeting demo; 1.6 s made every final trail speech by ~2.4 s.
    extra['vadEnd'] = 800;
    extra['maxAudioDuration'] = 62000;
    extra['recognizerMode'] = 'long';
    extra['endpointMaxUtteranceMs'] = 60000;
    extra['enableContinuousRecognition'] = true;
    extra['enablePoliceEnhancement'] = false;
    extra['voiceprintIds'] = [this.voiceprintId];
    extra['enableVoiceprintVerification'] = true;
    if (this.speakerVad) {
      extra['enableSpeakerVad'] = true;
      extra['speakerVadThreshold'] = SPEAKER_VAD_THRESHOLD;
      extra['speakerVadWindowMs'] = SPEAKER_VAD_WINDOW_MS;
      extra['speakerVadHopMs'] = SPEAKER_VAD_HOP_MS;
      extra['speakerVadConsecutiveBelow'] = SPEAKER_VAD_CONSECUTIVE_BELOW;
    }
    return params;
  }
}

class SessionListener implements RecognitionListener {
  private owner: LocalRecognizer;

  constructor(owner: LocalRecognizer) {
    this.owner = owner;
  }

  onStart(sessionId: string, _eventMessage?: string): void {
    this.owner.handleStart(sessionId);
  }

  onEvent(sessionId: string, eventCode: number, _message: string): void {
    this.owner.handleEvent(sessionId, eventCode);
  }

  onResult(sessionId: string, result: SpeechRecognitionResult): void {
    this.owner.handleResult(sessionId, result);
  }

  onComplete(sessionId: string, _eventMessage?: string): void {
    this.owner.handleComplete(sessionId);
  }

  onError(sessionId: string, errorCode: number, message: string): void {
    this.owner.handleError(sessionId, errorCode, message);
  }
}
