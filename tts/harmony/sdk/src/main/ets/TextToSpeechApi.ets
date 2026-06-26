import application from '@ohos.app.ability.application';
import fs from '@ohos.file.fs';
import { audio } from '@kit.AudioKit';
import { buffer } from '@kit.ArkTS';
import { cryptoFramework } from '@kit.CryptoArchitectureKit';

const MODEL_ID: string = 'transsion_lits_en_zh_vocos24k_streaming_proto_external_loop';
const MODEL_VERSION: string = '0.1.0';
const BUNDLED_MODEL_RAWFILE_DIR: string = `lits-models/tts/${MODEL_ID}/${MODEL_VERSION}`;
const DEFAULT_SAMPLE_RATE: number = 24000;
const MAX_ENGINE_COUNT: number = 3;
const MAX_TEXT_LENGTH: number = 10000;
const AUDIO_CHUNK_BYTES: number = 4096;
const SYNTHESIS_CALLBACK_CHUNK_BYTES: number = 524288;
const DEFAULT_LANGUAGE_CONTEXT: string = 'zh-CN';
const TN_LOG_TAG: string = '[LitsTn]';
const TEXT_METRIC_LOG_TAG: string = '[LitsTextMetric]';
const STREAM_METRIC_LOG_TAG: string = '[LitsStreamMetric]';
const DEFAULT_PCM_QUEUE_CAPACITY_VALUE: number = 32;
const MAX_PCM_QUEUE_CAPACITY_VALUE: number = 256;
const STREAMING_PREBUFFER_CHUNKS: number = 2;
const LICENSE_PUBLIC_KEY_B64: string = 'MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEc5BCEdeeELgXa3tTXeM6i49o+2NslcH9FrgpAMn3o61kFEv1Xlv7fD/kYA5NnXi2eLM8l+w4wEUvPgsbiM9tCQ==';

const SUPPORTED_LANGUAGES: Array<string> = ['zh-en', 'en-US'];
const SUPPORTED_LANGUAGE_SET: Set<string> = new Set<string>(SUPPORTED_LANGUAGES);
const SUPPORTED_SOUND_CHANNELS: Set<number> = new Set<number>([
  audio.StreamUsage.STREAM_USAGE_UNKNOWN,
  audio.StreamUsage.STREAM_USAGE_MUSIC,
  audio.StreamUsage.STREAM_USAGE_VOICE_COMMUNICATION,
  audio.StreamUsage.STREAM_USAGE_VOICE_ASSISTANT,
  audio.StreamUsage.STREAM_USAGE_ALARM,
  audio.StreamUsage.STREAM_USAGE_VOICE_MESSAGE,
  audio.StreamUsage.STREAM_USAGE_RINGTONE,
  audio.StreamUsage.STREAM_USAGE_NOTIFICATION,
  audio.StreamUsage.STREAM_USAGE_ACCESSIBILITY,
  audio.StreamUsage.STREAM_USAGE_MOVIE,
  audio.StreamUsage.STREAM_USAGE_GAME,
  audio.StreamUsage.STREAM_USAGE_AUDIOBOOK,
  audio.StreamUsage.STREAM_USAGE_NAVIGATION,
  audio.StreamUsage.STREAM_USAGE_VIDEO_COMMUNICATION
]);
const VOICES: Array<RegisteredVoice> = [
  {
    voiceId: 'lits-female-01',
    gender: 'Female',
    description: 'Lits delivery female speaker 01',
    speakerId: 0
  },
  {
    voiceId: 'lits-female-02',
    gender: 'Female',
    description: 'Lits delivery female speaker 02',
    speakerId: 1
  }
];

const REQUIRED_RUNTIME_FILES: Array<string> = [
  'manifest.json',
  'lits_hidden_encoder.onnx',
  'lits_stream_condition_chunk.onnx',
  'lits_stream_condition_final.onnx',
  'lits_stream_decoder_step.onnx',
  'vocos_vocoder.onnx',
  'chinese_lexicon.txt',
  'cmudict.txt',
  'polychar.txt',
  'zh_en_symbols.json',
  'pinyin_to_tokens.json',
  'arpabet_to_tokens.json'
];

const BUNDLED_MODEL_FILES: Array<string> = [
  'manifest.json',
  'export_report.json',
  'vocos_vocoder.export_report.json',
  'frontend_golden.json',
  'chinese_lexicon.txt',
  'chinese_lexicon.bin',
  'cmudict.txt',
  'cmudict.bin',
  'pinyin_2_bpmf.txt',
  'polychar.txt',
  'zh_en_symbols.json',
  'pinyin_to_tokens.json',
  'arpabet_to_tokens.json',
  'tn-bin/arm64-v8a/zh_tts',
  'tn-bin/arm64-v8a/en_tts',
  'rules/zh.json',
  'rules/en.json',
  'rules/zh_pinyin.json',
  'rules_v2/zh.full.json',
  'rules_v2/en.full.json',
  'lits_hidden_encoder.onnx',
  'lits_stream_condition_chunk.onnx',
  'lits_stream_condition_final.onnx',
  'lits_stream_decoder_step.onnx',
  'vocos_vocoder.onnx'
];

let bundledModelPackageDirCache: string | undefined = undefined;

const PUNCTUATION_SET: Set<string> = new Set<string>([
  ',',
  '.',
  '!',
  '?',
  ';',
  ':',
  '\'',
  '"',
  '(',
  ')',
  '[',
  ']',
  '<',
  '>',
  '-',
  '\u2026'
]);

const FULLWIDTH_PUNCTUATION: Map<string, string> = new Map<string, string>([
  ['\uFF0C', ','],
  ['\u3002', '.'],
  ['\uFF01', '!'],
  ['\uFF1F', '?'],
  ['\uFF1B', ';'],
  ['\uFF1A', ':'],
  ['\u3001', ','],
  ['\u2018', '\''],
  ['\u2019', '\''],
  ['\u201C', '"'],
  ['\u201D', '"'],
  ['\u3010', '['],
  ['\u3011', ']'],
  ['\uFF08', '('],
  ['\uFF09', ')'],
  ['\u300A', '<'],
  ['\u300B', '>'],
  ['\u2014', '-'],
  ['\u2013', '-'],
  ['\u22EF', '\u2026'],
  ['\u00B7', '.']
]);

const ENGLISH_DIGIT_WORD_BY_CHAR: Map<string, string> = new Map<string, string>([
  ['0', 'ZERO'],
  ['1', 'ONE'],
  ['2', 'TWO'],
  ['3', 'THREE'],
  ['4', 'FOUR'],
  ['5', 'FIVE'],
  ['6', 'SIX'],
  ['7', 'SEVEN'],
  ['8', 'EIGHT'],
  ['9', 'NINE']
]);

const CHINESE_DIGIT_TEXT_BY_CHAR: Map<string, string> = new Map<string, string>([
  ['0', '\u96F6'],
  ['1', '\u4E00'],
  ['2', '\u4E8C'],
  ['3', '\u4E09'],
  ['4', '\u56DB'],
  ['5', '\u4E94'],
  ['6', '\u516D'],
  ['7', '\u4E03'],
  ['8', '\u516B'],
  ['9', '\u4E5D']
]);

const ZH_EN_FRONTEND_CHAR_REPLACEMENTS: Map<string, string> = new Map<string, string>([
  ['/', '\u659C\u6760'],
  ['\\', '\u53CD\u659C\u6760'],
  ['^', '\u5E42'],
  ['\u2070', '\u96F6'],
  ['\u00B9', '\u4E00'],
  ['\u00B2', '\u4E8C'],
  ['\u00B3', '\u4E09'],
  ['\u2074', '\u56DB'],
  ['\u2075', '\u4E94'],
  ['\u2076', '\u516D'],
  ['\u2077', '\u4E03'],
  ['\u2078', '\u516B'],
  ['\u2079', '\u4E5D'],
  ['\u2080', '\u96F6'],
  ['\u2081', '\u4E00'],
  ['\u2082', '\u4E8C'],
  ['\u2083', '\u4E09'],
  ['\u2084', '\u56DB'],
  ['\u2085', '\u4E94'],
  ['\u2086', '\u516D'],
  ['\u2087', '\u4E03'],
  ['\u2088', '\u516B'],
  ['\u2089', '\u4E5D']
]);

const ZH_EN_ASCII_SYMBOL_TEXT: Map<string, string> = new Map<string, string>([
  ['@', '\u827E\u7279'],
  ['#', '\u4E95\u53F7'],
  ['$', '\u7F8E\u5143'],
  ['%', '\u767E\u5206\u53F7'],
  ['&', '\u548C'],
  ['*', '\u661F\u53F7'],
  ['+', '\u52A0'],
  ['=', '\u7B49\u4E8E'],
  ['_', '\u4E0B\u5212\u7EBF'],
  ['|', '\u7AD6\u7EBF'],
  ['~', '\u6CE2\u6D6A\u7EBF']
]);

const SYMBOL_TO_SAFE_PUNCTUATION: Map<string, string> = new Map<string, string>([
  ['{', '('],
  ['}', ')'],
  ['\uFF5B', '('],
  ['\uFF5D', ')'],
  ['\u300C', '"'],
  ['\u300D', '"'],
  ['\u300E', '"'],
  ['\u300F', '"'],
  ['\u3014', '['],
  ['\u3015', ']'],
  ['\u3016', '['],
  ['\u3017', ']'],
  ['\u3018', '['],
  ['\u3019', ']'],
  ['\u301A', '['],
  ['\u301B', ']'],
  ['\uFF3B', '['],
  ['\uFF3D', ']'],
  ['\uFF1C', '<'],
  ['\uFF1E', '>'],
  ['\uFF0F', ','],
  ['\uFF3C', ','],
  ['\uFF20', ','],
  ['\uFF03', ','],
  ['\uFF04', ','],
  ['\uFF05', ','],
  ['\uFF06', ','],
  ['\uFF0A', ','],
  ['\uFF0B', ','],
  ['\uFF1D', ','],
  ['\uFF3F', ','],
  ['\uFF5C', ','],
  ['\uFF5E', ','],
  ['\u2190', ','],
  ['\u2191', ','],
  ['\u2192', ','],
  ['\u2193', ','],
  ['\u21D2', ','],
  ['\u2605', ','],
  ['\u2606', ','],
  ['\u2713', ','],
  ['\u2714', ','],
  ['\u2715', ','],
  ['\u2716', ',']
]);

const ENGLISH_MERGE_RULES: Array<MergeRule> = [
  { pair: ['t', '\u0279'], replacement: 't\u0279' },
  { pair: ['d', '\u0279'], replacement: 'd\u0279' },
  { pair: ['t', 's'], replacement: 'ts' },
  { pair: ['d', 'z'], replacement: 'dz' },
  { pair: ['\u026A', '\u0279'], replacement: '\u026A\u0279' },
  { pair: ['o\u02D0', '\u0279'], replacement: 'o\u02D0\u0279' }
];

const PINYIN_SYLLABLE_REGEX: RegExp = /^[a-z]+[0-6]$/;
const SENTENCE_END_PUNCTUATION: Set<string> = new Set<string>(['.', '!', '?', ';', ',', '\u2026']);
const ATTACHED_SENTENCE_SUFFIX: Set<string> = new Set<string>([
  '"',
  '\'',
  ')',
  ']',
  '}',
  '>',
  '\u201D',
  '\u2019',
  '\u300B',
  '\u3011'
]);
const ENGLISH_ABBREVIATIONS: Set<string> = new Set<string>([
  'mr',
  'mrs',
  'ms',
  'dr',
  'prof',
  'sr',
  'jr',
  'st',
  'mt',
  'vs',
  'etc',
  'fig',
  'no',
  'e.g',
  'i.e',
  'a.m',
  'p.m',
  'u.s',
  'u.k'
]);
const ACRONYM_AT_END_REGEX: RegExp = /(?:^|\s)(?:[A-Za-z]\.){2,}$/;
const MIN_WEAK_PUNCTUATION_SEGMENT_CHARS: number = 24;
const MIN_SHORT_SYMBOL_SEGMENT_CHARS: number = 8;
const DEFAULT_WORDS_PER_STREAMING_SEGMENT: number = 7;
const PLATE_PROVINCES: string = '\u4EAC\u6D25\u6CAA\u6E1D\u5180\u8C6B\u4E91\u8FBD\u9ED1\u6E58\u7696\u9C81\u65B0\u82CF\u6D59\u8D63\u9102\u6842\u7518\u664B\u8499\u9655\u5409\u95FD\u8D35\u7CA4\u9752\u85CF\u5DDD\u5B81\u743C';
const PERCENTILE_CODE_REGEX: RegExp = /^P\d{1,3}$/;

interface NativeTtsModule {
  createRuntime(
    hiddenEncoderPath: string,
    streamConditionChunkPath: string,
    streamConditionFinalPath: string,
    streamDecoderStepPath: string,
    vocoderPath: string,
    chunkSize: number,
    preLookaheadLen: number,
    melCacheLen: number,
    hopLength: number,
    decoderTimesteps: number,
    decoderTemperature: number
  ): object;
  releaseRuntime(runtimeHandle: object): void;
  cancelRuntime(runtimeHandle: object): void;
  synthesize(runtimeHandle: object, tokenIds: Array<number>, speakerId: number): ArrayBuffer;
  synthesizeAsync(runtimeHandle: object, tokenIds: Array<number>, speakerId: number): Promise<ArrayBuffer>;
  synthesizeStreaming(
    runtimeHandle: object,
    tokenIds: Array<number>,
    speakerId: number,
    onChunk: (chunk: ArrayBuffer, sequence: number) => void
  ): Promise<NativeStreamingSynthesisMetrics>;
  normalizeTnSegment(binaryPath: string, workingDir: string, text: string): string;
}

interface NativeStreamingSynthesisMetrics {
  synthesisMs: number;
  firstChunkMs: number;
  audioBytes: number;
  chunkCount: number;
  textMetricSummary?: string;
}

