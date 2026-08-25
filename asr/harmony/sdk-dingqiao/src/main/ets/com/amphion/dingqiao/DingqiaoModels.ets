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

export class StartParams {
  sessionId: string = '';
  audioInfo: AudioInfo = new AudioInfo();
  extraParams: Record<string, Object> = {};
}

export class SpeechRecognitionResult {
  isFinal: boolean = false;
  isLast: boolean = false;
  result: string = '';
  beginTime?: number;
  endTime?: number;
  speakerSimilarity?: number;
  targetSpeakerEnhancementApplied?: boolean;
  /** Stable only for final meeting utterances. */
  utteranceId?: string;
  /** Anonymous meeting speaker ID (S1...S4 or UNKNOWN). */
  speakerId?: string;
  secondarySpeakerIds?: string[];
}

export class SpeakerUpdate {
  utteranceId: string = '';
  revision: number = 0;
  speakerId: string = 'UNKNOWN';
  secondarySpeakerIds: string[] = [];
  beginTime: number = 0;
  endTime: number = 0;
  confidence: number = 0;
}

export class MeetingUtterance {
  utteranceId: string = '';
  rawText: string = '';
  text: string = '';
  beginTime: number = 0;
  endTime: number = 0;
  speakerId: string = 'UNKNOWN';
  secondarySpeakerIds: string[] = [];
  overlap: boolean = false;
}

export class MeetingSpeakerTurn {
  beginTime: number = 0;
  endTime: number = 0;
  speakerId: string = 'UNKNOWN';
  secondarySpeakerIds: string[] = [];
  overlap: boolean = false;
}

export class MeetingResult {
  utterances: MeetingUtterance[] = [];
  speakerTurns: MeetingSpeakerTurn[] = [];
  speakerCount: number = 0;
  degraded: boolean = false;
  degradedReason?: string;
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
  onSpeakerUpdate?(sessionId: string, update: SpeakerUpdate): void;
  onMeetingResult?(sessionId: string, result: MeetingResult): void;
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
