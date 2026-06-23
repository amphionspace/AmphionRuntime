export class AudioInfo {
  audioType: string = 'pcm';
  sampleRate: number = 16000;
  sampleBit: number = 16;
  channel: number = 1;
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
  audioPaths: string[] = [];
}

export class VoiceprintRegisterResult {
  voiceprintId: string = '';
  success: boolean = false;
  message: string = '';
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
  isBusy(): boolean;
  shutdown(): void;
}

export interface CreateEngineCallback {
  onSuccess(engine: SpeechRecognitionEngine): void;
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
  static readonly VOICEPRINT_REGISTER_FAILED: number = 1002200020;
  static readonly VOICEPRINT_DELETE_FAILED: number = 1002200021;
  static readonly VOICEPRINT_MODEL_MISSING: number = 1002200022;
}

export class DingqiaoEventCode {
  static readonly SPEECH_BEGIN: number = 1;
  static readonly SPEECH_END: number = 3;
}

export class DingqiaoOnlineMode {
  static readonly OFFLINE: number = 1;
}

export const DINGQIAO_AUDIO_FRAME_BYTES: number = 640;