export enum TtsErrorCode {
  OK = 0,
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
  LICENSE_DEVICE_MISMATCH = 1002300018
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

export interface ExtraParams {
  modelPackageDir?: string;
  streamingChunkSize?: number;
  streamingFirstChunkSize?: number;
  pcmQueueCapacity?: number;
  pcmQueueSize?: number;
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
}

export interface SynthesisResponse {
  sequence: number;
  audioType: string;
}

export interface CompleteResponse {
  type: CompleteType;
  message: string;
  firstPacketMs?: number;
  synthesisMs?: number;
  audioDurationMs?: number;
  rtf?: number;
  profilingInfo?: string;
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

export enum LicenseEnforcement {
  ENFORCE = 'ENFORCE',
  PERMISSIVE = 'PERMISSIVE'
}

export enum TtsLicenseState {
  NOT_INITIALIZED = 'NOT_INITIALIZED',
  DEV_UNLICENSED = 'DEV_UNLICENSED',
  LICENSED = 'LICENSED',
  INVALID = 'INVALID'
}

export interface TtsLicenseStatus {
  state: TtsLicenseState;
  valid: boolean;
  errorCode: number;
  licenseId: string;
  customer: string;
  applicationId: string;
  issuedAt: string;
  expiresAt: string;
  installTier: string;
  features: Array<string>;
}

export interface TtsLicenseOptions {
  license?: string;
  applicationId?: string;
  certSha256?: string;
  deviceSha256?: string;
  expiryGraceDays?: number;
  enforcement?: LicenseEnforcement;
}

interface LicenseClaims {
  licenseId: string;
  customer: string;
  applicationId: string;
  certSha256: string;
  deviceSha256: string;
  issuedAt: string;
  expiresAt: string;
  installTier: string;
  features: Array<string>;
  sdkMajor: number;
}

interface LicenseEnvelope {
  payload_b64: string;
  sig_b64: string;
}

interface LicenseVerifierResult {
  status: TtsLicenseStatus;
  errorCode: number;
  errorMessage?: string;
}

class LicenseVerifier {
  private static readonly DAY_MS: number = 24 * 60 * 60 * 1000;

  static async verify(options: TtsLicenseOptions): Promise<LicenseVerifierResult> {
    const applicationId = options.applicationId ?? '';
    if (LICENSE_PUBLIC_KEY_B64.trim().length === 0) {
      return LicenseVerifier.okDev(applicationId);
    }
    if (options.license === undefined || options.license.trim().length === 0) {
      return LicenseVerifier.fail(applicationId, TtsErrorCode.LICENSE_MISSING, 'no license provided');
    }

    let payloadBytes: Uint8Array;
    let sigBytes: Uint8Array;
    try {
      const envelope = JSON.parse(options.license) as LicenseEnvelope;
      payloadBytes = base64Decode(envelope.payload_b64);
      sigBytes = base64Decode(envelope.sig_b64);
    } catch (error) {
      return LicenseVerifier.fail(
        applicationId,
        TtsErrorCode.LICENSE_MALFORMED,
        `bad envelope: ${formatError(error)}`
      );
    }

    let claims: LicenseClaims;
    try {
      claims = LicenseVerifier.parseClaims(buffer.from(payloadBytes.buffer).toString('utf-8'));
    } catch (error) {
      return LicenseVerifier.fail(
        applicationId,
        TtsErrorCode.LICENSE_MALFORMED,
        `bad payload: ${formatError(error)}`
      );
    }

    const signatureValid = await LicenseVerifier.verifySignature(payloadBytes, sigBytes);
    if (!signatureValid) {
      return LicenseVerifier.failWith(
        claims,
        TtsErrorCode.LICENSE_SIGNATURE_INVALID,
        'signature mismatch'
      );
    }

    if (claims.applicationId !== applicationId) {
      return LicenseVerifier.failWith(
        claims,
        TtsErrorCode.LICENSE_APP_MISMATCH,
        `license app=${claims.applicationId} host=${applicationId}`
      );
    }

    if (claims.certSha256.trim().length > 0) {
      const want = normalizeHex(claims.certSha256);
      const have = normalizeHex(options.certSha256 ?? '');
      if (want !== have) {
        return LicenseVerifier.failWith(
          claims,
          TtsErrorCode.LICENSE_CERT_MISMATCH,
          `license cert=${want} host=${have}`
        );
      }
    }

    if (claims.expiresAt.trim().length > 0) {
      const expMillis = parseDateUtcMillis(claims.expiresAt);
      if (expMillis === undefined) {
        return LicenseVerifier.failWith(
          claims,
          TtsErrorCode.LICENSE_MALFORMED,
          `bad expiresAt=${claims.expiresAt}`
        );
      }
      const graceDays = options.expiryGraceDays ?? 0;
      const deadline = expMillis + (graceDays + 1) * LicenseVerifier.DAY_MS;
      if (Date.now() >= deadline) {
        return LicenseVerifier.failWith(claims, TtsErrorCode.LICENSE_EXPIRED, `expiresAt=${claims.expiresAt}`);
      }
    }

    if (claims.deviceSha256.trim().length > 0) {
      const want = normalizeHex(claims.deviceSha256);
      const have = normalizeHex(options.deviceSha256 ?? '');
      if (want !== have) {
        return LicenseVerifier.failWith(
          claims,
          TtsErrorCode.LICENSE_DEVICE_MISMATCH,
          `license device=${want} host=${have}`
        );
      }
    }

    return {
      status: {
        state: TtsLicenseState.LICENSED,
        valid: true,
        errorCode: TtsErrorCode.OK,
        licenseId: claims.licenseId,
        customer: claims.customer,
        applicationId: claims.applicationId,
        issuedAt: claims.issuedAt,
        expiresAt: claims.expiresAt,
        installTier: claims.installTier,
        features: claims.features
      },
      errorCode: TtsErrorCode.OK
    };
  }

  private static async verifySignature(payloadBytes: Uint8Array, sigBytes: Uint8Array): Promise<boolean> {
    try {
      const keyGenerator = cryptoFramework.createAsyKeyGenerator('ECC256');
      const keyPair = await keyGenerator.convertKey({ data: base64Decode(LICENSE_PUBLIC_KEY_B64) }, null);
      const verifier = cryptoFramework.createVerify('ECC256|SHA256');
      await verifier.init(keyPair.pubKey);
      await verifier.update({ data: payloadBytes });
      return await verifier.verify({ data: sigBytes });
    } catch (_error) {
      return false;
    }
  }

  private static parseClaims(payloadJson: string): LicenseClaims {
    const raw = JSON.parse(payloadJson) as Record<string, Object>;
    const featuresRaw = raw['features'];
    const features = Array.isArray(featuresRaw) ? featuresRaw.map((item: Object): string => String(item)) : [];
    return {
      licenseId: String(raw['licenseId'] ?? ''),
      customer: String(raw['customer'] ?? ''),
      applicationId: String(raw['applicationId'] ?? ''),
      certSha256: String(raw['certSha256'] ?? ''),
      deviceSha256: String(raw['deviceSha256'] ?? ''),
      issuedAt: String(raw['issuedAt'] ?? ''),
      expiresAt: String(raw['expiresAt'] ?? ''),
      installTier: String(raw['installTier'] ?? ''),
      features,
      sdkMajor: Number(raw['sdkMajor'] ?? -1)
    };
  }

  private static okDev(applicationId: string): LicenseVerifierResult {
    return {
      status: makeLicenseStatus(TtsLicenseState.DEV_UNLICENSED, false, TtsErrorCode.OK, applicationId),
      errorCode: TtsErrorCode.OK
    };
  }

  private static fail(applicationId: string, errorCode: number, message: string): LicenseVerifierResult {
    return {
      status: makeLicenseStatus(TtsLicenseState.INVALID, false, errorCode, applicationId),
      errorCode,
      errorMessage: message
    };
  }

  private static failWith(claims: LicenseClaims, errorCode: number, message: string): LicenseVerifierResult {
    return {
      status: {
        state: TtsLicenseState.INVALID,
        valid: false,
        errorCode,
        licenseId: claims.licenseId,
        customer: claims.customer,
        applicationId: claims.applicationId,
        issuedAt: claims.issuedAt,
        expiresAt: claims.expiresAt,
        installTier: claims.installTier,
        features: claims.features
      },
      errorCode,
      errorMessage: message
    };
  }
}

class LicenseGuard {
  private static cached: LicenseVerifierResult | undefined = undefined;
  private static enforcement: LicenseEnforcement = LicenseEnforcement.ENFORCE;

  static async configureAndVerify(options: TtsLicenseOptions): Promise<void> {
    LicenseGuard.enforcement = options.enforcement ?? LicenseEnforcement.ENFORCE;
    const result = await LicenseVerifier.verify(options);
    LicenseGuard.cached = result;
    if (result.errorCode !== TtsErrorCode.OK && LicenseGuard.enforcement === LicenseEnforcement.ENFORCE) {
      throw LicenseGuard.licenseException(result);
    }
  }

  static gate(): void {
    const result = LicenseGuard.cached;
    if (LICENSE_PUBLIC_KEY_B64.trim().length > 0 && result === undefined) {
      throw new TextToSpeechException(TtsErrorCode.LICENSE_MISSING, 'license check has not been initialized');
    }
    if (
      result !== undefined &&
      result.errorCode !== TtsErrorCode.OK &&
      LicenseGuard.enforcement === LicenseEnforcement.ENFORCE
    ) {
      throw LicenseGuard.licenseException(result);
    }
  }

  static status(): TtsLicenseStatus {
    return LicenseGuard.cached?.status ?? makeLicenseStatus(
      TtsLicenseState.NOT_INITIALIZED,
      false,
      TtsErrorCode.OK,
      ''
    );
  }

  private static licenseException(result: LicenseVerifierResult): TextToSpeechException {
    return new TextToSpeechException(
      result.errorCode,
      `license check failed (code=${result.errorCode}): ${result.errorMessage ?? 'unauthorized'}`
    );
  }
}

interface RegisteredVoice {
  voiceId: string;
  gender: string;
  description: string;
  speakerId: number;
}

interface MergeRule {
  pair: Array<string>;
  replacement: string;
}

interface ModelManifest {
  manifest_version?: number;
  task?: string;
  model_id?: string;
  version?: string;
  model_type?: string;
  model_lang?: string;
  sample_rate?: number;
  mel_bins?: number;
  hop_length?: number;
  speaker_count?: number;
  default_speaker_id?: number;
  supports_streaming?: boolean;
  default_language?: string;
  supported_languages?: Array<string>;
  input_modes?: Array<string>;
  runtime_format?: string;
  vocoder_type?: string;
  streaming_chunk_size?: number;
  streaming_pre_lookahead_len?: number;
  streaming_mel_cache_len?: number;
  acoustic_model?: ManifestModelFile;
  hidden_encoder_model?: ManifestModelFile;
  stream_condition_chunk_model?: ManifestModelFile;
  stream_condition_final_model?: ManifestModelFile;
  stream_decoder_step_model?: ManifestModelFile;
  stream_decoder_external_loop?: boolean;
  stream_decoder_n_timesteps?: number;
  stream_decoder_temperature?: number;
  vocoder_model?: ManifestModelFile;
}

interface ManifestModelFile {
  file?: string;
  format?: string;
}

interface LoadedPackage {
  rootDir: string;
  manifest: RequiredManifest;
  wordPinyin: Map<string, string>;
  polyphonicWords: Set<string>;
  maxWordLength: number;
  cmudict: Map<string, Array<string>>;
  symbolToId: Map<string, number>;
  pinyinToTokens: Map<string, Array<string>>;
  arpabetToTokens: Map<string, Array<string>>;
}

interface RequiredManifest {
  sampleRate: number;
  hopLength: number;
  speakerCount: number;
  defaultSpeakerId: number;
  supportsStreaming: boolean;
  supportedLanguages: Array<string>;
  hiddenEncoderModelFile: string;
  streamConditionChunkModelFile: string;
  streamConditionFinalModelFile: string;
  streamDecoderStepModelFile: string;
  streamDecoderTimesteps: number;
  streamDecoderTemperature: number;
  vocoderModelFile: string;
  streamingChunkSize: number;
  streamingPreLookaheadLen: number;
  streamingMelCacheLen: number;
}

interface InternalSynthesis {
  pcm: ArrayBuffer;
  sampleRate: number;
  tokenIds: Array<number>;
}

interface TextMetric {
  rawText: string;
  tnText: string;
  cleanedText: string;
  cleanedTokenLength: number;
  modelTokenLength: number;
  tokenIds: Array<number>;
  tokenIdHead: Array<number>;
  tokenIdTail: Array<number>;
}

interface PcmQueueTakeResult {
  chunk?: ArrayBuffer;
  done: boolean;
}

interface SynthesisTask {
  text: string;
  params: SpeakParams;
  cancelled: boolean;
  stopNotified: boolean;
}

class FrontendResources {
  private static loadedPackages: Map<string, LoadedPackage> = new Map<string, LoadedPackage>();

  static load(modelPackageDir: string): LoadedPackage {
    const normalizedDir = normalizeDir(modelPackageDir);
    const cached = FrontendResources.loadedPackages.get(normalizedDir);
    if (cached !== undefined) {
      return cached;
    }

    const manifest = FrontendResources.loadManifest(normalizedDir);
    const wordPinyin = FrontendResources.loadWordPinyin(joinPath(normalizedDir, 'chinese_lexicon.txt'));
    const loaded: LoadedPackage = {
      rootDir: normalizedDir,
      manifest,
      wordPinyin,
      polyphonicWords: new Set<string>(readNonEmptyLines(joinPath(normalizedDir, 'polychar.txt'))),
      maxWordLength: FrontendResources.maxWordLength(wordPinyin),
      cmudict: FrontendResources.loadCmudict(joinPath(normalizedDir, 'cmudict.txt')),
      symbolToId: FrontendResources.loadSymbols(joinPath(normalizedDir, 'zh_en_symbols.json')),
      pinyinToTokens: FrontendResources.loadTokenMap(joinPath(normalizedDir, 'pinyin_to_tokens.json'), 'pinyin_to_tokens'),
      arpabetToTokens: FrontendResources.loadTokenMap(joinPath(normalizedDir, 'arpabet_to_tokens.json'), 'arpabet_to_tokens')
    };
    FrontendResources.loadedPackages.set(normalizedDir, loaded);
    return loaded;
  }

