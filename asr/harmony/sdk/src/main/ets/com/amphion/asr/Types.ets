import { isValidRule3MinUtteranceSec } from './EndpointRuleValidation';
import { isValidSpeakerMinimumSegment } from './TargetSpeakerConfigPolicy';

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
  PERMISSIVE = 'PERMISSIVE'
}

export class AmphionOptions {
  logLevel: AmphionLogLevel = AmphionLogLevel.WARN;
  license?: string;
  licenseAssetName?: string = 'amphion-license.lic';
  expiryGraceDays: number = 0;
  licenseEnforcement: LicenseEnforcement = LicenseEnforcement.ENFORCE;
  deviceIdProvider?: AmphionDeviceIdProvider;
  bundleName?: string;
  signingCertDigest?: string;
}

export interface AmphionDeviceIdProvider {
  getDeviceSerial(context: Context): string | undefined;
}

export enum VadModelType {
  SILERO = 'SILERO',
  TEN_VAD = 'TEN_VAD'
}

export class VadConfig {
  modelType: VadModelType = VadModelType.SILERO;
  threshold: number = 0.5;
  minSilenceDurationSec: number = 0.25;
  minSpeechDurationSec: number = 0.25;
  maxSpeechDurationSec: number = 15.0;
  activeEndpointSilenceMs: number = 500;
}

export class EndpointRules {
  rule1: boolean = true;
  rule1MinTrailingSilenceSec: number = 2.4;
  rule2: boolean = true;
  rule2MinTrailingSilenceSec: number = 1.4;
  rule3MinUtteranceLengthSec: number = 20.0;
}

export class SpeakerVadConfig {
  threshold: number = 0.35;
  winSec: number = 1.5;
  hopSec: number = 0.5;
  consecutiveBelow: number = 2;
  enabledByDefault: boolean = false;
}

/** Per-session runtime thresholds. Undefined fields inherit the engine configuration. */
export class SessionConfig {
  endpointSilenceMs?: number;
  initialSilenceTimeoutMs?: number;
  initialSilenceConfirmationGraceMs?: number;
  speakerVad?: SpeakerVadConfig;
}

export class TargetSpeakerConfig {
  modelPath: string = '';
  threshold: number = 0.30;
  winSec: number = 2.5;
  hopSec: number = 1.0;
  // Preferred strict-speech duration and initial-confirmation bound. Zero removes the SDK duration
  // gate: an ASR-confirmed public final uses its non-empty real PCM and leaves judgment to business.
  minSegSec: number = 0;
  preload: boolean = false;
  // Allows a session to start before the extractor is ready. The caller must attach an async
  // extractor load; final delivery waits for it, while streaming speaker VAD must keep this false.
  deferLoad: boolean = false;
  enabledByDefault: boolean = false;
  numThreads: number = 1;
  speakerVad?: SpeakerVadConfig;
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
  // 低内存/快加载模式:跳过 INT8 权重 prepack。冷加载 ~-156ms、峰值内存 ~-176MB;推理吞吐 ~-24%
  // (由 ASR ~7.5x 实时余量吸收)。默认 true(冷启动/峰值内存优先);可显式设 false 恢复吞吐优先。
  // 经 provider 内联配置下发到 native。
  disablePrepack: boolean = true;

  static builder(): AsrConfigBuilder {
    return new AsrConfigBuilder();
  }
}

export class AsrConfigBuilder {
  private config: AsrConfig = new AsrConfig();

