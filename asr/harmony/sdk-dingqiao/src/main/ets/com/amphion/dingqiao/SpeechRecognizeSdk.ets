import { AmphionDeviceIdProvider, AmphionLicenseStatus, AmphionRuntime, AmphionOptions, AsrCallback, AsrConfig, AsrEngine, AsrError, AsrErrorCode, AsrLanguage, AsrResult, AsrSession, SessionConfig, SpeakerEnroller, SpeakerVadConfig, TargetSpeakerConfig } from 'amphion_asr';
import { PoliceEngineConfig, PoliceEnhanceOptions, PoliceEnhancePipeline } from 'amphion_police';
import { fileIo as fs } from '@kit.CoreFileKit';
import deviceInfo from '@ohos.deviceInfo';
import { DingqiaoSpeakerModelAssets } from './DingqiaoSpeakerModelAssets';
import { rejectedFinalCompletesSession } from './RejectedFinalLifecycle';
import { VoiceprintStore } from './VoiceprintStore';
import {
  AudioInfo,
  CreateEngineCallback,
  CreateEngineParams,
  DINGQIAO_AUDIO_FRAME_BYTES_20MS,
  DINGQIAO_AUDIO_FRAME_BYTES_40MS,
  DINGQIAO_VOICEPRINT_MAX_SEC,
  DINGQIAO_VOICEPRINT_MIN_SAMPLES,
  DINGQIAO_VOICEPRINT_MIN_SEC,
  DingqiaoErrorCode,
  DingqiaoEventCode,
  LicenseActivationCallback,
  LicenseActivationResult,
  LicenseInfo,
  PrepareRuntimeCallback,
  RecognitionListener,
  SpeechRecognitionEngine,
  SpeechRecognitionResult,
  StartParams,
  VoiceprintRegisterParams,
  VoiceprintRegisterResult
} from './DingqiaoModels';

function languageOf(language: string): AsrLanguage {
  const normalized = language.toLowerCase();
  if (normalized === 'zh-cn' || normalized === 'zh-en' || normalized === 'zh_en') return AsrLanguage.ZH_EN;
  if (normalized === 'zh-yue' || normalized === 'zh_yue') return AsrLanguage.YUE_EN;
  throw new Error(`unsupported language: ${language}`);
}

function parseLexicon(value: Object | undefined): string[] {
  if (value === undefined) return [];
  if (Array.isArray(value)) return objectArrayToStrings(value as Object[]);
  if (typeof value !== 'string' || value.length === 0) return [];
  return value.split(/[\n,，]/).map((s: string): string => s.trim()).filter((s: string): boolean => s.length > 0);
}

function objectArrayToStrings(arr: Object[]): string[] {
  const out: string[] = [];
  for (let i = 0; i < arr.length; i++) {
    const s = `${arr[i]}`.trim();
    if (s.length > 0) out.push(s);
  }
  return out;
}

function stringArrayParam(params: Record<string, Object>, key: string): string[] {
  const value = params[key];
  if (value === undefined) return [];
  if (Array.isArray(value)) return objectArrayToStrings(value as Object[]);
  if (typeof value === 'string') {
    return value.split(/[\n,，]/).map((s: string): string => s.trim()).filter((s: string): boolean => s.length > 0);
  }
  return [];
}

function booleanParam(params: Record<string, Object>, key: string, defaultValue: boolean): boolean {
  const value = params[key];
  return typeof value === 'boolean' ? value : defaultValue;
}

function numberParam(params: Record<string, Object>, key: string, defaultValue: number): number {
  const value = params[key];
  if (typeof value === 'number') return Number.isFinite(value) ? value : defaultValue;
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : defaultValue;
  }
  return defaultValue;
}