  private static loadManifest(modelPackageDir: string): RequiredManifest {
    FrontendResources.ensureRuntimeFiles(modelPackageDir);
    const raw = readJsonFile<ModelManifest>(joinPath(modelPackageDir, 'manifest.json'));
    if (
      raw.task !== 'tts' ||
      raw.model_id !== MODEL_ID ||
      raw.version !== MODEL_VERSION ||
      raw.runtime_format !== 'onnx' ||
      raw.sample_rate !== DEFAULT_SAMPLE_RATE ||
      raw.hop_length === undefined ||
      raw.hop_length <= 0 ||
      raw.supports_streaming !== true ||
      (raw.supported_languages ?? []).indexOf('zh-en') < 0 ||
      (raw.supported_languages ?? []).indexOf('en-US') < 0 ||
      raw.hidden_encoder_model?.file !== 'lits_hidden_encoder.onnx' ||
      raw.stream_decoder_external_loop !== true ||
      raw.stream_condition_chunk_model?.file !== 'lits_stream_condition_chunk.onnx' ||
      raw.stream_condition_final_model?.file !== 'lits_stream_condition_final.onnx' ||
      raw.stream_decoder_step_model?.file !== 'lits_stream_decoder_step.onnx' ||
      raw.stream_decoder_n_timesteps === undefined ||
      raw.stream_decoder_n_timesteps <= 0 ||
      raw.stream_decoder_temperature === undefined ||
      raw.vocoder_model?.file !== 'vocos_vocoder.onnx' ||
      raw.streaming_chunk_size === undefined ||
      raw.streaming_chunk_size <= 0 ||
      raw.streaming_pre_lookahead_len === undefined ||
      raw.streaming_pre_lookahead_len < 0 ||
      raw.streaming_mel_cache_len === undefined ||
      raw.streaming_mel_cache_len <= 0 ||
      raw.speaker_count === undefined ||
      raw.speaker_count < 1 ||
      raw.default_speaker_id === undefined ||
      raw.default_speaker_id < 0 ||
      raw.default_speaker_id >= raw.speaker_count
    ) {
      throw new TextToSpeechException(
        TtsErrorCode.CREATE_ENGINE_FAILED,
        `invalid TTS manifest: ${joinPath(modelPackageDir, 'manifest.json')}`
      );
    }
    return {
      sampleRate: raw.sample_rate,
      hopLength: raw.hop_length,
      speakerCount: raw.speaker_count,
      defaultSpeakerId: raw.default_speaker_id,
      supportsStreaming: raw.supports_streaming,
      supportedLanguages: raw.supported_languages ?? ['zh-en', 'en-US'],
      hiddenEncoderModelFile: raw.hidden_encoder_model.file,
      streamConditionChunkModelFile: raw.stream_condition_chunk_model.file,
      streamConditionFinalModelFile: raw.stream_condition_final_model.file,
      streamDecoderStepModelFile: raw.stream_decoder_step_model.file,
      streamDecoderTimesteps: raw.stream_decoder_n_timesteps,
      streamDecoderTemperature: raw.stream_decoder_temperature,
      vocoderModelFile: raw.vocoder_model.file,
      streamingChunkSize: raw.streaming_chunk_size,
      streamingPreLookaheadLen: raw.streaming_pre_lookahead_len,
      streamingMelCacheLen: raw.streaming_mel_cache_len
    };
  }

  private static ensureRuntimeFiles(modelPackageDir: string): void {
    REQUIRED_RUNTIME_FILES.forEach((fileName: string): void => {
      const path = joinPath(modelPackageDir, fileName);
      if (!isRegularFile(path)) {
        throw new TextToSpeechException(
          TtsErrorCode.CREATE_ENGINE_FAILED,
          `missing runtime file: ${path}`
        );
      }
    });
  }

  private static loadWordPinyin(filePath: string): Map<string, string> {
    const output = new Map<string, string>();
    const lines = readText(filePath).split(/\r?\n/);
    lines.forEach((line: string): void => {
      const trimmed = line.trim();
      if (trimmed.length === 0) {
        return;
      }
      const parts = trimmed.split('\t');
      if (parts.length === 2) {
        output.set(parts[0], parts[1]);
      }
    });
    return output;
  }

  private static maxWordLength(wordPinyin: Map<string, string>): number {
    let maxLength = 1;
    wordPinyin.forEach((_value: string, key: string): void => {
      if (key.length > maxLength) {
        maxLength = key.length;
      }
    });
    return maxLength;
  }

  private static loadCmudict(filePath: string): Map<string, Array<string>> {
    const output = new Map<string, Array<string>>();
    const lines = readText(filePath).split(/\r?\n/);
    lines.forEach((line: string): void => {
      const trimmed = line.trim();
      if (trimmed.length === 0) {
        return;
      }
      const parts = trimmed.split('\t');
      if (parts.length !== 2) {
        return;
      }
      const key = parts[0].split('(')[0].toUpperCase();
      if (output.has(key)) {
        return;
      }
      const phones = splitByWhitespace(parts[1]);
      if (phones.length > 0) {
        output.set(key, phones);
      }
    });
    return output;
  }

  private static loadSymbols(filePath: string): Map<string, number> {
    const parsed = readJsonFile<Record<string, Object>>(filePath);
    const symbols = parsed['symbols'] as Array<string> | undefined;
    if (symbols === undefined || !Array.isArray(symbols)) {
      throw new TextToSpeechException(
        TtsErrorCode.CREATE_ENGINE_FAILED,
        `invalid zh_en_symbols.json: ${filePath}`
      );
    }
    const output = new Map<string, number>();
    symbols.forEach((symbol: string, index: number): void => {
      output.set(symbol, index);
    });
    return output;
  }

  private static loadTokenMap(filePath: string, key: string): Map<string, Array<string>> {
    const parsed = readJsonFile<Record<string, Object>>(filePath);
    const payload = parsed[key] as Record<string, Array<string>> | undefined;
    if (payload === undefined) {
      throw new TextToSpeechException(
        TtsErrorCode.CREATE_ENGINE_FAILED,
        `invalid token map: ${filePath}`
      );
    }
    const output = new Map<string, Array<string>>();
    Object.keys(payload).forEach((name: string): void => {
      const values = payload[name];
      if (Array.isArray(values)) {
        output.set(name, values.slice());
      }
    });
    return output;
  }
}

class TranssionTnNormalizer {
  static normalize(resources: LoadedPackage, text: string, language: string, languageContext: string): string {
    const input = TranssionTnNormalizer.prepareInput(text, languageContext);
    console.info(`${TN_LOG_TAG} normalize start language=${language} languageContext=${languageContext} inputLen=${input.length} root=${resources.rootDir}`);
    if (input.length === 0) {
      console.info(`${TN_LOG_TAG} normalize skip empty input`);
      return text;
    }
    if (!TranssionTnNormalizer.hasTnBinaries(resources)) {
      console.error(`${TN_LOG_TAG} normalize skip missing binaries zh=${TranssionTnNormalizer.binaryPath(resources, 'zh')} en=${TranssionTnNormalizer.binaryPath(resources, 'en')}`);
      return text;
    }
    let output: string;
    try {
      if (language === 'en-US' || languageContext === 'en-US') {
        output = TranssionTnNormalizer.normalizeSegment(resources, input, 'en');
      } else {
        output = TranssionTnNormalizer.segmentZhEn(input)
          .map((segment: TnTextSegment): string => TranssionTnNormalizer.normalizeSegment(resources, segment.text, segment.lang))
          .join('');
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error(`${TN_LOG_TAG} normalize failed language=${language} languageContext=${languageContext} message=${message}`);
      const code = error instanceof TextToSpeechException ? error.errorCode : TtsErrorCode.RUNTIME_EXCEPTION;
      throw new TextToSpeechException(code, message);
    }
    console.info(`${TN_LOG_TAG} normalize success outputLen=${output.length}`);
    return output;
  }

  private static prepareInput(text: string, languageContext: string): string {
    let output = '';
    const normalized = LitsTtsFrontend.normalizeText(text, languageContext);
    for (let index = 0; index < normalized.length; index += 1) {
      const code = normalized.charCodeAt(index);
      if ((code >= 0x00 && code <= 0x1f) || (code >= 0x7f && code <= 0x9f)) {
        continue;
      }
      const char = normalized[index];
      output += LitsTtsFrontend.isWhitespace(char) ? ' ' : char;
    }
    return output.replace(/\s+/g, ' ').trim();
  }

  private static hasTnBinaries(resources: LoadedPackage): boolean {
    const zhPath = TranssionTnNormalizer.binaryPath(resources, 'zh');
    const enPath = TranssionTnNormalizer.binaryPath(resources, 'en');
    const zhExists = isRegularFile(zhPath);
    const enExists = isRegularFile(enPath);
    console.info(`${TN_LOG_TAG} binary check zh=${zhExists} path=${zhPath} en=${enExists} path=${enPath}`);
    return zhExists && enExists;
  }

  private static normalizeSegment(resources: LoadedPackage, text: string, lang: string): string {
    if (text.trim().length === 0) {
      return text;
    }
    const binaryPath = TranssionTnNormalizer.binaryPath(resources, lang);
    console.info(`${TN_LOG_TAG} segment start lang=${lang} textLen=${text.length} binary=${binaryPath} root=${resources.rootDir} preview=${TranssionTnNormalizer.preview(text)}`);
    try {
      const normalized = resolveNativeTtsModule().normalizeTnSegment(
        binaryPath,
        resources.rootDir,
        text
      );
      console.info(`${TN_LOG_TAG} segment success lang=${lang} outputLen=${normalized.length} preview=${TranssionTnNormalizer.preview(normalized)}`);
      return normalized;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error(`${TN_LOG_TAG} segment failed lang=${lang} binary=${binaryPath} root=${resources.rootDir} message=${message}`);
      const code = error instanceof TextToSpeechException ? error.errorCode : TtsErrorCode.RUNTIME_EXCEPTION;
      throw new TextToSpeechException(code, message);
    }
  }

  private static binaryPath(resources: LoadedPackage, lang: string): string {
    return joinPath(resources.rootDir, lang === 'en' ? 'tn-bin/arm64-v8a/en_tts' : 'tn-bin/arm64-v8a/zh_tts');
  }

  private static preview(text: string): string {
    const singleLine = text.replace(/\s+/g, ' ');
    return singleLine.length > 80 ? `${singleLine.substring(0, 80)}...` : singleLine;
  }

  private static segmentZhEn(text: string): Array<TnTextSegment> {
    const segments: Array<TnTextSegment> = [];
    let index = 0;
    while (index < text.length) {
      const char = text[index];
      if (LitsTtsFrontend.isEnglishLetter(char)) {
        const end = TranssionTnNormalizer.scanAsciiRun(text, index);
        const segment = text.substring(index, end);
        const lang = TranssionTnNormalizer.protectedAsciiRunLang(text, index, end, segment) ?? 'en';
        segments.push({ text: segment, lang });
        index = end;
      } else {
        const end = TranssionTnNormalizer.scanNonAsciiRun(text, index);
        segments.push({ text: text.substring(index, end), lang: 'zh' });
        index = end;
      }
    }
    return segments;
  }

  private static scanAsciiRun(text: string, start: number): number {
    let index = start;
    while (index < text.length) {
      const char = text[index];
      const allowedPunctuation = char === '\'' || char === '.' || char === '_' || char === '-';
      if (!LitsTtsFrontend.isEnglishLetter(char) && !LitsTtsFrontend.isAsciiDigit(char) && !allowedPunctuation) {
        break;
      }
      index += 1;
    }
    return index;
  }

  private static scanNonAsciiRun(text: string, start: number): number {
    let index = start;
    while (
      index < text.length &&
      (!LitsTtsFrontend.isEnglishLetter(text[index]) || TranssionTnNormalizer.isAsciiCelsiusUnit(text, index))
    ) {
      index += 1;
    }
    return index;
  }

  private static isAsciiCelsiusUnit(text: string, index: number): boolean {
    return index > 0 && text[index - 1] === '\u00B0' && (text[index] === 'C' || text[index] === 'c');
  }

  private static protectedAsciiRunLang(text: string, start: number, end: number, run: string): string | undefined {
    if (TranssionTnNormalizer.isProtectedChemicalFormula(run)) {
      return 'en';
    }
    if (TranssionTnNormalizer.isChineseContextCode(text, start, end, run)) {
      return 'zh';
    }
    return undefined;
  }

  private static isProtectedChemicalFormula(run: string): boolean {
    return run === 'SO2' || run === 'CO2' || run === 'C6H12O6';
  }

  private static isChineseContextCode(text: string, start: number, end: number, run: string): boolean {
    const touchesChinese = (start > 0 && LitsTtsFrontend.isCjk(text[start - 1])) ||
      (end < text.length && LitsTtsFrontend.isCjk(text[end]));
    if (!touchesChinese) {
      return false;
    }
    let hasDigit = false;
    let upperCount = 0;
    let hasLower = false;
    for (let index = 0; index < run.length; index += 1) {
      const char = run[index];
      if (LitsTtsFrontend.isAsciiDigit(char)) {
        hasDigit = true;
      } else if (char >= 'A' && char <= 'Z') {
        upperCount += 1;
      } else if (char >= 'a' && char <= 'z') {
        hasLower = true;
      }
    }
    const followsPlateProvince = start > 0 && PLATE_PROVINCES.includes(text[start - 1]);
    const isPercentileCode = PERCENTILE_CODE_REGEX.test(run);
    return hasDigit && !hasLower && (upperCount >= 1 || followsPlateProvince || isPercentileCode);
  }
}

interface TnTextSegment {
  text: string;
  lang: string;
}

class LitsTtsFrontend {
  static encode(resources: LoadedPackage, text: string, language: string, languageContext: string): Array<number> {
    return LitsTtsFrontend.buildTextMetric(resources, text, language, languageContext).tokenIds;
  }

