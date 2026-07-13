import common from '@ohos.app.ability.common';
import fs from '@ohos.file.fs';
import { audio } from '@kit.AudioKit';
import deviceInfo from '@ohos.deviceInfo';
import { HarmonyLicenseVerifier, AmphionLicenseStatus } from './License';

const MODEL_ID: string = 'dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop';
const MODEL_VERSION: string = '0.1.0';
const FRONTEND_ASSET_SIGNATURE_VERSION: string = '20260701-chunk50-polyphone-v1';
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
const DEFAULT_PCM_QUEUE_CAPACITY_VALUE: number = 128;
const MAX_PCM_QUEUE_CAPACITY_VALUE: number = 256;
const STREAMING_PREBUFFER_CHUNKS: number = 1;
const PLAYBACK_DRAIN_PADDING_MS: number = 500;
const PLAYBACK_DRAIN_MAX_MS: number = 30000;
const MIN_RUNTIME_STREAMING_CHUNK_SIZE: number = 16;
const MAX_RUNTIME_STREAMING_CHUNK_SIZE: number = 128;
const PREFERRED_TN_SEGMENT_LENGTH: number = 160;
const MAX_TN_SEGMENT_LENGTH: number = 220;
const MAX_TN_SEGMENTS_PER_REQUEST: number = 40;

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
  'chinese_surname_lexicon.txt',
  'cmudict.txt',
  'supplement_lexicon.json',
  'frontend_rules.json',
  'polychar.txt',
  'polyphone_context.txt',
  'polyphone_phrases.txt',
  'zh_en_symbols.json',
  'pinyin_to_tokens.json',
  'arpabet_to_tokens.json'
];

