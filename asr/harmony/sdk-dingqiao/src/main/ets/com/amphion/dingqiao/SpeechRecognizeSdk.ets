import { AmphionDeviceIdProvider, AmphionRuntime, AmphionOptions, AsrCallback, AsrConfig, AsrEngine, AsrError, AsrErrorCode, AsrLanguage, AsrResult, AsrSession, SpeakerEnroller, SpeakerVadConfig, TargetSpeakerConfig } from 'amphion_asr';
import { PoliceEngineConfig, PoliceEnhanceOptions, PoliceEnhancePipeline } from 'amphion_police';
import { fileIo as fs } from '@kit.CoreFileKit';
import deviceInfo from '@ohos.deviceInfo';
import { VoiceprintStore } from './VoiceprintStore';
import {
  AudioInfo,
  CreateEngineCallback,
  CreateEngineParams,
  DINGQIAO_AUDIO_FRAME_BYTES_20MS,
  DINGQIAO_AUDIO_FRAME_BYTES_40MS,
  DingqiaoErrorCode,
  DingqiaoEventCode,
  LicenseActivationCallback,
  LicenseActivationResult,
  LicenseInfo,
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
  if (typeof value === 'number') return value;
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : defaultValue;
  }
  return defaultValue;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function vadEndMs(params?: StartParams): number {
  return clamp(numberParam(params?.extraParams ?? {}, 'vadEnd', 800), 500, 10000);
}

function isSupportedAudioFrameBytes(byteLength: number): boolean {
  return byteLength === DINGQIAO_AUDIO_FRAME_BYTES_20MS;
}

function maxAudioBytesOf(params: StartParams): number {
  const ms = Math.max(numberParam(params.extraParams, 'maxAudioDuration', 20000), 20000);
  // 16 kHz mono 16-bit PCM = 32 bytes per millisecond.
  return Math.round(ms * 32);
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
    asrCode === AsrErrorCode.LICENSE_SDK_MAJOR_MISMATCH) {
    return DingqiaoErrorCode.LICENSE_INVALID;
  }
  return DingqiaoErrorCode.LICENSE_ACTIVATION_FAILED;
}

function buildAsrConfig(params: CreateEngineParams, startParams?: StartParams, withTargetSpeaker: boolean = false, withSpeakerVad: boolean = false): AsrConfig {
  const plate = booleanParam(params.extraParams, 'plateNormalizeEnabled', true);
  const station = booleanParam(params.extraParams, 'stationNormalizeEnabled', true);
  const terms = booleanParam(params.extraParams, 'termsNormalizeEnabled', true);
  const config = PoliceEngineConfig.build(parseLexicon(params.extraParams['sysGeneralLexicon']), plate, station, terms);
  config.vadConfig.activeEndpointSilenceMs = vadEndMs(startParams);
  config.endpointRules.rule2MinTrailingSilenceSec = 2.0;
  if (withTargetSpeaker) {
    config.targetSpeaker = buildTargetSpeakerConfig(startParams, withSpeakerVad);
  }
  return config;
}

function buildTargetSpeakerConfig(startParams: StartParams | undefined, withSpeakerVad: boolean): TargetSpeakerConfig {
  const extra = startParams?.extraParams ?? {};
  const cfg = new TargetSpeakerConfig();
  cfg.modelPath = `${SpeechRecognizeSdk.getWorkPath()}/eres2net.onnx`;
  // Score-only: never reject on segment-end verification so onFinal always carries speakerSimilarity
  // (mirrors Android Dingqiao SCORE_ONLY_THRESHOLD = -1). Speaker VAD does its own gating.
  cfg.threshold = -1.0;
  cfg.enabledByDefault = false;
  cfg.numThreads = 1;
  if (withSpeakerVad) {
    const sv = new SpeakerVadConfig();
    sv.threshold = clamp(numberParam(extra, 'speakerVadThreshold', 0.40), -1.0, 1.0);
    sv.winSec = clamp(numberParam(extra, 'speakerVadWindowMs', 1000), 500, 5000) / 1000;
    sv.hopSec = clamp(numberParam(extra, 'speakerVadHopMs', 300), 100, 2000) / 1000;
    sv.consecutiveBelow = Math.round(clamp(numberParam(extra, 'speakerVadConsecutiveBelow', 2), 1, 5));
    sv.enabledByDefault = false;
    cfg.speakerVad = sv;
  }
  return cfg;
}