  numThreads(value: number): AsrConfigBuilder {
    if (value < 1 || value > 8) throw new Error(`numThreads must be in [1, 8], got ${value}`);
    this.config.numThreads = value;
    return this;
  }
  punctuation(value: boolean): AsrConfigBuilder { this.config.punctuation = value; return this; }
  itn(value: boolean): AsrConfigBuilder { this.config.itn = value; return this; }
  disablePrepack(value: boolean): AsrConfigBuilder { this.config.disablePrepack = value; return this; }
  vad(value: boolean): AsrConfigBuilder { this.config.vad = value; return this; }
  vadConfig(value: VadConfig): AsrConfigBuilder {
    validateVadConfig(value);
    this.config.vadConfig = value;
    return this;
  }
  endpoint(value: boolean): AsrConfigBuilder { this.config.endpoint = value; return this; }
  endpointRules(value: EndpointRules): AsrConfigBuilder {
    if (value.rule1MinTrailingSilenceSec < 0 || value.rule2MinTrailingSilenceSec < 0 ||
      !isValidRule3MinUtteranceSec(value.rule3MinUtteranceLengthSec)) {
      throw new Error('endpoint rule silence values must be non-negative and ' +
        'rule3 must be -1 or a positive finite number');
    }
    this.config.endpointRules = value;
    return this;
  }
  hotwords(value: string[], score: number = 1.5): AsrConfigBuilder {
    if (score < 0.0 || score > 5.0) throw new Error('hotwordsScore must be in [0.0, 5.0]');
    this.config.hotwords = value.filter((word: string): boolean => word.trim().length > 0);
    this.config.hotwordsScore = score;
    return this;
  }
  hotwordsScore(value: number): AsrConfigBuilder {
    if (value < 0.0 || value > 5.0) throw new Error('hotwordsScore must be in [0.0, 5.0]');
    this.config.hotwordsScore = value;
    return this;
  }
  targetSpeaker(value: TargetSpeakerConfig | undefined): AsrConfigBuilder {
    if (value !== undefined) validateTargetSpeakerConfig(value);
    this.config.targetSpeaker = value;
    return this;
  }
  build(): AsrConfig {
    validateVadConfig(this.config.vadConfig);
    validateTargetSpeakerConfig(this.config.targetSpeaker);
    return this.config;
  }
}

export class AsrResult {
  text: string = '';
  /** Decoder text before ITN and punctuation. */
  rawText: string = '';
  confidence: number = 1.0;
  tokens: string[] = [];
  timestamps: number[] = [];
  tokenConfidences: number[] = [];
  speakerScore?: number;
  isTargetSpeaker?: boolean;
  // True only for the final produced by an explicit stop/finish; endpoint finals stay false.
  isLast: boolean = false;
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
  static readonly OK: number = 0;
  static readonly INVALID_ARGUMENT: number = 1001;
  static readonly SDK_NOT_INITIALIZED: number = 1002;
  static readonly SESSION_ALREADY_CLOSED: number = 1003;
  static readonly LANGUAGE_UNAVAILABLE: number = 2001;
  static readonly ASSET_INSTALL_FAILED: number = 2002;
  static readonly STORAGE_INSUFFICIENT: number = 2003;
  static readonly DECODE_FAILED: number = 3001;
  static readonly POSTPROCESS_FAILED: number = 3002;
  static readonly LICENSE_MISSING: number = 6001;
  static readonly LICENSE_MALFORMED: number = 6002;
  static readonly LICENSE_SIGNATURE_INVALID: number = 6003;
  static readonly LICENSE_APP_MISMATCH: number = 6004;
  static readonly LICENSE_CERT_MISMATCH: number = 6005;
  static readonly LICENSE_EXPIRED: number = 6006;
  static readonly LICENSE_DEVICE_MISMATCH: number = 6007;
  static readonly LICENSE_SDK_MAJOR_MISMATCH: number = 6008;
  static readonly LICENSE_MAINTENANCE_EXPIRED: number = 6009;
  static readonly LICENSE_FEATURE_MISSING: number = 6010;
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
  assetInstallMs: number = -1;
  assetTotalBytes: number = -1;
  engineReadyMs: number = -1;
  nativeRssMbAtReady: number = -1;
  utteranceIndex: number = -1;
  utteranceDurationMs: number = -1;
  decodeDurationMs: number = -1;
  postProcessMs: number = -1;
  firstPartialLatencyMs: number = -1;
  endpointToFinalLatencyMs: number = -1;
  utteranceE2eLatencyMs: number = -1;
  rtf: number = -1;
  nativeRssMbDelta: number = 0;
  nativeRssMb: number = -1;
  pcmBytesAccepted: number = -1;
  totalUtterances: number = -1;
  totalPcmBytes: number = -1;
  avgRtf: number = -1;
  p95Rtf: number = -1;
  peakNativeRssMb: number = -1;

