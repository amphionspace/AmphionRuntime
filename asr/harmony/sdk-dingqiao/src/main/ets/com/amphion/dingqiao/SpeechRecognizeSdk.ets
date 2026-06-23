import { AmphionRuntime, AmphionOptions, AsrCallback, AsrConfig, AsrEngine, AsrLanguage, AsrResult, AsrSession, SpeakerEnroller } from 'amphion_asr';
import { PoliceEngineConfig, PoliceEnhanceOptions, PoliceEnhancePipeline } from 'amphion_police';
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
  if (typeof value !== 'string' || value.length === 0) return [];
  return value.split(/[\n,，]/).map((s: string) => s.trim()).filter((s: string) => s.length > 0);
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

function buildAsrConfig(params: CreateEngineParams, startParams?: StartParams): AsrConfig {
  const plate = booleanParam(params.extraParams, 'plateNormalizeEnabled', true);
  const station = booleanParam(params.extraParams, 'stationNormalizeEnabled', true);
  const terms = booleanParam(params.extraParams, 'termsNormalizeEnabled', true);
  const config = PoliceEngineConfig.build(parseLexicon(params.extraParams['sysGeneralLexicon']), plate, station, terms);
  config.vadConfig.activeEndpointSilenceMs = vadEndMs(startParams);
  config.endpointRules.rule2MinTrailingSilenceSec = 2.0;
  return config;
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
    this.rebuildEngine(params);
    this.currentSessionId = params.sessionId;
    this.finishRequested = false;
    this.partialEnabled = params.extraParams['enablePartialResult'] !== false;
    this.busy = true;
    const callback: AsrCallback = {
      onPartial: (text: string): void => {
        if (!this.partialEnabled || text.length === 0) return;
        const result = new SpeechRecognitionResult();
        result.isFinal = false;
        result.isLast = false;
        result.result = text;
        this.listener?.onResult?.(this.currentSessionId, result);
      },
      onEndpoint: (): void => {
        this.listener?.onEvent?.(this.currentSessionId, DingqiaoEventCode.SPEECH_END, 'speech stopped.');
      },
      onFinalResult: (result: AsrResult): void => {
        this.deliverFinal(result);
      },
      onError: (error): void => {
        this.listener?.onError?.(this.currentSessionId, DingqiaoErrorCode.RECOGNITION_ERROR, `${error.code}: ${error.message}`);
        this.tearDownSession();
      },
      onSessionStarted: (): void => {
        this.listener?.onStart?.(this.currentSessionId);
        this.listener?.onEvent?.(this.currentSessionId, DingqiaoEventCode.SPEECH_BEGIN, 'speech started.');
      },
      onSessionStopped: (): void => {
        if (this.finishRequested) this.listener?.onComplete?.(this.currentSessionId);
        this.tearDownSession();
      }
    };
    this.session = this.asrEngine.newSession(callback);
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

  private rebuildEngine(params: StartParams): void {
    this.asrEngine.close();
    this.asrEngine = AmphionRuntime.create(this.context, languageOf(this.params.language), buildAsrConfig(this.params, params));
  }

  private ensureAlive(): void {
    if (this.destroyed) throw new Error('engine destroyed');
  }
}

export class SpeechRecognizeSdk {
  private static context?: Context;
  private static workPath: string = '';
  private static voiceprints: Map<string, Float32Array> = new Map<string, Float32Array>();
  private static licenseInfo: LicenseInfo = new LicenseInfo();

  static init(context: Context): void {
    SpeechRecognizeSdk.context = context;
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
    const info = new LicenseInfo();
    info.licensePath = licensePath;
    info.status = 1;
    info.remainingDays = 0;
    SpeechRecognizeSdk.licenseInfo = info;
    const options = new AmphionOptions();
    options.license = licensePath;
    AmphionRuntime.init(SpeechRecognizeSdk.context, options);

    const result = new LicenseActivationResult();
    result.success = true;
    result.errorCode = 0;
    result.message = 'license placeholder accepted';
    result.licenseInfo = info;
    callback.onResult(result);
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
    if (params.voiceprintId.length === 0) {
      result.status = DingqiaoErrorCode.INVALID_ARGUMENT;
      result.message = 'voiceprintId is empty';
      return result;
    }
    if (params.samplePaths.length < 3) {
      result.status = DingqiaoErrorCode.VOICEPRINT_REGISTER_FAILED;
      result.message = 'at least 3 audio samples required';
      return result;
    }
    const modelPath = `${SpeechRecognizeSdk.workPath}/eres2net.onnx`;
    const enroller = new SpeakerEnroller(modelPath);
    SpeechRecognizeSdk.voiceprints.set(params.voiceprintId, enroller.enroll(params.samplePaths));
    result.status = 0;
    result.message = 'registered';
    return result;
  }

  static deleteVoiceprint(voiceprintId: string): boolean {
    return SpeechRecognizeSdk.voiceprints.delete(voiceprintId);
  }

  static getWorkPath(): string { return SpeechRecognizeSdk.workPath; }
}