function optionalNumberParam(params: Record<string, Object>, key: string): number | undefined {
  const value = params[key];
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined;
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function vadEndMs(params?: StartParams): number {
  return clamp(numberParam(params?.extraParams ?? {}, 'vadEnd', 800), 500, 10000);
}

function vadBeginMs(params: StartParams): number | undefined {
  if (params.extraParams['vadBegin'] === undefined) return undefined;
  const value = optionalNumberParam(params.extraParams, 'vadBegin');
  return value === undefined ? undefined : Math.round(clamp(value, 500, 10000));
}

function isSupportedAudioFrameBytes(byteLength: number): boolean {
  return byteLength === DINGQIAO_AUDIO_FRAME_BYTES_20MS;
}

function maxAudioBytesOf(params: StartParams): number {
  const ms = clamp(numberParam(params.extraParams, 'maxAudioDuration', 20000), 20000, 28800000);
  // 16 kHz mono 16-bit PCM = 32 bytes per millisecond.
  return Math.round(ms * 32);
}

function validateRecognitionMode(params: StartParams): string {
  const raw = params.extraParams['recognitionMode'];
  if (raw === undefined) return '';
  const mode = optionalNumberParam(params.extraParams, 'recognitionMode');
  return mode === 1 ? '' : 'only recognitionMode=1 (external audio stream) is supported';
}

function validateRecognizerMode(params: CreateEngineParams): void {
  const raw = params.extraParams['recognizerMode'];
  if (raw === undefined) return;
  const mode = `${raw}`.trim().toLowerCase();
  if (mode !== 'short' && mode !== 'long') throw new Error('recognizerMode must be short or long');
}

function validateAudioInfo(audioInfo: AudioInfo): string {
  if (audioInfo.audioType !== 'pcm') return 'audioType must be pcm';
  if (audioInfo.sampleRate !== 16000) return 'sampleRate must be 16000';
  if (audioInfo.sampleBit !== 16) return 'sampleBit must be 16';
  if (audioInfo.soundChannel !== 1) return 'soundChannel must be 1';
  return '';
}

function isValidSessionId(sessionId: string): boolean {
  return /^[A-Za-z0-9_-]+$/.test(sessionId);
}

function fileDurationMs(path: string): number {
  const fp = fs.openSync(path);
  try {
    const size = fs.statSync(fp.fd).size;
    const audioBytes = Math.max(size - (path.toLowerCase().endsWith('.wav') ? 44 : 0), 0);
    return Math.round(audioBytes * 1000 / 32000);
  } finally {
    fs.close(fp.fd);
  }
}

function baseName(path: string): string {
  const idx = path.lastIndexOf('/');
  return idx >= 0 ? path.substring(idx + 1) : path;
}

class DingqiaoSdkError extends Error {
  errorCode: number;

  constructor(errorCode: number, message: string) {
    super(message);
    this.errorCode = errorCode;
  }
}

function readTextFile(path: string): string {
  const fp = fs.openSync(path);
  try {
    const size = fs.statSync(fp.fd).size;
    const raw = new ArrayBuffer(size);
    fs.readSync(fp.fd, raw);
    return utf8BytesToString(new Uint8Array(raw));
  } finally {
    fs.close(fp.fd);
  }
}

function utf8BytesToString(bytes: Uint8Array): string {
  let out = '';
  for (let i = 0; i < bytes.length;) {
    const b0 = bytes[i++];
    if (b0 < 0x80) {
      out += String.fromCharCode(b0);
    } else if (b0 < 0xE0 && i < bytes.length) {
      const b1 = bytes[i++] & 0x3F;
      out += String.fromCharCode(((b0 & 0x1F) << 6) | b1);
    } else if (b0 < 0xF0 && i + 1 < bytes.length) {
      const b1 = bytes[i++] & 0x3F;
      const b2 = bytes[i++] & 0x3F;
      out += String.fromCharCode(((b0 & 0x0F) << 12) | (b1 << 6) | b2);
    } else if (i + 2 < bytes.length) {
      const b1 = bytes[i++] & 0x3F;
      const b2 = bytes[i++] & 0x3F;
      const b3 = bytes[i++] & 0x3F;
      const cp = ((b0 & 0x07) << 18) | (b1 << 12) | (b2 << 6) | b3;
      const u = cp - 0x10000;
      out += String.fromCharCode(0xD800 + (u >> 10), 0xDC00 + (u & 0x3FF));
    }
  }
  return out;
}

function extractAsrErrorCode(message: string): number {
  const prefix = 'code=';
  const idx = message.indexOf(prefix);
  if (idx < 0) return -1;
  let end = idx + prefix.length;
  while (end < message.length && message.charCodeAt(end) >= 48 && message.charCodeAt(end) <= 57) end++;
  const parsed = Number(message.substring(idx + prefix.length, end));
  return Number.isFinite(parsed) ? parsed : -1;
}

function mapLicenseErrorCode(asrCode: number): number {
  if (asrCode === AsrErrorCode.LICENSE_MISSING) return DingqiaoErrorCode.LICENSE_FILE_UNREADABLE;
  if (asrCode === AsrErrorCode.LICENSE_EXPIRED || asrCode === AsrErrorCode.LICENSE_MAINTENANCE_EXPIRED) return DingqiaoErrorCode.LICENSE_EXPIRED;
  if (asrCode === AsrErrorCode.LICENSE_APP_MISMATCH ||
    asrCode === AsrErrorCode.LICENSE_CERT_MISMATCH ||
    asrCode === AsrErrorCode.LICENSE_DEVICE_MISMATCH) {
    return DingqiaoErrorCode.LICENSE_DEVICE_MISMATCH;
  }
  if (asrCode === AsrErrorCode.LICENSE_MALFORMED ||
    asrCode === AsrErrorCode.LICENSE_SIGNATURE_INVALID ||
    asrCode === AsrErrorCode.LICENSE_SDK_MAJOR_MISMATCH ||
    asrCode === AsrErrorCode.LICENSE_FEATURE_MISSING) {
    return DingqiaoErrorCode.LICENSE_INVALID;
  }
  return DingqiaoErrorCode.LICENSE_ACTIVATION_FAILED;
}

function buildAsrConfig(context: Context, params: CreateEngineParams, startParams?: StartParams,
  withTargetSpeaker: boolean = false, withSpeakerVad: boolean = false,
  speakerModelPath?: string): AsrConfig {
  validateRecognizerMode(params);
  const plate = booleanParam(params.extraParams, 'plateNormalizeEnabled', true);
  const station = booleanParam(params.extraParams, 'stationNormalizeEnabled', true);
  const terms = booleanParam(params.extraParams, 'termsNormalizeEnabled', true);
  const config = PoliceEngineConfig.build(
    context, parseLexicon(params.extraParams['sysGeneralLexicon']), plate, station, terms);
  config.vadConfig.activeEndpointSilenceMs = vadEndMs(startParams);
  config.endpointRules.rule2MinTrailingSilenceSec = 2.0;
  // 低内存/快加载模式开关(默认关=保留 prepack)。host 传 extraParams["disablePrepack"]=true 启用。
  config.disablePrepack = booleanParam(params.extraParams, 'disablePrepack', false);
  if (withTargetSpeaker) {
    if (speakerModelPath === undefined) throw new Error('voiceprint model path is required');
    config.targetSpeaker = buildTargetSpeakerConfig(startParams, withSpeakerVad, speakerModelPath);
  }
  return config;
}

function snapshotExtraParams(source: Record<string, Object>): Record<string, Object> {
  const snapshot: Record<string, Object> = {};
  const keys: string[] = Object.keys(source);
  for (let i = 0; i < keys.length; i++) {
    const key = keys[i];
    const value = source[key];
    if (Array.isArray(value)) {
      const sourceArray = value as Object[];
      const arraySnapshot: Object[] = [];
      for (let j = 0; j < sourceArray.length; j++) arraySnapshot.push(sourceArray[j]);
      snapshot[key] = arraySnapshot;
    } else if (value !== undefined) {
      snapshot[key] = value;
    }
  }
  return snapshot;
}

function snapshotCreateEngineParams(source: CreateEngineParams): CreateEngineParams {
  const snapshot = new CreateEngineParams();
  snapshot.language = source.language;
  snapshot.online = source.online;
  snapshot.extraParams = snapshotExtraParams(source.extraParams);
  return snapshot;
}

function buildTargetSpeakerConfig(startParams: StartParams | undefined, withSpeakerVad: boolean,
  speakerModelPath: string): TargetSpeakerConfig {
  const cfg = new TargetSpeakerConfig();
  cfg.modelPath = speakerModelPath;
  // Score-only: never reject on segment-end verification so onFinal always carries speakerSimilarity
  // (mirrors Android Dingqiao SCORE_ONLY_THRESHOLD = -1). Speaker VAD does its own gating.
  cfg.threshold = -1.0;
  cfg.enabledByDefault = false;
  cfg.numThreads = 1;
  // Final-only verification can attach the extractor after ASR streaming starts. Speaker VAD
  // scores sliding windows during streaming, so it must keep synchronous session construction.
  cfg.deferLoad = !withSpeakerVad;
  // Keep Speaker VAD configured even when initially disabled so the Android-aligned runtime toggle
  // can enable it later in the same session. Only an initially enabled Speaker VAD makes load sync.
  cfg.speakerVad = buildSpeakerVadConfig(startParams?.extraParams ?? {});
  return cfg;
}

function buildSpeakerVadConfig(extra: Record<string, Object>): SpeakerVadConfig {
  const config = new SpeakerVadConfig();
  config.threshold = clamp(numberParam(extra, 'speakerVadThreshold', 0.40), -1.0, 1.0);
  config.winSec = clamp(numberParam(extra, 'speakerVadWindowMs', 1000), 500, 5000) / 1000;
  config.hopSec = clamp(numberParam(extra, 'speakerVadHopMs', 300), 100, 2000) / 1000;
  config.consecutiveBelow = Math.round(clamp(numberParam(extra, 'speakerVadConsecutiveBelow', 2), 1, 5));
  config.enabledByDefault = false;
  return config;
}

function buildSessionConfig(params: StartParams, withTargetSpeaker: boolean,
  needsVoiceprintAudio: boolean): SessionConfig {
  const config = new SessionConfig();
  config.endpointSilenceMs = vadEndMs(params);
  config.initialSilenceTimeoutMs = vadBeginMs(params);
  if (needsVoiceprintAudio) {
    const targetSpeakerDefaults = new TargetSpeakerConfig();
    config.initialSilenceConfirmationGraceMs = Math.round(targetSpeakerDefaults.minSegSec * 1000);
  }
  if (withTargetSpeaker) config.speakerVad = buildSpeakerVadConfig(params.extraParams);
  return config;
}

function buildEnhanceOptions(params: CreateEngineParams): PoliceEnhanceOptions {
  const options = new PoliceEnhanceOptions();
  options.plateNormalizeEnabled = booleanParam(params.extraParams, 'plateNormalizeEnabled', true);
  options.stationNormalizeEnabled = booleanParam(params.extraParams, 'stationNormalizeEnabled', true);
  options.termsNormalizeEnabled = booleanParam(params.extraParams, 'termsNormalizeEnabled', true);
  return options;
}

const STOP_FALLBACK_DELAY_MS: number = 1500;

class DingqiaoRecognitionEngineImpl implements SpeechRecognitionEngine {
  private context: Context;
  private params: CreateEngineParams;
  private listener?: RecognitionListener;
  private asrEngine: AsrEngine;
  private session?: AsrSession;
  private pipeline: PoliceEnhancePipeline;
  private busy: boolean = false;
  private destroyed: boolean = false;
  private currentSessionId: string = '';
  private lastFinishedSessionId: string = '';
  private lastAutoFinishedSessionId: string = '';
  private finishRequested: boolean = false;
  private partialEnabled: boolean = true;
  private finalResultSent: boolean = false;
  private completeSent: boolean = false;
  private maxAudioBytes: number = 0;
  private audioBytesWritten: number = 0;
  private voiceprintIds: string[] = [];
  private speechActive: boolean = false;
  private startingSession: boolean = false;
  private sessionStartedDuringCreate: boolean = false;
  private cancelRequestedDuringStart: boolean = false;
  // 当前 asrEngine 是用什么会话级配置建的;下次 startListening 若配置相同则复用,不重载模型。
  private engineCfgKey: string = '';

  constructor(context: Context, params: CreateEngineParams, preloadedEngine?: AsrEngine) {
    this.context = context;
    this.params = snapshotCreateEngineParams(params);
    this.pipeline = PoliceEnhancePipeline.create(context, buildEnhanceOptions(this.params));
    this.asrEngine = preloadedEngine ??
      AmphionRuntime.create(context, languageOf(this.params.language), buildAsrConfig(context, this.params));
    this.engineCfgKey = this.computeEngineCfgKey(false, false);
  }

  // vadBegin/vadEnd/speaker 窗口均由 SessionConfig 覆盖；只有目标说话人能力和同步加载策略需要重建引擎。
  private computeEngineCfgKey(withTargetSpeaker: boolean, withSpeakerVad: boolean): string {
    return [`${withTargetSpeaker}`, `${withSpeakerVad}`].join('|');
  }

  setListener(listener: RecognitionListener): void { this.listener = listener; }

  startListening(params: StartParams): void {
    this.ensureAlive();
    if (this.busy) {
      this.listener?.onError?.(params.sessionId, DingqiaoErrorCode.ENGINE_BUSY, 'engine is busy');
      return;
    }
    const audioError = validateAudioInfo(params.audioInfo);
    if (audioError.length > 0) {
      this.listener?.onError?.(params.sessionId, DingqiaoErrorCode.START_LISTENING_FAILED, audioError);
      return;
    }
    const recognitionModeError = validateRecognitionMode(params);
    if (recognitionModeError.length > 0) {
      this.listener?.onError?.(params.sessionId, DingqiaoErrorCode.START_LISTENING_FAILED, recognitionModeError);
      return;
    }
    if (!isValidSessionId(params.sessionId)) {
      this.listener?.onError?.(params.sessionId, DingqiaoErrorCode.START_LISTENING_FAILED, 'sessionId must be non-empty alphanumeric/underscore/dash');
      return;
    }

    const verify = booleanParam(params.extraParams, 'enableVoiceprintVerification', false);
    const speakerVad = booleanParam(params.extraParams, 'enableSpeakerVad', false);
    const voiceprintIds = stringArrayParam(params.extraParams, 'voiceprintIds');
    let embedding: Float32Array | undefined;
    let speakerModelPath: string | undefined;
    if ((verify || speakerVad) && voiceprintIds.length === 0) {
      this.listener?.onError?.(params.sessionId, DingqiaoErrorCode.START_LISTENING_FAILED, 'voiceprintIds required when enableVoiceprintVerification=true or enableSpeakerVad=true');
      return;
    }
    if ((verify || speakerVad) && voiceprintIds.length > 0) {
      // Every path uses the same bundled rawfile identity, so registration, final verification,
      // preload, and Speaker VAD share one extractor pool entry without copying 40 MB on ArkTS.
      speakerModelPath = DingqiaoSpeakerModelAssets.bundledPath();
      embedding = new VoiceprintStore(SpeechRecognizeSdk.getWorkPath()).loadMergedEmbedding(voiceprintIds);
      if (embedding === undefined) {
        this.listener?.onError?.(params.sessionId, DingqiaoErrorCode.VOICEPRINT_NOT_FOUND, `voiceprint not found for ids: ${voiceprintIds.join(',')}`);
        return;
      }
    }
    // Android builds the session with voiceprint capability whenever IDs are supplied, even if both
    // switches start disabled. This preserves setSpeakerVadEnabled(true) for a running session without
    // loading the model for ordinary sessions that have no voiceprint IDs.
    const configureTarget = verify || speakerVad || voiceprintIds.length > 0;
    const useTarget = embedding !== undefined && (verify || speakerVad);

    try {
      if (configureTarget && speakerModelPath === undefined) {
        speakerModelPath = DingqiaoSpeakerModelAssets.bundledPath();
      }
      this.rebuildEngine(params, configureTarget, useTarget && speakerVad, speakerModelPath);
      this.lastFinishedSessionId = '';
      this.lastAutoFinishedSessionId = '';
      this.currentSessionId = params.sessionId;
      this.finishRequested = false;
      this.finalResultSent = false;
      this.completeSent = false;
      this.partialEnabled = params.extraParams['enablePartialResult'] !== false;
      this.maxAudioBytes = maxAudioBytesOf(params);
      this.audioBytesWritten = 0;
      this.voiceprintIds = voiceprintIds;
      this.speechActive = false;
      this.busy = true;
      const callback: AsrCallback = new DingqiaoAsrCallback(this);
      this.startingSession = true;
      this.sessionStartedDuringCreate = false;
      this.cancelRequestedDuringStart = false;
      const createdSession = this.asrEngine.newSession(
        callback,
        buildSessionConfig(params, configureTarget, verify || speakerVad)
      );
      this.startingSession = false;
      if (this.cancelRequestedDuringStart || this.destroyed || !this.busy || this.currentSessionId !== params.sessionId) {
        this.sessionStartedDuringCreate = false;
        this.cancelRequestedDuringStart = false;
        createdSession.close();
        return;
      }
      this.session = createdSession;
      if (useTarget && embedding !== undefined) {
        this.session.setTargetSpeaker(embedding);
        this.session.setTargetSpeakerEnabled(verify);
        if (speakerVad) {
          this.session.setSpeakerVadEnabled(true);
        }
      }
      if (this.sessionStartedDuringCreate) {
        this.sessionStartedDuringCreate = false;
        this.handleSessionStarted();
      }
    } catch (e) {
      this.startingSession = false;
      this.sessionStartedDuringCreate = false;
      this.cancelRequestedDuringStart = false;
      this.tearDownSession();
      this.listener?.onError?.(params.sessionId, DingqiaoErrorCode.START_LISTENING_FAILED, `${e}`);
    }
  }

  writeAudio(sessionId: string, audio: ArrayBuffer): void {
    this.ensureAlive();
    if (!this.busy || this.session === undefined) {
      if (!this.busy && sessionId === this.lastAutoFinishedSessionId) return;
      this.listener?.onError?.(sessionId, DingqiaoErrorCode.NOT_LISTENING, 'startListening not succeeded');
      return;
    }
    if (sessionId !== this.currentSessionId) {
      this.listener?.onError?.(sessionId, DingqiaoErrorCode.RECOGNITION_ERROR, 'sessionId mismatch');
      return;
    }
    if (audio.byteLength === 0) return;
    if (!isSupportedAudioFrameBytes(audio.byteLength)) {
      this.listener?.onError?.(sessionId, DingqiaoErrorCode.RECOGNITION_ERROR, 'audio frame must be 640 bytes');
      return;
    }
    if (this.finishRequested) return;
    this.session.acceptPcmBytes(audio);
    this.audioBytesWritten += audio.byteLength;
    if (!this.finishRequested && this.maxAudioBytes > 0 && this.audioBytesWritten >= this.maxAudioBytes) {
      // 达到单会话上限是正常的生命周期终止，不是错误：等价于自动 finish，
      // flush 出最终 onResult + onComplete 并清理会话，使引擎可被再次 startListening。
      this.finishRequested = true;
      this.lastFinishedSessionId = sessionId;
      this.lastAutoFinishedSessionId = sessionId;
      this.session.stop();
    }
  }

  setSpeakerVadEnabled(enabled: boolean): void {
    this.ensureAlive();
    if (this.session === undefined || !this.busy) return;
    const sessionId = this.currentSessionId;
    const session = this.session;
    try {
      if (enabled) {
        const embedding = new VoiceprintStore(SpeechRecognizeSdk.getWorkPath()).loadMergedEmbedding(this.voiceprintIds);
        if (embedding === undefined) {
          this.listener?.onError?.(sessionId, DingqiaoErrorCode.VOICEPRINT_NOT_FOUND, 'voiceprint not found for speaker VAD');
          return;
        }
        session.setTargetSpeaker(embedding);
        // This API is synchronous by contract. Enabling streaming Speaker VAD is the one path that
        // intentionally blocks until the extractor is ready; final-only verification never does.
        session.ensureTargetSpeakerExtractor();
        // ensureTargetSpeakerExtractor() can synchronously flush a final result. Its callbacks may
        // complete and tear down this session before control returns here.
        if (this.session !== session || !this.busy || this.currentSessionId !== sessionId) return;
      }
      session.setSpeakerVadEnabled(enabled);
      this.listener?.onEvent?.(sessionId, DingqiaoEventCode.SPEAKER_VAD_CHANGED, `speaker vad ${enabled ? 'enabled' : 'disabled'}.`);
    } catch (e) {
      if (this.session === session) session.setSpeakerVadEnabled(false);
      this.listener?.onError?.(sessionId, DingqiaoErrorCode.RECOGNITION_ERROR, `setSpeakerVadEnabled failed: ${e}`);
    }
  }

  finish(sessionId: string): void {
    this.ensureAlive();
    // stop() 在 Harmony 上可同步回调并清空会话。记住最近正常结束的 session，
    // 让紧随其后的重复 finish 与 Android 的异步完成窗口保持同样的幂等语义。
    if (!this.busy && sessionId === this.lastFinishedSessionId) return;
    if (!this.busy || sessionId !== this.currentSessionId || this.session === undefined) {
      this.listener?.onError?.(sessionId, DingqiaoErrorCode.FINISH_FAILED, 'finish failed');
      return;
    }
    if (this.finishRequested) return;
    this.finishRequested = true;
    this.lastFinishedSessionId = sessionId;
    this.session.stop();
  }

  cancel(sessionId: string): void {
    this.ensureAlive();
    if (!this.busy || sessionId !== this.currentSessionId) {
      this.listener?.onError?.(sessionId, DingqiaoErrorCode.CANCEL_FAILED, 'cancel failed');
      return;
    }
    if (this.startingSession && this.session === undefined) {
      this.cancelRequestedDuringStart = true;
      this.resetSessionState();
      return;
    }
    this.tearDownSession();
  }

  isBusy(): boolean { return this.busy; }

  // Kept off the customer interface; the delivery cold-load harness uses this to reject a
  // misleading "fast" sample when optional punctuation construction silently degraded.
  isPunctuationLoaded(): boolean { return this.asrEngine.isPunctuationLoaded(); }

  shutdown(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.tearDownSession();
    this.asrEngine.close();
    this.pipeline.close();
  }

  private deliverFinal(result: AsrResult): void {
    if (!this.busy || this.currentSessionId.length === 0 || this.completeSent) return;
    const enhanced = this.pipeline.enhance(result.text);
    const payload = new SpeechRecognitionResult();
    payload.isFinal = true;
    payload.isLast = result.isLast;
    payload.result = enhanced.text;
    payload.speakerSimilarity = result.speakerScore;
    // beginTime/endTime from token timestamps (seconds -> ms), aligned with Android dispatchResult.
    const ts = result.timestamps;
    if (ts.length > 0) {
      payload.beginTime = Math.round(ts[0] * 1000);
      payload.endTime = Math.round(ts[ts.length - 1] * 1000);
    }
    this.finalResultSent = true;
    this.listener?.onResult?.(this.currentSessionId, payload);
    if (result.isLast) {
      this.completeCurrentSession();
    }
  }

  private completeCurrentSession(): void {
    if (this.completeSent) return;
    const sessionId = this.currentSessionId;
    if (sessionId.length === 0) return;
    this.completeSent = true;
    this.tearDownSession();
    this.listener?.onComplete?.(sessionId, 'recognize complete');
  }

  private resetSessionState(): void {
    this.session = undefined;
    this.busy = false;
    this.currentSessionId = '';
    this.finishRequested = false;
    this.finalResultSent = false;
    this.completeSent = false;
    this.voiceprintIds = [];
    this.speechActive = false;
    this.sessionStartedDuringCreate = false;
  }

  private tearDownSession(): void {
    const oldSession = this.session;
    this.resetSessionState();
    oldSession?.close();
  }

  private rebuildEngine(params: StartParams, withTargetSpeaker: boolean, withSpeakerVad: boolean,
    speakerModelPath?: string): void {
    const newKey = this.computeEngineCfgKey(withTargetSpeaker, withSpeakerVad);
    if (newKey === this.engineCfgKey) {
      // 会话配置未变(纯 ASR 反复开始/结束):复用已加载的引擎与模型,避免每次点"开始识别"重载模型卡 3~4 秒。
      return;
    }
    // 先建新引擎、成功后再关旧引擎:create() 可能抛(模型加载 / 鉴权失败)。若先 close 再 create,
    // create 抛出后旧引擎已被关闭而 engineCfgKey 仍是旧值 —— 下次相同配置的 startListening 会 early-return
    // 复用这个已关闭的引擎(newSession on closed engine)→ native use-after-close 崩溃且不可恢复。
    // create-before-close 保证 create 抛出时旧引擎仍可用、engineCfgKey 不变。create() 复用池化 recognizer,不会重载大模型。
    const next = AmphionRuntime.create(this.context, languageOf(this.params.language),
      buildAsrConfig(this.context, this.params, params, withTargetSpeaker, withSpeakerVad, speakerModelPath));
    this.asrEngine.close();
    this.asrEngine = next;
    this.engineCfgKey = newKey;
  }

  handlePartial(text: string): void {
    if (!this.busy || this.currentSessionId.length === 0) return;
    if (!this.partialEnabled || text.length === 0) return;
    const result = new SpeechRecognitionResult();
    result.isFinal = false;
    result.isLast = false;
    result.result = text;
    this.listener?.onResult?.(this.currentSessionId, result);
  }

  handleSpeechBegin(): void {
    if (!this.busy || this.currentSessionId.length === 0) return;
    this.speechActive = true;
    this.listener?.onEvent?.(this.currentSessionId, DingqiaoEventCode.SPEECH_BEGIN, 'speech started.');
  }

  handleInitialSilenceTimeout(): void {
    if (!this.busy || this.finishRequested || this.session === undefined) return;
    const sessionId = this.currentSessionId;
    const session = this.session;
    this.finishRequested = true;
    this.lastFinishedSessionId = sessionId;
    this.lastAutoFinishedSessionId = sessionId;
    // VAD callback runs inside acceptPcmBytes; defer stop to avoid re-entering the native stream.
    setTimeout((): void => {
      if (!this.busy || this.session !== session || this.currentSessionId !== sessionId) return;
      session.stop();
    }, 0);
  }

  handleEndpoint(): void {
    if (!this.busy || this.currentSessionId.length === 0) return;
    if (!this.speechActive) return;
    this.speechActive = false;
    this.listener?.onEvent?.(this.currentSessionId, DingqiaoEventCode.SPEECH_END, 'speech stopped.');
  }

  handleFinalResult(result: AsrResult): void {
    this.deliverFinal(result);
  }

  handleFinalRejected(result: AsrResult): void {
    // Speaker VAD dropped a non-target span (no transcription emitted); surface as an event so the UI
    // can show the target speaker left without polluting the recognized text.
    const detail = result.speakerScore !== undefined ? `score=${result.speakerScore.toFixed(2)}` : 'target speaker absent';
    this.listener?.onEvent?.(this.currentSessionId, DingqiaoEventCode.SPEAKER_VAD_REJECTED, `speaker vad rejected: ${detail}`);
    if (rejectedFinalCompletesSession(result.isLast)) {
      const payload = new SpeechRecognitionResult();
      payload.isFinal = true;
      payload.isLast = true;
      payload.result = '';
      payload.speakerSimilarity = result.speakerScore;
      this.finalResultSent = true;
      this.listener?.onResult?.(this.currentSessionId, payload);
      this.completeCurrentSession();
    }
  }

  handleAsrError(error: AsrError): void {
    const sessionId = this.currentSessionId;
    this.tearDownSession();
    this.listener?.onError?.(sessionId, DingqiaoErrorCode.RECOGNITION_ERROR, `${error.code}: ${error.message}`);
  }

  handleSessionStarted(): void {
    if (this.startingSession) {
      this.sessionStartedDuringCreate = true;
      return;
    }
    const sessionId = this.currentSessionId;
    if (!this.busy || this.session === undefined || sessionId.length === 0) return;
    this.listener?.onStart?.(sessionId, 'startListening success.');
  }

  handleSessionStopped(): void {
    if (this.finishRequested) {
      const sessionId = this.currentSessionId;
      setTimeout((): void => {
        if (!this.busy || !this.finishRequested || this.completeSent || this.currentSessionId !== sessionId) return;
        const result = new SpeechRecognitionResult();
        result.isFinal = true;
        result.isLast = true;
        result.result = '';
        this.finalResultSent = true;
        this.listener?.onResult?.(sessionId, result);
        this.completeCurrentSession();
      }, STOP_FALLBACK_DELAY_MS);
    } else {
      this.tearDownSession();
    }
  }

  private ensureAlive(): void {
    if (this.destroyed) throw new Error('engine destroyed');
  }
}

class DingqiaoAsrCallback implements AsrCallback {
  private owner: DingqiaoRecognitionEngineImpl;

  constructor(owner: DingqiaoRecognitionEngineImpl) {
    this.owner = owner;
  }

  onSpeechBegin(): void {
    this.owner.handleSpeechBegin();
  }

  onInitialSilenceTimeout(): void {
    this.owner.handleInitialSilenceTimeout();
  }

  onPartial(text: string): void {
    this.owner.handlePartial(text);
  }

  onEndpoint(): void {
    this.owner.handleEndpoint();
  }

  onFinalResult(result: AsrResult): void {
    this.owner.handleFinalResult(result);
  }

  onFinalRejected(result: AsrResult): void {
    this.owner.handleFinalRejected(result);
  }

  onError(error: AsrError): void {
    this.owner.handleAsrError(error);
  }

  onSessionStarted(): void {
    this.owner.handleSessionStarted();
  }

  onSessionStopped(): void {
    this.owner.handleSessionStopped();
  }
}

export interface LicenseDeviceIdProvider {
  getDeviceSerial(context: Context): string | undefined;
}

// 设备 SN 提供者(对齐 Android DingqiaoDeviceIdProvider):读设备序列号供 license SN 白名单校验。
// 读取 deviceInfo.serial 需要 ohos.permission.sec.ACCESS_UDID(系统/特权权限);普通 Demo 读不到 -> 返回 undefined。
class SystemDeviceIdProvider implements LicenseDeviceIdProvider {
  getDeviceSerial(_context: Context): string | undefined {
    try {
      const sn = deviceInfo.serial;
      return sn !== undefined && sn.length > 0 ? sn : undefined;
    } catch (e) {
      return undefined;
    }
  }
}

// Keep the public Dingqiao provider type independent from the core HAR's emitted API type.
// The explicit adapter also prevents core package type identity from leaking to customers.
class CoreDeviceIdProviderAdapter implements AmphionDeviceIdProvider {
  private delegate: LicenseDeviceIdProvider;

  constructor(delegate: LicenseDeviceIdProvider) {
    this.delegate = delegate;
  }

  getDeviceSerial(context: Context): string | undefined {
    try {
      return this.delegate.getDeviceSerial(context);
    } catch (e) {
      // 设备标识不可读统一落到 License 的 device mismatch 状态，避免 provider 异常逃逸为兜底错误。
      return undefined;
    }
  }
}

// license expiresAt("YYYY-MM-DD")→ epoch ms(当日 00:00:00 UTC),对齐安卓 toExpireTimeMillis
// (LocalDate.parse(x).atStartOfDay().toInstant(UTC))。空/非法返回 -1。
function expireTimeMillisFromClaim(expiresAt: string | undefined): number {
  if (expiresAt === undefined || expiresAt.trim().length === 0) return -1;
  const ms = new Date(`${expiresAt.trim()}T00:00:00Z`).getTime();
  return Number.isNaN(ms) ? -1 : ms;
}

// 剩余天数,对齐安卓 toRemainingDays(ChronoUnit.DAYS.between(now(UTC), expiry))。
// 两端都取当日 00:00:00 UTC,差为整数天;已过期返回负数(与安卓一致,不夹取到 0)。空/非法返回 -1。
function remainingDaysFromClaim(expiresAt: string | undefined): number {
  if (expiresAt === undefined || expiresAt.trim().length === 0) return -1;
  const expMs = new Date(`${expiresAt.trim()}T00:00:00Z`).getTime();
  if (Number.isNaN(expMs)) return -1;
  const todayMs = new Date(`${new Date().toISOString().substring(0, 10)}T00:00:00Z`).getTime();
  return Math.round((expMs - todayMs) / 86400000);
}

export class SpeechRecognizeSdk {
  private static context?: Context;
  private static workPath: string = '';
  private static licenseInfo?: LicenseInfo;
  private static deviceIdProvider?: LicenseDeviceIdProvider;
  private static activatedLicenseText?: string;
  private static licenseRequestGeneration: number = 0;
  private static runtimeGeneration: number = 0;
  private static prepareTask?: Promise<void>;

  /** Uses the host provider for device-bound licenses; privileged hosts may omit it to use hardware SN. */
  static init(context: Context, deviceIdProvider?: LicenseDeviceIdProvider): void {
    if (SpeechRecognizeSdk.context !== undefined &&
      (SpeechRecognizeSdk.context !== context || SpeechRecognizeSdk.deviceIdProvider !== deviceIdProvider)) {
      SpeechRecognizeSdk.invalidateRuntime();
      SpeechRecognizeSdk.activatedLicenseText = undefined;
      SpeechRecognizeSdk.licenseInfo = undefined;
      SpeechRecognizeSdk.licenseRequestGeneration += 1;
    }
    SpeechRecognizeSdk.context = context;
    SpeechRecognizeSdk.deviceIdProvider = deviceIdProvider;
  }

  static setWorkPath(path: string): void {
    if (path.trim().length === 0) throw new Error('workPath must not be empty');
    if (!fs.accessSync(path)) fs.mkdirSync(path, true);
    SpeechRecognizeSdk.workPath = path;
  }

  static setLicense(licensePath: string, callback: LicenseActivationCallback): void {
    const context = SpeechRecognizeSdk.context;
    if (context === undefined) {
      callback.onError(DingqiaoErrorCode.ENGINE_NOT_INITIALIZED, 'SpeechRecognizeSdk.init must be called first');
      return;
    }
    // 每次调用都参与 latest-wins；即使新请求的文件路径本身无效，也不能让更早的异步校验稍后覆盖状态。
    const requestGeneration = ++SpeechRecognizeSdk.licenseRequestGeneration;
    if (licensePath.length === 0) {
      callback.onError(DingqiaoErrorCode.LICENSE_FILE_UNREADABLE, 'licensePath is empty');
      return;
    }
    if (!fs.accessSync(licensePath)) {
      callback.onError(DingqiaoErrorCode.LICENSE_FILE_UNREADABLE, `license file not found: ${licensePath}`);
      return;
    }
    let licenseText = '';
    try {
      licenseText = readTextFile(licensePath);
    } catch (e) {
      callback.onError(DingqiaoErrorCode.LICENSE_FILE_UNREADABLE, `license file not readable: ${e}`);
      return;
    }
    // 完整鉴权是异步的，但只校验并缓存授权；Runtime 必须由 prepareRuntime 显式拉起。
    SpeechRecognizeSdk.activateLicense(context, licenseText, callback, requestGeneration);
  }

  private static async activateLicense(
    context: Context,
    licenseText: string,
    callback: LicenseActivationCallback,
    requestGeneration: number
  ): Promise<void> {
    const provider = SpeechRecognizeSdk.deviceIdProvider ?? new SystemDeviceIdProvider();
    const options = SpeechRecognizeSdk.buildRuntimeOptions(licenseText, provider);
    let status: AmphionLicenseStatus;
    try {
      // 与 Runtime.init 共用完整的单遍校验：结构/feature/有效期/maintenance/sdkMajor/ECDSA/SN。
      // validateLicense 无副作用，不会提前创建 Runtime 或模型。
      status = await AmphionRuntime.validateLicense(context, options);
    } catch (e) {
      if (requestGeneration !== SpeechRecognizeSdk.licenseRequestGeneration) {
        callback.onError(DingqiaoErrorCode.LICENSE_ACTIVATION_FAILED,
          'setLicense superseded by a newer request');
        return;
      }
      const info = new LicenseInfo();
      info.status = 2;
      info.expireTime = -1;
      info.remainingDays = -1;
      info.authorizedFeatures = [];
      SpeechRecognizeSdk.recordLicenseFailureIfInactive(info);
      callback.onError(DingqiaoErrorCode.LICENSE_ACTIVATION_FAILED, `license validation failed: ${e}`);
      return;
    }
    if (requestGeneration !== SpeechRecognizeSdk.licenseRequestGeneration) {
      callback.onError(DingqiaoErrorCode.LICENSE_ACTIVATION_FAILED,
        'setLicense superseded by a newer request');
      return;
    }

    const code = status.valid ? 0 : mapLicenseErrorCode(status.errorCode);
    const info = SpeechRecognizeSdk.licenseInfoFromStatus(status, code);
    if (!status.valid) {
      SpeechRecognizeSdk.recordLicenseFailureIfInactive(info);
      callback.onError(code, status.message);
      return;
    }

    // 新授权只有在完整校验成功后才替换旧状态；替换授权会使旧 Runtime/模型失效。
    SpeechRecognizeSdk.invalidateRuntime();
    SpeechRecognizeSdk.activatedLicenseText = licenseText;
    SpeechRecognizeSdk.licenseInfo = info;
    const result = new LicenseActivationResult();
    result.errorCode = 0;
    result.errorMessage = '';
    result.remainingDays = info.remainingDays;
    result.authorizedFeatures = info.authorizedFeatures;
    callback.onResult(result);
  }

  private static buildRuntimeOptions(licenseText: string,
    provider: LicenseDeviceIdProvider): AmphionOptions {
    const options = new AmphionOptions();
    options.license = licenseText;
    options.deviceIdProvider = new CoreDeviceIdProviderAdapter(provider);
    return options;
  }

  private static licenseInfoFromStatus(status: AmphionLicenseStatus, code: number): LicenseInfo {
    const info = new LicenseInfo();
    info.status = status.valid ? 0 :
      (code === DingqiaoErrorCode.LICENSE_EXPIRED ? 1 :
        (code === DingqiaoErrorCode.LICENSE_DEVICE_MISMATCH ? 3 : 2));
    info.expireTime = status.valid ? expireTimeMillisFromClaim(status.expiresAt) : -1;
    info.remainingDays = status.valid ? remainingDaysFromClaim(status.expiresAt) : -1;
    info.authorizedFeatures = status.valid ? status.features.slice() : [];
    return info;
  }

  private static recordLicenseFailureIfInactive(info: LicenseInfo): void {
    // setLicense 是原子替换：已有可用授权时，失败的新授权不能破坏正在使用的旧授权/Runtime。
    if (SpeechRecognizeSdk.activatedLicenseText === undefined) {
      SpeechRecognizeSdk.licenseInfo = info;
    }
  }

  static getLicenseInfo(): LicenseInfo {
    if (SpeechRecognizeSdk.licenseInfo === undefined) {
      throw new DingqiaoSdkError(DingqiaoErrorCode.LICENSE_NOT_SET, 'license not set');
    }
    return SpeechRecognizeSdk.licenseInfo;
  }

  // ---- 两级加载(L1 运行时 / L2 模型)---------------------------------------------------------
  // 甲方契约:占内存的模型「用完释放、用时当场起」;不占内存的运行时框架「可常驻加速」。
  // prepareRuntime/unloadRuntime 管 L1(运行时);createEngine/registerVoiceprint/unloadModel 管 L2
  // (内存模型)。具体净内存与时延以目标设备的交付测量表为准。createEngine 已实现
  // 「未加载则加载,已加载则复用只建会话」。

  /**
   * L1:只拉起 SDK 运行时框架，不加载或复制模型。调用前必须先成功 setLicense；Runtime 初始化
   * 幂等且 single-flight，并发调用共享同一任务。
   */
  static prepareRuntime(callback: PrepareRuntimeCallback): void {
    const context = SpeechRecognizeSdk.context;
    if (context === undefined) {
      callback.onError(DingqiaoErrorCode.ENGINE_NOT_INITIALIZED, 'SpeechRecognizeSdk.init must be called first');
      return;
    }
    const licenseText = SpeechRecognizeSdk.activatedLicenseText;
    const licenseInfo = SpeechRecognizeSdk.licenseInfo;
    if (licenseText === undefined || licenseInfo === undefined) {
      callback.onError(DingqiaoErrorCode.LICENSE_NOT_SET,
        'setLicense must succeed before prepareRuntime');
      return;
    }
    if (licenseInfo.status !== 0) {
      const errorCode = licenseInfo.status === 1 ? DingqiaoErrorCode.LICENSE_EXPIRED :
        (licenseInfo.status === 3 ? DingqiaoErrorCode.LICENSE_DEVICE_MISMATCH :
          DingqiaoErrorCode.LICENSE_INVALID);
      callback.onError(errorCode, 'cached license is no longer valid; call setLicense again');
      return;
    }
    if (AmphionRuntime.isRuntimeReady()) {
      callback.onReady();
      return;
    }
    const generation = SpeechRecognizeSdk.runtimeGeneration;
    let task = SpeechRecognizeSdk.prepareTask;
    if (task === undefined) {
      const provider = SpeechRecognizeSdk.deviceIdProvider ?? new SystemDeviceIdProvider();
      task = AmphionRuntime.init(context, SpeechRecognizeSdk.buildRuntimeOptions(licenseText, provider));
      SpeechRecognizeSdk.prepareTask = task;
    }
    const observedTask = task;
    observedTask
      .then((): void => {
        if (generation !== SpeechRecognizeSdk.runtimeGeneration || !AmphionRuntime.isRuntimeReady()) {
          callback.onError(DingqiaoErrorCode.ENGINE_NOT_INITIALIZED, 'prepareRuntime cancelled by unloadRuntime');
          return;
        }
        callback.onReady();
      })
      .catch((e: Object): void => {
        const message = `${e}`;
        const licenseCode = mapLicenseErrorCode(extractAsrErrorCode(message));
        const errorCode = licenseCode === DingqiaoErrorCode.LICENSE_ACTIVATION_FAILED ?
          DingqiaoErrorCode.ENGINE_NOT_INITIALIZED : licenseCode;
        // unloadRuntime 保留的是上次激活快照；重新 prepare 时会再次完整验权。若授权在此期间
        // 过期/失效，同步刷新公开状态。generation + 文本双重检查防止旧 Promise 覆盖新授权。
        if (licenseCode !== DingqiaoErrorCode.LICENSE_ACTIVATION_FAILED &&
          generation === SpeechRecognizeSdk.runtimeGeneration &&
          SpeechRecognizeSdk.activatedLicenseText === licenseText) {
          const failedInfo = new LicenseInfo();
          failedInfo.status = licenseCode === DingqiaoErrorCode.LICENSE_EXPIRED ? 1 :
            (licenseCode === DingqiaoErrorCode.LICENSE_DEVICE_MISMATCH ? 3 : 2);
          failedInfo.expireTime = -1;
          failedInfo.remainingDays = -1;
          failedInfo.authorizedFeatures = [];
          SpeechRecognizeSdk.licenseInfo = failedInfo;
        }
        callback.onError(errorCode, `prepareRuntime failed: ${message}`);
      })
      .finally((): void => {
        if (SpeechRecognizeSdk.prepareTask === observedTask) {
          SpeechRecognizeSdk.prepareTask = undefined;
        }
      });
  }

  /**
   * L2:从内存卸载模型(recognizer / punctuation / voiceprint extractor / vad),运行时保留常驻。
   * SDK 包内及 workPath 中的模型文件、已注册声纹 embedding 都是持久数据,不会被删除。下次使用只重付
   * 内存模型加载,无需重建运行时。
   */
  static unloadModel(): void {
    AmphionRuntime.unloadModel();
  }

  /**
   * L1:卸载 SDK 运行时框架资源,重置为未初始化态。若模型仍在,模型跟随卸载(release 内部先 unloadModel)。
   * 已激活授权会保留；再次使用只需 prepareRuntime，无需重新 setLicense。native .so 由 OS 保留映射。
   */
  static unloadRuntime(): void {
    SpeechRecognizeSdk.invalidateRuntime();
  }

  private static invalidateRuntime(): void {
    SpeechRecognizeSdk.runtimeGeneration += 1;
    // Promise 不可取消；清掉 wrapper 引用并让 core generation 拒绝旧任务提交。
    SpeechRecognizeSdk.prepareTask = undefined;
    AmphionRuntime.release();
  }

  // L2:若模型未加载则加载,若已加载则复用(不重复加载模型)、只建会话。复用由 AmphionRuntime 的按语言+
  // 配置池化实现:同配置命中池;unloadModel 后池空 → 重新冷加载。需先成功 setLicense，再完成
  // prepareRuntime，否则内部 checkInitialized 抛错。
  static createEngine(params: CreateEngineParams): SpeechRecognitionEngine {
    if (SpeechRecognizeSdk.context === undefined) throw new Error('SpeechRecognizeSdk.init must be called first');
    return new DingqiaoRecognitionEngineImpl(SpeechRecognizeSdk.context, params);
  }

  static createEngineAsync(params: CreateEngineParams, callback: CreateEngineCallback): void {
    const context = SpeechRecognizeSdk.context;
    if (context === undefined) {
      callback.onError(DingqiaoErrorCode.ENGINE_NOT_INITIALIZED, 'SpeechRecognizeSdk.init must be called first');
      return;
    }
    try {
      const paramsSnapshot = snapshotCreateEngineParams(params);
      const language: AsrLanguage = languageOf(paramsSnapshot.language);
      const config: AsrConfig = buildAsrConfig(context, paramsSnapshot);
      AmphionRuntime.createAsync(context, language, config)
        .then((engine: AsrEngine): void => {
          callback.onSuccess(new DingqiaoRecognitionEngineImpl(context, paramsSnapshot, engine));
        })
        .catch((e: Object): void => {
          callback.onError(DingqiaoErrorCode.CREATE_ENGINE_FAILED, `${e}`);
        });
    } catch (e) {
      callback.onError(DingqiaoErrorCode.CREATE_ENGINE_FAILED, `${e}`);
    }
  }

  static registerVoiceprint(params: VoiceprintRegisterParams): VoiceprintRegisterResult {
    const result = new VoiceprintRegisterResult();
    if (params.samplePaths.length < DINGQIAO_VOICEPRINT_MIN_SAMPLES) {
      result.status = DingqiaoErrorCode.VOICEPRINT_SAMPLE_COUNT;
      result.message = `sample count must be >= ${DINGQIAO_VOICEPRINT_MIN_SAMPLES}`;
      return result;
    }
    for (let i = 0; i < params.samplePaths.length; i++) {
      const path = params.samplePaths[i];
      if (!fs.accessSync(path)) {
        result.status = DingqiaoErrorCode.VOICEPRINT_REGISTER_FAILED;
        result.message = `sample not found: ${path}`;
        return result;
      }
      const durationMs = fileDurationMs(path);
      if (durationMs < DINGQIAO_VOICEPRINT_MIN_SEC * 1000 ||
        durationMs > DINGQIAO_VOICEPRINT_MAX_SEC * 1000) {
        result.status = DingqiaoErrorCode.VOICEPRINT_SAMPLE_DURATION;
        result.message = `sample duration must be ${DINGQIAO_VOICEPRINT_MIN_SEC}s..` +
          `${DINGQIAO_VOICEPRINT_MAX_SEC}s: ${path}`;
        return result;
      }
    }
    try {
      const context = SpeechRecognizeSdk.context;
      if (context === undefined) throw new Error('SpeechRecognizeSdk.init must be called first');
      const modelPath = DingqiaoSpeakerModelAssets.bundledPath();
      // Reuse the shared, pooled extractor so registration warms the SAME instance the recognition
      // path uses — the ~38 MB eres2net load is paid here (where a wait is expected) and start
      // recognition stays instant.
      const extractor = AmphionRuntime.getOrCreateSpeakerExtractor(context, modelPath, 1);
      const enroller = new SpeakerEnroller(modelPath, 1, context, extractor);
      const embedding = enroller.enrollFiles(params.samplePaths);
      enroller.close();
      // Persist to {workPath}/voiceprints/{id}; auto-generated id is returned to the caller and
      // later passed back via StartParams.extraParams.voiceprintIds for the recognition session.
      const store = new VoiceprintStore(SpeechRecognizeSdk.workPath);
      const id = store.saveVoiceprint(params.samplePaths, embedding);
      result.voiceprintId = {};
      result.voiceprintId[id] = baseName(params.samplePaths[0]);
      result.status = 0;
      result.message = 'registered';
    } catch (e) {
      result.status = DingqiaoErrorCode.VOICEPRINT_REGISTER_FAILED;
      result.message = `${e}`;
    }
    return result;
  }

  static deleteVoiceprint(voiceprintId: string): boolean {
    if (!new VoiceprintStore(SpeechRecognizeSdk.workPath).deleteVoiceprint(voiceprintId)) {
      throw new DingqiaoSdkError(DingqiaoErrorCode.VOICEPRINT_NOT_FOUND, `voiceprint not found: ${voiceprintId}`);
    }
    return true;
  }

  static getWorkPath(): string { return SpeechRecognizeSdk.workPath; }

  /**
   * Preload + warm the voiceprint extractor. Final-only verification already loads it in the
   * background; explicit preload removes its final-result wait and Speaker VAD cold-start cost.
   * Idempotent (no-op once pooled). Returns false if Runtime is not ready or model loading fails.
   * Registration already warms the same pool, so this mainly covers the app-restart case
   * (model on disk + voiceprint registered, but the in-memory pool is cold). Synchronous - call it
   * only at a caller-chosen non-critical moment.
   */
  static preloadVoiceprintModel(): boolean {
    try {
      const context = SpeechRecognizeSdk.context;
      if (context === undefined) return false;
      const modelPath = DingqiaoSpeakerModelAssets.bundledPath();
      AmphionRuntime.getOrCreateSpeakerExtractor(context, modelPath, 1);
      return true;
    } catch (e) {
      return false;
    }
  }

}