function buildEnhanceOptions(params: CreateEngineParams): PoliceEnhanceOptions {
  const options = new PoliceEnhanceOptions();
  options.plateNormalizeEnabled = booleanParam(params.extraParams, 'plateNormalizeEnabled', true);
  options.stationNormalizeEnabled = booleanParam(params.extraParams, 'stationNormalizeEnabled', true);
  options.termsNormalizeEnabled = booleanParam(params.extraParams, 'termsNormalizeEnabled', true);
  return options;
}

class DingqiaoRecognitionEngineImpl implements SpeechRecognitionEngine {
  private context: Context;
  private params: CreateEngineParams;
  private listener?: RecognitionListener;
  private asrEngine: AsrEngine;
  private session?: AsrSession;
  private pipeline: PoliceEnhancePipeline = PoliceEnhancePipeline.create();
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
  // 当前 asrEngine 是用什么会话级配置建的;下次 startListening 若配置相同则复用,不重载模型。
  private engineCfgKey: string = '';

  constructor(context: Context, params: CreateEngineParams) {
    this.context = context;
    this.params = params;
    this.pipeline = PoliceEnhancePipeline.create(buildEnhanceOptions(params));
    this.asrEngine = AmphionRuntime.create(context, languageOf(params.language), buildAsrConfig(params));
    this.engineCfgKey = this.computeEngineCfgKey(undefined, false, false);
  }

  // 会话级配置指纹:只含影响引擎构建的可变项(VAD 端点、目标说话人/说话人VAD)。
  // recognizer(模型)级配置由 CreateEngineParams 固定,不随 startListening 变。
  private computeEngineCfgKey(sp: StartParams | undefined, withTargetSpeaker: boolean, withSpeakerVad: boolean): string {
    const extra: Record<string, Object> = sp?.extraParams ?? {};
    const parts: string[] = [`${withTargetSpeaker}`, `${withSpeakerVad}`, `${vadEndMs(sp)}`];
    if (withTargetSpeaker) {
      parts.push(`${numberParam(extra, 'speakerVadThreshold', 0.40)}`);
      parts.push(`${numberParam(extra, 'speakerVadWindowMs', 1000)}`);
      parts.push(`${numberParam(extra, 'speakerVadHopMs', 300)}`);
      parts.push(`${numberParam(extra, 'speakerVadConsecutiveBelow', 2)}`);
    }
    return parts.join('|');
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
    if (!isValidSessionId(params.sessionId)) {
      this.listener?.onError?.(params.sessionId, DingqiaoErrorCode.START_LISTENING_FAILED, 'sessionId must be non-empty alphanumeric/underscore/dash');
      return;
    }

    const verify = booleanParam(params.extraParams, 'enableVoiceprintVerification', false);
    const speakerVad = booleanParam(params.extraParams, 'enableSpeakerVad', false);
    const voiceprintIds = stringArrayParam(params.extraParams, 'voiceprintIds');
    let embedding: Float32Array | undefined;
    if ((verify || speakerVad) && voiceprintIds.length === 0) {
      this.listener?.onError?.(params.sessionId, DingqiaoErrorCode.START_LISTENING_FAILED, 'voiceprintIds required when enableVoiceprintVerification=true or enableSpeakerVad=true');
      return;
    }
    if ((verify || speakerVad) && voiceprintIds.length > 0) {
      const modelPath = `${SpeechRecognizeSdk.getWorkPath()}/eres2net.onnx`;
      if (!fs.accessSync(modelPath)) {
        this.listener?.onError?.(params.sessionId, DingqiaoErrorCode.START_LISTENING_FAILED, `voiceprint model not found: ${modelPath}`);
        return;
      }
      embedding = new VoiceprintStore(SpeechRecognizeSdk.getWorkPath()).loadMergedEmbedding(voiceprintIds);
      if (embedding === undefined) {
        this.listener?.onError?.(params.sessionId, DingqiaoErrorCode.VOICEPRINT_NOT_FOUND, `voiceprint not found for ids: ${voiceprintIds.join(',')}`);
        return;
      }
    }
    const useTarget = embedding !== undefined && (verify || speakerVad);

    try {
      this.rebuildEngine(params, useTarget, useTarget && speakerVad);
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
      this.busy = true;
      const callback: AsrCallback = new DingqiaoAsrCallback(this);
      this.session = this.asrEngine.newSession(callback);
      if (useTarget && embedding !== undefined) {
        this.session.setTargetSpeaker(embedding);
        this.session.setTargetSpeakerEnabled(verify);
        this.session.setSpeakerVadEnabled(speakerVad);
      }
    } catch (e) {
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
    if (enabled) {
      const embedding = new VoiceprintStore(SpeechRecognizeSdk.getWorkPath()).loadMergedEmbedding(this.voiceprintIds);
      if (embedding === undefined) {
        this.listener?.onError?.(this.currentSessionId, DingqiaoErrorCode.VOICEPRINT_NOT_FOUND, 'voiceprint not found for speaker VAD');
        return;
      }
      this.session.setTargetSpeaker(embedding);
    }
    this.session.setSpeakerVadEnabled(enabled);
    this.listener?.onEvent?.(this.currentSessionId, DingqiaoEventCode.SPEAKER_VAD_CHANGED, `speaker vad ${enabled ? 'enabled' : 'disabled'}.`);
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
    this.tearDownSession();
  }

  isBusy(): boolean { return this.busy; }

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
    payload.isLast = this.finishRequested;
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
    if (this.finishRequested) {
      this.maybeComplete();
      this.tearDownSession();
    }
  }

