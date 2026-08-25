export class AudioInfo {
  audioType: string = 'pcm';
  sampleRate: number = 16000;
  sampleBit: number = 16;
  soundChannel: number = 1;
}

export class CreateEngineParams {
  language: string = 'zh-CN';
  online: number = 1;
  extraParams: Record<string, Object> = {};
}

export class SpeakerDiarizationConfig {
  /** Full HTTPS window endpoint. HTTP is accepted only for loopback development. */
  serviceUrl: string = '';
  /** Optional service-specific headers, for example Authorization. */
  serviceHeaders: Record<string, string> = {};
  /** Stable speaker indexes are limited to 0...(maxSpeakers - 1). */
  maxSpeakers: number = 4;
}

export class StartParams {
  sessionId: string = '';
  audioInfo: AudioInfo = new AudioInfo();
  extraParams: Record<string, Object> = {};
  /** Undefined disables speaker diarization; a config instance enables it. */
  speakerDiarization?: SpeakerDiarizationConfig;
}

export class SpeechRecognitionResult {
  isFinal: boolean = false;
  isLast: boolean = false;
  result: string = '';
  beginTime?: number;
  endTime?: number;
  speakerSimilarity?: number;
  targetSpeakerEnhancementApplied?: boolean;
  /** Stable only for final utterances when speaker diarization is enabled. */
  utteranceId?: string;
  /** -1 means unassigned; assigned speakers use stable zero-based indexes. */
  speakerIndex: number = -1;
  secondarySpeakerIndexes: number[] = [];
  /** Assignment score in [0, 1], not a calibrated probability. */
  speakerConfidence: number = 0;
}

export class SpeakerDiarizationUpdate {
  utteranceId: string = '';
  revision: number = 0;
  speakerIndex: number = -1;
  secondarySpeakerIndexes: number[] = [];
  beginTime: number = 0;
  endTime: number = 0;
  confidence: number = 0;
}

export class DiarizedUtterance {
  utteranceId: string = '';
  rawText: string = '';
  text: string = '';
  beginTime: number = 0;
  endTime: number = 0;
  speakerIndex: number = -1;
  secondarySpeakerIndexes: number[] = [];
  confidence: number = 0;
  overlap: boolean = false;
}

export class SpeakerTurn {
  beginTime: number = 0;
  endTime: number = 0;
  speakerIndex: number = -1;
  secondarySpeakerIndexes: number[] = [];
  confidence: number = 0;
  overlap: boolean = false;
}

export enum SpeakerDiarizationDegradedReason {
  NONE = 0,
  SERVICE_UNAVAILABLE = 1,
  MODEL_UNAVAILABLE = 2,
  INFERENCE_TIMEOUT = 3,
  FINISH_TIMEOUT = 4,
  STORAGE_UNAVAILABLE = 5,
  SPEAKER_LIMIT_EXCEEDED = 6,
  AUTHENTICATION_FAILED = 7,
  INVALID_SERVICE_RESPONSE = 8,
}

export class SpeakerDiarizationResult {
  utterances: DiarizedUtterance[] = [];
  speakerTurns: SpeakerTurn[] = [];
  speakerCount: number = 0;
  degraded: boolean = false;
  degradedReason: SpeakerDiarizationDegradedReason = SpeakerDiarizationDegradedReason.NONE;
  degradedMessage?: string;
  inferenceMs: number = 0;
  rtf: number = 0;
}

export class VoiceprintRegisterParams {
  voiceprintId: string = '';
  samplePaths: string[] = [];
  audioInfo: AudioInfo = new AudioInfo();
}

export class VoiceprintRegisterResult {
  voiceprintId: Record<string, string> = {};
  status: number = 0;
  message: string = '';
}

export class LicenseInfo {
  status: number = 0;
  expireTime: number = -1;
  remainingDays: number = -1;
  authorizedFeatures: string[] = [];
}

export class LicenseActivationResult {
  errorCode: number = 0;
  errorMessage: string = '';
  remainingDays?: number;
  authorizedFeatures?: string[];
}

export interface RecognitionListener {
  onStart?(sessionId: string, eventMessage?: string): void;
  onEvent?(sessionId: string, eventCode: number, message: string): void;
  onResult?(sessionId: string, result: SpeechRecognitionResult): void;
  onSpeakerDiarizationUpdate?(sessionId: string, update: SpeakerDiarizationUpdate): void;
  onSpeakerDiarizationResult?(sessionId: string, result: SpeakerDiarizationResult): void;
  onComplete?(sessionId: string, eventMessage?: string): void;
  onError?(sessionId: string, errorCode: number, message: string): void;
}

export interface SpeechRecognitionEngine {
  setListener(listener: RecognitionListener): void;
  startListening(params: StartParams): void;
  writeAudio(sessionId: string, audio: ArrayBuffer): void;
  finish(sessionId: string): void;
  cancel(sessionId: string): void;
  setSpeakerVadEnabled(enabled: boolean): void;
  isBusy(): boolean;
  shutdown(): void;
}