  static buildTextMetric(
    resources: LoadedPackage,
    text: string,
    language: string,
    languageContext: string,
    alreadyNormalized: boolean = false
  ): TextMetric {
    const tnText = alreadyNormalized ? text : TranssionTnNormalizer.normalize(resources, text, language, languageContext);
    const normalized = LitsTtsFrontend.normalizeText(tnText, languageContext).trim();
    if (normalized.length === 0) {
      throw new TextToSpeechException(TtsErrorCode.TEXT_LENGTH_INVALID, 'text must not be empty');
    }
    if (language === 'en-US' && LitsTtsFrontend.containsHanzi(normalized)) {
      throw new TextToSpeechException(
        TtsErrorCode.LANGUAGE_UNSUPPORTED,
        'en-US mode does not support Chinese input'
      );
    }

    const output: Array<string> = [];
    let index = 0;
    let previousPhonemeLanguage = '';
    while (index < normalized.length) {
      const char = normalized[index];
      if (LitsTtsFrontend.isWhitespace(char)) {
        LitsTtsFrontend.appendBoundary(output);
        index += 1;
        continue;
      }
      if (PUNCTUATION_SET.has(char)) {
        LitsTtsFrontend.appendPunctuation(output, char);
        previousPhonemeLanguage = 'boundary';
        index += 1;
        continue;
      }
      if (LitsTtsFrontend.isAsciiDigit(char)) {
        const end = LitsTtsFrontend.scanDigits(normalized, index);
        const digits = normalized.substring(index, end);
        if (languageContext === 'zh-en') {
          const chineseText = digits.split('').map((digit: string): string => {
            const mapped = CHINESE_DIGIT_TEXT_BY_CHAR.get(digit);
            if (mapped === undefined) {
              throw new TextToSpeechException(TtsErrorCode.RUNTIME_EXCEPTION, `unsupported digit: ${digit}`);
            }
            return mapped;
          }).join('');
          const syllables = LitsTtsFrontend.applyThirdToneSandhi(
            LitsTtsFrontend.hanziChunkToPinyin(resources, chineseText)
          );
          LitsTtsFrontend.appendChineseSyllables(
            output,
            resources,
            syllables,
            previousPhonemeLanguage === 'en' || previousPhonemeLanguage === 'boundary'
          );
          previousPhonemeLanguage = 'zh';
        } else {
          digits.split('').forEach((digit: string): void => {
            LitsTtsFrontend.appendBoundary(output);
            const word = ENGLISH_DIGIT_WORD_BY_CHAR.get(digit);
            const phones = word === undefined ? undefined : resources.cmudict.get(word);
            if (phones === undefined) {
              throw new TextToSpeechException(
                TtsErrorCode.RUNTIME_EXCEPTION,
                `english digit is not covered by cmudict.txt: ${digit}`
              );
            }
            const tokens = LitsTtsFrontend.arpabetToTokens(resources, phones);
            tokens.forEach((token: string): void => {
              output.push(token);
            });
          });
          LitsTtsFrontend.appendBoundary(output);
          previousPhonemeLanguage = 'en';
        }
        index = end;
        continue;
      }
      if (LitsTtsFrontend.isHanzi(char)) {
        const end = LitsTtsFrontend.scanHanziChunk(normalized, index);
        const syllables = LitsTtsFrontend.applyThirdToneSandhi(
          LitsTtsFrontend.hanziChunkToPinyin(resources, normalized.substring(index, end))
        );
        LitsTtsFrontend.appendChineseSyllables(
          output,
          resources,
          syllables,
          previousPhonemeLanguage === 'en' || previousPhonemeLanguage === 'boundary'
        );
        previousPhonemeLanguage = 'zh';
        index = end;
        continue;
      }
      if (LitsTtsFrontend.isEnglishLetter(char)) {
        const end = LitsTtsFrontend.scanEnglishWord(normalized, index);
        if (end < normalized.length && LitsTtsFrontend.isAsciiDigit(normalized[end])) {
          const candidate = normalized.substring(index, end + 1);
          const mapped = resources.pinyinToTokens.get(candidate.toLowerCase());
          if (mapped !== undefined) {
            while (output.length > 0 && output[output.length - 1] === '_') {
              output.pop();
            }
            mapped.forEach((token: string): void => {
              output.push(token);
            });
            previousPhonemeLanguage = 'zh';
            index = end + 1;
            continue;
          }
        }
        if (end <= index) {
          throw new TextToSpeechException(TtsErrorCode.RUNTIME_EXCEPTION, `unsupported frontend character: ${char}`);
        }
        LitsTtsFrontend.appendBoundary(output);
        const phones = LitsTtsFrontend.phonesForEnglishWord(resources, normalized.substring(index, end));
        const tokens = LitsTtsFrontend.arpabetToTokens(resources, phones);
        tokens.forEach((token: string): void => {
          output.push(token);
        });
        LitsTtsFrontend.appendBoundary(output);
        previousPhonemeLanguage = 'en';
        index = end;
        continue;
      }
      LitsTtsFrontend.appendPunctuation(output, ',');
      previousPhonemeLanguage = 'boundary';
      index += 1;
    }

    while (output.length > 0 && output[output.length - 1] === '_') {
      output.pop();
    }

    const ids = output.map((token: string): number => {
      const id = resources.symbolToId.get(token);
      if (id === undefined) {
        throw new TextToSpeechException(
          TtsErrorCode.RUNTIME_EXCEPTION,
          `frontend token is not in zh_en_symbols.json: ${token}`
        );
      }
      return id;
    });
    const modelTokenIds = ids;
    return {
      rawText: text,
      tnText,
      cleanedText: output.join(' '),
      cleanedTokenLength: ids.length,
      modelTokenLength: modelTokenIds.length,
      tokenIds: modelTokenIds,
      tokenIdHead: modelTokenIds.slice(0, Math.min(24, modelTokenIds.length)),
      tokenIdTail: modelTokenIds.slice(Math.max(0, modelTokenIds.length - 24), modelTokenIds.length)
    };
  }

  static splitForStreaming(
    resources: LoadedPackage,
    text: string,
    language: string = 'zh-en',
    languageContext: string = 'zh-en',
    wordsPerSegment: number = DEFAULT_WORDS_PER_STREAMING_SEGMENT
  ): Array<string> {
    const tnText = TranssionTnNormalizer.normalize(resources, text, language, languageContext);
    const normalized = LitsTtsFrontend.normalizeText(tnText, languageContext).trim();
    if (normalized.length === 0) {
      return [];
    }
    const segments: Array<string> = [];
    let current = '';
    let index = 0;
    while (index < normalized.length) {
      const char = normalized[index];
      if (LitsTtsFrontend.isWhitespace(char)) {
        if (current.length > 0 && current[current.length - 1] !== ' ') {
          current += ' ';
        }
        index += 1;
        continue;
      }
      current += char;
      if (LitsTtsFrontend.shouldSplitAfterPunctuation(normalized, index, current, wordsPerSegment)) {
        while (
          index + 1 < normalized.length &&
          LitsTtsFrontend.isAttachedSentenceSuffix(normalized[index + 1])
        ) {
          index += 1;
          current += normalized[index];
        }
        while (
          index + 1 < normalized.length &&
          LitsTtsFrontend.isSentenceEndPunctuation(normalized[index + 1]) &&
          normalized[index + 1] !== ','
        ) {
          index += 1;
          current += normalized[index];
        }
        current = LitsTtsFrontend.flushSegment(segments, current);
      }
      index += 1;
    }
    current = LitsTtsFrontend.flushSegment(segments, current);
    return segments.length > 0 ? segments : [normalized];
  }

  static normalizeText(text: string, languageContext: string = DEFAULT_LANGUAGE_CONTEXT): string {
    let normalized = text
      .replace(/\.\.\./g, '\u2026')
      .replace(/\u22EF/g, '\u2026')
      .replace(/\u00B7\u00B7\u00B7/g, '\u2026')
      .replace(/\u30FB\u30FB\u30FB/g, '\u2026');
    let output = '';
    for (let index = 0; index < normalized.length; index += 1) {
      const code = normalized.charCodeAt(index);
      if (LitsTtsFrontend.isHighSurrogate(code)) {
        if (index + 1 < normalized.length && LitsTtsFrontend.isLowSurrogate(normalized.charCodeAt(index + 1))) {
          index += 1;
        }
        output += ',';
        continue;
      }
      if (LitsTtsFrontend.isLowSurrogate(code) || LitsTtsFrontend.isIgnoredFormatCode(code)) {
        continue;
      }
      const char = normalized[index];
      output += LitsTtsFrontend.normalizeFrontendChar(char, languageContext);
    }
    return output;
  }

  private static normalizeFrontendChar(char: string, languageContext: string): string {
    const fullwidthMapped = FULLWIDTH_PUNCTUATION.get(char);
    if (fullwidthMapped !== undefined) {
      return fullwidthMapped;
    }
    if (LitsTtsFrontend.isSupportedFrontendChar(char)) {
      return char;
    }
    const shouldReadAsChinese = languageContext !== 'en-US';
    if (shouldReadAsChinese) {
      const zhReplacement = ZH_EN_FRONTEND_CHAR_REPLACEMENTS.get(char) ?? ZH_EN_ASCII_SYMBOL_TEXT.get(char);
      if (zhReplacement !== undefined) {
        return zhReplacement;
      }
    }
    const safePunctuation = SYMBOL_TO_SAFE_PUNCTUATION.get(char);
    if (safePunctuation !== undefined) {
      return safePunctuation;
    }
    if (LitsTtsFrontend.isAsciiSymbol(char) || LitsTtsFrontend.isUnicodeSymbolLike(char)) {
      return ',';
    }
    return ',';
  }

  private static shouldSplitAfterPunctuation(
    text: string,
    index: number,
    current: string,
    minWordsForWeakSplit: number
  ): boolean {
    const char = text[index];
    if (!LitsTtsFrontend.isSentenceEndPunctuation(char)) {
      return false;
    }
    if (LitsTtsFrontend.isPunctuationInsideTechnicalToken(text, index)) {
      return false;
    }
    if (LitsTtsFrontend.wouldCreateShortSymbolSegment(current)) {
      return false;
    }
    if (char === ',' && !LitsTtsFrontend.shouldSplitAfterWeakComma(text, index, current, minWordsForWeakSplit)) {
      return false;
    }
    if (char === '.' && !LitsTtsFrontend.shouldSplitAfterPeriod(text, index)) {
      return false;
    }
    return true;
  }

  private static shouldSplitAfterPeriod(text: string, index: number): boolean {
    const prev = LitsTtsFrontend.previousNonSpace(text, index - 1);
    const next = LitsTtsFrontend.nextNonSpace(text, index + 1);
    if (
      prev !== undefined &&
      next !== undefined &&
      LitsTtsFrontend.isAsciiDigit(prev) &&
      LitsTtsFrontend.isAsciiDigit(next)
    ) {
      return false;
    }
    if (LitsTtsFrontend.isUrlOrEmailPeriod(text, index)) {
      return false;
    }
    if (LitsTtsFrontend.isEnglishAbbreviationPeriod(text, index)) {
      return false;
    }
    if (prev !== undefined && LitsTtsFrontend.isHanzi(prev)) {
      return true;
    }
    return LitsTtsFrontend.isBoundaryAfterSentencePunctuation(text, index);
  }

  private static shouldSplitAfterWeakComma(
    text: string,
    index: number,
    current: string,
    minWordsForWeakSplit: number
  ): boolean {
    const prev = LitsTtsFrontend.previousNonSpace(text, index - 1);
    const next = LitsTtsFrontend.nextNonSpace(text, index + 1);
    if (
      prev !== undefined &&
      next !== undefined &&
      LitsTtsFrontend.isAsciiDigit(prev) &&
      LitsTtsFrontend.isAsciiDigit(next)
    ) {
      return false;
    }
    const trimmed = current.trim();
    if (trimmed.length < MIN_WEAK_PUNCTUATION_SEGMENT_CHARS) {
      return false;
    }
    return LitsTtsFrontend.countRoughWords(trimmed) >= minWordsForWeakSplit || LitsTtsFrontend.containsHanzi(trimmed);
  }

  private static isBoundaryAfterSentencePunctuation(text: string, index: number): boolean {
    let cursor = index + 1;
    while (cursor < text.length && LitsTtsFrontend.isAttachedSentenceSuffix(text[cursor])) {
      cursor += 1;
    }
    return cursor >= text.length || LitsTtsFrontend.isWhitespace(text[cursor]) || LitsTtsFrontend.isHanzi(text[cursor]);
  }

  private static isEnglishAbbreviationPeriod(text: string, index: number): boolean {
    const token = LitsTtsFrontend.asciiTokenBefore(text, index).toLowerCase();
    if (ENGLISH_ABBREVIATIONS.has(token)) {
      return true;
    }
    if (token.length === 1 && LitsTtsFrontend.isLowercaseAsciiLetter(token)) {
      return true;
    }
    const prefix = text.substring(0, index + 1);
    return ACRONYM_AT_END_REGEX.test(prefix);
  }

  private static isUrlOrEmailPeriod(text: string, index: number): boolean {
    const start = LitsTtsFrontend.scanNonSpaceTokenStart(text, index);
    const end = LitsTtsFrontend.scanNonSpaceTokenEnd(text, index);
    const token = text.substring(start, end);
    const next = index + 1 < text.length ? text[index + 1] : undefined;
    const nextIsAsciiAlnum = next !== undefined && LitsTtsFrontend.isAsciiAlnum(next);
    const dotCount = token.split('.').length - 1;
    return (
      nextIsAsciiAlnum &&
      (token.includes('://') || token.includes('@') || token.toLowerCase().startsWith('www.'))
    ) || (
      index + 1 < text.length &&
      next !== undefined &&
      LitsTtsFrontend.isAsciiAlnum(next) &&
      dotCount >= 1
    );
  }

  private static isPunctuationInsideTechnicalToken(text: string, index: number): boolean {
    const char = text[index];
    const prev = index > 0 ? text[index - 1] : undefined;
    const next = index + 1 < text.length ? text[index + 1] : undefined;
    if (prev === undefined || next === undefined) {
      return false;
    }
    if (LitsTtsFrontend.isAsciiDigit(prev) && LitsTtsFrontend.isAsciiDigit(next)) {
      return true;
    }
    if (
      (char === ':' || char === '/' || char === '?' || char === '=' || char === '&') &&
      LitsTtsFrontend.hasAsciiNear(text, index)
    ) {
      return true;
    }
    if (
      (char === '.' || char === '-' || char === '_' || char === '#') &&
      LitsTtsFrontend.isAsciiAlnum(next)
    ) {
      return true;
    }
    return false;
  }

  private static hasAsciiNear(text: string, index: number): boolean {
    const start = LitsTtsFrontend.scanNonSpaceTokenStart(text, index);
    const end = LitsTtsFrontend.scanNonSpaceTokenEnd(text, index);
    for (let cursor = start; cursor < end; cursor += 1) {
      if (LitsTtsFrontend.isAsciiAlnum(text[cursor])) {
        return true;
      }
    }
    return false;
  }

  private static wouldCreateShortSymbolSegment(current: string): boolean {
    const trimmed = current.trim();
    if (trimmed.length >= MIN_SHORT_SYMBOL_SEGMENT_CHARS) {
      return false;
    }
    if (LitsTtsFrontend.containsHanzi(trimmed) && !LitsTtsFrontend.containsAsciiAlnum(trimmed)) {
      return false;
    }
    return true;
  }

  private static asciiTokenBefore(text: string, endExclusive: number): string {
    let cursor = endExclusive - 1;
    while (cursor >= 0 && LitsTtsFrontend.isEnglishLetter(text[cursor])) {
      cursor -= 1;
    }
    return text.substring(cursor + 1, endExclusive);
  }

  private static scanNonSpaceTokenStart(text: string, index: number): number {
    let cursor = index;
    while (cursor > 0 && !LitsTtsFrontend.isWhitespace(text[cursor - 1])) {
      cursor -= 1;
    }
    return cursor;
  }

  private static scanNonSpaceTokenEnd(text: string, index: number): number {
    let cursor = index + 1;
    while (cursor < text.length && !LitsTtsFrontend.isWhitespace(text[cursor])) {
      cursor += 1;
    }
    return cursor;
  }

  private static previousNonSpace(text: string, start: number): string | undefined {
    let cursor = start;
    while (cursor >= 0) {
      if (!LitsTtsFrontend.isWhitespace(text[cursor])) {
        return text[cursor];
      }
      cursor -= 1;
    }
    return undefined;
  }

  private static nextNonSpace(text: string, start: number): string | undefined {
    let cursor = start;
    while (cursor < text.length) {
      if (!LitsTtsFrontend.isWhitespace(text[cursor])) {
        return text[cursor];
      }
      cursor += 1;
    }
    return undefined;
  }

  private static countRoughWords(text: string): number {
    let count = 0;
    let inAsciiWord = false;
    for (let index = 0; index < text.length; index += 1) {
      const char = text[index];
      if (LitsTtsFrontend.isHanzi(char)) {
        count += 1;
        inAsciiWord = false;
      } else if (LitsTtsFrontend.isAsciiAlnum(char)) {
        if (!inAsciiWord) {
          count += 1;
          inAsciiWord = true;
        }
      } else {
        inAsciiWord = false;
      }
    }
    return count;
  }