const BUNDLED_MODEL_FILES: Array<string> = [
  'manifest.json',
  'export_report.json',
  'external_loop_export_report.json',
  'frontend_golden.json',
  'chinese_lexicon.txt',
  'chinese_lexicon.bin',
  'cmudict.txt',
  'cmudict.bin',
  'supplement_lexicon.json',
  'frontend_rules.json',
  'pinyin_2_bpmf.txt',
  'polychar.txt',
  'polyphone_context.txt',
  'polyphone_phrases.txt',
  'chinese_surname_lexicon.txt',
  'zh_en_symbols.json',
  'pinyin_to_tokens.json',
  'arpabet_to_tokens.json',
  'tn-bin/arm64-v8a/zh_tts',
  'tn-bin/arm64-v8a/en_tts',
  'rules_v2/zh.full.json',
  'rules_v2/en.full.json',
  'rules_v2/zh_pinyin.json',
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
  ['\u3010', ','],
  ['\u3011', ','],
  ['\uFF08', '('],
  ['\uFF09', ')'],
  ['\u300A', ','],
  ['\u300B', ','],
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
  ['\uFF05', '\u767E\u5206\u53F7'],
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
const PERCENT_NUMBER_REGEX: RegExp = /(\d+(?:\.\d+)?)[%％]/g;
const COMMA_INTEGER_CURRENCY_REGEX: RegExp = /(^|[^\d])(\d{1,3}(?:,\d{3})+)\.00(?=元)/g;
const THOUSANDS_SEPARATOR_REGEX: RegExp = /(\d),(?=\d{3}(?:\D|$))/g;
const CLOCK_MINUTE_LEADING_ZERO_REGEX: RegExp = /(^|[^\d])(\d{1,2})点0([1-9])分/g;
const HANZI_CLOCK_MINUTE_LEADING_ZERO_REGEX: RegExp = /([零一二三四五六七八九十两]+)点0([1-9])分/g;
const DURATION_MINUTE_LEADING_ZERO_REGEX: RegExp = /(^|[^\d])(\d+)小时0([1-9])分钟/g;
const YEAR_MONTH_LEADING_ZERO_REGEX: RegExp = /(\d{2,4}年)0([1-9])月/g;
const YEAR_MONTH_REGEX: RegExp = /(\d{2,4}年)(\d{1,2})月/g;
const MONTH_DAY_LEADING_ZERO_REGEX: RegExp = /(月)0([1-9])日/g;
const MONTH_DAY_REGEX: RegExp = /(月)(\d{1,2})(日|号)/g;
const NEGATIVE_TEMPERATURE_REGEX: RegExp = /((?:气温|温度|体温))-(\d+(?:\.\d+)?)(度|℃)/g;
const NEGATIVE_TEMPERATURE_RANGE_REGEX: RegExp = /(温度范围是)-(\d+(?:\.\d+)?)到(\d+(?:\.\d+)?)(度|℃)/g;
const VERSION_NUMBER_WITH_SUFFIX_REGEX: RegExp = /(^|[^\d])(\d+(?:\.\d+){2,})(?=[-A-Za-z])/g;
const DIGIT_DOT_REGEX: RegExp = /(\d)\.(?=\d)/g;
const HANZI_DIGIT_DOT_REGEX: RegExp = /([零一二三四五六七八九十百千万两])\.(?=[零一二三四五六七八九十百千万两])/g;
const LEADING_DOT_ASCII_TOKEN_REGEX: RegExp = /(^|[^A-Za-z0-9])\.(?=[A-Za-z0-9])/g;
const URL_SCHEME_SEPARATOR_REGEX: RegExp = /(^|[^A-Za-z0-9])(https?|ftp):\/\//gi;
const CARET_POWER_TWO_REGEX: RegExp = /\^(?:2|二)/g;
const TECHNICAL_ASCII_TOKEN_REGEX: RegExp = /(^|[^A-Za-z0-9])([A-Za-z0-9./\\_@:?=&#%+\-]*[A-Za-z0-9])(?![A-Za-z0-9])/g;
const CONNECTOR_HYPHEN_REGEX: RegExp = /(^|[^A-Za-z0-9])(USB|Type)-([A-Za-z])(?=$|[^A-Za-z0-9])/gi;
const CONNECTOR_SPOKEN_HYPHEN_REGEX: RegExp = /(^|[^A-Za-z0-9])(USB|Type)杠([A-Za-z])(?=$|[^A-Za-z0-9])/gi;
const CHATGPT_SPLIT_REGEX: RegExp = /(^|[^A-Za-z0-9])chat\s+g\s*p\s*t(?=$|[^A-Za-z0-9])/gi;
const SERIAL_CODE_REGEX: RegExp = /((?:设备)?(?:序列号|编号)|S\/N|SN)(\s*)([A-Z0-9]*[A-Z][A-Z0-9]*\d[A-Z0-9]*)/g;
const CHINESE_DIGIT_SEQUENCE_CHARS: Set<string> = new Set<string>(['零', '〇', '一', '二', '两', '三', '四', '五', '六', '七', '八', '九']);
const ARPABET_BOUNDARY_TOKENS: Set<string> = new Set<string>(['/', '|', '_']);
const ACRONYM_WORD_READINGS: Set<string> = new Set<string>(['SIM']);

const TECHNICAL_SYMBOL_READINGS: Map<string, string> = new Map<string, string>([
  ['.', '点'],
  [':', '冒号'],
  ['/', '斜杠'],
  ['\\', '反斜杠'],
  ['?', '问号'],
  ['=', '等于'],
  ['&', '和'],
  ['@', '艾特'],
  ['_', '下划线'],
  ['#', '井号'],
  ['+', '加'],
  ['-', '杠']
]);

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
    lengthScale: number,
    chunkSizeOverride: number,
    onChunk: (chunk: ArrayBuffer, sequence: number) => void
  ): Promise<NativeStreamingSynthesisMetrics>;
  normalizeTnSegment(binaryPath: string, workingDir: string, text: string): string;
  releaseTnResources(): void;
}

interface NativeStreamingSynthesisMetrics {
  synthesisMs: number;
  firstChunkMs: number;
  audioBytes: number;
  chunkCount: number;
  textMetricSummary?: string;
}

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

function utf8BytesToText(bytes: Uint8Array): string {
  let out = '';
  for (let i = 0; i < bytes.length;) {
    const b0 = bytes[i++];
    if (b0 < 0x80) {
      out += String.fromCharCode(b0);
    } else if (b0 < 0xE0 && i < bytes.length) {
      const b1 = bytes[i++] & 0x3F;
      out += String.fromCharCode(((b0 & 0x1F) << 6) | b1);
    } else if (b0 < 0xF0 && i + 1 < bytes.length) {
      const b1 = bytes[i++] & 0x3F;
      const b2 = bytes[i++] & 0x3F;
      out += String.fromCharCode(((b0 & 0x0F) << 12) | (b1 << 6) | b2);
    } else if (i + 2 < bytes.length) {
      const b1 = bytes[i++] & 0x3F;
      const b2 = bytes[i++] & 0x3F;
      const b3 = bytes[i++] & 0x3F;
      const cp = ((b0 & 0x07) << 18) | (b1 << 12) | (b2 << 6) | b3;
      const u = cp - 0x10000;
      out += String.fromCharCode(0xD800 + (u >> 10), 0xDC00 + (u & 0x3FF));
    }
  }
  return out;
}

function readLicenseText(path: string): string {
  const fp = fs.openSync(path);
  try {
    const size = fs.statSync(fp.fd).size;
    const raw = new ArrayBuffer(size);
    fs.readSync(fp.fd, raw);
    return utf8BytesToText(new Uint8Array(raw));
  } finally {
    fs.close(fp.fd);
  }
}

// Reads the device serial for license SN-whitelist checks. Requires ohos.permission.sn
// (system/privileged); ordinary demo hosts get undefined, which only matters for SN-bound licenses.
function readDeviceSerial(): string | undefined {
  try {
    const sn = deviceInfo.serial;
    return sn !== undefined && sn.length > 0 ? sn : undefined;
  } catch (e) {
    return undefined;
  }
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
  overrideWordPinyin: Map<string, string>;
  polyphonicWords: Set<string>;
  maxWordLength: number;
  cmudict: Map<string, Array<string>>;
  supplementLexicon: Map<string, Array<string>>;
  englishLexicon: Map<string, Array<string>>;
  frontendRules: Array<FrontendReplacementRule>;
  symbolToId: Map<string, number>;
  pinyinToTokens: Map<string, Array<string>>;
  arpabetToTokens: Map<string, Array<string>>;
}

interface FrontendReplacementRule {
  name: string;
  stages: Set<string>;
  pattern: string;
  replacement: string;
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
  startedAtMs: number;
  playbackStartMs: number;
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
    const overrideWordPinyin = FrontendResources.loadWordPinyinOverrides(normalizedDir);
    overrideWordPinyin.forEach((pinyin: string, word: string): void => {
      wordPinyin.set(word, pinyin);
    });
    const cmudict = FrontendResources.loadCmudict(joinPath(normalizedDir, 'cmudict.txt'));
    const supplementLexicon = FrontendResources.loadSupplementLexicon(joinPath(normalizedDir, 'supplement_lexicon.json'));
    const loaded: LoadedPackage = {
      rootDir: normalizedDir,
      manifest,
      wordPinyin,
      overrideWordPinyin,
      polyphonicWords: new Set<string>(readNonEmptyLines(joinPath(normalizedDir, 'polychar.txt'))),
      maxWordLength: FrontendResources.maxWordLength(wordPinyin, overrideWordPinyin),
      cmudict,
      supplementLexicon,
      englishLexicon: FrontendResources.mergeEnglishLexicon(cmudict, supplementLexicon),
      frontendRules: FrontendResources.loadFrontendRules(joinPath(normalizedDir, 'frontend_rules.json')),
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

  private static loadWordPinyinOverrides(modelPackageDir: string): Map<string, string> {
    const output = new Map<string, string>();
    FrontendResources.mergeWordPinyinText(output, joinPath(modelPackageDir, 'polyphone_phrases.txt'));
    FrontendResources.mergeWordPinyinText(output, joinPath(modelPackageDir, 'chinese_surname_lexicon.txt'));
    return output;
  }

  private static mergeWordPinyinText(output: Map<string, string>, filePath: string): void {
    const text = readTextSafely(filePath);
    if (text.length === 0) {
      return;
    }
    text.split(/\r?\n/).forEach((line: string): void => {
      const trimmed = line.trim();
      if (trimmed.length === 0 || trimmed.startsWith('#')) {
        return;
      }
      const parts = trimmed.split('\t');
      if (parts.length === 2) {
        output.set(parts[0], parts[1]);
      }
    });
  }

  private static maxWordLength(wordPinyin: Map<string, string>, overrideWordPinyin: Map<string, string>): number {
    let maxLength = 1;
    wordPinyin.forEach((_value: string, key: string): void => {
      if (key.length > maxLength) {
        maxLength = key.length;
      }
    });
    overrideWordPinyin.forEach((_value: string, key: string): void => {
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

  private static loadSupplementLexicon(filePath: string): Map<string, Array<string>> {
    const output = new Map<string, Array<string>>();
    const raw = readJsonFile<Record<string, Object>>(filePath);
    const entries = raw['entries'] as Record<string, Object> | undefined;
    if (entries === undefined || typeof entries !== 'object') {
      return output;
    }
    Object.keys(entries).forEach((key: string): void => {
      const entry = entries[key] as Record<string, Object>;
      const phones = entry['phones'] as Array<string> | undefined;
      if (Array.isArray(phones) && phones.length > 0) {
        output.set(key.toUpperCase(), phones.slice());
      }
    });
    return output;
  }

  private static mergeEnglishLexicon(
    cmudict: Map<string, Array<string>>,
    supplementLexicon: Map<string, Array<string>>
  ): Map<string, Array<string>> {
    const output = new Map<string, Array<string>>();
    cmudict.forEach((value: Array<string>, key: string): void => {
      output.set(key, value);
    });
    supplementLexicon.forEach((value: Array<string>, key: string): void => {
      if (!output.has(key)) {
        output.set(key, value);
      }
    });
    return output;
  }

  private static loadFrontendRules(filePath: string): Array<FrontendReplacementRule> {
    if (!isRegularFile(filePath)) {
      return [];
    }
    const raw = readJsonFile<Record<string, Object>>(filePath);
    const replacements = raw['replacements'] as Array<Record<string, Object>> | undefined;
    if (!Array.isArray(replacements)) {
      return [];
    }
    const output: Array<FrontendReplacementRule> = [];
    replacements.forEach((item: Record<string, Object>, index: number): void => {
      const name = typeof item['name'] === 'string' ? item['name'] as string : `rule-${index}`;
      const pattern = typeof item['pattern'] === 'string' ? item['pattern'] as string : '';
      const replacement = typeof item['replacement'] === 'string' ? item['replacement'] as string : '';
      const rawStages = item['stages'] as Array<string> | undefined;
      if (pattern.length === 0 || replacement.length === 0 || !Array.isArray(rawStages) || rawStages.length === 0) {
        return;
      }
      output.push({
        name,
        pattern,
        replacement,
        stages: new Set<string>(rawStages.filter((stage: string): boolean => stage.length > 0))
      });
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

class DingqiaoTnNormalizer {
  static normalize(resources: LoadedPackage, text: string, language: string, languageContext: string): string {
    const input = DingqiaoTnNormalizer.prepareInput(resources, text, languageContext);
    console.info(`${TN_LOG_TAG} normalize start language=${language} languageContext=${languageContext} inputLen=${input.length} root=${resources.rootDir}`);
    if (input.length === 0) {
      console.info(`${TN_LOG_TAG} normalize skip empty input`);
      return text;
    }
    if (!DingqiaoTnNormalizer.hasTnBinaries(resources)) {
      console.error(`${TN_LOG_TAG} normalize skip missing binaries zh=${DingqiaoTnNormalizer.binaryPath(resources, 'zh')} en=${DingqiaoTnNormalizer.binaryPath(resources, 'en')}`);
      return text;
    }
    let output: string;
    try {
      if (language === 'en-US' || languageContext === 'en-US') {
        output = DingqiaoTnNormalizer.normalizeSegments(resources, [{ text: input, lang: 'en' }]);
      } else {
        output = DingqiaoTnNormalizer.normalizeSegments(resources, DingqiaoTnNormalizer.segmentZhEn(input));
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

  private static prepareInput(resources: LoadedPackage, text: string, languageContext: string): string {
    let output = '';
    const normalized = LitsTtsFrontend.applyFrontendRules(
      resources,
      'pre_tn',
      LitsTtsFrontend.preprocessZhMixedInput(LitsTtsFrontend.normalizeText(text, languageContext))
    );
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

  private static normalizeSegments(resources: LoadedPackage, segments: Array<TnTextSegment>): string {
    const tnSegments = segments.flatMap((segment: TnTextSegment): Array<TnTextSegment> =>
      DingqiaoTnNormalizer.splitLongSegment(segment)
    );
    console.info(`${TN_LOG_TAG} normalize segments original=${segments.length} tn=${tnSegments.length}`);
    const output: Array<string> = [];
    for (let index = 0; index < tnSegments.length; index += 1) {
      const segment = tnSegments[index];
      if (index >= MAX_TN_SEGMENTS_PER_REQUEST) {
        const fallback = tnSegments.slice(index)
          .map((item: TnTextSegment): string => item.text)
          .join('');
        console.error(`${TN_LOG_TAG} normalize segment cap reached processed=${index} total=${tnSegments.length} fallbackLen=${fallback.length}`);
        output.push(fallback);
        break;
      }
      output.push(DingqiaoTnNormalizer.normalizeSegment(resources, segment.text, segment.lang));
    }
    return output.join('');
  }

  private static hasTnBinaries(resources: LoadedPackage): boolean {
    const zhPath = DingqiaoTnNormalizer.binaryPath(resources, 'zh');
    const enPath = DingqiaoTnNormalizer.binaryPath(resources, 'en');
    const zhExists = isRegularFile(zhPath);
    const enExists = isRegularFile(enPath);
    console.info(`${TN_LOG_TAG} binary check zh=${zhExists} path=${zhPath} en=${enExists} path=${enPath}`);
    return zhExists && enExists;
  }

  private static normalizeSegment(resources: LoadedPackage, text: string, lang: string): string {
    if (text.trim().length === 0) {
      return text;
    }
    const binaryPath = DingqiaoTnNormalizer.binaryPath(resources, lang);
    console.info(`${TN_LOG_TAG} segment start lang=${lang} textLen=${text.length} binary=${binaryPath} root=${resources.rootDir} preview=${DingqiaoTnNormalizer.preview(text)}`);
    try {
      const normalized = resolveNativeTtsModule().normalizeTnSegment(
        binaryPath,
        resources.rootDir,
        text
      );
      console.info(`${TN_LOG_TAG} segment success lang=${lang} outputLen=${normalized.length} preview=${DingqiaoTnNormalizer.preview(normalized)}`);
      return normalized;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error(`${TN_LOG_TAG} segment failed lang=${lang} binary=${binaryPath} root=${resources.rootDir} message=${message}`);
      return text;
    }
  }

  private static binaryPath(resources: LoadedPackage, lang: string): string {
    return joinPath(resources.rootDir, lang === 'en' ? 'tn-bin/arm64-v8a/en_tts' : 'tn-bin/arm64-v8a/zh_tts');
  }

  private static preview(text: string): string {
    const singleLine = text.replace(/\s+/g, ' ');
    return singleLine.length > 80 ? `${singleLine.substring(0, 80)}...` : singleLine;
  }

  private static splitLongSegment(segment: TnTextSegment): Array<TnTextSegment> {
    if (segment.text.length <= MAX_TN_SEGMENT_LENGTH) {
      return [segment];
    }
    const output: Array<TnTextSegment> = [];
    let current = '';
    for (let index = 0; index < segment.text.length; index += 1) {
      const char = segment.text[index];
      current += char;
      const canSplitAtBoundary = current.length >= PREFERRED_TN_SEGMENT_LENGTH &&
        (DingqiaoTnNormalizer.isTnSplitBoundary(char) || LitsTtsFrontend.isWhitespace(char));
      const mustSplit = current.length >= MAX_TN_SEGMENT_LENGTH;
      if (canSplitAtBoundary || mustSplit) {
        output.push({ text: current, lang: segment.lang });
        current = '';
      }
    }
    if (current.length > 0) {
      output.push({ text: current, lang: segment.lang });
    }
    return output.length > 0 ? output : [segment];
  }

  private static isTnSplitBoundary(char: string): boolean {
    return char === ',' || char === '.' || char === '!' || char === '?' ||
      char === ';' || char === ':' || char === '\u3002' || char === '\uFF01' ||
      char === '\uFF1F' || char === '\uFF1B' || char === '\uFF1A';
  }

  private static segmentZhEn(text: string): Array<TnTextSegment> {
    const segments: Array<TnTextSegment> = [];
    let index = 0;
    while (index < text.length) {
      const char = text[index];
      if (LitsTtsFrontend.isEnglishLetter(char)) {
        const end = DingqiaoTnNormalizer.scanAsciiRun(text, index);
        const segment = text.substring(index, end);
        const lang = DingqiaoTnNormalizer.protectedAsciiRunLang(text, index, end, segment) ?? 'en';
        segments.push({ text: segment, lang });
        index = end;
      } else {
        const end = DingqiaoTnNormalizer.scanNonAsciiRun(text, index);
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
      (!LitsTtsFrontend.isEnglishLetter(text[index]) || DingqiaoTnNormalizer.isAsciiCelsiusUnit(text, index))
    ) {
      index += 1;
    }
    return index;
  }

  private static isAsciiCelsiusUnit(text: string, index: number): boolean {
    return index > 0 && text[index - 1] === '\u00B0' && (text[index] === 'C' || text[index] === 'c');
  }

  private static protectedAsciiRunLang(text: string, start: number, end: number, run: string): string | undefined {
    if (DingqiaoTnNormalizer.isProtectedChemicalFormula(run)) {
      return 'en';
    }
    if (DingqiaoTnNormalizer.isChineseContextCode(text, start, end, run)) {
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
    const tnText = alreadyNormalized ? text : DingqiaoTnNormalizer.normalize(resources, text, language, languageContext);
    const arpabetTokens = LitsTtsFrontend.tokenizeArpabetInput(resources, tnText);
    if (arpabetTokens !== undefined) {
      return LitsTtsFrontend.metricFromTokens(text, tnText, arpabetTokens, resources);
    }
    const normalized = LitsTtsFrontend.normalizeTechnicalText(
      resources,
      LitsTtsFrontend.normalizeText(
        LitsTtsFrontend.applyFrontendRules(resources, 'pre_frontend', LitsTtsFrontend.preprocessZhMixedInput(tnText)),
        languageContext
      ),
      languageContext
    ).trim();
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
          const syllables = LitsTtsFrontend.restoreOverridePinyin(
            resources,
            chineseText,
            LitsTtsFrontend.applyMandarinToneSandhi(
              chineseText,
              LitsTtsFrontend.hanziChunkToPinyin(resources, chineseText)
            )
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
        const hanziText = normalized.substring(index, end);
        const syllables = LitsTtsFrontend.restoreOverridePinyin(
          resources,
          hanziText,
          LitsTtsFrontend.applyMandarinToneSandhi(
            hanziText,
            LitsTtsFrontend.hanziChunkToPinyin(resources, hanziText)
          )
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
        const word = normalized.substring(index, end);
        const phones = LitsTtsFrontend.phonesForEnglishWord(
          resources,
          word,
          LitsTtsFrontend.shouldPreferLetterName(normalized, end, word)
        );
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

  static applyFrontendRules(resources: LoadedPackage, stage: string, text: string): string {
    let output = text;
    resources.frontendRules.forEach((rule: FrontendReplacementRule): void => {
      if (rule.stages.has(stage)) {
        output = LitsTtsFrontend.applyFrontendReplacementRule(rule, output);
      }
    });
    return output;
  }

  private static applyFrontendReplacementRule(rule: FrontendReplacementRule, text: string): string {
    const regex = new RegExp(rule.pattern, 'gi');
    let output = '';
    let cursor = 0;
    let match = regex.exec(text);
    while (match !== null) {
      output += text.substring(cursor, match.index);
      output += LitsTtsFrontend.renderFrontendReplacement(rule.replacement, match);
      cursor = match.index + match[0].length;
      if (match[0].length === 0) {
        regex.lastIndex += 1;
      }
      match = regex.exec(text);
    }
    output += text.substring(cursor);
    return output;
  }

  private static renderFrontendReplacement(template: string, groups: RegExpExecArray): string {
    let output = '';
    let index = 0;
    while (index < template.length) {
      if (template[index] === '$' && index + 1 < template.length) {
        const groupIndex = Number.parseInt(template[index + 1], 10);
        if (!Number.isNaN(groupIndex)) {
          output += groups[groupIndex] ?? '';
          index += 2;
          continue;
        }
      }
      output += template[index];
      index += 1;
    }
    return output;
  }

  private static metricFromTokens(
    rawText: string,
    tnText: string,
    output: Array<string>,
    resources: LoadedPackage
  ): TextMetric {
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
    return {
      rawText,
      tnText,
      cleanedText: output.join(' '),
      cleanedTokenLength: ids.length,
      modelTokenLength: ids.length,
      tokenIds: ids,
      tokenIdHead: ids.slice(0, Math.min(24, ids.length)),
      tokenIdTail: ids.slice(Math.max(0, ids.length - 24), ids.length)
    };
  }

  static splitForStreaming(
    resources: LoadedPackage,
    text: string,
    language: string = 'zh-en',
    languageContext: string = 'zh-en',
    wordsPerSegment: number = DEFAULT_WORDS_PER_STREAMING_SEGMENT
  ): Array<string> {
    const tnText = DingqiaoTnNormalizer.normalize(resources, text, language, languageContext);
    const normalized = LitsTtsFrontend.normalizeText(LitsTtsFrontend.preprocessZhMixedInput(tnText), languageContext).trim();
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

  static preprocessZhMixedInput(text: string): string {
    let normalized = text.replace(
      COMMA_INTEGER_CURRENCY_REGEX,
      (_match: string, prefix: string, value: string): string => `${prefix}${LitsTtsFrontend.compactIntegerCurrencyWithCommas(value)}`
    );
    normalized = normalized.replace(
      THOUSANDS_SEPARATOR_REGEX,
      (_match: string, digit: string): string => digit
    );
    normalized = normalized.replace(
      NEGATIVE_TEMPERATURE_RANGE_REGEX,
      (_match: string, prefix: string, low: string, high: string, unit: string): string =>
        `${prefix}零下${LitsTtsFrontend.numberTextToHanzi(low)}到${LitsTtsFrontend.numberTextToHanzi(high)}${unit}`
    );
    normalized = normalized.replace(
      NEGATIVE_TEMPERATURE_REGEX,
      (_match: string, prefix: string, value: string, unit: string): string =>
        `${prefix}零下${LitsTtsFrontend.numberTextToHanzi(value)}${unit}`
    );
    normalized = normalized.replace(
      CLOCK_MINUTE_LEADING_ZERO_REGEX,
      (_match: string, prefix: string, hour: string, minute: string): string =>
        `${prefix}${LitsTtsFrontend.numberTextToHanzi(hour)}点零${LitsTtsFrontend.digitToChinese(minute)}分`
    );
    normalized = normalized.replace(
      HANZI_CLOCK_MINUTE_LEADING_ZERO_REGEX,
      (_match: string, hour: string, minute: string): string =>
        `${hour}点零${LitsTtsFrontend.digitToChinese(minute)}分`
    );
    normalized = normalized.replace(
      DURATION_MINUTE_LEADING_ZERO_REGEX,
      (_match: string, prefix: string, hour: string, minute: string): string =>
        `${prefix}${LitsTtsFrontend.numberTextToHanzi(hour)}小时零${LitsTtsFrontend.numberTextToHanzi(minute)}分钟`
    );
    normalized = normalized.replace(
      YEAR_MONTH_LEADING_ZERO_REGEX,
      (_match: string, prefix: string, month: string): string => `${prefix}零${LitsTtsFrontend.numberTextToHanzi(month)}月`
    );
    normalized = normalized.replace(
      YEAR_MONTH_REGEX,
      (_match: string, prefix: string, month: string): string => `${prefix}${LitsTtsFrontend.numberTextToHanzi(month)}月`
    );
    normalized = normalized.replace(
      MONTH_DAY_LEADING_ZERO_REGEX,
      (_match: string, prefix: string, day: string): string => `${prefix}零${LitsTtsFrontend.numberTextToHanzi(day)}日`
    );
    normalized = normalized.replace(
      MONTH_DAY_REGEX,
      (_match: string, prefix: string, day: string, suffix: string): string =>
        `${prefix}${LitsTtsFrontend.numberTextToHanzi(day)}${suffix}`
    );
    normalized = normalized.replace(
      SERIAL_CODE_REGEX,
      (_match: string, prefix: string, space: string, code: string): string =>
        `${prefix}${space}${LitsTtsFrontend.normalizeSerialCode(code)}`
    );
    return normalized;
  }

  private static normalizeSerialCode(code: string): string {
    let output = '';
    for (let index = 0; index < code.length; index += 1) {
      const char = code[index];
      output += CHINESE_DIGIT_TEXT_BY_CHAR.get(char) ?? char;
    }
    return output;
  }

  private static compactIntegerCurrencyWithCommas(text: string): string {
    const compact = text.replace(/,/g, '');
    const value = Number.parseInt(compact, 10);
    if (!Number.isFinite(value)) {
      return compact;
    }
    if (value >= 100000000 && value % 100000000 === 0) {
      return `${LitsTtsFrontend.integerTextToHanzi(`${value / 100000000}`)}亿`;
    }
    if (value >= 10000 && value % 10000 === 0) {
      return `${LitsTtsFrontend.integerTextToHanzi(`${value / 10000}`)}万`;
    }
    return `${value}`;
  }

  private static digitToChinese(digit: string): string {
    return CHINESE_DIGIT_TEXT_BY_CHAR.get(digit) ?? digit;
  }

  private static numberTextToHanzi(text: string): string {
    const parts = text.split('.');
    const integer = LitsTtsFrontend.integerTextToHanzi(parts[0]);
    if (parts.length === 1) {
      return integer;
    }
    return integer + '点' + parts[1].split('').map((char: string): string => LitsTtsFrontend.digitToChinese(char)).join('');
  }

  private static integerTextToHanzi(text: string): string {
    const value = Number.parseInt(text, 10);
    if (!Number.isFinite(value)) {
      return text.split('').map((char: string): string => LitsTtsFrontend.digitToChinese(char)).join('');
    }
    if (value === 0) {
      return '零';
    }
    if (value < 10) {
      return LitsTtsFrontend.digitToChinese(`${value}`);
    }
    if (value < 20) {
      const ones = value % 10;
      return '十' + (ones === 0 ? '' : LitsTtsFrontend.digitToChinese(`${ones}`));
    }
    if (value < 100) {
      const tens = Math.floor(value / 10);
      const ones = value % 10;
      return LitsTtsFrontend.digitToChinese(`${tens}`) + '十' + (
        ones === 0 ? '' : LitsTtsFrontend.digitToChinese(`${ones}`)
      );
    }
    if (value < 1000) {
      const hundreds = Math.floor(value / 100);
      const remainder = value % 100;
      if (remainder === 0) {
        return LitsTtsFrontend.digitToChinese(`${hundreds}`) + '百';
      }
      if (remainder < 10) {
        return LitsTtsFrontend.digitToChinese(`${hundreds}`) + '百零' + LitsTtsFrontend.digitToChinese(`${remainder}`);
      }
      return LitsTtsFrontend.digitToChinese(`${hundreds}`) + '百' + LitsTtsFrontend.integerTextToHanzi(`${remainder}`);
    }
    return text.split('').map((char: string): string => LitsTtsFrontend.digitToChinese(char)).join('');
  }

  private static normalizeTechnicalText(resources: LoadedPackage, text: string, languageContext: string): string {
    let normalized = LitsTtsFrontend.applyFrontendRules(resources, 'post_frontend', text);
    normalized = normalized.replace(
      PERCENT_NUMBER_REGEX,
      (_match: string, numberText: string): string => `百分之${LitsTtsFrontend.numberTextToHanzi(numberText)}`
    );
    if (languageContext !== 'en-US') {
      normalized = normalized.replace(/\b(?:dot|point)\b/gi, '点');
      normalized = normalized.replace(/\bunderscore\b/gi, '下划线');
    }
    normalized = normalized.replace(
      VERSION_NUMBER_WITH_SUFFIX_REGEX,
      (_match: string, prefix: string, version: string): string =>
        prefix + version.split('.').map((part: string): string => LitsTtsFrontend.numberTextToHanzi(part)).join('点')
    );
    normalized = normalized.replace(DIGIT_DOT_REGEX, '$1点');
    normalized = normalized.replace(HANZI_DIGIT_DOT_REGEX, '$1点');
    normalized = normalized.replace(LEADING_DOT_ASCII_TOKEN_REGEX, '$1点');
    normalized = normalized.replace(CARET_POWER_TWO_REGEX, '平方');
    if (languageContext !== 'en-US') {
      normalized = normalized.replace(/=/g, '等于');
      normalized = normalized.replace(
        URL_SCHEME_SEPARATOR_REGEX,
        (_match: string, prefix: string, scheme: string): string => `${prefix}${scheme}冒号斜杠斜杠`
      );
    }
    normalized = normalized.replace(
      TECHNICAL_ASCII_TOKEN_REGEX,
      (_match: string, prefix: string, token: string): string => {
        if (languageContext === 'en-US' || LitsTtsFrontend.looksLikeIpv6(token) || !LitsTtsFrontend.hasTechnicalSymbol(token)) {
          return prefix + token;
        }
        let output = '';
        for (let index = 0; index < token.length; index += 1) {
          const char = token[index];
          output += TECHNICAL_SYMBOL_READINGS.get(char) ?? char;
        }
        return prefix + output;
      }
    );
    return LitsTtsFrontend.normalizeResidualSymbols(normalized, languageContext);
  }

  private static normalizeResidualSymbols(text: string, languageContext: string): string {
    let output = '';
    for (let index = 0; index < text.length; index += 1) {
      const code = text.charCodeAt(index);
      if (LitsTtsFrontend.isHighSurrogate(code)) {
        if (index + 1 < text.length && LitsTtsFrontend.isLowSurrogate(text.charCodeAt(index + 1))) {
          index += 1;
        }
        output += ',';
        continue;
      }
      if (LitsTtsFrontend.isLowSurrogate(code) || LitsTtsFrontend.isIgnoredFormatCode(code)) {
        continue;
      }
      const char = text[index];
      if (LitsTtsFrontend.isSupportedFrontendChar(char)) {
        output += char;
      } else if (languageContext !== 'en-US') {
        output += ZH_EN_FRONTEND_CHAR_REPLACEMENTS.get(char) ??
          ZH_EN_ASCII_SYMBOL_TEXT.get(char) ??
          SYMBOL_TO_SAFE_PUNCTUATION.get(char) ??
          ',';
      } else {
        output += SYMBOL_TO_SAFE_PUNCTUATION.get(char) ?? ',';
      }
    }
    return output;
  }

  private static hasTechnicalSymbol(token: string): boolean {
    for (let index = 0; index < token.length; index += 1) {
      if (TECHNICAL_SYMBOL_READINGS.has(token[index])) {
        return true;
      }
    }
    return false;
  }

  private static looksLikeIpv6(token: string): boolean {
    let colonCount = 0;
    for (let index = 0; index < token.length; index += 1) {
      const char = token[index].toLowerCase();
      if (char === ':') {
        colonCount += 1;
      } else if (!LitsTtsFrontend.isAsciiDigit(char) && (char < 'a' || char > 'f')) {
        return false;
      }
    }
    return colonCount >= 2;
  }

  private static normalizeFrontendChar(char: string, languageContext: string): string {
    const code = char.charCodeAt(0);
    if (code === 0x3000) {
      return ' ';
    }
    if (code >= 0xFF10 && code <= 0xFF19) {
      return String.fromCharCode(code - 0xFEE0);
    }
    if ((code >= 0xFF21 && code <= 0xFF3A) || (code >= 0xFF41 && code <= 0xFF5A)) {
      return String.fromCharCode(code - 0xFEE0);
    }
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
    let longestOverride = '';
    resources.overrideWordPinyin.forEach((_pinyin: string, word: string): void => {
      if (word.length > 1 && word.length > longestOverride.length && text.startsWith(word, start)) {
        longestOverride = word;
      }
    });
    if (longestOverride.length > 0) {
      return longestOverride;
    }
    const maxLength = Math.min(resources.maxWordLength, text.length - start);
    for (let length = maxLength; length >= 2; length -= 1) {
      const candidate = text.substring(start, start + length);
      if (resources.overrideWordPinyin.has(candidate) || resources.wordPinyin.has(candidate)) {
        return candidate;
      }
    }
    return text[start];
  }

  private static lexiconPinyinForWord(resources: LoadedPackage, word: string): Array<string> {
    const override = resources.overrideWordPinyin.get(word);
    if (override !== undefined) {
      const overrideTokens = LitsTtsFrontend.normalizeLexiconPinyin(override);
      if (overrideTokens.length > 0) {
        return overrideTokens;
      }
    }
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

  private static applyMandarinToneSandhi(text: string, tokens: Array<string>): Array<string> {
    const output = LitsTtsFrontend.applyThirdToneSandhi(tokens);
    if (text.length !== output.length) {
      return output;
    }
    if (text.length > 1 && LitsTtsFrontend.isChineseDigitSequence(text)) {
      return output;
    }
    LitsTtsFrontend.applyBuSandhi(text, output);
    LitsTtsFrontend.applyYiSandhi(text, output);
    LitsTtsFrontend.applyErSandhi(text, output);
    return output;
  }

  private static restoreOverridePinyin(resources: LoadedPackage, text: string, tokens: Array<string>): Array<string> {
    if (text.length !== tokens.length || resources.overrideWordPinyin.size === 0) {
      return tokens;
    }
    const output = tokens.slice();
    const occupied: Array<boolean> = new Array<boolean>(output.length).fill(false);
    const entries: Array<[string, string]> = [];
    resources.overrideWordPinyin.forEach((pinyin: string, word: string): void => {
      if (word.length > 1) {
        entries.push([word, pinyin]);
      }
    });
    entries.sort((left: [string, string], right: [string, string]): number => right[0].length - left[0].length);
    entries.forEach((entry: [string, string]): void => {
      const word = entry[0];
      const syllables = LitsTtsFrontend.normalizeLexiconPinyin(entry[1]);
      if (syllables.length !== word.length) {
        return;
      }
      let start = text.indexOf(word);
      while (start >= 0) {
        const end = start + word.length;
        let free = true;
        for (let index = start; index < end; index += 1) {
          if (occupied[index]) {
            free = false;
            break;
          }
        }
        if (free) {
          syllables.forEach((syllable: string, offset: number): void => {
            output[start + offset] = syllable;
            occupied[start + offset] = true;
          });
        }
        start = text.indexOf(word, start + 1);
      }
    });
    return output;
  }

  private static isChineseDigitSequence(text: string): boolean {
    for (let index = 0; index < text.length; index += 1) {
      if (!CHINESE_DIGIT_SEQUENCE_CHARS.has(text[index])) {
        return false;
      }
    }
    return true;
  }

  private static applyBuSandhi(text: string, tokens: Array<string>): void {
    if (/^不+$/.test(text) || text === '不字') {
      return;
    }
    if (text.length === 3 && text[1] === '不' && (tokens[1] ?? '').startsWith('bu')) {
      tokens[1] = LitsTtsFrontend.changePinyinTone(tokens[1], '5');
      return;
    }
    for (let index = 0; index < text.length; index += 1) {
      if (text[index] === '不' && (tokens[index + 1] ?? '').endsWith('4')) {
        tokens[index] = LitsTtsFrontend.changePinyinTone(tokens[index], '2');
      }
    }
  }

  private static applyYiSandhi(text: string, tokens: Array<string>): void {
    if (text.length === 3 && text[1] === '一' && text[0] === text[2]) {
      tokens[1] = LitsTtsFrontend.changePinyinTone(tokens[1], '5');
      return;
    }
    if (text.startsWith('第一') && tokens.length > 1) {
      tokens[1] = LitsTtsFrontend.changePinyinTone(tokens[1], '1');
    }
    if (text.startsWith('一月') || text.startsWith('一日') || text.startsWith('一号')) {
      tokens[0] = LitsTtsFrontend.changePinyinTone(tokens[0], '1');
    }
    for (let index = 0; index < text.length; index += 1) {
      if (text[index] !== '一') {
        continue;
      }
      if ((tokens[index] ?? '').startsWith('yi') && (tokens[index] ?? '').endsWith('5')) {
        continue;
      }
      const next = tokens[index + 1] ?? '';
      if (next.endsWith('4')) {
        tokens[index] = LitsTtsFrontend.changePinyinTone(tokens[index], '2');
      } else if (next.length > 0 && PINYIN_SYLLABLE_REGEX.test(next)) {
        tokens[index] = LitsTtsFrontend.changePinyinTone(tokens[index], '4');
      }
    }
  }

  private static applyErSandhi(text: string, tokens: Array<string>): void {
    const lastToken = tokens[tokens.length - 1];
    if (text.length > 1 && text[text.length - 1] === '儿' && lastToken !== undefined && lastToken.startsWith('er')) {
      tokens[tokens.length - 1] = LitsTtsFrontend.changePinyinTone(lastToken, '5');
    }
  }

  private static changePinyinTone(syllable: string, tone: string): string {
    if (!PINYIN_SYLLABLE_REGEX.test(syllable)) {
      return syllable;
    }
    return syllable.substring(0, syllable.length - 1) + tone;
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

  private static phonesForEnglishWord(
    resources: LoadedPackage,
    rawWord: string,
    preferLetterName: boolean = false
  ): Array<string> {
    const normalized = rawWord.toUpperCase();
    if (preferLetterName && rawWord.length === 1) {
      const letterPhones = LitsTtsFrontend.letterPhones(resources, normalized);
      if (letterPhones.length > 0) {
        return letterPhones;
      }
    }
    const supplement = resources.supplementLexicon.get(normalized);
    if (supplement !== undefined) {
      return supplement;
    }
    if (LitsTtsFrontend.shouldSpellUppercaseWord(rawWord, normalized)) {
      const spelled = LitsTtsFrontend.spellEnglishWord(resources, normalized);
      if (spelled.length > 0) {
        return spelled;
      }
    }
    const direct = resources.englishLexicon.get(normalized);
    if (direct !== undefined) {
      return direct;
    }
    if (normalized.indexOf('-') >= 0) {
      const output: Array<string> = [];
      normalized.split('-').forEach((part: string): void => {
        if (part.length === 0) {
          return;
        }
        const mapped = resources.englishLexicon.get(part) ??
          LitsTtsFrontend.spellEnglishWord(resources, part);
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

  private static shouldSpellUppercaseWord(rawWord: string, normalized: string): boolean {
    if (rawWord.length <= 1 || ACRONYM_WORD_READINGS.has(normalized)) {
      return false;
    }
    for (let index = 0; index < rawWord.length; index += 1) {
      const char = rawWord[index];
      if (char < 'A' || char > 'Z') {
        return false;
      }
    }
    return true;
  }

  private static shouldPreferLetterName(text: string, end: number, word: string): boolean {
    if (word.length !== 1 || !LitsTtsFrontend.isEnglishLetter(word)) {
      return false;
    }
    if (word.toUpperCase() !== 'A') {
      return true;
    }
    return !LitsTtsFrontend.hasEnglishWordAfter(text, end);
  }

  private static hasEnglishWordAfter(text: string, start: number): boolean {
    for (let index = start; index < text.length; index += 1) {
      if (LitsTtsFrontend.isEnglishLetter(text[index])) {
        return true;
      }
    }
    return false;
  }

  private static letterPhones(resources: LoadedPackage, letter: string): Array<string> {
    return resources.cmudict.get(letter) ?? [];
  }

  private static tokenizeArpabetInput(resources: LoadedPackage, text: string): Array<string> | undefined {
    let normalized = text.replace(/\//g, ' / ')
      .replace(/\|/g, ' | ')
      .replace(/_/g, ' _ ')
      .trim();
    if (normalized.length === 0) {
      return undefined;
    }
    for (let index = 0; index < normalized.length; index += 1) {
      if (LitsTtsFrontend.isHanzi(normalized[index])) {
        return undefined;
      }
    }
    const parts = splitByWhitespace(normalized);
    if (parts.length === 0) {
      return undefined;
    }
    const output: Array<string> = [];
    let sawPhone = false;
    let endedWithPunctuation = false;
    for (let index = 0; index < parts.length; index += 1) {
      const part = parts[index];
      const token = part.toUpperCase();
      if (ARPABET_BOUNDARY_TOKENS.has(part)) {
        LitsTtsFrontend.appendBoundary(output);
        endedWithPunctuation = false;
      } else if (part.length === 1 && PUNCTUATION_SET.has(part)) {
        LitsTtsFrontend.appendPunctuation(output, part);
        endedWithPunctuation = true;
      } else if (resources.arpabetToTokens.has(token)) {
        LitsTtsFrontend.arpabetToTokens(resources, [token]).forEach((phoneToken: string): void => {
          output.push(phoneToken);
        });
        sawPhone = true;
        endedWithPunctuation = false;
      } else {
        return undefined;
      }
    }
    if (sawPhone && !endedWithPunctuation) {
      LitsTtsFrontend.appendPunctuation(output, '.');
    }
    while (output.length > 0 && output[output.length - 1] === '_') {
      output.pop();
    }
    return sawPhone ? output : undefined;
  }

  private static spellEnglishWord(resources: LoadedPackage, word: string): Array<string> {
    const output: Array<string> = [];
    for (let index = 0; index < word.length; index += 1) {
      const char = word[index];
      if (!LitsTtsFrontend.isEnglishLetter(char)) {
        continue;
      }
      const phones = LitsTtsFrontend.letterPhones(resources, char.toUpperCase());
      if (phones.length === 0) {
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
    return LitsTtsFrontend.mergeEnglishTokens(resources, rawTokens);
  }

  private static mergeEnglishTokens(resources: LoadedPackage, tokens: Array<string>): Array<string> {
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
          if (resources.symbolToId.has(rule.replacement)) {
            output.push(rule.replacement);
            index += rule.pair.length;
            merged = true;
          }
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

  static applyPitchAndVolume(source: ArrayBuffer, params: SpeakParams): ArrayBuffer {
    const pitch = params.pitch ?? 1.0;
    const volume = params.volume ?? 1.0;
    if (pitch === 1.0 && volume === 1.0) {
      return source;
    }
    let samples = new Int16Array(source.slice(0));
    if (pitch !== 1.0) {
      samples = AudioTransforms.applyPitch(samples, clampNumber(pitch, 0.5, 2.0));
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
  private rendererSampleRate: number = DEFAULT_SAMPLE_RATE;

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
    onSynthesisComplete: () => void,
    onFirstAudioWritten: () => void = (): void => {}
  ): Promise<void> {
    this.stopped = false;
    await this.releaseRenderer();
    const renderer = await this.createRenderer(sampleRate, soundChannel);
    this.renderer = renderer;
    this.rendererSampleRate = sampleRate;
    const queue = new PcmChunkQueue(queueCapacity);
    let queuedChunks = 0;
    let queuedBytes = 0;
    let playbackStartedAt = 0;
    let producerError: string | undefined = undefined;
    let playbackError: string | undefined = undefined;

    console.error(
      `[LitsTtsPlaybackTrace] playStreaming start sampleRate=${sampleRate}` +
        ` queueCapacity=${queueCapacity} soundChannel=${soundChannel ?? 'default'}`
    );
    const playbackPromise = (async (): Promise<void> => {
      try {
        await queue.waitForPrebuffer(STREAMING_PREBUFFER_CHUNKS);
        if (this.stopped) {
          console.error('[LitsTtsPlaybackTrace] playback stopped before renderer.start');
          return;
        }
        await renderer.start();
        playbackStartedAt = Date.now();
        onFirstAudioWritten();
        console.error(`[LitsTtsPlaybackTrace] renderer started prebuffer=${STREAMING_PREBUFFER_CHUNKS}`);
        while (!this.stopped) {
          const next = await queue.take();
          if (next.done) {
            console.error(`[LitsTtsPlaybackTrace] queue done writtenBytes=${queuedBytes} queuedChunks=${queuedChunks}`);
            return;
          }
          if (next.chunk !== undefined) {
            const written = await this.writeToRenderer(renderer, next.chunk);
            queuedBytes += written;
            console.error(
              `[LitsTtsPlaybackTrace] renderer write chunkBytes=${next.chunk.byteLength}` +
                ` written=${written} totalWritten=${queuedBytes}`
            );
          }
        }
      } catch (error) {
        playbackError = formatError(error);
        console.error(`[LitsTtsPlaybackTrace] playback error ${playbackError}`);
        this.stopped = true;
        queue.close();
      }
    })();

    try {
      try {
        await producer(async (chunk: ArrayBuffer): Promise<void> => {
          if (this.stopped) {
            console.error(`[LitsTtsPlaybackTrace] drop chunk because stopped bytes=${chunk.byteLength}`);
            return;
          }
          queuedChunks += 1;
          console.error(`[LitsTtsPlaybackTrace] enqueue chunk index=${queuedChunks - 1} bytes=${chunk.byteLength}`);
          await queue.put(copyArrayBuffer(chunk, 0, chunk.byteLength));
        });
        console.error(`[LitsTtsPlaybackTrace] producer complete queuedChunks=${queuedChunks}`);
        onSynthesisComplete();
      } catch (error) {
        producerError = formatError(error);
        console.error(`[LitsTtsPlaybackTrace] producer error ${producerError}`);
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
        console.error(`[LitsTtsPlaybackTrace] renderer drain complete totalWritten=${queuedBytes}`);
        await this.waitForPlaybackComplete(queuedBytes, playbackStartedAt, sampleRate);
        console.error(`[LitsTtsPlaybackTrace] playback wait complete totalWritten=${queuedBytes}`);
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
    this.rendererSampleRate = sampleRate;
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
      await this.waitForPlaybackComplete(AUDIO_CHUNK_BYTES, Date.now(), this.rendererSampleRate);
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
      const written = await renderer.write(chunk);
      if (written <= 0) {
        break;
      }
      offset += Math.min(written, length);
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

  private async waitForPlaybackComplete(totalBytes: number, playbackStartedAt: number, sampleRate: number): Promise<void> {
    if (this.stopped || totalBytes <= 0 || playbackStartedAt <= 0 || sampleRate <= 0) {
      return;
    }
    const targetAudioMs = Math.ceil(totalBytes * 1000 / (sampleRate * 2));
    const elapsedMs = Math.max(0, Date.now() - playbackStartedAt);
    const remainingMs = Math.max(0, targetAudioMs - elapsedMs);
    const waitMs = clampInt(remainingMs + PLAYBACK_DRAIN_PADDING_MS, PLAYBACK_DRAIN_PADDING_MS, PLAYBACK_DRAIN_MAX_MS);
    console.error(
      `[LitsTtsPlaybackTrace] waitForPlaybackComplete totalBytes=${totalBytes}` +
        ` targetAudioMs=${targetAudioMs} elapsedMs=${elapsedMs} waitMs=${waitMs}`
    );
    await new Promise<void>((resolve: () => void): void => {
      setTimeout(resolve, waitMs);
    });
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

  static createEngine(
    params: CreateEngineParams,
    workPath: string | undefined,
    context: common.Context | undefined
  ): TextToSpeechEngine {
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
      const engine = new TextToSpeechEngineImpl(params, speaker, workPath, context, (): boolean => {
        EngineRegistry.activeEngines.delete(engine);
        return EngineRegistry.activeEngines.size === 0;
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
  private readonly modelInfo: string;
  private readonly loadProfileInfo: string;
  private readonly onRelease: () => boolean;
  private readonly player: HarmonyPcmPlayer = new HarmonyPcmPlayer();
  private readonly seenRequestIds: Set<string> = new Set<string>();

  private listener: SpeakListener | undefined;
  private queue: Array<SynthesisTask> = [];
  private currentTask: SynthesisTask | undefined;
  private processing: boolean = false;
  private destroyed: boolean = false;
  // 当前在途的 native synthesizeStreaming(至多一个,处理循环串行执行)。shutdown() 释放 native runtime
  // 前会等它结算,避免 worker 线程仍在解引用 nativeRuntime 时 runtime 就被 delete → native use-after-free。
  private activeSynthesis: Promise<void> | undefined = undefined;
  private released: boolean = false;

  constructor(
    engineParams: CreateEngineParams,
    voice: RegisteredVoice,
    workPath: string | undefined,
    context: common.Context | undefined,
    onRelease: () => boolean
  ) {
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
    this.modelPackageDir = resolveModelPackageDir(this.engineParams.extraParams, workPath, context);
    const loadStartedAt = Date.now();
    this.modelPackage = FrontendResources.load(this.modelPackageDir);
    const runtimeChunkSize = resolveIntegerExtraParam(
      this.engineParams.extraParams,
      ['streamingChunkSize', 'chunkSize'],
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
    this.modelInfo = this.buildModelInfo(runtimeChunkSize);
    this.loadProfileInfo = `createRuntimeWall=${Math.max(0, Date.now() - loadStartedAt)}ms`;
  }

  setListener(listener: SpeakListener): void {
    this.ensureNotDestroyed();
    this.listener = listener;
  }

  speak(text: string, params: SpeakParams): void {
    const listener = this.listener;
    if (listener === undefined) {
      throw new TextToSpeechException(
        TtsErrorCode.ENGINE_NOT_INITIALIZED,
        'listener must be set before speak'
      );
    }
    const rawRequestId = params.requestId;
    if (this.destroyed) {
      listener.onError?.(rawRequestId, TtsErrorCode.ENGINE_DESTROYED, 'engine has been destroyed');
      return;
    }
    const trimmedText = text.trim();
    this.validateSpeak(trimmedText, params);
    const normalizedParams = this.normalizeSpeakParams(params);
    const normalizedText = ensureTerminalPunctuation(trimmedText, this.engineParams.language);
    if (this.seenRequestIds.has(normalizedParams.requestId)) {
      listener.onError?.(normalizedParams.requestId, TtsErrorCode.RUNTIME_EXCEPTION, 'requestId duplicated');
      return;
    }
    // 有界去重集:超过上限即清空,避免长生命周期引擎无限增长(极旧 requestId 被复用时放行是可接受折衷)。
    if (this.seenRequestIds.size >= 4096) {
      this.seenRequestIds.clear();
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
      stopNotified: false,
      startedAtMs: Date.now(),
      playbackStartMs: -1
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
    // 释放 native runtime 前必须等在途的 native synthesizeStreaming 结算:cancelNativeSynthesis() 已置协作
    // 取消标志,在途调用会在下一个 chunk 边界(数毫秒)返回。若此刻直接 releaseRuntime,worker 线程仍在
    // 解引用 this.nativeRuntime → native use-after-free。等 activeSynthesis 结算后再 releaseOnce(幂等)。
    const inFlight = this.activeSynthesis;
    if (inFlight !== undefined) {
      inFlight.then((): void => this.releaseOnce(), (): void => this.releaseOnce());
    } else {
      this.releaseOnce();
    }
  }

  private scheduleProcessing(): void {
    if (this.processing || this.destroyed) {
      return;
    }
    this.processing = true;
    Promise.resolve().then(async (): Promise<void> => {
      try {
        await this.processNextTask();
      } finally {
        this.processing = false;
        if (!this.destroyed && this.hasPendingTask()) {
          this.scheduleProcessing();
        }
      }
    });
  }

  private async processNextTask(): Promise<void> {
    if (this.destroyed) {
      return;
    }
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

  private takeNextTask(): SynthesisTask | undefined {
    while (this.queue.length > 0) {
      const task = this.queue.shift();
      if (task !== undefined && !task.cancelled) {
        return task;
      }
    }
    return undefined;
  }

  private hasPendingTask(): boolean {
    return this.queue.some((task: SynthesisTask): boolean => !task.cancelled);
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
              listener.onComplete?.(
                task.params.requestId,
                this.buildSynthesisCompleteResponse(synthesisMetrics, task.playbackStartMs)
              );
            }
          },
          (): void => {
            if (task.playbackStartMs < 0) {
              task.playbackStartMs = Math.max(0, Date.now() - task.startedAtMs);
            }
          }
        );
        if (task.cancelled || this.destroyed) {
          this.runTerminalCallback(task, (): void => this.notifyStop(listener, task));
          return;
        }
        if (!synthesisCompleteNotified) {
          listener.onComplete?.(
            task.params.requestId,
            this.buildSynthesisCompleteResponse(synthesisMetrics, task.playbackStartMs)
          );
        }
        this.runTerminalCallback(task, (): void => {
          listener.onComplete?.(task.params.requestId, {
            type: CompleteType.PLAYBACK_COMPLETE,
            message: 'playback complete'
          });
        });
        return;
      }
      const synthesisMetrics = await this.synthesizeStreaming(task, listener);
      if (task.cancelled || this.destroyed) {
        this.runTerminalCallback(task, (): void => this.notifyStop(listener, task));
        return;
      }
      this.runTerminalCallback(task, (): void => {
        listener.onComplete?.(task.params.requestId, this.buildSynthesisCompleteResponse(synthesisMetrics));
      });
    } catch (error) {
      const code = error instanceof TextToSpeechException ? error.errorCode : TtsErrorCode.RUNTIME_EXCEPTION;
      const message = error instanceof Error ? error.message : String(error);
      this.runTerminalCallback(task, (): void => {
        listener.onError?.(task.params.requestId, code, message);
      });
      return;
    }
  }

  private runTerminalCallback(task: SynthesisTask, callback: () => void): void {
    if (this.currentTask === task) {
      this.currentTask = undefined;
    }
    callback();
  }

  private synthesizeStreaming(
    task: SynthesisTask,
    listener: SpeakListener,
    chunkWriter?: (chunk: ArrayBuffer) => Promise<void>
  ): Promise<NativeStreamingSynthesisMetrics> {
    const pending = this.synthesizeStreamingInner(task, listener, chunkWriter);
    // 记录在途 native 合成供 shutdown() 等待(见 activeSynthesis 声明)。设置发生在返回 pending 之前、
    // 任何 await 让出事件循环之前,故 native 调用在途时该字段必已被赋值,shutdown 不会漏等。
    this.activeSynthesis = pending.then((): void => {}, (): void => {});
    return pending;
  }

  private async synthesizeStreamingInner(
    task: SynthesisTask,
    listener: SpeakListener,
    chunkWriter?: (chunk: ArrayBuffer) => Promise<void>
  ): Promise<NativeStreamingSynthesisMetrics> {
    const params = task.params;
    const languageContext = params.languageContext ?? 'zh-en';
    const segments = LitsTtsFrontend.splitForStreaming(this.modelPackage, task.text, this.engineParams.language, languageContext);
    const chunkSizeOverride = this.streamingChunkSizeOverride(params);
    let sequence = 0;
    let synthesisMs = 0;
    let firstChunkMs = -1;
    let audioBytes = 0;
    let chunkCount = 0;
    const textMetricSummaries: Array<string> = [];
    const pendingChunkWrites: Array<Promise<void>> = [];
    for (let index = 0; index < segments.length; index += 1) {
      if (task.cancelled || this.destroyed) {
        await Promise.all(pendingChunkWrites);
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
      const lengthScale = lengthScaleForSpeed(params.speed ?? 1.0);
      textMetricSummaries.push(
        `seg=${index} cleaned=${textMetric.cleanedTokenLength} model=${textMetric.modelTokenLength} lengthScale=${lengthScale}`
      );
      console.info(
        `${TEXT_METRIC_LOG_TAG} requestId=${task.params.requestId} segment=${index + 1}/${segments.length}` +
          ` language=${this.engineParams.language} languageContext=${languageContext} speakerId=${this.voice.speakerId}` +
          ` speed=${params.speed ?? 1.0} lengthScale=${lengthScale}` +
          ` raw="${previewForHilLog(textMetric.rawText)}" tn="${previewForHilLog(textMetric.tnText)}"` +
          ` cleaned="${previewForHilLog(textMetric.cleanedText, 240)}"` +
          ` cleanedTokenLength=${textMetric.cleanedTokenLength} modelTokenLength=${textMetric.modelTokenLength}` +
          ` tokenHead=${JSON.stringify(textMetric.tokenIdHead)} tokenTail=${JSON.stringify(textMetric.tokenIdTail)}`
      );
      const segmentMetrics = await resolveNativeTtsModule().synthesizeStreaming(
        this.nativeRuntime,
        segmentTokenIds,
        this.voice.speakerId,
        lengthScale,
        chunkSizeOverride ?? 0,
        (chunk: ArrayBuffer, _nativeSequence: number): void => {
          if (_nativeSequence < 0) {
            console.error(
              `[LitsTtsPlaybackTrace] native progress requestId=${task.params.requestId}` +
                ` segment=${index + 1}/${segments.length} marker=${_nativeSequence} bytes=${chunk.byteLength}`
            );
            return;
          }
          if (task.cancelled || this.destroyed) {
            console.error(`[LitsTtsPlaybackTrace] native callback ignored cancelled bytes=${chunk.byteLength} nativeSequence=${_nativeSequence}`);
            return;
          }
          const transformedChunk = AudioTransforms.applyPitchAndVolume(chunk, params);
          console.error(
            `[LitsTtsPlaybackTrace] native callback requestId=${task.params.requestId}` +
              ` segment=${index + 1}/${segments.length} nativeBytes=${chunk.byteLength}` +
              ` transformedBytes=${transformedChunk.byteLength} nativeSequence=${_nativeSequence} sequence=${sequence}`
          );
          sequence = this.emitAudioChunks(listener, task, transformedChunk, sequence, 'model_stream');
          if (chunkWriter !== undefined) {
            pendingChunkWrites.push(chunkWriter(transformedChunk));
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
    await Promise.all(pendingChunkWrites);
    return { synthesisMs, firstChunkMs, audioBytes, chunkCount, textMetricSummary: textMetricSummaries.join(';') };
  }

  private buildSynthesisCompleteResponse(
    metrics: NativeStreamingSynthesisMetrics | undefined,
    playbackStartMs: number = -1
  ): CompleteResponse {
    if (metrics === undefined) {
      return {
        type: CompleteType.SYNTHESIS_COMPLETE,
        message: 'synthesis complete',
        playbackStartMs
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
      profilingInfo: `chunks=${metrics.chunkCount} audioBytes=${metrics.audioBytes} textMetric=${metrics.textMetricSummary ?? ''}`,
      playbackStartMs
    };
  }

  private streamingChunkSizeOverride(params: SpeakParams): number | undefined {
    return resolveOptionalIntegerExtraParam(
      params.extraParams,
      ['streamingChunkSize', 'chunkSize'],
      MIN_RUNTIME_STREAMING_CHUNK_SIZE,
      MAX_RUNTIME_STREAMING_CHUNK_SIZE
    );
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

  private emitAudioChunks(
    listener: SpeakListener,
    task: SynthesisTask,
    pcm: ArrayBuffer,
    initialSequence: number,
    chunkSource: string
  ): number {
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
        audioType: 'pcm',
        isStreaming: true,
        chunkSource
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
    if (this.engineParams.language !== 'zh-en' && this.engineParams.language !== 'en-US') {
      throw new TextToSpeechException(TtsErrorCode.LANGUAGE_UNSUPPORTED, 'language is not supported');
    }
    if (this.voice.voiceId !== this.engineParams.voiceId) {
      throw new TextToSpeechException(TtsErrorCode.VOICE_UNSUPPORTED, 'voiceId is not supported');
    }
    if (params.pitch !== undefined && (!Number.isFinite(params.pitch) || params.pitch < 0.5 || params.pitch > 2.0)) {
      throw new TextToSpeechException(TtsErrorCode.RUNTIME_EXCEPTION, 'pitch out of range');
    }
    if (params.volume !== undefined && (!Number.isFinite(params.volume) || params.volume < 0.0 || params.volume > 2.0)) {
      throw new TextToSpeechException(TtsErrorCode.RUNTIME_EXCEPTION, 'volume out of range');
    }
    if (
      params.languageContext !== undefined &&
        params.languageContext !== 'zh-CN' &&
        params.languageContext !== 'zh-en' &&
        params.languageContext !== 'en-US'
    ) {
      throw new TextToSpeechException(TtsErrorCode.RUNTIME_EXCEPTION, 'languageContext is not supported');
    }
    if (params.audioType !== undefined && params.audioType !== 'pcm') {
      throw new TextToSpeechException(TtsErrorCode.RUNTIME_EXCEPTION, 'only pcm audioType is supported');
    }
  }

  private normalizeSpeakParams(params: SpeakParams): SpeakParams {
    return {
      requestId: params.requestId,
      speed: this.normalizeSpeed(params.speed),
      volume: this.defaultNonFinite(params.volume),
      pitch: this.defaultNonFinite(params.pitch),
      languageContext: normalizeLanguageContext(params.languageContext),
      audioType: params.audioType ?? 'pcm',
      playType: params.playType ?? PlayType.SYNTHESIZE_AND_PLAY,
      soundChannel: normalizeSoundChannel(params.soundChannel),
      queueMode: params.queueMode ?? QueueMode.QUEUE,
      extraParams: params.extraParams ?? {}
    };
  }

  private normalizeSpeed(value: number | undefined): number {
    if (value === undefined || !Number.isFinite(value)) {
      return 1.0;
    }
    return Math.min(2.0, Math.max(0.5, value));
  }

  private defaultNonFinite(value: number | undefined): number {
    if (value === undefined || !Number.isFinite(value)) {
      return 1.0;
    }
    return value;
  }

  private notifyStart(listener: SpeakListener, task: SynthesisTask): void {
    listener.onStart?.(task.params.requestId, {
      audioType: 'pcm',
      sampleRate: this.modelPackage.manifest.sampleRate,
      sampleBit: 16,
      audioChannel: 1,
      compressRate: 0,
      isStreaming: true,
      dataPath: task.params.playType === PlayType.SYNTHESIZE_ONLY ? 'model_stream_callback' : 'model_stream_playback',
      modelSource: this.modelInfo.indexOf('source=external') >= 0 ? 'external' : 'bundled',
      modelInfo: this.modelInfo,
      loadProfileInfo: this.loadProfileInfo
    });
  }

  private buildModelInfo(runtimeChunkSize: number): string {
    const sourceLabel = this.engineParams.extraParams?.modelPackageDir !== undefined ? 'external' : 'bundled';
    return `source=${sourceLabel} model=${MODEL_ID} version=${MODEL_VERSION} mode=streaming chunkSize=${runtimeChunkSize} path=${this.modelPackage.rootDir}`;
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
    const noActiveEngines = this.onRelease();
    if (noActiveEngines) {
      try {
        resolveNativeTtsModule().releaseTnResources();
      } catch (_error) {
      }
    }
  }
}

export class TextToSpeechSdk {
  private static workPath: string | undefined;
  private static context: common.Context | undefined;
  private static licensed: boolean = false;
  private static licenseInfo: LicenseInfo | undefined;
  private static licenseGateCode: number = TtsErrorCode.LICENSE_MISSING;
  private static licenseGateMessage: string =
    'no valid license: call TextToSpeechSdk.setLicense with a valid license before createEngine';

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

  static setContext(context: common.Context): void {
    if (EngineRegistry.hasActiveEngines()) {
      throw new TextToSpeechException(
        TtsErrorCode.INTERNAL_SERVICE_ERROR,
        'setContext must be called before createEngine'
      );
    }
    TextToSpeechSdk.context = context;
  }

  static setLicense(licensePath: string, callback: LicenseActivationCallback): void {
    if (licensePath.trim().length === 0) {
      TextToSpeechSdk.recordLicenseFailure(TtsErrorCode.LICENSE_MISSING, 'licensePath is empty');
      callback.onError(TtsErrorCode.LICENSE_MISSING, 'licensePath is empty');
      return;
    }
    if (!fs.accessSync(licensePath)) {
      TextToSpeechSdk.recordLicenseFailure(TtsErrorCode.LICENSE_MISSING, `license file not found: ${licensePath}`);
      callback.onError(TtsErrorCode.LICENSE_MISSING, `license file not found: ${licensePath}`);
      return;
    }
    let licenseText = '';
    try {
      licenseText = readLicenseText(licensePath);
    } catch (e) {
      const msg = `license file not readable: ${e}`;
      TextToSpeechSdk.recordLicenseFailure(TtsErrorCode.LICENSE_MISSING, msg);
      callback.onError(TtsErrorCode.LICENSE_MISSING, msg);
      return;
    }
    TextToSpeechSdk.activateLicense(licenseText, callback);
  }

  private static async activateLicense(licenseText: string, callback: LicenseActivationCallback): Promise<void> {
    const pub = HarmonyLicenseVerifier.publicKey();
    if (pub.trim().length === 0) {
      // SECURITY: 未注入公钥(unarmed)——下面的签名校验对任意 license 直接放行(fail-open)。正式发布/交付
      // 构建绝不能走到这里。此告警用于在错误清空了内置公钥的 release 构建里第一时间暴露问题(配合
      // HarmonyLicenseVerifier.isArmed() 的发版自检)。
      console.error('[AmphionLicense] SECURITY: TTS SDK is UNARMED (empty public key) — signature verification is bypassed; DO NOT ship a release build in this state.');
    }
    // Gate 1: real ECDSA signature. Tampered/forged licenses (e.g. edited expiresAt) are rejected here.
    let signatureValid = false;
    try {
      signatureValid = await HarmonyLicenseVerifier.verifySignature(licenseText, pub);
    } catch (e) {
      signatureValid = false;
    }
    if (!signatureValid) {
      TextToSpeechSdk.recordLicenseFailure(TtsErrorCode.LICENSE_SIGNATURE_INVALID, 'license signature verification failed');
      TextToSpeechSdk.licenseInfo = TextToSpeechSdk.buildLicenseInfo(2, []);
      callback.onError(TtsErrorCode.LICENSE_SIGNATURE_INVALID, 'license signature verification failed');
      return;
    }
    // Gate 2: SN whitelist (aligns with ASR / Android). SN-bound licenses activate only on whitelisted devices.
    const serial = readDeviceSerial();
    let deviceOk = false;
    try {
      deviceOk = await HarmonyLicenseVerifier.deviceHashOk(licenseText, serial);
    } catch (e) {
      deviceOk = false;
    }
    if (!deviceOk) {
      TextToSpeechSdk.recordLicenseFailure(TtsErrorCode.LICENSE_DEVICE_MISMATCH, 'device not authorized');
      TextToSpeechSdk.licenseInfo = TextToSpeechSdk.buildLicenseInfo(3, []);
      callback.onError(TtsErrorCode.LICENSE_DEVICE_MISMATCH, 'device not authorized');
      return;
    }
    // Gate 3: claim policy (feature must include TTS, not expired, maintenance, etc.).
    const status: AmphionLicenseStatus = HarmonyLicenseVerifier.verify(licenseText, undefined, undefined, serial, pub);
    if (!status.valid) {
      const infoStatus =
        status.errorCode === TtsErrorCode.LICENSE_EXPIRED || status.errorCode === TtsErrorCode.LICENSE_MAINTENANCE_EXPIRED ? 1 : 2;
      TextToSpeechSdk.recordLicenseFailure(status.errorCode, status.message);
      TextToSpeechSdk.licenseInfo = TextToSpeechSdk.buildLicenseInfo(infoStatus, []);
      callback.onError(status.errorCode, status.message);
      return;
    }
    TextToSpeechSdk.licensed = true;
    TextToSpeechSdk.licenseInfo = TextToSpeechSdk.buildLicenseInfo(0, status.features);
    const result = new LicenseActivationResult();
    result.errorCode = 0;
    result.errorMessage = '';
    result.remainingDays = -1;
    result.authorizedFeatures = status.features;
    callback.onResult(result);
  }

  static getLicenseInfo(): LicenseInfo {
    if (TextToSpeechSdk.licenseInfo === undefined) {
      throw new TextToSpeechException(TtsErrorCode.LICENSE_NOT_SET, 'license not set');
    }
    return TextToSpeechSdk.licenseInfo;
  }

  private static recordLicenseFailure(code: number, message: string): void {
    TextToSpeechSdk.licensed = false;
    TextToSpeechSdk.licenseGateCode = code;
    TextToSpeechSdk.licenseGateMessage = message;
  }

  private static buildLicenseInfo(status: number, features: string[]): LicenseInfo {
    const info = new LicenseInfo();
    info.status = status;
    info.expireTime = -1;
    info.remainingDays = -1;
    info.authorizedFeatures = features;
    return info;
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
    // 回调在调用方线程的微任务里执行(非真正 off-thread)。注意两块开销的归属:
    //  1) 5 个 ONNX 模型(~160MB)的加载 **不在这里**:native Runtime 构造函数用 std::async 在后台线程
    //     加载,首次 speak 时在合成 worker 线程 join(见 lits_tts_native.cpp Runtime::EnsureLoaded),不占 UI 线程。
    //  2) 前端词典解析(chinese_lexicon.txt ~14MB + cmudict.txt ~3.4MB → Map)**是同步的**,首次创建约
    //     ~2s 的 UI 线程开销。FrontendResources 按 modelPackageDir 缓存(loadedPackages),同一进程内仅首个
    //     引擎付这笔钱,之后 createEngine 直接命中缓存。
    // 若要彻底消除这一次性卡顿,需把前端加载搬到 taskpool/Worker(涉及 Map 结果的 Sendable 序列化),风险较大,暂缓。
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
    if (!TextToSpeechSdk.licensed) {
      throw new TextToSpeechException(TextToSpeechSdk.licenseGateCode, TextToSpeechSdk.licenseGateMessage);
    }
    return EngineRegistry.createEngine(params, TextToSpeechSdk.workPath, TextToSpeechSdk.context);
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
    typeof nativeModule.normalizeTnSegment !== 'function' ||
    typeof nativeModule.releaseTnResources !== 'function'
  ) {
    throw new TextToSpeechException(
      TtsErrorCode.CREATE_ENGINE_FAILED,
      'native module liblitsttsnative.so is unavailable'
    );
  }
  nativeTtsModuleCache = nativeModule;
  return nativeModule;
}

function resolveModelPackageDir(
  extraParams: ExtraParams | undefined,
  workPath: string | undefined,
  context: common.Context | undefined
): string {
  const extraModelDir = extraParams?.modelPackageDir;
  if (typeof extraModelDir === 'string' && extraModelDir.trim().length > 0) {
    return requireManifestDir(extraModelDir.trim());
  }

  const workPathModelDir = resolveWorkPathModelPackageDir(workPath);
  if (workPathModelDir !== undefined) {
    return workPathModelDir;
  }

  return ensureBundledModelPackageDir(workPath, context);
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

function ensureTerminalPunctuation(text: string, language: string): string {
  const trimmed = text.trimEnd();
  if (trimmed.length === 0 || hasTerminalPunctuation(trimmed)) {
    return text;
  }
  const suffix = language === 'en-US' ? '.' : '。';
  return `${trimmed}${suffix}`;
}

function hasTerminalPunctuation(text: string): boolean {
  const last = text.charAt(text.length - 1);
  return last === '!' || last === '?' || last === '。' || last === '.' || last === '！' || last === '？';
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

function ensureBundledModelPackageDir(workPath: string | undefined, context: common.Context | undefined): string {
  const modelPackageDir = resolveBundledModelPackageDir(workPath, context);
  if (
    bundledModelPackageDirCache !== modelPackageDir ||
      !hasRequiredRuntimeFiles(modelPackageDir) ||
      !hasExpectedAssetSignature(modelPackageDir)
  ) {
    extractBundledModelPackage(modelPackageDir, context);
    bundledModelPackageDirCache = modelPackageDir;
  }
  return requireManifestDir(modelPackageDir);
}

function resolveBundledModelPackageDir(workPath: string | undefined, context: common.Context | undefined): string {
  const baseDir = workPath !== undefined && workPath.trim().length > 0
    ? normalizeDir(workPath)
    : normalizeDir(requireContext(context).filesDir);
  return joinPath(joinPath(baseDir, 'tts'), MODEL_ID, MODEL_VERSION);
}

function hasRequiredRuntimeFiles(modelPackageDir: string): boolean {
  return REQUIRED_RUNTIME_FILES.every((fileName: string): boolean => isRegularFile(joinPath(modelPackageDir, fileName)));
}

function hasExpectedAssetSignature(modelPackageDir: string): boolean {
  return readTextSafely(joinPath(modelPackageDir, '.asset_signature')) === bundledAssetSignature();
}

function bundledAssetSignature(): string {
  return `${MODEL_ID}:${MODEL_VERSION}:${FRONTEND_ASSET_SIGNATURE_VERSION}:${BUNDLED_MODEL_FILES.join('|')}`;
}

function extractBundledModelPackage(modelPackageDir: string, context: common.Context | undefined): void {
  ensureDirectory(modelPackageDir);
  try {
    const resourceManager = resolveBundledModelResourceManager(context);
    BUNDLED_MODEL_FILES.forEach((fileName: string): void => {
      const rawfilePath = joinPath(BUNDLED_MODEL_RAWFILE_DIR, fileName);
      writeBinaryFile(
        joinPath(modelPackageDir, fileName),
        resourceManager.getRawFileContentSync(rawfilePath)
      );
    });
    writeTextFile(joinPath(modelPackageDir, '.asset_signature'), bundledAssetSignature());
  } catch (error) {
    const message = error instanceof Error ? error.message : 'failed to extract bundled model package';
    throw new TextToSpeechException(TtsErrorCode.CREATE_ENGINE_FAILED, message);
  }
}

function resolveBundledModelResourceManager(context: common.Context | undefined) {
  const appContext = requireContext(context);
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

function requireContext(context: common.Context | undefined): common.Context {
  if (context !== undefined) {
    return context;
  }
  throw new TextToSpeechException(
    TtsErrorCode.CREATE_ENGINE_FAILED,
    'TextToSpeechSdk.setContext(context) must be called before createEngine when using bundled model resources'
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

function readTextSafely(filePath: string): string {
  try {
    return fs.readTextSync(filePath);
  } catch (_error) {
    return '';
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

function writeTextFile(filePath: string, content: string): void {
  ensureDirectory(parentDir(filePath));
  let file: fs.File | undefined = undefined;
  try {
    file = fs.openSync(filePath, fs.OpenMode.CREATE | fs.OpenMode.WRITE_ONLY | fs.OpenMode.TRUNC);
    const bytes = new Uint8Array(content.length);
    for (let index = 0; index < content.length; index += 1) {
      bytes[index] = content.charCodeAt(index) & 0xff;
    }
    fs.writeSync(file.fd, bytes.buffer);
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
  const resolved = resolveOptionalIntegerExtraParam(extraParams, keys, minValue, maxValue);
  if (resolved !== undefined) {
    return resolved;
  }
  return clampInt(Math.round(defaultValue), minValue, maxValue);
}

function resolveOptionalIntegerExtraParam(
  extraParams: ExtraParams | undefined,
  keys: Array<string>,
  minValue: number,
  maxValue: number
): number | undefined {
  for (let index = 0; index < keys.length; index += 1) {
    const key = keys[index];
    const raw = key === 'streamingChunkSize'
      ? extraParams?.streamingChunkSize
      : key === 'chunkSize'
        ? extraParams?.chunkSize
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
  return undefined;
}

function clampNumber(value: number, minValue: number, maxValue: number): number {
  return Math.max(minValue, Math.min(maxValue, value));
}

function lengthScaleForSpeed(speed: number): number {
  const clampedSpeed = Number.isFinite(speed) ? clampNumber(speed, 0.5, 2.0) : 1.0;
  return clampNumber(1.0 / clampedSpeed, 0.5, 2.0);
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

function formatError(error: Object): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}
