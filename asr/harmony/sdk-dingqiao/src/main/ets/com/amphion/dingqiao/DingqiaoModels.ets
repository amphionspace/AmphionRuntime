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
}

export class VoiceprintRegisterParams {
  voiceprintId: string = '';
  samplePaths: string[] = [];
  audioInfo: AudioInfo = new AudioInfo();
}

export class VoiceprintRegisterResult {
  voiceprintId: string = '';
  status: number = 0;
  message: string = '';
}

export class LicenseInfo {
  licensePath: string = '';
  status: number = 0;
  expireTime: number = 0;
  remainingDays: number = 0;
  deviceId: string = '';
}

export class LicenseActivationResult {
  success: boolean = false;
  errorCode: number = 0;
  message: string = '';
  licenseInfo?: LicenseInfo;
}

export interface RecognitionListener {
  onStart?(sessionId: string): void;
  onEvent?(sessionId: string, eventCode: number, message: string): void;
  onResult?(sessionId: string, result: SpeechRecognitionResult): void;
  onComplete?(sessionId: string): void;
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

export class DingqiaoErrorCode {
  static readonly ENGINE_CREATE_FAILED: number = 1002200001;
  static readonly ENGINE_NOT_INITIALIZED: number = 1002200002;
  static readonly ENGINE_BUSY: number = 1002200003;
  static readonly INVALID_ARGUMENT: number = 1002200004;
  static readonly START_RECOGNITION_FAILED: number = 1002200005;
  static readonly WRITE_AUDIO_FAILED: number = 1002200006;
  static readonly FINISH_FAILED: number = 1002200007;
  static readonly CANCEL_FAILED: number = 1002200008;
  static readonly ENGINE_DESTROYED: number = 1002200009;
  static readonly RECOGNITION_TIMEOUT: number = 1002200010;
  static readonly RECOGNITION_ERROR: number = 1002200011;
  static readonly MAX_AUDIO_DURATION: number = 1002200012;
  static readonly VOICEPRINT_REGISTER_FAILED: number = 1002200020;
  static readonly VOICEPRINT_DELETE_FAILED: number = 1002200021;
  static readonly VOICEPRINT_MODEL_MISSING: number = 1002200022;
  static readonly LICENSE_FILE_MISSING: number = 1002200030;
  static readonly LICENSE_INVALID: number = 1002200031;
  static readonly LICENSE_EXPIRED: number = 1002200032;
  static readonly LICENSE_DEVICE_MISMATCH: number = 1002200033;
  static readonly LICENSE_ACTIVATION_FAILED: number = 1002200034;
  static readonly LICENSE_NOT_ACTIVATED: number = 1002200035;
}

export class DingqiaoEventCode {
  static readonly SPEECH_BEGIN: number = 1;
  static readonly SPEECH_END: number = 3;
  static readonly SPEAKER_VAD_REJECTED: number = 11;
}

export class DingqiaoOnlineMode {
  static readonly OFFLINE: number = 1;
}

export class DingqiaoRecognitionMode {
  static readonly SINGLE: number = 0;
  static readonly CONTINUOUS: number = 1;
}

export const DINGQIAO_AUDIO_FRAME_BYTES_20MS: number = 640;
export const DINGQIAO_AUDIO_FRAME_BYTES_40MS: number = 1280;
