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

export class TtsErrorCode {
  static readonly OK: number = 0;
  static readonly TEXT_LENGTH_INVALID: number = 1002300001;
  static readonly LANGUAGE_UNSUPPORTED: number = 1002300002;
  static readonly VOICE_UNSUPPORTED: number = 1002300003;
  static readonly CREATE_ENGINE_FAILED: number = 1002300005;
  static readonly ENGINE_NOT_INITIALIZED: number = 1002300007;
  static readonly ENGINE_DESTROYED: number = 1002300008;
  static readonly INTERNAL_SERVICE_ERROR: number = 1002300009;
  static readonly RUNTIME_EXCEPTION: number = 1002300011;
  static readonly MODEL_MISSING: number = 1002300020;
}

export class TtsCreateEngineParams {
  language: string = 'zh-en';
  mode: RunMode = RunMode.OFFLINE;
  voiceId: string = 'kokoro-zh-en';
  locate: string = 'CN';
  numThreads: number = 2;
  extraParams: Record<string, Object> = {};
}

export class SpeakParams {
  requestId: string = '';
  speed: number = 1.0;
  volume: number = 1.0;
  pitch: number = 1.0;
  languageContext: string = 'zh-en';
  audioType: string = 'pcm';
  playType: PlayType = PlayType.SYNTHESIZE_AND_PLAY;
  sid: number = 0;
  queueMode: QueueMode = QueueMode.QUEUE;
  extraParams: Record<string, Object> = {};
}

export class TtsVoiceInfo {
  language: string = '';
  voiceId: string = '';
  gender: string = '';
  description?: string;

  constructor(language: string, voiceId: string, gender: string, description?: string) {
    this.language = language;
    this.voiceId = voiceId;
    this.gender = gender;
    this.description = description;
  }
}

export class TtsAudioFormat {
  audioType: string = 'pcm';
  sampleRate: number = 24000;
  sampleBit: number = 16;
  channel: number = 1;
}

export interface TextToSpeechListener {
  onStart?(requestId: string): void;
  onData?(requestId: string, audio: ArrayBuffer): void;
  onComplete?(requestId: string): void;
  onStop?(requestId: string): void;
  onError?(requestId: string, errorCode: number, message: string): void;
}

export interface TextToSpeechEngine {
  setListener(listener: TextToSpeechListener): void;
  speak(text: string, params: SpeakParams): void;
  stop(): void;
  isBusy(): boolean;
  shutdown(): void;
}