  private static flushSegment(segments: Array<string>, current: string): string {
    const segment = current.trim();
    if (segment.length > 0) {
      segments.push(segment);
    }
    return '';
  }

  private static containsHanzi(text: string): boolean {
    for (let index = 0; index < text.length; index += 1) {
      if (LitsTtsFrontend.isHanzi(text[index])) {
        return true;
      }
    }
    return false;
  }

  private static hanziChunkToPinyin(resources: LoadedPackage, text: string): Array<string> {
    const output: Array<string> = [];
    let index = 0;
    while (index < text.length) {
      const word = LitsTtsFrontend.longestWord(resources, text, index);
      const syllables = LitsTtsFrontend.lexiconPinyinForWord(resources, word);
      syllables.forEach((syllable: string): void => {
        output.push(syllable);
      });
      index += word.length;
    }
    return output;
  }

  private static longestWord(resources: LoadedPackage, text: string, start: number): string {
    const maxLength = Math.min(resources.maxWordLength, text.length - start);
    for (let length = maxLength; length >= 2; length -= 1) {
      const candidate = text.substring(start, start + length);
      if (resources.wordPinyin.has(candidate)) {
        return candidate;
      }
    }
    return text[start];
  }

  private static lexiconPinyinForWord(resources: LoadedPackage, word: string): Array<string> {
    const direct = resources.wordPinyin.get(word);
    if (direct !== undefined && !resources.polyphonicWords.has(word)) {
      const directTokens = LitsTtsFrontend.normalizeLexiconPinyin(direct);
      if (directTokens.length > 0) {
        return directTokens;
      }
    }
    const output: Array<string> = [];
    word.split('').forEach((char: string): void => {
      const pinyin = resources.wordPinyin.get(char);
      if (pinyin === undefined) {
        output.push(',');
        return;
      }
      const syllables = LitsTtsFrontend.normalizeLexiconPinyin(pinyin);
      if (syllables.length === 0) {
        output.push(',');
        return;
      }
      syllables.forEach((syllable: string): void => {
        output.push(syllable);
      });
    });
    return output;
  }

  private static normalizeLexiconPinyin(text: string): Array<string> {
    return splitByWhitespace(text.trim())
      .map((token: string): string => token
        .replace(/ü/g, 'v')
        .replace(/ǖ/g, 'v')
        .replace(/ǘ/g, 'v')
        .replace(/ǚ/g, 'v')
        .replace(/ǜ/g, 'v'))
      .filter((token: string): boolean => PINYIN_SYLLABLE_REGEX.test(token));
  }

  private static applyThirdToneSandhi(tokens: Array<string>): Array<string> {
    const output = tokens.slice();
    const pinyinIndices: Array<number> = [];
    for (let index = 0; index < output.length; index += 1) {
      if (PINYIN_SYLLABLE_REGEX.test(output[index])) {
        pinyinIndices.push(index);
      }
    }
    for (let index = 0; index + 1 < pinyinIndices.length; index += 1) {
      const current = pinyinIndices[index];
      const next = pinyinIndices[index + 1];
      if (output[current].endsWith('3') && output[next].endsWith('3')) {
        output[current] = output[current].substring(0, output[current].length - 1) + '2';
      }
    }
    return output;
  }

  private static phonesForEnglishWord(resources: LoadedPackage, rawWord: string): Array<string> {
    const normalized = rawWord.toUpperCase();
    const direct = resources.cmudict.get(normalized);
    if (direct !== undefined) {
      return direct;
    }
    if (normalized.indexOf('-') >= 0) {
      const output: Array<string> = [];
      normalized.split('-').forEach((part: string): void => {
        if (part.length === 0) {
          return;
        }
        const mapped = resources.cmudict.get(part) ?? LitsTtsFrontend.spellEnglishWord(resources, part);
        if (mapped.length === 0) {
          return;
        }
        mapped.forEach((phone: string): void => {
          output.push(phone);
        });
      });
      if (output.length > 0) {
        return output;
      }
    }
    const spelled = LitsTtsFrontend.spellEnglishWord(resources, normalized);
    if (spelled.length > 0) {
      return spelled;
    }
    return [];
  }

  private static spellEnglishWord(resources: LoadedPackage, word: string): Array<string> {
    const output: Array<string> = [];
    for (let index = 0; index < word.length; index += 1) {
      const char = word[index];
      if (!LitsTtsFrontend.isEnglishLetter(char)) {
        continue;
      }
      const phones = resources.cmudict.get(char);
      if (phones === undefined) {
        return [];
      }
      phones.forEach((phone: string): void => {
        output.push(phone);
      });
    }
    return output;
  }

  private static arpabetToTokens(resources: LoadedPackage, phones: Array<string>): Array<string> {
    const rawTokens: Array<string> = [];
    phones.forEach((phone: string): void => {
      const tokens = resources.arpabetToTokens.get(phone);
      if (tokens === undefined) {
        return;
      }
      tokens.forEach((token: string): void => {
        rawTokens.push(token);
      });
    });
    return LitsTtsFrontend.mergeEnglishTokens(rawTokens);
  }

  private static mergeEnglishTokens(tokens: Array<string>): Array<string> {
    const output: Array<string> = [];
    let index = 0;
    while (index < tokens.length) {
      let merged = false;
      ENGLISH_MERGE_RULES.forEach((rule: MergeRule): void => {
        if (merged) {
          return;
        }
        if (rule.pair.length > tokens.length - index) {
          return;
        }
        let matched = true;
        for (let pairIndex = 0; pairIndex < rule.pair.length; pairIndex += 1) {
          if (tokens[index + pairIndex] !== rule.pair[pairIndex]) {
            matched = false;
            break;
          }
        }
        if (matched) {
          output.push(rule.replacement);
          index += rule.pair.length;
          merged = true;
        }
      });
      if (!merged) {
        output.push(tokens[index]);
        index += 1;
      }
    }
    return output;
  }

  private static appendBoundary(output: Array<string>): void {
    if (output.length > 0 && output[output.length - 1] !== '_') {
      output.push('_');
    }
  }

  private static appendPunctuation(output: Array<string>, token: string): void {
    LitsTtsFrontend.appendBoundary(output);
    output.push(token);
    LitsTtsFrontend.appendBoundary(output);
  }

  private static appendChineseSyllables(
    output: Array<string>,
    resources: LoadedPackage,
    syllables: Array<string>,
    preserveLeadingBoundary: boolean = false
  ): void {
    if (!preserveLeadingBoundary) {
      while (output.length > 0 && output[output.length - 1] === '_') {
        output.pop();
      }
    }
    syllables.forEach((syllable: string): void => {
      if (syllable === ',') {
        LitsTtsFrontend.appendPunctuation(output, ',');
        return;
      }
      const tokens = resources.pinyinToTokens.get(syllable);
      if (tokens === undefined) {
        LitsTtsFrontend.appendPunctuation(output, ',');
        return;
      }
      tokens.forEach((token: string): void => {
        output.push(token);
      });
    });
  }

  private static intersperseZero(ids: Array<number>): Array<number> {
    const output: Array<number> = [0];
    ids.forEach((id: number): void => {
      output.push(id);
      output.push(0);
    });
    return output;
  }

  private static scanDigits(text: string, start: number): number {
    let index = start;
    while (index < text.length && LitsTtsFrontend.isAsciiDigit(text[index])) {
      index += 1;
    }
    return index;
  }

  private static scanHanziChunk(text: string, start: number): number {
    let index = start;
    while (index < text.length && LitsTtsFrontend.isHanzi(text[index])) {
      index += 1;
    }
    return index;
  }

  private static scanEnglishWord(text: string, start: number): number {
    let index = start;
    while (index < text.length && LitsTtsFrontend.isEnglishLetter(text[index])) {
      index += 1;
    }
    while (
      index + 1 < text.length &&
      (text[index] === '\'' || text[index] === '-') &&
      LitsTtsFrontend.isEnglishLetter(text[index + 1])
    ) {
      index += 1;
      while (index < text.length && LitsTtsFrontend.isEnglishLetter(text[index])) {
        index += 1;
      }
    }
    return index;
  }

  static isWhitespace(char: string): boolean {
    return char === ' ' || char === '\t' || char === '\n' || char === '\r';
  }

  private static isSupportedFrontendChar(char: string): boolean {
    return LitsTtsFrontend.isWhitespace(char) ||
      PUNCTUATION_SET.has(char) ||
      LitsTtsFrontend.isAsciiDigit(char) ||
      LitsTtsFrontend.isEnglishLetter(char) ||
      LitsTtsFrontend.isHanzi(char);
  }

  private static isAsciiSymbol(char: string): boolean {
    const code = char.charCodeAt(0);
    return code >= 0x21 && code <= 0x7e &&
      !LitsTtsFrontend.isAsciiDigit(char) &&
      !LitsTtsFrontend.isEnglishLetter(char);
  }

  private static isUnicodeSymbolLike(char: string): boolean {
    const code = char.charCodeAt(0);
    return (code >= 0x2000 && code <= 0x206f) ||
      (code >= 0x20a0 && code <= 0x27bf) ||
      (code >= 0x2b00 && code <= 0x2bff) ||
      (code >= 0x3000 && code <= 0x303f) ||
      (code >= 0xfe10 && code <= 0xfe6f) ||
      (code >= 0xff00 && code <= 0xffef);
  }

  private static isHighSurrogate(code: number): boolean {
    return code >= 0xd800 && code <= 0xdbff;
  }

  private static isLowSurrogate(code: number): boolean {
    return code >= 0xdc00 && code <= 0xdfff;
  }

  private static isIgnoredFormatCode(code: number): boolean {
    return code === 0x200c ||
      code === 0x200d ||
      code === 0x20e3 ||
      code === 0xfe0e ||
      code === 0xfe0f;
  }

  private static isHanzi(char: string): boolean {
    const code = char.charCodeAt(0);
    return code >= 0x4e00 && code <= 0x9fff;
  }

  static isEnglishLetter(char: string): boolean {
    const code = char.charCodeAt(0);
    return (code >= 65 && code <= 90) || (code >= 97 && code <= 122);
  }

  private static isLowercaseAsciiLetter(char: string): boolean {
    const code = char.charCodeAt(0);
    return code >= 97 && code <= 122;
  }

  static isAsciiDigit(char: string): boolean {
    const code = char.charCodeAt(0);
    return code >= 48 && code <= 57;
  }

  private static isAsciiAlnum(char: string): boolean {
    return LitsTtsFrontend.isEnglishLetter(char) || LitsTtsFrontend.isAsciiDigit(char);
  }

  static isCjk(char: string): boolean {
    const code = char.charCodeAt(0);
    return code >= 0x4e00 && code <= 0x9fff;
  }

  private static containsAsciiAlnum(text: string): boolean {
    for (let index = 0; index < text.length; index += 1) {
      if (LitsTtsFrontend.isAsciiAlnum(text[index])) {
        return true;
      }
    }
    return false;
  }

  private static isSentenceEndPunctuation(char: string): boolean {
    return SENTENCE_END_PUNCTUATION.has(char);
  }

  private static isAttachedSentenceSuffix(char: string): boolean {
    return ATTACHED_SENTENCE_SUFFIX.has(char);
  }
}

class AudioTransforms {
  static apply(source: ArrayBuffer, params: SpeakParams): ArrayBuffer {
    const pitch = params.pitch ?? 1.0;
    const speed = params.speed ?? 1.0;
    const volume = params.volume ?? 1.0;
    if (pitch === 1.0 && speed === 1.0 && volume === 1.0) {
      return source;
    }
    let samples = new Int16Array(source.slice(0));
    if (pitch !== 1.0) {
      samples = AudioTransforms.applyPitch(samples, clampNumber(pitch, 0.5, 2.0));
    }
    if (speed !== 1.0) {
      samples = AudioTransforms.applySpeed(samples, clampNumber(speed, 0.5, 2.0));
    }
    if (volume !== 1.0) {
      samples = AudioTransforms.applyVolume(samples, clampNumber(volume, 0.0, 2.0));
    }
    return samples.buffer as ArrayBuffer;
  }

  private static applyPitch(input: Int16Array, pitch: number): Int16Array {
    if (input.length === 0) {
      return input;
    }
    const shifted = AudioTransforms.resampleToLength(input, Math.max(1, Math.round(input.length / pitch)));
    return AudioTransforms.resampleToLength(shifted, input.length);
  }

  private static applySpeed(input: Int16Array, speed: number): Int16Array {
    if (input.length === 0) {
      return input;
    }
    return AudioTransforms.resampleToLength(input, Math.max(1, Math.round(input.length / speed)));
  }

  private static applyVolume(input: Int16Array, volume: number): Int16Array {
    const output = new Int16Array(input.length);
    for (let index = 0; index < input.length; index += 1) {
      const scaled = Math.round(input[index] * volume);
      output[index] = clampInt16(scaled);
    }
    return output;
  }

  private static resampleToLength(input: Int16Array, targetLength: number): Int16Array {
    if (input.length === targetLength) {
      return new Int16Array(input.slice().buffer);
    }
    if (targetLength <= 1) {
      return new Int16Array([input[0]]);
    }
    const output = new Int16Array(targetLength);
    const ratio = (input.length - 1) / (targetLength - 1);
    for (let index = 0; index < targetLength; index += 1) {
      const position = index * ratio;
      const left = Math.min(input.length - 1, Math.floor(position));
      const right = Math.min(input.length - 1, left + 1);
      const fraction = position - left;
      const value = input[left] + Math.round((input[right] - input[left]) * fraction);
      output[index] = clampInt16(value);
    }
    return output;
  }
}

class HarmonyPcmPlayer {
  private renderer: audio.AudioRenderer | undefined;
  private stopped: boolean = false;

  async play(pcm: ArrayBuffer, sampleRate: number, soundChannel: number | undefined): Promise<void> {
    await this.begin(sampleRate, soundChannel);
    await this.write(pcm);
    await this.finish();
  }

