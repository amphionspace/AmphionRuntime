export enum TtsErrorCode {
  TEXT_LENGTH_INVALID = 1002300001,
  LANGUAGE_UNSUPPORTED = 1002300002,
  VOICE_UNSUPPORTED = 1002300003,
  CREATE_ENGINE_FAILED = 1002300005,
  ENGINE_LIMIT_REACHED = 1002300006,
  ENGINE_NOT_INITIALIZED = 1002300007,
  ENGINE_DESTROYED = 1002300008,
  INTERNAL_SERVICE_ERROR = 1002300009,
  QUEUE_FULL = 1002300010,
  RUNTIME_EXCEPTION = 1002300011,
  LICENSE_MISSING = 1002300012,
  LICENSE_MALFORMED = 1002300013,
  LICENSE_SIGNATURE_INVALID = 1002300014,
  LICENSE_APP_MISMATCH = 1002300015,
  LICENSE_CERT_MISMATCH = 1002300016,
  LICENSE_EXPIRED = 1002300017,
  LICENSE_DEVICE_MISMATCH = 1002300018,
  LICENSE_SDK_MAJOR_MISMATCH = 1002300019,
  LICENSE_MAINTENANCE_EXPIRED = 1002300020,
  LICENSE_FEATURE_MISSING = 1002300021,
  LICENSE_NOT_SET = 1002300034
}

export class TextToSpeechException extends Error {
  readonly errorCode: number;

  constructor(errorCode: number, message: string) {
    super(message);
    this.errorCode = errorCode;
  }
}

export interface Callback<T> {
  onSuccess(result: T): void;
  onError(errorCode: number, errorMessage: string): void;
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
  remainingDays: number = -1;
  authorizedFeatures: string[] = [];
}

export interface LicenseActivationCallback {
  onResult(result: LicenseActivationResult): void;
  onError(errorCode: number, errorMessage: string): void;
}

export interface ExtraParams {
  modelPackageDir?: string;
  streamingChunkSize?: number | string;
  chunkSize?: number | string;
  pcmQueueCapacity?: number | string;
  pcmQueueSize?: number | string;
}

export enum RunMode {
  OFFLINE = 'OFFLINE',
  ONLINE = 'ONLINE'
}

export enum PlayType {
  SYNTHESIZE_ONLY = 'SYNTHESIZE_ONLY',
  SYNTHESIZE_AND_PLAY = 'SYNTHESIZE_AND_PLAY'
}

export enum QueueMode {
  QUEUE = 'QUEUE',
  PREEMPT = 'PREEMPT'
}

export enum CompleteType {
  SYNTHESIS_COMPLETE = 'SYNTHESIS_COMPLETE',
  PLAYBACK_COMPLETE = 'PLAYBACK_COMPLETE'
}

export enum StopType {
  STOP_ALL = 'STOP_ALL',
  STOP_PLAYBACK_ONLY = 'STOP_PLAYBACK_ONLY'
}

export interface CreateEngineParams {
  language: string;
  mode: RunMode;
  voiceId: string;
  locate?: string;
  engineName?: string;
  extraParams?: ExtraParams;
  modelLoadOnCreate?: boolean;
}

export interface VoiceQuery {
  requestId: string;
  mode: RunMode;
  language?: string;
  extraParams?: ExtraParams;
}

export interface VoiceInfo {
  language: string;
  voiceId: string;
  gender: string;
  description?: string;
}

export interface SpeakParams {
  requestId: string;
  speed?: number;
  volume?: number;
  pitch?: number;
  languageContext?: string;
  audioType?: string;
  playType?: PlayType;
  soundChannel?: number;
  queueMode?: QueueMode;
  extraParams?: ExtraParams;
}

export interface StartResponse {
  audioType: string;
  sampleRate: number;
  sampleBit: number;
  audioChannel: number;
  compressRate: number;
  isStreaming: boolean;
  dataPath: string;
  modelSource: string;
  modelInfo: string;
  loadProfileInfo: string;
}

export interface SynthesisResponse {
  sequence: number;
  audioType: string;
  isStreaming: boolean;
  chunkSource: string;
}

export interface CompleteResponse {
  type: CompleteType;
  message: string;
  firstPacketMs?: number;
  synthesisMs?: number;
  audioDurationMs?: number;
  rtf?: number;
  profilingInfo?: string;
  playbackStartMs?: number;
}

export interface StopResponse {
  type: StopType;
  message: string;
}

export interface SpeakListener {
  onStart?(requestId: string, response: StartResponse): void;
  onData?(requestId: string, audio: ArrayBuffer, response: SynthesisResponse): void;
  onComplete?(requestId: string, response: CompleteResponse): void;
  onStop?(requestId: string, response: StopResponse): void;
  onError?(requestId: string, errorCode: number, errorMessage: string): void;
}

export interface TextToSpeechEngine {
  setListener(listener: SpeakListener): void;
  speak(text: string, params: SpeakParams): void;
  stop(): void;
  isBusy(): boolean;
  shutdown(): void;
}
