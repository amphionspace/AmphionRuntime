export enum AsrLanguage {
  ZH_EN = 'ZH_EN',
  YUE_EN = 'YUE_EN'
}

export enum AmphionLogLevel {
  DEBUG = 0,
  INFO = 1,
  WARN = 2,
  ERROR = 3,
  NONE = 4
}

export enum LicenseEnforcement {
  ENFORCE = 'ENFORCE',
  WARN_ONLY = 'WARN_ONLY'
}

export class AmphionOptions {
  logLevel: AmphionLogLevel = AmphionLogLevel.WARN;
  license?: string;
  licenseAssetName?: string = 'amphion-license.lic';
  expiryGraceDays: number = 0;
  licenseEnforcement: LicenseEnforcement = LicenseEnforcement.ENFORCE;
}

export class VadConfig {
  modelType: string = 'SILERO';
  threshold: number = 0.5;
  minSpeechDurationMs: number = 250;
  minSilenceDurationMs: number = 500;
  activeEndpointSilenceMs: number = 500;
}

export class EndpointRules {
  rule1MinTrailingSilenceSec: number = 2.4;
  rule2MinTrailingSilenceSec: number = 1.4;
  rule3MinUtteranceLengthSec: number = 20.0;
}

export class TargetSpeakerConfig {
  enabledByDefault: boolean = false;
  threshold: number = 0.30;
  winSec: number = 1.5;
  hopSec: number = 0.75;
  minSegSec: number = 1.0;
  modelPath?: string;
}

export class AsrConfig {
  numThreads: number = 2;
  punctuation: boolean = true;
  itn: boolean = true;
  vad: boolean = true;
  vadConfig: VadConfig = new VadConfig();
  endpoint: boolean = true;
  endpointRules: EndpointRules = new EndpointRules();
  hotwords: string[] = [];
  hotwordsScore: number = 1.5;
  targetSpeaker?: TargetSpeakerConfig;

  static builder(): AsrConfigBuilder {
    return new AsrConfigBuilder();
  }
}

export class AsrConfigBuilder {
  private config: AsrConfig = new AsrConfig();

  numThreads(value: number): AsrConfigBuilder { this.config.numThreads = value; return this; }
  punctuation(value: boolean): AsrConfigBuilder { this.config.punctuation = value; return this; }
  itn(value: boolean): AsrConfigBuilder { this.config.itn = value; return this; }
  vad(value: boolean): AsrConfigBuilder { this.config.vad = value; return this; }
  vadConfig(value: VadConfig): AsrConfigBuilder { this.config.vadConfig = value; return this; }
  endpoint(value: boolean): AsrConfigBuilder { this.config.endpoint = value; return this; }
  endpointRules(value: EndpointRules): AsrConfigBuilder { this.config.endpointRules = value; return this; }
  hotwords(value: string[]): AsrConfigBuilder { this.config.hotwords = value; return this; }
  hotwordsScore(value: number): AsrConfigBuilder { this.config.hotwordsScore = value; return this; }
  targetSpeaker(value: TargetSpeakerConfig): AsrConfigBuilder { this.config.targetSpeaker = value; return this; }
  build(): AsrConfig { return this.config; }
}

export class AsrResult {
  text: string = '';
  confidence: number = 1.0;
  tokens: string[] = [];
  timestamps: number[] = [];
  tokenConfidences: number[] = [];
  speakerScore?: number;
  isTargetSpeaker?: boolean;
}

export class AsrError {
  code: number;
  message: string;

  constructor(code: number, message: string) {
    this.code = code;
    this.message = message;
  }
}

export class AsrErrorCode {
  static readonly INVALID_ARGUMENT: number = 1001;
  static readonly SDK_NOT_INITIALIZED: number = 1002;
  static readonly SESSION_ALREADY_CLOSED: number = 1003;
  static readonly LANGUAGE_UNAVAILABLE: number = 2001;
  static readonly ASSET_INSTALL_FAILED: number = 2002;
  static readonly STORAGE_INSUFFICIENT: number = 2003;
  static readonly DECODE_FAILED: number = 3001;
  static readonly POSTPROCESS_FAILED: number = 3002;
  static readonly LICENSE_MISSING: number = 6001;
  static readonly LICENSE_INVALID: number = 6002;
  static readonly LICENSE_EXPIRED: number = 6003;
  static readonly NATIVE_CRASH: number = 9001;
}

export enum AmphionMetricsKind {
  UTTERANCE = 'UTTERANCE',
  SESSION = 'SESSION'
}

export class AmphionMetrics {
  kind: AmphionMetricsKind = AmphionMetricsKind.UTTERANCE;
  language: AsrLanguage = AsrLanguage.ZH_EN;
  sessionId: number = 0;
  utteranceIndex?: number;
  utteranceDurationMs?: number;
  decodeDurationMs?: number;
  postProcessMs?: number;
  firstPartialLatencyMs?: number;
  endpointToFinalLatencyMs?: number;
  utteranceE2eLatencyMs?: number;
  rtf?: number;
  nativeRssMb?: number;
  pcmBytesAccepted?: number;
  totalUtterances?: number;
  totalPcmBytes?: number;
  avgRtf?: number;
  p95Rtf?: number;
  peakNativeRssMb?: number;

  toLogLine(): string {
    const parts: string[] = [];
    parts.push(`kind=${this.kind}`);
    parts.push(`language=${this.language}`);
    parts.push(`sessionId=${this.sessionId}`);
    if (this.utteranceIndex !== undefined) parts.push(`utteranceIndex=${this.utteranceIndex}`);
    if (this.utteranceE2eLatencyMs !== undefined) parts.push(`utteranceE2eLatencyMs=${this.utteranceE2eLatencyMs}`);
    if (this.rtf !== undefined) parts.push(`rtf=${this.rtf}`);
    if (this.pcmBytesAccepted !== undefined) parts.push(`pcmBytesAccepted=${this.pcmBytesAccepted}`);
    return parts.join(' ');
  }
}

export interface AsrCallback {
  onPartial?(text: string): void;
  onPartialResult?(result: AsrResult): void;
  onFinal?(text: string, confidence: number): void;
  onFinalResult?(result: AsrResult): void;
  onFinalRejected?(result: AsrResult): void;
  onEndpoint?(): void;
  onError?(error: AsrError): void;
  onSessionStarted?(): void;
  onSessionStopped?(): void;
  onMetrics?(metrics: AmphionMetrics): void;
}

export interface Cancellable {
  cancel(): void;
  isDone(): boolean;
}