  async playStreaming(
    sampleRate: number,
    soundChannel: number | undefined,
    queueCapacity: number,
    producer: (chunkWriter: (chunk: ArrayBuffer) => Promise<void>) => Promise<void>,
    onSynthesisComplete: () => void
  ): Promise<void> {
    this.stopped = false;
    await this.releaseRenderer();
    const renderer = await this.createRenderer(sampleRate, soundChannel);
    this.renderer = renderer;
    const queue = new PcmChunkQueue(queueCapacity);
    let queuedChunks = 0;
    let producerError: string | undefined = undefined;
    let playbackError: string | undefined = undefined;

    const playbackPromise = (async (): Promise<void> => {
      try {
        await queue.waitForPrebuffer(STREAMING_PREBUFFER_CHUNKS);
        if (this.stopped) {
          return;
        }
        await renderer.start();
        while (!this.stopped) {
          const next = await queue.take();
          if (next.done) {
            return;
          }
          if (next.chunk !== undefined) {
            await this.writeToRenderer(renderer, next.chunk);
          }
        }
      } catch (error) {
        playbackError = formatError(error);
        this.stopped = true;
        queue.close();
      }
    })();

    try {
      try {
        await producer(async (chunk: ArrayBuffer): Promise<void> => {
          if (this.stopped) {
            return;
          }
          queuedChunks += 1;
          await queue.put(copyArrayBuffer(chunk, 0, chunk.byteLength));
        });
        onSynthesisComplete();
      } catch (error) {
        producerError = formatError(error);
        this.stopped = true;
      } finally {
        queue.close();
      }
      await playbackPromise;
      if (producerError !== undefined) {
        throw new TextToSpeechException(TtsErrorCode.RUNTIME_EXCEPTION, producerError);
      }
      if (playbackError !== undefined) {
        throw new TextToSpeechException(TtsErrorCode.RUNTIME_EXCEPTION, playbackError);
      }
      if (!this.stopped && queuedChunks > 0) {
        await renderer.drain();
      }
    } finally {
      await this.releaseRenderer();
    }
  }

  async begin(sampleRate: number, soundChannel: number | undefined): Promise<void> {
    this.stopped = false;
    await this.releaseRenderer();
    const renderer = await this.createRenderer(sampleRate, soundChannel);
    this.renderer = renderer;
    await renderer.start();
  }

  async write(pcm: ArrayBuffer): Promise<void> {
    const renderer = this.renderer;
    if (renderer === undefined || pcm.byteLength === 0) {
      return;
    }
    let offset = 0;
    while (offset < pcm.byteLength && !this.stopped) {
      const written = await this.writeToRenderer(renderer, copyArrayBuffer(pcm, offset, Math.min(AUDIO_CHUNK_BYTES, pcm.byteLength - offset)));
      if (written <= 0) {
        return;
      }
      offset += written;
    }
  }

  async finish(): Promise<void> {
    const renderer = this.renderer;
    if (renderer === undefined) {
      return;
    }
    try {
      if (this.stopped) {
        try {
          await renderer.flush();
        } catch (_error) {
        }
        return;
      }
      await renderer.drain();
    } finally {
      await this.releaseRenderer();
    }
  }

  async stop(): Promise<void> {
    this.stopped = true;
    await this.releaseRenderer();
  }

  private async writeToRenderer(renderer: audio.AudioRenderer, pcm: ArrayBuffer): Promise<number> {
    let offset = 0;
    while (offset < pcm.byteLength && !this.stopped) {
      const length = Math.min(AUDIO_CHUNK_BYTES, pcm.byteLength - offset);
      const chunk = copyArrayBuffer(pcm, offset, length);
      await renderer.write(chunk);
      offset += length;
    }
    return offset;
  }

  private async createRenderer(sampleRate: number, soundChannel: number | undefined): Promise<audio.AudioRenderer> {
    const options: audio.AudioRendererOptions = {
      streamInfo: {
        samplingRate: sampleRate,
        channels: audio.AudioChannel.CHANNEL_1,
        sampleFormat: audio.AudioSampleFormat.SAMPLE_FORMAT_S16LE,
        encodingType: audio.AudioEncodingType.ENCODING_TYPE_RAW
      },
      rendererInfo: {
        usage: resolveHarmonyStreamUsage(soundChannel),
        rendererFlags: 0
      }
    };
    return audio.createAudioRenderer(options);
  }

  private async releaseRenderer(): Promise<void> {
    const renderer = this.renderer;
    this.renderer = undefined;
    if (renderer === undefined) {
      return;
    }
    try {
      if (renderer.state === audio.AudioState.STATE_RUNNING) {
        await renderer.stop();
      }
    } catch (_error) {
    }
    try {
      await renderer.release();
    } catch (_error) {
    }
  }
}

class PcmChunkQueue {
  private readonly capacity: number;
  private readonly chunks: Array<ArrayBuffer> = [];
  private closed: boolean = false;
  private waitingTakers: Array<(result: PcmQueueTakeResult) => void> = [];
  private waitingPutters: Array<() => void> = [];
  private prebufferWaiters: Array<() => void> = [];

  constructor(capacity: number) {
    this.capacity = clampInt(Math.round(capacity), 1, MAX_PCM_QUEUE_CAPACITY_VALUE);
  }

  async put(chunk: ArrayBuffer): Promise<void> {
    while (!this.closed && this.chunks.length >= this.capacity) {
      await new Promise<void>((resolve: () => void): void => {
        this.waitingPutters.push(resolve);
      });
    }
    if (this.closed) {
      return;
    }
    const taker = this.waitingTakers.shift();
    if (taker !== undefined) {
      taker({ chunk, done: false });
      return;
    }
    this.chunks.push(chunk);
    this.notifyPrebufferWaiters();
  }

  async take(): Promise<PcmQueueTakeResult> {
    const chunk = this.chunks.shift();
    if (chunk !== undefined) {
      this.notifyPutters();
      return { chunk, done: false };
    }
    if (this.closed) {
      return { done: true };
    }
    return new Promise<PcmQueueTakeResult>((resolve: (result: PcmQueueTakeResult) => void): void => {
      this.waitingTakers.push(resolve);
    });
  }

  async waitForPrebuffer(targetChunks: number): Promise<void> {
    const target = Math.min(Math.max(1, targetChunks), this.capacity);
    while (!this.closed && this.chunks.length < target) {
      await new Promise<void>((resolve: () => void): void => {
        this.prebufferWaiters.push(resolve);
      });
    }
  }

  close(): void {
    this.closed = true;
    this.waitingTakers.splice(0).forEach((resolve: (result: PcmQueueTakeResult) => void): void => {
      resolve({ done: true });
    });
    this.notifyPutters();
    this.notifyPrebufferWaiters();
  }

  private notifyPutters(): void {
    this.waitingPutters.splice(0).forEach((resolve: () => void): void => resolve());
  }

  private notifyPrebufferWaiters(): void {
    this.prebufferWaiters.splice(0).forEach((resolve: () => void): void => resolve());
  }
}

class EngineRegistry {
  private static activeEngines: Set<TextToSpeechEngineImpl> = new Set<TextToSpeechEngineImpl>();

  static hasActiveEngines(): boolean {
    return EngineRegistry.activeEngines.size > 0;
  }

  static createEngine(params: CreateEngineParams, workPath: string | undefined): TextToSpeechEngine {
    if ((params.modelLoadOnCreate ?? true) === false) {
      throw new TextToSpeechException(
        TtsErrorCode.CREATE_ENGINE_FAILED,
        'modelLoadOnCreate=false is not supported'
      );
    }
    if (EngineRegistry.activeEngines.size >= MAX_ENGINE_COUNT) {
      throw new TextToSpeechException(TtsErrorCode.ENGINE_LIMIT_REACHED, 'engine instance limit reached');
    }
    EngineRegistry.validateMode(params.mode);
    EngineRegistry.validateLanguage(params.language);
    EngineRegistry.validateLocate(params.locate ?? 'CN');
    if (params.engineName !== undefined && params.engineName.trim().length === 0) {
      throw new TextToSpeechException(TtsErrorCode.CREATE_ENGINE_FAILED, 'engineName must not be blank');
    }
    const speaker = EngineRegistry.resolveVoice(params.voiceId);
    try {
      const engine = new TextToSpeechEngineImpl(params, speaker, workPath, (): void => {
        EngineRegistry.activeEngines.delete(engine);
      });
      EngineRegistry.activeEngines.add(engine);
      return engine;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'failed to create TTS engine';
      throw new TextToSpeechException(TtsErrorCode.CREATE_ENGINE_FAILED, message);
    }
  }

  static listVoices(params: VoiceQuery): Array<VoiceInfo> {
    if (params.requestId.trim().length === 0) {
      throw new TextToSpeechException(TtsErrorCode.RUNTIME_EXCEPTION, 'requestId must not be blank');
    }
    EngineRegistry.validateMode(params.mode);
    if (params.language !== undefined) {
      EngineRegistry.validateLanguage(params.language);
    }
    const voices: Array<VoiceInfo> = [];
    SUPPORTED_LANGUAGES.forEach((language: string): void => {
      VOICES.forEach((speaker: RegisteredVoice): void => {
        voices.push({
          language,
          voiceId: speaker.voiceId,
          gender: speaker.gender,
          description: speaker.description
        });
      });
    });
    return voices.filter((voice: VoiceInfo): boolean => params.language === undefined || voice.language === params.language);
  }

  private static resolveVoice(voiceId: string): RegisteredVoice {
    const matched = VOICES.find((item: RegisteredVoice): boolean => item.voiceId === voiceId);
    if (matched === undefined) {
      throw new TextToSpeechException(TtsErrorCode.VOICE_UNSUPPORTED, 'voiceId is not supported');
    }
    return matched;
  }

  private static validateMode(mode: RunMode): void {
    if (mode !== RunMode.OFFLINE) {
      throw new TextToSpeechException(TtsErrorCode.CREATE_ENGINE_FAILED, 'only OFFLINE mode is supported');
    }
  }

  private static validateLocate(locate: string): void {
    if (locate.trim().length === 0) {
      throw new TextToSpeechException(TtsErrorCode.CREATE_ENGINE_FAILED, 'locate must not be blank');
    }
  }

  private static validateLanguage(language: string): void {
    if (!SUPPORTED_LANGUAGE_SET.has(language)) {
      throw new TextToSpeechException(TtsErrorCode.LANGUAGE_UNSUPPORTED, 'language is not supported');
    }
  }
}

export class TextToSpeechEngineImpl implements TextToSpeechEngine {
  private readonly engineParams: CreateEngineParams;
  private readonly voice: RegisteredVoice;
  private readonly modelPackageDir: string;
  private readonly modelPackage: LoadedPackage;
  private readonly nativeRuntime: object;
  private readonly onRelease: () => void;
  private readonly player: HarmonyPcmPlayer = new HarmonyPcmPlayer();
  private readonly seenRequestIds: Set<string> = new Set<string>();

  private listener: SpeakListener | undefined;
  private queue: Array<SynthesisTask> = [];
  private currentTask: SynthesisTask | undefined;
  private processing: boolean = false;
  private destroyed: boolean = false;
  private released: boolean = false;

  constructor(engineParams: CreateEngineParams, voice: RegisteredVoice, workPath: string | undefined, onRelease: () => void) {
    this.engineParams = {
      language: engineParams.language,
      mode: engineParams.mode,
      voiceId: engineParams.voiceId,
      locate: engineParams.locate ?? 'CN',
      engineName: engineParams.engineName,
      extraParams: engineParams.extraParams ?? {},
      modelLoadOnCreate: engineParams.modelLoadOnCreate ?? true
    };
    this.voice = voice;
    this.onRelease = onRelease;
    this.modelPackageDir = resolveModelPackageDir(this.engineParams.extraParams, workPath);
    this.modelPackage = FrontendResources.load(this.modelPackageDir);
    const runtimeChunkSize = resolveIntegerExtraParam(
      this.engineParams.extraParams,
      ['streamingChunkSize', 'streamingFirstChunkSize'],
      this.modelPackage.manifest.streamingChunkSize,
      1,
      10000
    );
    const nativeTts = resolveNativeTtsModule();
    this.nativeRuntime = nativeTts.createRuntime(
      joinPath(this.modelPackageDir, this.modelPackage.manifest.hiddenEncoderModelFile),
      joinPath(this.modelPackageDir, this.modelPackage.manifest.streamConditionChunkModelFile),
      joinPath(this.modelPackageDir, this.modelPackage.manifest.streamConditionFinalModelFile),
      joinPath(this.modelPackageDir, this.modelPackage.manifest.streamDecoderStepModelFile),
      joinPath(this.modelPackageDir, this.modelPackage.manifest.vocoderModelFile),
      runtimeChunkSize,
      this.modelPackage.manifest.streamingPreLookaheadLen,
      this.modelPackage.manifest.streamingMelCacheLen,
      this.modelPackage.manifest.hopLength,
      this.modelPackage.manifest.streamDecoderTimesteps,
      this.modelPackage.manifest.streamDecoderTemperature
    );
  }

  setListener(listener: SpeakListener): void {
    this.ensureNotDestroyed();
    this.listener = listener;
  }

  speak(text: string, params: SpeakParams): void {
    const listener = this.listener;
    const normalizedParams = this.normalizeSpeakParams(params);
    if (listener === undefined) {
      throw new TextToSpeechException(
        TtsErrorCode.ENGINE_NOT_INITIALIZED,
        'listener must be set before speak'
      );
    }
    if (this.destroyed) {
      listener.onError?.(normalizedParams.requestId, TtsErrorCode.ENGINE_DESTROYED, 'engine has been destroyed');
      return;
    }
    const normalizedText = text.trim();
    this.validateSpeak(normalizedText, normalizedParams);
    if (this.seenRequestIds.has(normalizedParams.requestId)) {
      listener.onError?.(normalizedParams.requestId, TtsErrorCode.RUNTIME_EXCEPTION, 'requestId duplicated');
      return;
    }
    this.seenRequestIds.add(normalizedParams.requestId);
    const task: SynthesisTask = {
      text: normalizedText,
      params: {
        requestId: normalizedParams.requestId,
        speed: normalizedParams.speed,
        volume: normalizedParams.volume,
        pitch: normalizedParams.pitch,
        languageContext: normalizedParams.languageContext,
        audioType: normalizedParams.audioType,
        playType: normalizedParams.playType,
        soundChannel: normalizedParams.soundChannel,
        queueMode: normalizedParams.queueMode,
        extraParams: normalizedParams.extraParams
      },
      cancelled: false,
      stopNotified: false
    };

    const stoppedTasks = task.params.queueMode === QueueMode.PREEMPT ? this.cancelAllTasks() : [];
    if (stoppedTasks.length > 0) {
      this.cancelNativeSynthesis();
    }
    stoppedTasks.forEach((stoppedTask: SynthesisTask): void => this.notifyStop(listener, stoppedTask));
    this.queue.push(task);
    this.scheduleProcessing();
  }

  stop(): void {
    this.ensureNotDestroyed();
    const listener = this.listener;
    const stoppedTasks = this.cancelAllTasks();
    if (stoppedTasks.length > 0) {
      this.cancelNativeSynthesis();
    }
    void this.player.stop();
    if (listener !== undefined) {
      stoppedTasks.forEach((task: SynthesisTask): void => this.notifyStop(listener, task));
    }
  }

  isBusy(): boolean {
    this.ensureNotDestroyed();
    return this.currentTask !== undefined || this.queue.some((task: SynthesisTask): boolean => !task.cancelled);
  }

  shutdown(): void {
    this.ensureNotDestroyed();
    this.destroyed = true;
    const listener = this.listener;
    const stoppedTasks = this.cancelAllTasks();
    if (stoppedTasks.length > 0) {
      this.cancelNativeSynthesis();
    }
    void this.player.stop();
    if (listener !== undefined) {
      stoppedTasks.forEach((task: SynthesisTask): void => this.notifyStop(listener, task));
    }
    this.releaseOnce();
  }