export interface CreateEngineCallback {
  onSuccess(engine: SpeechRecognitionEngine): void;
  onError(errorCode: number, message: string): void;
}

export interface LicenseActivationCallback {
  onResult(result: LicenseActivationResult): void;
  onError(errorCode: number, message: string): void;
}

/**
 * Runtime 和默认中英模型就绪回调。onReady 在默认模型进入共享池后触发；重复
 * prepareRuntime 复用已准备的模型，并发调用共享同一次准备任务。
 */
export interface PrepareRuntimeCallback {
  onReady(): void;
  onError(errorCode: number, message: string): void;
}

/** @deprecated Diagnostics behavior is selected by the HAR build mode in 0.3.8. */
export class DiagnosticMode {
  static readonly BASIC: string = 'BASIC';
  static readonly CUSTOMER_SUPPORT: string = 'CUSTOMER_SUPPORT';
  static readonly FAILURE_ONLY: string = 'FAILURE_ONLY';
}

/**
 * @deprecated Kept for 0.3.7 Debug SDK source compatibility. In 0.3.8 these values do not
 * change capture behavior; use the dedicated Diagnostics SDK to enable diagnostics.
 */
export class DiagnosticOptions {
  enabled: boolean = false;
  mode: string = DiagnosticMode.BASIC;
  captureAudio: boolean = false;
  includeRecognitionText: boolean = false;
  maxSessionAudioSec: number = 300;
  failureRingAudioSec: number = 20;
  maxSessionEvents: number = 512;
  maxDirectoryMb: number = 200;
  maxRetainedRuns: number = 3;

  static customerSupport(): DiagnosticOptions {
    const options = new DiagnosticOptions();
    options.enabled = true;
    options.mode = DiagnosticMode.CUSTOMER_SUPPORT;
    return options;
  }

  static failureOnly(): DiagnosticOptions {
    const options = new DiagnosticOptions();
    options.enabled = true;
    options.mode = DiagnosticMode.FAILURE_ONLY;
    return options;
  }
}

export interface DiagnosticExportCallback {
  onSuccess(path: string): void;
  onError(errorCode: number, message: string): void;
}

export class DingqiaoErrorCode {
  static readonly CREATE_ENGINE_FAILED: number = 1002200001;
  static readonly START_LISTENING_FAILED: number = 1002200002;
  static readonly MAX_AUDIO_DURATION: number = 1002200003;
  static readonly FINISH_FAILED: number = 1002200004;
  static readonly CANCEL_FAILED: number = 1002200005;
  static readonly ENGINE_BUSY: number = 1002200006;
  static readonly ENGINE_NOT_INITIALIZED: number = 1002200007;
  static readonly ENGINE_DESTROYED: number = 1002200008;
  static readonly INTERNAL_ERROR: number = 1002200009;
  static readonly NOT_LISTENING: number = 1002200010;
  static readonly RECOGNITION_ERROR: number = 1002200011;
  static readonly NO_MIC_PERMISSION: number = 1002200012;
  static readonly VOICEPRINT_REGISTER_FAILED: number = 1002200020;
  static readonly VOICEPRINT_SAMPLE_COUNT: number = 1002200021;
  static readonly VOICEPRINT_SAMPLE_DURATION: number = 1002200022;
  static readonly VOICEPRINT_NOT_FOUND: number = 1002200024;
  static readonly LICENSE_FILE_UNREADABLE: number = 1002200030;
  static readonly LICENSE_INVALID: number = 1002200031;
  static readonly LICENSE_EXPIRED: number = 1002200032;
  static readonly LICENSE_DEVICE_MISMATCH: number = 1002200033;
  static readonly LICENSE_NOT_SET: number = 1002200034;
  static readonly LICENSE_ACTIVATION_FAILED: number = 1002200035;
}

export class DingqiaoEventCode {
  static readonly SPEECH_BEGIN: number = 1;
  static readonly SPEECH_END: number = 3;
  static readonly SPEAKER_VAD_CHANGED: number = 20;
  static readonly SPEAKER_VAD_DEBUG: number = 21;
  static readonly SPEAKER_VAD_REJECTED: number = 22;
}

export class DingqiaoOnlineMode {
  static readonly OFFLINE: number = 1;
}

export class DingqiaoRecognitionMode {
  static readonly RECORD: number = 0;
  static readonly STREAM: number = 1;
  /** @deprecated Use RECORD. */
  static readonly SINGLE: number = 0;
  /** @deprecated Use STREAM. */
  static readonly CONTINUOUS: number = 1;
}

export const DINGQIAO_AUDIO_FRAME_BYTES_20MS: number = 640;
export const DINGQIAO_AUDIO_FRAME_BYTES_40MS: number = 1280;
export const DINGQIAO_VOICEPRINT_MIN_SAMPLES: number = 1;
export const DINGQIAO_VOICEPRINT_MIN_SEC: number = 3;
export const DINGQIAO_VOICEPRINT_MAX_SEC: number = 8;