  toLogLine(): string {
    const parts: string[] = [];
    parts.push(`kind=${this.kind}`);
    parts.push(`language=${this.language}`);
    parts.push(`sessionId=${this.sessionId}`);
    if (this.kind === AmphionMetricsKind.UTTERANCE) {
      parts.push(`utteranceIndex=${this.utteranceIndex}`);
      parts.push(`utteranceDurationMs=${this.utteranceDurationMs}`);
      parts.push(`decodeDurationMs=${this.decodeDurationMs}`);
      parts.push(`postProcessMs=${this.postProcessMs}`);
      parts.push(`firstPartialLatencyMs=${this.firstPartialLatencyMs}`);
      parts.push(`endpointToFinalLatencyMs=${this.endpointToFinalLatencyMs}`);
      parts.push(`utteranceE2eLatencyMs=${this.utteranceE2eLatencyMs}`);
      parts.push(`rtf=${formatMetricFloat(this.rtf)}`);
      parts.push(`nativeRssMb=${this.nativeRssMb}`);
      parts.push(`nativeRssMbDelta=${this.nativeRssMbDelta}`);
      parts.push(`pcmBytesAccepted=${this.pcmBytesAccepted}`);
      if (this.assetInstallMs >= 0) {
        parts.push(`assetInstallMs=${this.assetInstallMs}`);
        parts.push(`assetTotalBytes=${this.assetTotalBytes}`);
        parts.push(`engineReadyMs=${this.engineReadyMs}`);
        parts.push(`nativeRssMbAtReady=${this.nativeRssMbAtReady}`);
      }
    } else {
      parts.push(`totalUtterances=${this.totalUtterances}`);
      parts.push(`totalPcmBytes=${this.totalPcmBytes}`);
      parts.push(`avgRtf=${formatMetricFloat(this.avgRtf)}`);
      parts.push(`p95Rtf=${formatMetricFloat(this.p95Rtf)}`);
      parts.push(`peakNativeRssMb=${this.peakNativeRssMb}`);
      parts.push(`nativeRssMb=${this.nativeRssMb}`);
    }
    return parts.join(' ');
  }
}

export interface AsrCallback {
  onSpeechBegin?(): void;
  onInitialSilenceTimeout?(): void;
  onPartial?(text: string): void;
  onPartialResult?(result: AsrResult): void;
  onFinal?(text: string, confidence: number): void;
  onFinalResult?(result: AsrResult): void;
  onFinalRejected?(result: AsrResult): void;
  onEndpoint?(): void;
  onDebug?(message: string): void;
  onError?(error: AsrError): void;
  onSessionStarted?(): void;
  onSessionStopped?(): void;
  onMetrics?(metrics: AmphionMetrics): void;
}

export interface Cancellable {
  cancel(): void;
  isDone(): boolean;
}

function validateVadConfig(config: VadConfig): void {
  if (config.threshold < 0.0 || config.threshold > 1.0) {
    throw new Error(`VadConfig.threshold must be in [0.0, 1.0], got ${config.threshold}`);
  }
  if (config.minSilenceDurationSec < 0 || config.minSpeechDurationSec < 0) {
    throw new Error('VadConfig min durations must be >= 0');
  }
  if (config.maxSpeechDurationSec <= 0) {
    throw new Error('VadConfig.maxSpeechDurationSec must be > 0');
  }
  if (config.activeEndpointSilenceMs < 0) {
    throw new Error('VadConfig.activeEndpointSilenceMs must be >= 0');
  }
}

function validateSpeakerVadConfig(config: SpeakerVadConfig | undefined): void {
  if (config === undefined) return;
  if (config.threshold < -1.0 || config.threshold > 1.0) {
    throw new Error(`SpeakerVadConfig.threshold must be in [-1.0, 1.0], got ${config.threshold}`);
  }
  if (config.winSec <= 0 || config.hopSec <= 0) {
    throw new Error('SpeakerVadConfig winSec and hopSec must be > 0');
  }
  if (config.consecutiveBelow < 1) {
    throw new Error('SpeakerVadConfig.consecutiveBelow must be >= 1');
  }
}

function validateTargetSpeakerConfig(config: TargetSpeakerConfig | undefined): void {
  if (config === undefined) return;
  if (config.modelPath.trim().length === 0) {
    throw new Error('TargetSpeakerConfig.modelPath must not be blank');
  }
  if (config.threshold < -1.0 || config.threshold > 1.0) {
    throw new Error(`TargetSpeakerConfig.threshold must be in [-1.0, 1.0], got ${config.threshold}`);
  }
  if (config.winSec <= 0 || config.hopSec <= 0 ||
    !isValidSpeakerMinimumSegment(config.minSegSec)) {
    throw new Error(
      'TargetSpeakerConfig winSec and hopSec must be > 0; minSegSec must be finite and >= 0');
  }
  if (config.numThreads < 1 || config.numThreads > 8) {
    throw new Error(`TargetSpeakerConfig.numThreads must be in [1, 8], got ${config.numThreads}`);
  }
  validateSpeakerVadConfig(config.speakerVad);
}

function formatMetricFloat(value: number): string {
  return value < 0 ? '-1' : value.toFixed(3);
}