  private scheduleProcessing(): void {
    if (this.processing || this.destroyed) {
      return;
    }
    this.processing = true;
    Promise.resolve().then(async (): Promise<void> => {
      try {
        await this.processQueue();
      } finally {
        this.processing = false;
      }
    });
  }

  private async processQueue(): Promise<void> {
    while (!this.destroyed) {
      const nextTask = this.takeNextTask();
      if (nextTask === undefined) {
        return;
      }
      this.currentTask = nextTask;
      try {
        await this.runTask(nextTask);
      } finally {
        if (this.currentTask === nextTask) {
          this.currentTask = undefined;
        }
      }
    }
  }

  private takeNextTask(): SynthesisTask | undefined {
    while (this.queue.length > 0) {
      const task = this.queue.shift();
      if (task !== undefined && !task.cancelled) {
        return task;
      }
    }
    return undefined;
  }

  private async runTask(task: SynthesisTask): Promise<void> {
    const listener = this.listener;
    if (listener === undefined || task.cancelled || this.destroyed) {
      return;
    }
    this.notifyStart(listener, task);
    try {
      if (task.params.playType === PlayType.SYNTHESIZE_AND_PLAY) {
        let synthesisCompleteNotified = false;
        let synthesisMetrics: NativeStreamingSynthesisMetrics | undefined = undefined;
        await this.player.playStreaming(
          this.modelPackage.manifest.sampleRate,
          task.params.soundChannel,
          this.pcmQueueCapacity(task.params),
          async (chunkWriter: (chunk: ArrayBuffer) => Promise<void>): Promise<void> => {
            synthesisMetrics = await this.synthesizeStreaming(task, listener, chunkWriter);
          },
          (): void => {
            if (!task.cancelled && !this.destroyed) {
              synthesisCompleteNotified = true;
              listener.onComplete?.(task.params.requestId, this.buildSynthesisCompleteResponse(synthesisMetrics));
            }
          }
        );
        if (task.cancelled || this.destroyed) {
          this.notifyStop(listener, task);
          return;
        }
        if (!synthesisCompleteNotified) {
          listener.onComplete?.(task.params.requestId, this.buildSynthesisCompleteResponse(synthesisMetrics));
        }
        listener.onComplete?.(task.params.requestId, {
          type: CompleteType.PLAYBACK_COMPLETE,
          message: 'playback complete'
        });
        return;
      }
      const synthesisMetrics = await this.synthesizeStreaming(task, listener);
      if (task.cancelled || this.destroyed) {
        this.notifyStop(listener, task);
        return;
      }
      listener.onComplete?.(task.params.requestId, this.buildSynthesisCompleteResponse(synthesisMetrics));
    } catch (error) {
      const code = error instanceof TextToSpeechException ? error.errorCode : TtsErrorCode.RUNTIME_EXCEPTION;
      const message = error instanceof Error ? error.message : 'synthesis failed';
      listener.onError?.(task.params.requestId, code, message);
      return;
    }
  }

  private async synthesizeStreaming(
    task: SynthesisTask,
    listener: SpeakListener,
    chunkWriter?: (chunk: ArrayBuffer) => Promise<void>
  ): Promise<NativeStreamingSynthesisMetrics> {
    const params = task.params;
    const languageContext = params.languageContext ?? 'zh-en';
    const segments = LitsTtsFrontend.splitForStreaming(this.modelPackage, task.text, this.engineParams.language, languageContext);
    let sequence = 0;
    let synthesisMs = 0;
    let firstChunkMs = -1;
    let audioBytes = 0;
    let chunkCount = 0;
    const textMetricSummaries: Array<string> = [];
    for (let index = 0; index < segments.length; index += 1) {
      if (task.cancelled || this.destroyed) {
        return { synthesisMs, firstChunkMs, audioBytes, chunkCount };
      }
      const textMetric = LitsTtsFrontend.buildTextMetric(
        this.modelPackage,
        segments[index],
        this.engineParams.language,
        languageContext,
        true
      );
      const segmentTokenIds = textMetric.tokenIds;
      textMetricSummaries.push(
        `seg=${index} cleaned=${textMetric.cleanedTokenLength} model=${textMetric.modelTokenLength}`
      );
      console.info(
        `${TEXT_METRIC_LOG_TAG} requestId=${task.params.requestId} segment=${index + 1}/${segments.length}` +
          ` language=${this.engineParams.language} languageContext=${languageContext} speakerId=${this.voice.speakerId}` +
          ` raw="${previewForHilLog(textMetric.rawText)}" tn="${previewForHilLog(textMetric.tnText)}"` +
          ` cleaned="${previewForHilLog(textMetric.cleanedText, 240)}"` +
          ` cleanedTokenLength=${textMetric.cleanedTokenLength} modelTokenLength=${textMetric.modelTokenLength}` +
          ` tokenHead=${JSON.stringify(textMetric.tokenIdHead)} tokenTail=${JSON.stringify(textMetric.tokenIdTail)}`
      );
      const segmentMetrics = await resolveNativeTtsModule().synthesizeStreaming(
        this.nativeRuntime,
        segmentTokenIds,
        this.voice.speakerId,
        (chunk: ArrayBuffer, _nativeSequence: number): void => {
          if (task.cancelled || this.destroyed) {
            return;
          }
          const transformedChunk = AudioTransforms.apply(chunk, params);
          sequence = this.emitAudioChunks(listener, task, transformedChunk, sequence);
          if (chunkWriter !== undefined) {
            void chunkWriter(transformedChunk);
          }
        }
      );
      synthesisMs += Math.max(0, Math.round(segmentMetrics.synthesisMs));
      audioBytes += Math.max(0, Math.round(segmentMetrics.audioBytes));
      chunkCount += Math.max(0, Math.round(segmentMetrics.chunkCount));
      if (firstChunkMs < 0 && segmentMetrics.firstChunkMs >= 0) {
        firstChunkMs = synthesisMs - Math.max(0, Math.round(segmentMetrics.synthesisMs)) + Math.round(segmentMetrics.firstChunkMs);
      }
      console.info(
        `${STREAM_METRIC_LOG_TAG} requestId=${task.params.requestId} segment=${index + 1}/${segments.length}` +
          ` nativeFirstChunkMs=${segmentMetrics.firstChunkMs} nativeSynthesisMs=${segmentMetrics.synthesisMs}` +
          ` nativeAudioBytes=${segmentMetrics.audioBytes} nativeChunks=${segmentMetrics.chunkCount}` +
          ` totalSynthesisMs=${synthesisMs} totalAudioBytes=${audioBytes} totalChunks=${chunkCount}`
      );
    }
    return { synthesisMs, firstChunkMs, audioBytes, chunkCount, textMetricSummary: textMetricSummaries.join(';') };
  }

  private buildSynthesisCompleteResponse(metrics: NativeStreamingSynthesisMetrics | undefined): CompleteResponse {
    if (metrics === undefined) {
      return {
        type: CompleteType.SYNTHESIS_COMPLETE,
        message: 'synthesis complete'
      };
    }
    const audioDuration = audioDurationMs(metrics.audioBytes, this.modelPackage.manifest.sampleRate);
    const rtf = metrics.synthesisMs >= 0 && audioDuration > 0 ? metrics.synthesisMs / audioDuration : -1;
    return {
      type: CompleteType.SYNTHESIS_COMPLETE,
      message: `synthesis complete firstPacketMs=${metrics.firstChunkMs} synthesisMs=${metrics.synthesisMs} audioDurationMs=${audioDuration} rtf=${formatSdkRtf(rtf)} chunks=${metrics.chunkCount}`,
      firstPacketMs: metrics.firstChunkMs,
      synthesisMs: metrics.synthesisMs,
      audioDurationMs: audioDuration,
      rtf,
      profilingInfo: `chunks=${metrics.chunkCount} audioBytes=${metrics.audioBytes} textMetric=${metrics.textMetricSummary ?? ''}`
    };
  }

  private pcmQueueCapacity(params: SpeakParams): number {
    return resolveIntegerExtraParam(
      params.extraParams,
      ['pcmQueueCapacity', 'pcmQueueSize'],
      DEFAULT_PCM_QUEUE_CAPACITY_VALUE,
      1,
      MAX_PCM_QUEUE_CAPACITY_VALUE
    );
  }

  private cancelNativeSynthesis(): void {
    try {
      resolveNativeTtsModule().cancelRuntime(this.nativeRuntime);
    } catch (_error) {
    }
  }

  private emitAudioChunks(listener: SpeakListener, task: SynthesisTask, pcm: ArrayBuffer, initialSequence: number): number {
    let offset = 0;
    let sequence = initialSequence;
    while (offset < pcm.byteLength) {
      if (task.cancelled || this.destroyed) {
        return sequence;
      }
      const length = Math.min(SYNTHESIS_CALLBACK_CHUNK_BYTES, pcm.byteLength - offset);
      const chunk = copyArrayBuffer(pcm, offset, length);
      listener.onData?.(task.params.requestId, chunk, {
        sequence,
        audioType: 'pcm'
      });
      offset += length;
      sequence += 1;
    }
    return sequence;
  }

  private cancelAllTasks(): Array<SynthesisTask> {
    const stoppedTasks: Array<SynthesisTask> = [];
    if (this.currentTask !== undefined && !this.currentTask.cancelled) {
      this.currentTask.cancelled = true;
      stoppedTasks.push(this.currentTask);
    }
    this.queue.forEach((task: SynthesisTask): void => {
      if (!task.cancelled) {
        task.cancelled = true;
        stoppedTasks.push(task);
      }
    });
    this.queue = [];
    return stoppedTasks;
  }

  private validateSpeak(text: string, params: SpeakParams): void {
    if (text.length === 0 || text.length > MAX_TEXT_LENGTH) {
      throw new TextToSpeechException(TtsErrorCode.TEXT_LENGTH_INVALID, 'text length must be 1..10000');
    }
    if (params.requestId.trim().length === 0) {
      throw new TextToSpeechException(TtsErrorCode.RUNTIME_EXCEPTION, 'requestId must not be blank');
    }
    if (params.audioType !== undefined && params.audioType !== 'pcm') {
      throw new TextToSpeechException(TtsErrorCode.RUNTIME_EXCEPTION, 'only pcm audioType is supported');
    }
    if (params.speed !== undefined && (params.speed < 0.5 || params.speed > 2.0)) {
      throw new TextToSpeechException(TtsErrorCode.RUNTIME_EXCEPTION, 'speed out of range');
    }
    if (params.pitch !== undefined && (params.pitch < 0.5 || params.pitch > 2.0)) {
      throw new TextToSpeechException(TtsErrorCode.RUNTIME_EXCEPTION, 'pitch out of range');
    }
    if (params.volume !== undefined && (params.volume < 0.0 || params.volume > 2.0)) {
      throw new TextToSpeechException(TtsErrorCode.RUNTIME_EXCEPTION, 'volume out of range');
    }
  }

  private normalizeSpeakParams(params: SpeakParams): SpeakParams {
    return {
      requestId: params.requestId,
      speed: params.speed ?? 1.0,
      volume: params.volume ?? 1.0,
      pitch: params.pitch ?? 1.0,
      languageContext: normalizeLanguageContext(params.languageContext),
      audioType: params.audioType ?? 'pcm',
      playType: params.playType ?? PlayType.SYNTHESIZE_AND_PLAY,
      soundChannel: normalizeSoundChannel(params.soundChannel),
      queueMode: params.queueMode ?? QueueMode.QUEUE,
      extraParams: params.extraParams ?? {}
    };
  }

  private notifyStart(listener: SpeakListener, task: SynthesisTask): void {
    listener.onStart?.(task.params.requestId, {
      audioType: 'pcm',
      sampleRate: this.modelPackage.manifest.sampleRate,
      sampleBit: 16,
      audioChannel: 1,
      compressRate: 0
    });
  }

  private notifyStop(listener: SpeakListener, task: SynthesisTask): void {
    if (task.stopNotified) {
      return;
    }
    task.stopNotified = true;
    listener.onStop?.(task.params.requestId, {
      type: StopType.STOP_ALL,
      message: 'stopped'
    });
  }

  private ensureNotDestroyed(): void {
    if (this.destroyed) {
      throw new TextToSpeechException(TtsErrorCode.ENGINE_DESTROYED, 'engine has been destroyed');
    }
  }

  private releaseOnce(): void {
    if (this.released) {
      return;
    }
    this.released = true;
    try {
      resolveNativeTtsModule().releaseRuntime(this.nativeRuntime);
    } catch (_error) {
    }
    this.onRelease();
  }
}

export class TextToSpeechSdk {
  private static workPath: string | undefined;

  static async init(options: TtsLicenseOptions): Promise<void> {
    await LicenseGuard.configureAndVerify(options);
  }

  static licenseStatus(): TtsLicenseStatus {
    return LicenseGuard.status();
  }

  static setWorkPath(workPath: string): void {
    if (workPath.trim().length === 0) {
      throw new TextToSpeechException(TtsErrorCode.RUNTIME_EXCEPTION, 'workPath must not be blank');
    }
    if (EngineRegistry.hasActiveEngines()) {
      throw new TextToSpeechException(
        TtsErrorCode.INTERNAL_SERVICE_ERROR,
        'setWorkPath must be called before createEngine'
      );
    }
    TextToSpeechSdk.workPath = workPath;
  }

  static createEngine(params: CreateEngineParams): TextToSpeechEngine;
  static createEngine(params: CreateEngineParams, callback: Callback<TextToSpeechEngine>): void;
  static createEngine(
    params: CreateEngineParams,
    callback?: Callback<TextToSpeechEngine>
  ): TextToSpeechEngine | void {
    if (callback !== undefined) {
      TextToSpeechSdk.createEngineAsync(params, callback);
      return;
    }
    return TextToSpeechSdk.createEngineInternal(params);
  }

  static createEngineAsync(params: CreateEngineParams, callback: Callback<TextToSpeechEngine>): void {
    Promise.resolve().then((): void => {
      try {
        callback.onSuccess(TextToSpeechSdk.createEngineInternal(params));
      } catch (error) {
        const code = error instanceof TextToSpeechException ? error.errorCode : TtsErrorCode.CREATE_ENGINE_FAILED;
        const message = error instanceof Error ? error.message : 'create engine failed';
        callback.onError(code, message);
      }
    });
  }

  static listVoices(params: VoiceQuery): Array<VoiceInfo>;
  static listVoices(params: VoiceQuery, callback: Callback<Array<VoiceInfo>>): void;
  static listVoices(
    params: VoiceQuery,
    callback?: Callback<Array<VoiceInfo>>
  ): Array<VoiceInfo> | void {
    if (callback !== undefined) {
      TextToSpeechSdk.listVoicesAsync(params, callback);
      return;
    }
    return TextToSpeechSdk.listVoicesInternal(params);
  }

