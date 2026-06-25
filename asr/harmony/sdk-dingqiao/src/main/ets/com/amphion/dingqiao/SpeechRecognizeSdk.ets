import { AmphionRuntime, AmphionOptions, AsrCallback, AsrConfig, AsrEngine, AsrError, AsrErrorCode, AsrLanguage, AsrResult, AsrSession, SpeakerEnroller, SpeakerVadConfig, TargetSpeakerConfig } from 'amphion_asr';
import { PoliceEngineConfig, PoliceEnhanceOptions, PoliceEnhancePipeline } from 'amphion_police';
import { fileIo as fs } from '@kit.CoreFileKit';
import { VoiceprintStore } from './VoiceprintStore';
import {
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
  if (normalized === 'zh-yue' || normalized === 'zh_yue' || normalized === 'yue-en') return AsrLanguage.YUE_EN;
  return AsrLanguage.ZH_EN;
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
  return byteLength === DINGQIAO_AUDIO_FRAME_BYTES_20MS || byteLength === DINGQIAO_AUDIO_FRAME_BYTES_40MS;
}

function maxAudioBytesOf(params: StartParams): number {
  const ms = numberParam(params.extraParams, 'maxAudioDuration', 0);
  if (ms <= 0) return 0;
  // 16 kHz mono 16-bit PCM = 32 bytes per millisecond.
  return Math.round(ms * 32);
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
  if (asrCode === AsrErrorCode.LICENSE_MISSING) return DingqiaoErrorCode.LICENSE_FILE_MISSING;
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
  private finishRequested: boolean = false;
  private partialEnabled: boolean = true;
  private maxAudioBytes: number = 0;
  private audioBytesWritten: number = 0;

  constructor(context: Context, params: CreateEngineParams) {
    this.context = context;
    this.params = params;
    this.pipeline = PoliceEnhancePipeline.create(buildEnhanceOptions(params));
    this.asrEngine = AmphionRuntime.create(context, languageOf(params.language), buildAsrConfig(params));
  }

  setListener(listener: RecognitionListener): void { this.listener = listener; }

  startListening(params: StartParams): void {
    this.ensureAlive();
    if (this.busy) throw new Error('engine busy');
    if (params.audioInfo.sampleRate !== 16000 || params.audioInfo.sampleBit !== 16 || params.audioInfo.soundChannel !== 1) {
      this.listener?.onError?.(params.sessionId, DingqiaoErrorCode.INVALID_ARGUMENT, 'only 16k/16bit/mono PCM is supported');
      return;
    }

    const verify = booleanParam(params.extraParams, 'enableVoiceprintVerification', false);
    const speakerVad = booleanParam(params.extraParams, 'enableSpeakerVad', false);
    const voiceprintIds = stringArrayParam(params.extraParams, 'voiceprintIds');
    let embedding: Float32Array | undefined;
    if ((verify || speakerVad) && voiceprintIds.length > 0) {
      const modelPath = `${SpeechRecognizeSdk.getWorkPath()}/eres2net.onnx`;
      if (!fs.accessSync(modelPath)) {
        this.listener?.onError?.(params.sessionId, DingqiaoErrorCode.VOICEPRINT_MODEL_MISSING, `voiceprint model not found: ${modelPath}`);
        return;
      }
      embedding = new VoiceprintStore(SpeechRecognizeSdk.getWorkPath()).loadMergedEmbedding(voiceprintIds);
      if (embedding === undefined) {
        this.listener?.onError?.(params.sessionId, DingqiaoErrorCode.VOICEPRINT_REGISTER_FAILED, `voiceprint not found for ids: ${voiceprintIds.join(',')}`);
        return;
      }
    }
    const useTarget = embedding !== undefined && (verify || speakerVad);

    this.rebuildEngine(params, useTarget, useTarget && speakerVad);
    this.currentSessionId = params.sessionId;
    this.finishRequested = false;
    this.partialEnabled = params.extraParams['enablePartialResult'] !== false;
    this.maxAudioBytes = maxAudioBytesOf(params);
    this.audioBytesWritten = 0;
    this.busy = true;
    const callback: AsrCallback = new DingqiaoAsrCallback(this);
    this.session = this.asrEngine.newSession(callback);
    if (useTarget && embedding !== undefined) {
      this.session.setTargetSpeaker(embedding);
      this.session.setTargetSpeakerEnabled(verify);
      this.session.setSpeakerVadEnabled(speakerVad);
    }
  }

  writeAudio(sessionId: string, audio: ArrayBuffer): void {
    this.ensureAlive();
    if (!this.busy || sessionId !== this.currentSessionId || this.session === undefined) return;
    if (audio.byteLength === 0) return;
    if (!isSupportedAudioFrameBytes(audio.byteLength)) {
      this.listener?.onError?.(sessionId, DingqiaoErrorCode.INVALID_ARGUMENT, 'audio frame must be 640 or 1280 bytes');
      return;
    }
    this.session.acceptPcmBytes(audio);
    this.audioBytesWritten += audio.byteLength;
    if (this.maxAudioBytes > 0 && this.audioBytesWritten >= this.maxAudioBytes) {
      this.listener?.onError?.(sessionId, DingqiaoErrorCode.MAX_AUDIO_DURATION, 'max audio duration exceeded');
      this.tearDownSession();
    }
  }

  setSpeakerVadEnabled(enabled: boolean): void {
    this.session?.setSpeakerVadEnabled(enabled);
  }

  finish(sessionId: string): void {
    this.ensureAlive();
    if (sessionId !== this.currentSessionId || this.session === undefined) return;
    this.finishRequested = true;
    this.session.stop();
  }

  cancel(sessionId: string): void {
    if (sessionId !== this.currentSessionId) return;
    this.tearDownSession();
  }

  isBusy(): boolean { return this.busy; }

  shutdown(): void {
    this.destroyed = true;
    this.tearDownSession();
    this.asrEngine.close();
    this.pipeline.close();
  }

  private deliverFinal(result: AsrResult): void {
    const enhanced = this.pipeline.enhance(result.text);
    const payload = new SpeechRecognitionResult();
    payload.isFinal = true;
    payload.isLast = this.finishRequested;
    payload.result = enhanced.text;
    payload.speakerSimilarity = result.speakerScore;
    this.listener?.onResult?.(this.currentSessionId, payload);
    if (this.finishRequested) {
      this.listener?.onComplete?.(this.currentSessionId);
      this.tearDownSession();
    }
  }

  private tearDownSession(): void {
    this.session?.close();
    this.session = undefined;
    this.busy = false;
    this.finishRequested = false;
  }

  private rebuildEngine(params: StartParams, withTargetSpeaker: boolean, withSpeakerVad: boolean): void {
    this.asrEngine.close();
    this.asrEngine = AmphionRuntime.create(this.context, languageOf(this.params.language), buildAsrConfig(this.params, params, withTargetSpeaker, withSpeakerVad));
  }

  handlePartial(text: string): void {
    if (!this.partialEnabled || text.length === 0) return;
    const result = new SpeechRecognitionResult();
    result.isFinal = false;
    result.isLast = false;
    result.result = text;
    this.listener?.onResult?.(this.currentSessionId, result);
  }

  handleEndpoint(): void {
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
  }

  handleAsrError(error: AsrError): void {
    this.listener?.onError?.(this.currentSessionId, DingqiaoErrorCode.RECOGNITION_ERROR, `${error.code}: ${error.message}`);
    this.tearDownSession();
  }

  handleSessionStarted(): void {
    this.listener?.onStart?.(this.currentSessionId);
    this.listener?.onEvent?.(this.currentSessionId, DingqiaoEventCode.SPEECH_BEGIN, 'speech started.');
  }

  handleSessionStopped(): void {
    if (this.finishRequested) this.listener?.onComplete?.(this.currentSessionId);
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

export class SpeechRecognizeSdk {
  private static context?: Context;
  private static workPath: string = '';
  private static licenseInfo: LicenseInfo = new LicenseInfo();

  static init(context: Context): void {
    SpeechRecognizeSdk.context = context;
    try {
      AmphionRuntime.init(context);
    } catch (e) {
      // AmphionRuntime.init is process-level and idempotent; keep Dingqiao init tolerant.
    }
  }

  static setWorkPath(path: string): void {
    SpeechRecognizeSdk.workPath = path;
  }

  static setLicense(licensePath: string, callback: LicenseActivationCallback): void {
    if (SpeechRecognizeSdk.context === undefined) {
      callback.onError(DingqiaoErrorCode.ENGINE_NOT_INITIALIZED, 'SpeechRecognizeSdk.init must be called first');
      return;
    }
    if (licensePath.length === 0) {
      callback.onError(DingqiaoErrorCode.LICENSE_FILE_MISSING, 'licensePath is empty');
      return;
    }
    if (!fs.accessSync(licensePath)) {
      callback.onError(DingqiaoErrorCode.LICENSE_FILE_MISSING, `license file not found: ${licensePath}`);
      return;
    }
    let licenseText = '';
    try {
      licenseText = readTextFile(licensePath);
    } catch (e) {
      callback.onError(DingqiaoErrorCode.LICENSE_FILE_MISSING, `license file not readable: ${e}`);
      return;
    }
    try {
      const options = new AmphionOptions();
      options.license = licenseText;
      AmphionRuntime.release();
      AmphionRuntime.init(SpeechRecognizeSdk.context, options);
      const status = AmphionRuntime.licenseStatus();
      const info = new LicenseInfo();
      info.licensePath = licensePath;
      info.status = status.valid ? 0 : 2;
      info.expireTime = -1;
      info.remainingDays = -1;
      SpeechRecognizeSdk.licenseInfo = info;

      const result = new LicenseActivationResult();
      result.success = status.valid;
      result.errorCode = status.valid ? 0 : mapLicenseErrorCode(status.errorCode);
      result.message = status.message;
      result.licenseInfo = info;
      callback.onResult(result);
    } catch (e) {
      const message = `${e}`;
      const code = mapLicenseErrorCode(extractAsrErrorCode(message));
      const info = new LicenseInfo();
      info.licensePath = licensePath;
      info.status = code === DingqiaoErrorCode.LICENSE_EXPIRED ? 1 : 2;
      info.expireTime = -1;
      info.remainingDays = -1;
      SpeechRecognizeSdk.licenseInfo = info;
      callback.onError(code, message);
    }
  }

  static getLicenseInfo(): LicenseInfo {
    return SpeechRecognizeSdk.licenseInfo;
  }

  static createEngine(params: CreateEngineParams): SpeechRecognitionEngine {
    if (SpeechRecognizeSdk.context === undefined) throw new Error('SpeechRecognizeSdk.init must be called first');
    return new DingqiaoRecognitionEngineImpl(SpeechRecognizeSdk.context, params);
  }

  static createEngineAsync(params: CreateEngineParams, callback: CreateEngineCallback): void {
    try {
      callback.onSuccess(SpeechRecognizeSdk.createEngine(params));
    } catch (e) {
      callback.onError(DingqiaoErrorCode.ENGINE_CREATE_FAILED, `${e}`);
    }
  }

  static registerVoiceprint(params: VoiceprintRegisterParams): VoiceprintRegisterResult {
    const result = new VoiceprintRegisterResult();
    result.voiceprintId = params.voiceprintId;
    if (params.samplePaths.length < 3) {
      result.status = DingqiaoErrorCode.VOICEPRINT_REGISTER_FAILED;
      result.message = 'at least 3 audio samples required';
      return result;
    }
    const modelPath = SpeechRecognizeSdk.speakerModelPath();
    if (!fs.accessSync(modelPath)) {
      result.status = DingqiaoErrorCode.VOICEPRINT_MODEL_MISSING;
      result.message = `voiceprint model not found: ${modelPath}`;
      return result;
    }
    try {
      const enroller = new SpeakerEnroller(modelPath);
      const embedding = enroller.enrollFiles(params.samplePaths);
      enroller.close();
      // Persist to {workPath}/voiceprints/{id}; auto-generated id is returned to the caller and
      // later passed back via StartParams.extraParams.voiceprintIds for the recognition session.
      const store = new VoiceprintStore(SpeechRecognizeSdk.workPath);
      result.voiceprintId = store.saveVoiceprint(params.samplePaths, embedding);
      result.status = 0;
      result.message = 'registered';
    } catch (e) {
      result.status = DingqiaoErrorCode.VOICEPRINT_REGISTER_FAILED;
      result.message = `${e}`;
    }
    return result;
  }

  static deleteVoiceprint(voiceprintId: string): boolean {
    return new VoiceprintStore(SpeechRecognizeSdk.workPath).deleteVoiceprint(voiceprintId);
  }

  static getWorkPath(): string { return SpeechRecognizeSdk.workPath; }

  private static speakerModelPath(): string {
    return `${SpeechRecognizeSdk.workPath}/eres2net.onnx`;
  }
}