  private maybeComplete(): void {
    if (this.completeSent) return;
    this.completeSent = true;
    this.listener?.onComplete?.(this.currentSessionId, 'recognize complete');
  }

  private tearDownSession(): void {
    this.session?.close();
    this.session = undefined;
    this.busy = false;
    this.currentSessionId = '';
    this.finishRequested = false;
    this.finalResultSent = false;
    this.completeSent = false;
    this.voiceprintIds = [];
  }

  private rebuildEngine(params: StartParams, withTargetSpeaker: boolean, withSpeakerVad: boolean): void {
    const newKey = this.computeEngineCfgKey(params, withTargetSpeaker, withSpeakerVad);
    if (newKey === this.engineCfgKey) {
      // 会话配置未变(纯 ASR 反复开始/结束):复用已加载的引擎与模型,避免每次点"开始识别"重载模型卡 3~4 秒。
      return;
    }
    // 先建新引擎、成功后再关旧引擎:create() 可能抛(模型加载 / 鉴权失败)。若先 close 再 create,
    // create 抛出后旧引擎已被关闭而 engineCfgKey 仍是旧值 —— 下次相同配置的 startListening 会 early-return
    // 复用这个已关闭的引擎(newSession on closed engine)→ native use-after-close 崩溃且不可恢复。
    // create-before-close 保证 create 抛出时旧引擎仍可用、engineCfgKey 不变。create() 复用池化 recognizer,不会重载大模型。
    const next = AmphionRuntime.create(this.context, languageOf(this.params.language), buildAsrConfig(this.params, params, withTargetSpeaker, withSpeakerVad));
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

  handleEndpoint(): void {
    if (!this.busy || this.currentSessionId.length === 0) return;
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
    if (this.finishRequested) {
      this.maybeComplete();
      this.tearDownSession();
    }
  }

  handleAsrError(error: AsrError): void {
    this.listener?.onError?.(this.currentSessionId, DingqiaoErrorCode.RECOGNITION_ERROR, `${error.code}: ${error.message}`);
    this.tearDownSession();
  }

  handleSessionStarted(): void {
    this.listener?.onStart?.(this.currentSessionId, 'startListening success.');
    this.listener?.onEvent?.(this.currentSessionId, DingqiaoEventCode.SPEECH_BEGIN, 'speech started.');
  }

  handleSessionStopped(): void {
    if (this.finishRequested) {
      if (!this.finalResultSent) {
        const result = new SpeechRecognitionResult();
        result.isFinal = true;
        result.isLast = true;
        result.result = '';
        this.finalResultSent = true;
        this.listener?.onResult?.(this.currentSessionId, result);
      }
      this.maybeComplete();
    }
    this.tearDownSession();
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
    return this.delegate.getDeviceSerial(context);
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

  /** Uses the host provider for device-bound licenses; privileged hosts may omit it to use hardware SN. */
  static init(context: Context, deviceIdProvider?: LicenseDeviceIdProvider): void {
    SpeechRecognizeSdk.context = context;
    SpeechRecognizeSdk.deviceIdProvider = deviceIdProvider;
    // AmphionRuntime.init 现为异步(核心路径也强制 ECDSA 签名 + SN 白名单)。此处不带 license,真正的
    // 授权在 setLicense→activateLicense 完成(其会 release() 后再 init(options))。保持本 init 同步且容错:
    // 此处的 license 判定结果无意义(无 license),忽略其 rejection 即可。
    AmphionRuntime.init(context).catch((_e: Object): void => {});
  }

  static setWorkPath(path: string): void {
    SpeechRecognizeSdk.workPath = path;
  }

  static setLicense(licensePath: string, callback: LicenseActivationCallback): void {
    const context = SpeechRecognizeSdk.context;
    if (context === undefined) {
      callback.onError(DingqiaoErrorCode.ENGINE_NOT_INITIALIZED, 'SpeechRecognizeSdk.init must be called first');
      return;
    }
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
    // 真鉴权(ECDSA 验签 + SN 白名单)是异步的,交给 activateLicense 继续。
    SpeechRecognizeSdk.activateLicense(context, licenseText, callback);
  }

  private static async activateLicense(
    context: Context,
    licenseText: string,
    callback: LicenseActivationCallback
  ): Promise<void> {
    // 第一道门:真 ECDSA 验签。被篡改/伪造的 license(如改了 expiresAt)在这里被拒,引擎不会初始化。
    // 开发(未注入公钥)构建下 verifyLicenseSignature 返回 true,保持可用。
    let signatureValid: boolean = false;
    try {
      signatureValid = await AmphionRuntime.verifyLicenseSignature(licenseText);
    } catch (e) {
      const info = new LicenseInfo();
      info.status = 2;
      info.expireTime = -1;
      info.remainingDays = -1;
      info.authorizedFeatures = [];
      SpeechRecognizeSdk.licenseInfo = info;
      callback.onError(DingqiaoErrorCode.LICENSE_INVALID, `license signature verification failed: ${e}`);
      return;
    }
    if (!signatureValid) {
      const info = new LicenseInfo();
      info.status = 2;
      info.expireTime = -1;
      info.remainingDays = -1;
      info.authorizedFeatures = [];
      SpeechRecognizeSdk.licenseInfo = info;
      callback.onError(DingqiaoErrorCode.LICENSE_INVALID, 'license signature verification failed');
      return;
    }
    // 第二道门:设备白名单(对齐 Android)。特权宿主默认读取硬件 SN，普通宿主可注入稳定设备标识。
    const provider = SpeechRecognizeSdk.deviceIdProvider ?? new SystemDeviceIdProvider();
    let deviceOk: boolean = false;
    try {
      const deviceId: string | undefined = provider.getDeviceSerial(context);
      deviceOk = await AmphionRuntime.checkDeviceBinding(licenseText, deviceId);
    } catch (e) {
      const info = new LicenseInfo();
      info.status = 3;
      info.expireTime = -1;
      info.remainingDays = -1;
      info.authorizedFeatures = [];
      SpeechRecognizeSdk.licenseInfo = info;
      callback.onError(DingqiaoErrorCode.LICENSE_DEVICE_MISMATCH, `device identity check failed: ${e}`);
      return;
    }
    if (!deviceOk) {
      const info = new LicenseInfo();
      info.status = 3;
      info.expireTime = -1;
      info.remainingDays = -1;
      info.authorizedFeatures = [];
      SpeechRecognizeSdk.licenseInfo = info;
      callback.onError(DingqiaoErrorCode.LICENSE_DEVICE_MISMATCH, 'device not authorized');
      return;
    }
    try {
      const options = new AmphionOptions();
      options.license = licenseText;
      options.deviceIdProvider = new CoreDeviceIdProviderAdapter(provider);
      AmphionRuntime.release();
      await AmphionRuntime.init(context, options);
      const status = AmphionRuntime.licenseStatus();
      const info = new LicenseInfo();
      info.status = status.valid ? 0 : 2;
      // 与安卓 SpeechRecognizeSdk(toExpireTimeMillis/toRemainingDays)对齐:从签名 claims 的 expiresAt 计算,
      // 而非恒 -1。否则 Harmony 端 getLicenseInfo / remainingDays 永远返回 -1,违反契约 §5.5/§5.6。
      info.expireTime = status.valid ? expireTimeMillisFromClaim(status.expiresAt) : -1;
      info.remainingDays = status.valid ? remainingDaysFromClaim(status.expiresAt) : -1;
      info.authorizedFeatures = status.features ?? [];
      SpeechRecognizeSdk.licenseInfo = info;

      const result = new LicenseActivationResult();
      result.errorCode = status.valid ? 0 : mapLicenseErrorCode(status.errorCode);
      result.errorMessage = status.valid ? '' : status.message;
      result.remainingDays = info.remainingDays;
      result.authorizedFeatures = info.authorizedFeatures;
      callback.onResult(result);
    } catch (e) {
      const message = `${e}`;
      const code = mapLicenseErrorCode(extractAsrErrorCode(message));
      const info = new LicenseInfo();
      info.status = code === DingqiaoErrorCode.LICENSE_EXPIRED ? 1 : 2;
      info.expireTime = -1;
      info.remainingDays = -1;
      info.authorizedFeatures = [];
      SpeechRecognizeSdk.licenseInfo = info;
      callback.onError(code, message);
    }
  }

  static getLicenseInfo(): LicenseInfo {
    if (SpeechRecognizeSdk.licenseInfo === undefined) {
      throw new DingqiaoSdkError(DingqiaoErrorCode.LICENSE_NOT_SET, 'license not set');
    }
    return SpeechRecognizeSdk.licenseInfo;
  }

  static createEngine(params: CreateEngineParams): SpeechRecognitionEngine {
    if (SpeechRecognizeSdk.context === undefined) throw new Error('SpeechRecognizeSdk.init must be called first');
    return new DingqiaoRecognitionEngineImpl(SpeechRecognizeSdk.context, params);
  }

  static createEngineAsync(params: CreateEngineParams, callback: CreateEngineCallback): void {
    // 让出一帧再做重活(模型加载+一次性预热),使 UI 先渲染"加载中"态,避免调用即冻屏。
    // 注:sherpa NAPI 对象线程绑定,无法搬到 Worker,故仍在调用线程执行;此处仅消除"点击即卡死"的观感。
    setTimeout((): void => {
      try {
        callback.onSuccess(SpeechRecognizeSdk.createEngine(params));
      } catch (e) {
        callback.onError(DingqiaoErrorCode.CREATE_ENGINE_FAILED, `${e}`);
      }
    }, 0);
  }

  static registerVoiceprint(params: VoiceprintRegisterParams): VoiceprintRegisterResult {
    const result = new VoiceprintRegisterResult();
    if (params.samplePaths.length < 1) {
      result.status = DingqiaoErrorCode.VOICEPRINT_SAMPLE_COUNT;
      result.message = 'sample count must be >= 1';
      return result;
    }
    const modelPath = SpeechRecognizeSdk.speakerModelPath();
    if (!fs.accessSync(modelPath)) {
      result.status = DingqiaoErrorCode.VOICEPRINT_REGISTER_FAILED;
      result.message = `voiceprint model not found: ${modelPath}`;
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
      if (durationMs < 3000 || durationMs > 8000) {
        result.status = DingqiaoErrorCode.VOICEPRINT_SAMPLE_DURATION;
        result.message = `sample duration must be 3s..8s: ${path}`;
        return result;
      }
    }
    try {
      // Reuse the shared, pooled extractor so registration warms the SAME instance the recognition
      // path uses — the ~38 MB eres2net load is paid here (where a wait is expected) and start
      // recognition stays instant.
      const extractor = AmphionRuntime.getOrCreateSpeakerExtractor(undefined, modelPath, 1);
      const enroller = new SpeakerEnroller(modelPath, 1, undefined, extractor);
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
   * Preload + warm the voiceprint extractor so the first startListening with
   * enableVoiceprintVerification does not block the UI thread on the ~38 MB eres2net load.
   * Idempotent (no-op once pooled). Returns false if the model file is not present yet.
   * Registration already warms the same pool, so this mainly covers the app-restart case
   * (model on disk + voiceprint registered, but the in-memory pool is cold). Synchronous —
   * call it at a non-critical moment (e.g. when the caller enables voiceprint verification).
   */
  static preloadVoiceprintModel(): boolean {
    const modelPath = SpeechRecognizeSdk.speakerModelPath();
    if (!fs.accessSync(modelPath)) return false;
    try {
      AmphionRuntime.getOrCreateSpeakerExtractor(undefined, modelPath, 1);
      return true;
    } catch (e) {
      return false;
    }
  }

  private static speakerModelPath(): string {
    return `${SpeechRecognizeSdk.workPath}/eres2net.onnx`;
  }
}