  static listVoicesAsync(params: VoiceQuery, callback: Callback<Array<VoiceInfo>>): void {
    Promise.resolve().then((): void => {
      try {
        callback.onSuccess(TextToSpeechSdk.listVoicesInternal(params));
      } catch (error) {
        const code = error instanceof TextToSpeechException ? error.errorCode : TtsErrorCode.INTERNAL_SERVICE_ERROR;
        const message = error instanceof Error ? error.message : 'list voices failed';
        callback.onError(code, message);
      }
    });
  }

  private static createEngineInternal(params: CreateEngineParams): TextToSpeechEngine {
    LicenseGuard.gate();
    return EngineRegistry.createEngine(params, TextToSpeechSdk.workPath);
  }

  private static listVoicesInternal(params: VoiceQuery): Array<VoiceInfo> {
    return EngineRegistry.listVoices(params);
  }
}

let nativeTtsModuleCache: NativeTtsModule | undefined = undefined;

function resolveNativeTtsModule(): NativeTtsModule {
  if (nativeTtsModuleCache !== undefined) {
    return nativeTtsModuleCache;
  }
  const nativeModule = loadNativeModule('liblitsttsnative.so') as NativeTtsModule | undefined;
  if (
    nativeModule === undefined ||
    typeof nativeModule.createRuntime !== 'function' ||
    typeof nativeModule.releaseRuntime !== 'function' ||
    typeof nativeModule.cancelRuntime !== 'function' ||
    typeof nativeModule.synthesize !== 'function' ||
    typeof nativeModule.synthesizeStreaming !== 'function' ||
    typeof nativeModule.normalizeTnSegment !== 'function'
  ) {
    throw new TextToSpeechException(
      TtsErrorCode.CREATE_ENGINE_FAILED,
      'native module liblitsttsnative.so is unavailable'
    );
  }
  nativeTtsModuleCache = nativeModule;
  return nativeModule;
}

function resolveModelPackageDir(extraParams: ExtraParams | undefined, workPath: string | undefined): string {
  const extraModelDir = extraParams?.modelPackageDir;
  if (typeof extraModelDir === 'string' && extraModelDir.trim().length > 0) {
    return requireManifestDir(extraModelDir.trim());
  }

  const workPathModelDir = resolveWorkPathModelPackageDir(workPath);
  if (workPathModelDir !== undefined) {
    return workPathModelDir;
  }

  return ensureBundledModelPackageDir(workPath);
}

function normalizeLanguageContext(languageContext: string | undefined): string {
  const value = languageContext ?? DEFAULT_LANGUAGE_CONTEXT;
  if (value === 'zh-CN' || value === 'zh-en') {
    return 'zh-en';
  }
  if (value === 'en-US') {
    return value;
  }
  throw new TextToSpeechException(TtsErrorCode.RUNTIME_EXCEPTION, 'languageContext is not supported');
}

function normalizeSoundChannel(soundChannel: number | undefined): number | undefined {
  if (soundChannel === undefined) {
    return undefined;
  }
  if (!Number.isInteger(soundChannel) || !SUPPORTED_SOUND_CHANNELS.has(soundChannel)) {
    throw new TextToSpeechException(TtsErrorCode.RUNTIME_EXCEPTION, 'soundChannel is not supported');
  }
  return soundChannel;
}

function resolveHarmonyStreamUsage(soundChannel: number | undefined): audio.StreamUsage {
  if (soundChannel === undefined) {
    return audio.StreamUsage.STREAM_USAGE_MUSIC;
  }
  return soundChannel as audio.StreamUsage;
}

function resolveWorkPathModelPackageDir(workPath: string | undefined): string | undefined {
  if (workPath !== undefined && workPath.trim().length > 0) {
    const normalizedWorkPath = normalizeDir(workPath);
    const candidates = [
      normalizedWorkPath,
      joinPath(normalizedWorkPath, MODEL_ID, MODEL_VERSION),
      joinPath(joinPath(normalizedWorkPath, 'tts'), MODEL_ID, MODEL_VERSION)
    ];
    for (let index = 0; index < candidates.length; index += 1) {
      if (isRegularFile(joinPath(candidates[index], 'manifest.json'))) {
        return requireManifestDir(candidates[index]);
      }
    }
  }

  return undefined;
}

function ensureBundledModelPackageDir(workPath: string | undefined): string {
  const modelPackageDir = resolveBundledModelPackageDir(workPath);
  if (bundledModelPackageDirCache !== modelPackageDir || !hasRequiredRuntimeFiles(modelPackageDir)) {
    extractBundledModelPackage(modelPackageDir);
    bundledModelPackageDirCache = modelPackageDir;
  }
  return requireManifestDir(modelPackageDir);
}

function resolveBundledModelPackageDir(workPath: string | undefined): string {
  const baseDir = workPath !== undefined && workPath.trim().length > 0
    ? normalizeDir(workPath)
    : normalizeDir(application.getApplicationContext().filesDir);
  return joinPath(joinPath(baseDir, 'tts'), MODEL_ID, MODEL_VERSION);
}

function hasRequiredRuntimeFiles(modelPackageDir: string): boolean {
  return REQUIRED_RUNTIME_FILES.every((fileName: string): boolean => isRegularFile(joinPath(modelPackageDir, fileName)));
}

function extractBundledModelPackage(modelPackageDir: string): void {
  ensureDirectory(modelPackageDir);
  try {
    const resourceManager = resolveBundledModelResourceManager();
    BUNDLED_MODEL_FILES.forEach((fileName: string): void => {
      const rawfilePath = joinPath(BUNDLED_MODEL_RAWFILE_DIR, fileName);
      writeBinaryFile(
        joinPath(modelPackageDir, fileName),
        resourceManager.getRawFileContentSync(rawfilePath)
      );
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'failed to extract bundled model package';
    throw new TextToSpeechException(TtsErrorCode.CREATE_ENGINE_FAILED, message);
  }
}

function resolveBundledModelResourceManager() {
  const appContext = application.getApplicationContext();
  try {
    return appContext.resourceManager;
  } catch (_error) {
  }

  try {
    return appContext.createModuleContext('sdk').resourceManager;
  } catch (_error) {
  }

  throw new TextToSpeechException(
    TtsErrorCode.CREATE_ENGINE_FAILED,
    'failed to access bundled model resources'
  );
}

function requireManifestDir(path: string): string {
  const normalized = normalizeDir(path);
  if (!isRegularFile(joinPath(normalized, 'manifest.json'))) {
    throw new TextToSpeechException(
      TtsErrorCode.CREATE_ENGINE_FAILED,
      `manifest.json is missing in modelPackageDir: ${normalized}`
    );
  }
  return normalized;
}

function readJsonFile<T>(filePath: string): T {
  try {
    return JSON.parse(readText(filePath)) as T;
  } catch (error) {
    const message = error instanceof Error ? error.message : 'failed to parse json';
    throw new TextToSpeechException(TtsErrorCode.CREATE_ENGINE_FAILED, `${filePath}: ${message}`);
  }
}

function readText(filePath: string): string {
  try {
    return fs.readTextSync(filePath);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'failed to read file';
    throw new TextToSpeechException(TtsErrorCode.CREATE_ENGINE_FAILED, `${filePath}: ${message}`);
  }
}

function readNonEmptyLines(filePath: string): Array<string> {
  return readText(filePath)
    .split(/\r?\n/)
    .map((line: string): string => line.trim())
    .filter((line: string): boolean => line.length > 0);
}

function writeBinaryFile(filePath: string, content: Uint8Array): void {
  ensureDirectory(parentDir(filePath));
  let file: fs.File | undefined = undefined;
  try {
    file = fs.openSync(filePath, fs.OpenMode.CREATE | fs.OpenMode.WRITE_ONLY | fs.OpenMode.TRUNC);
    const payload = content.byteOffset === 0 && content.byteLength === content.buffer.byteLength
      ? content.buffer
      : content.slice().buffer;
    fs.writeSync(file.fd, payload);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'failed to write file';
    throw new TextToSpeechException(TtsErrorCode.CREATE_ENGINE_FAILED, `${filePath}: ${message}`);
  } finally {
    if (file !== undefined) {
      try {
        fs.closeSync(file);
      } catch (_error) {
      }
    }
  }
}

function splitByWhitespace(text: string): Array<string> {
  return text.split(/\s+/).filter((item: string): boolean => item.length > 0);
}

function concatArrayBuffers(buffers: Array<ArrayBuffer>): ArrayBuffer {
  if (buffers.length === 0) {
    return new ArrayBuffer(0);
  }
  if (buffers.length === 1) {
    return buffers[0];
  }
  let totalLength = 0;
  buffers.forEach((buffer: ArrayBuffer): void => {
    totalLength += buffer.byteLength;
  });
  const output = new Uint8Array(totalLength);
  let offset = 0;
  buffers.forEach((buffer: ArrayBuffer): void => {
    output.set(new Uint8Array(buffer), offset);
    offset += buffer.byteLength;
  });
  return output.buffer as ArrayBuffer;
}

function joinPath(basePath: string, ...parts: Array<string>): string {
  let output = normalizeDir(basePath);
  parts.forEach((part: string): void => {
    const cleaned = trimSlashes(part);
    if (cleaned.length === 0) {
      return;
    }
    output = `${output}/${cleaned}`;
  });
  return output;
}

function normalizeDir(path: string): string {
  const withForwardSlash = path.replace(/\\/g, '/');
  if (withForwardSlash.length <= 1) {
    return withForwardSlash;
  }
  let end = withForwardSlash.length;
  while (end > 1 && withForwardSlash[end - 1] === '/') {
    end -= 1;
  }
  return withForwardSlash.substring(0, end);
}

function parentDir(path: string): string {
  const normalized = normalizeDir(path);
  const lastSlash = normalized.lastIndexOf('/');
  if (lastSlash <= 0) {
    return normalized;
  }
  return normalized.substring(0, lastSlash);
}

function trimSlashes(path: string): string {
  let start = 0;
  let end = path.length;
  while (start < end && (path[start] === '/' || path[start] === '\\')) {
    start += 1;
  }
  while (end > start && (path[end - 1] === '/' || path[end - 1] === '\\')) {
    end -= 1;
  }
  return path.substring(start, end);
}

function ensureDirectory(path: string): void {
  const normalized = normalizeDir(path);
  if (normalized.length === 0) {
    return;
  }
  if (isDirectory(normalized)) {
    return;
  }
  if (fs.accessSync(normalized)) {
    throw new TextToSpeechException(
      TtsErrorCode.CREATE_ENGINE_FAILED,
      `path exists but is not a directory: ${normalized}`
    );
  }
  try {
    fs.mkdirSync(normalized, true);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'failed to create directory';
    throw new TextToSpeechException(TtsErrorCode.CREATE_ENGINE_FAILED, `${normalized}: ${message}`);
  }
}

function isRegularFile(path: string): boolean {
  try {
    return fs.statSync(path).isFile();
  } catch (_error) {
    return false;
  }
}

function isDirectory(path: string): boolean {
  try {
    return fs.statSync(path).isDirectory();
  } catch (_error) {
    return false;
  }
}

function copyArrayBuffer(source: ArrayBuffer, offset: number, length: number): ArrayBuffer {
  const view = new Uint8Array(source, offset, length);
  const copy = new Uint8Array(length);
  copy.set(view);
  return copy.buffer;
}

function resolveIntegerExtraParam(
  extraParams: ExtraParams | undefined,
  keys: Array<string>,
  defaultValue: number,
  minValue: number,
  maxValue: number
): number {
  for (let index = 0; index < keys.length; index += 1) {
    const key = keys[index];
    const raw = key === 'streamingChunkSize'
      ? extraParams?.streamingChunkSize
      : key === 'streamingFirstChunkSize'
        ? extraParams?.streamingFirstChunkSize
        : key === 'pcmQueueCapacity'
          ? extraParams?.pcmQueueCapacity
          : key === 'pcmQueueSize'
            ? extraParams?.pcmQueueSize
            : undefined;
    let value: number | undefined = undefined;
    if (typeof raw === 'number') {
      value = raw;
    } else if (typeof raw === 'string') {
      const parsed = parseInt(raw, 10);
      value = Number.isNaN(parsed) ? undefined : parsed;
    }
    if (value !== undefined && Number.isFinite(value)) {
      return clampInt(Math.round(value), minValue, maxValue);
    }
  }
  return clampInt(Math.round(defaultValue), minValue, maxValue);
}

function clampNumber(value: number, minValue: number, maxValue: number): number {
  return Math.max(minValue, Math.min(maxValue, value));
}

function clampInt(value: number, minValue: number, maxValue: number): number {
  return Math.max(minValue, Math.min(maxValue, Math.round(value)));
}

function clampInt16(value: number): number {
  if (value > 32767) {
    return 32767;
  }
  if (value < -32768) {
    return -32768;
  }
  return value;
}

function audioDurationMs(audioBytes: number, sampleRate: number): number {
  if (sampleRate <= 0) {
    return 0;
  }
  return Math.floor(audioBytes * 1000 / (sampleRate * 2));
}

function formatSdkRtf(rtf: number): string {
  if (!Number.isFinite(rtf) || rtf < 0) {
    return '--';
  }
  return rtf.toFixed(3);
}

function previewForHilLog(value: string, maxLength: number = 160): string {
  const singleLine = value.replace(/\s+/g, ' ');
  return singleLine.length > maxLength ? `${singleLine.substring(0, maxLength)}...` : singleLine;
}

function makeLicenseStatus(
  state: TtsLicenseState,
  valid: boolean,
  errorCode: number,
  applicationId: string
): TtsLicenseStatus {
  return {
    state,
    valid,
    errorCode,
    licenseId: '',
    customer: '',
    applicationId,
    issuedAt: '',
    expiresAt: '',
    installTier: '',
    features: []
  };
}

function normalizeHex(value: string): string {
  return value.replace(/[:\s]/g, '').toUpperCase();
}

function parseDateUtcMillis(value: string): number | undefined {
  const matched = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (matched === null) {
    return undefined;
  }
  const year = Number(matched[1]);
  const month = Number(matched[2]);
  const day = Number(matched[3]);
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) {
    return undefined;
  }
  return Date.UTC(year, month - 1, day);
}

function base64Decode(input: string): Uint8Array {
  const table = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  const output: Array<number> = [];
  let collected = 0;
  let bits = 0;
  for (let i = 0; i < input.length; i += 1) {
    const char = input.charAt(i);
    if (char === '=' || char === '\n' || char === '\r' || char === ' ' || char === '\t') {
      continue;
    }
    const value = table.indexOf(char);
    if (value < 0) {
      throw new Error(`illegal base64 character: ${char}`);
    }
    collected = (collected << 6) | value;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      output.push((collected >> bits) & 0xff);
    }
  }
  return new Uint8Array(output);
}

function formatError(error: Object): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}
