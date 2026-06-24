import application from '@ohos.app.ability.application';
import fs from '@ohos.file.fs';
import { audio } from '@kit.AudioKit';

const MODEL_ID: string = 'lits_delivery_16k_hifigan';
const MODEL_VERSION: string = '1.0.0';
const BUNDLED_MODEL_RAWFILE_DIR: string = `lits-models/tts/${MODEL_ID}/${MODEL_VERSION}`;
const DEFAULT_SAMPLE_RATE: number = 16000;
const MAX_ENGINE_COUNT: number = 3;
const MAX_TEXT_LENGTH: number = 10000;
const AUDIO_CHUNK_BYTES: number = 4096;
const SYNTHESIS_CALLBACK_CHUNK_BYTES: number = 524288;
const DEFAULT_LANGUAGE_CONTEXT: string = 'zh-CN';

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
  'lits_acoustic.onnx',
  'hifigan_vocoder.onnx',
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
  'smoke_tokens.json',
  'frontend_golden.json',
  'chinese_lexicon.txt',
  'cmudict.txt',
  'pinyin_2_bpmf.txt',
  'polychar.txt',
  'zh_en_symbols.json',
  'pinyin_to_tokens.json',
  'arpabet_to_tokens.json',
  'lits_acoustic.onnx',
  'hifigan_vocoder.onnx'
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

const ENGLISH_MERGE_RULES: Array<MergeRule> = [
  { pair: ['t', '\u0279'], replacement: 't\u0279' },
  { pair: ['d', '\u0279'], replacement: 'd\u0279' },
  { pair: ['t', 's'], replacement: 'ts' },
  { pair: ['d', 'z'], replacement: 'dz' },
  { pair: ['\u026A', '\u0279'], replacement: '\u026A\u0279' },
  { pair: ['o\u02D0', '\u0279'], replacement: 'o\u02D0\u0279' }
];

const PINYIN_SYLLABLE_REGEX: RegExp = /^[a-z]+[0-6]$/;

interface NativeTtsModule {
  createRuntime(acousticPath: string, vocoderPath: string): object;
  releaseRuntime(runtimeHandle: object): void;
  synthesize(runtimeHandle: object, tokenIds: Array<number>, speakerId: number): ArrayBuffer;
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
  RUNTIME_EXCEPTION = 1002300011
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
  acoustic_model?: ManifestModelFile;
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
  speakerCount: number;
  defaultSpeakerId: number;
  supportedLanguages: Array<string>;
  acousticModelFile: string;
  vocoderModelFile: string;
}

interface InternalSynthesis {
  pcm: ArrayBuffer;
  sampleRate: number;
  tokenIds: Array<number>;
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
      (raw.supported_languages ?? []).indexOf('zh-en') < 0 ||
      (raw.supported_languages ?? []).indexOf('en-US') < 0 ||
      raw.acoustic_model?.file !== 'lits_acoustic.onnx' ||
      raw.vocoder_model?.file !== 'hifigan_vocoder.onnx' ||
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
      speakerCount: raw.speaker_count,
      defaultSpeakerId: raw.default_speaker_id,
      supportedLanguages: raw.supported_languages ?? ['zh-en', 'en-US'],
      acousticModelFile: raw.acoustic_model.file,
      vocoderModelFile: raw.vocoder_model.file
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

class LitsTtsFrontend {
  static encode(resources: LoadedPackage, text: string, language: string, languageContext: string): Array<number> {
    const normalized = LitsTtsFrontend.normalizeText(text).trim();
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
    while (index < normalized.length) {
      const char = normalized[index];
      if (LitsTtsFrontend.isWhitespace(char)) {
        LitsTtsFrontend.appendBoundary(output);
        index += 1;
        continue;
      }
      if (PUNCTUATION_SET.has(char)) {
        LitsTtsFrontend.appendPunctuation(output, char);
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
          LitsTtsFrontend.appendChineseSyllables(output, resources, syllables);
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
        }
        index = end;
        continue;
      }
      if (LitsTtsFrontend.isHanzi(char)) {
        const end = LitsTtsFrontend.scanHanziChunk(normalized, index);
        const syllables = LitsTtsFrontend.applyThirdToneSandhi(
          LitsTtsFrontend.hanziChunkToPinyin(resources, normalized.substring(index, end))
        );
        LitsTtsFrontend.appendChineseSyllables(output, resources, syllables);
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
        index = end;
        continue;
      }
      throw new TextToSpeechException(TtsErrorCode.RUNTIME_EXCEPTION, `unsupported frontend character: ${char}`);
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
    return LitsTtsFrontend.intersperseZero(ids);
  }

  private static normalizeText(text: string): string {
    let normalized = text
      .replace(/\.\.\./g, '\u2026')
      .replace(/\u22EF/g, '\u2026')
      .replace(/\u00B7\u00B7\u00B7/g, '\u2026')
      .replace(/\u30FB\u30FB\u30FB/g, '\u2026');
    let output = '';
    for (let index = 0; index < normalized.length; index += 1) {
      const char = normalized[index];
      output += FULLWIDTH_PUNCTUATION.get(char) ?? char;
    }
    return output;
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
        throw new TextToSpeechException(
          TtsErrorCode.RUNTIME_EXCEPTION,
          `hanzi is not covered by chinese_lexicon.txt: ${char}`
        );
      }
      const syllables = LitsTtsFrontend.normalizeLexiconPinyin(pinyin);
      if (syllables.length === 0) {
        throw new TextToSpeechException(
          TtsErrorCode.RUNTIME_EXCEPTION,
          `hanzi pinyin is invalid in chinese_lexicon.txt: ${char}`
        );
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
          throw new TextToSpeechException(
            TtsErrorCode.RUNTIME_EXCEPTION,
            `english word is not covered by cmudict.txt: ${rawWord}`
          );
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
    throw new TextToSpeechException(
      TtsErrorCode.RUNTIME_EXCEPTION,
      `english word is not covered by cmudict.txt: ${rawWord}`
    );
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
        throw new TextToSpeechException(
          TtsErrorCode.RUNTIME_EXCEPTION,
          `ARPAbet phone is not supported by HarmonyOS frontend: ${phone}`
        );
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
    while (output.length > 0 && output[output.length - 1] === '_') {
      output.pop();
    }
    output.push(token);
  }

  private static appendChineseSyllables(
    output: Array<string>,
    resources: LoadedPackage,
    syllables: Array<string>
  ): void {
    while (output.length > 0 && output[output.length - 1] === '_') {
      output.pop();
    }
    syllables.forEach((syllable: string): void => {
      const tokens = resources.pinyinToTokens.get(syllable);
      if (tokens === undefined) {
        throw new TextToSpeechException(
          TtsErrorCode.RUNTIME_EXCEPTION,
          `pinyin is not covered by generated mapping: ${syllable}`
        );
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

  private static isWhitespace(char: string): boolean {
    return char === ' ' || char === '\t' || char === '\n' || char === '\r';
  }

  private static isHanzi(char: string): boolean {
    const code = char.charCodeAt(0);
    return code >= 0x4e00 && code <= 0x9fff;
  }

  private static isEnglishLetter(char: string): boolean {
    const code = char.charCodeAt(0);
    return (code >= 65 && code <= 90) || (code >= 97 && code <= 122);
  }

  private static isAsciiDigit(char: string): boolean {
    const code = char.charCodeAt(0);
    return code >= 48 && code <= 57;
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
    this.stopped = false;
    const renderer = await this.createRenderer(sampleRate, soundChannel);
    this.renderer = renderer;
    try {
      await renderer.start();
      let offset = 0;
      while (offset < pcm.byteLength && !this.stopped) {
        const length = Math.min(AUDIO_CHUNK_BYTES, pcm.byteLength - offset);
        const chunk = copyArrayBuffer(pcm, offset, length);
        await renderer.write(chunk);
        offset += length;
      }
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
    const nativeTts = resolveNativeTtsModule();
    this.nativeRuntime = nativeTts.createRuntime(
      joinPath(this.modelPackageDir, this.modelPackage.manifest.acousticModelFile),
      joinPath(this.modelPackageDir, this.modelPackage.manifest.vocoderModelFile)
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
    stoppedTasks.forEach((stoppedTask: SynthesisTask): void => this.notifyStop(listener, stoppedTask));
    this.queue.push(task);
    this.scheduleProcessing();
  }

  stop(): void {
    this.ensureNotDestroyed();
    const listener = this.listener;
    const stoppedTasks = this.cancelAllTasks();
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
    let audioResult: InternalSynthesis;
    try {
      audioResult = this.synthesizeInternal(task.text, task.params);
    } catch (error) {
      const code = error instanceof TextToSpeechException ? error.errorCode : TtsErrorCode.RUNTIME_EXCEPTION;
      const message = error instanceof Error ? error.message : 'synthesis failed';
      listener.onError?.(task.params.requestId, code, message);
      return;
    }
    if (task.cancelled || this.destroyed) {
      this.notifyStop(listener, task);
      return;
    }

    if (task.params.playType === PlayType.SYNTHESIZE_ONLY) {
      this.emitAudioChunks(listener, task, audioResult.pcm);
      if (task.cancelled || this.destroyed) {
        this.notifyStop(listener, task);
        return;
      }
    }

    listener.onComplete?.(task.params.requestId, {
      type: CompleteType.SYNTHESIS_COMPLETE,
      message: 'synthesis complete'
    });

    if (task.params.playType === PlayType.SYNTHESIZE_AND_PLAY && !task.cancelled && !this.destroyed) {
      try {
        await this.player.play(audioResult.pcm, audioResult.sampleRate, task.params.soundChannel);
      } catch (error) {
        const code = error instanceof TextToSpeechException ? error.errorCode : TtsErrorCode.RUNTIME_EXCEPTION;
        const message = error instanceof Error ? error.message : 'playback failed';
        listener.onError?.(task.params.requestId, code, message);
        return;
      }
    }

    if (task.params.playType === PlayType.SYNTHESIZE_AND_PLAY && !task.cancelled && !this.destroyed) {
      listener.onComplete?.(task.params.requestId, {
        type: CompleteType.PLAYBACK_COMPLETE,
        message: 'playback complete'
      });
    }
  }

  private synthesizeInternal(text: string, params: SpeakParams): InternalSynthesis {
    const tokenIds = LitsTtsFrontend.encode(
      this.modelPackage,
      text,
      this.engineParams.language,
      params.languageContext ?? 'zh-en'
    );
    const rawPcm = resolveNativeTtsModule().synthesize(this.nativeRuntime, tokenIds, this.voice.speakerId) as ArrayBuffer;
    const transformedPcm = AudioTransforms.apply(rawPcm, params);
    return {
      pcm: transformedPcm,
      sampleRate: this.modelPackage.manifest.sampleRate,
      tokenIds
    };
  }

  private emitAudioChunks(listener: SpeakListener, task: SynthesisTask, pcm: ArrayBuffer): void {
    let offset = 0;
    let sequence = 0;
    while (offset < pcm.byteLength) {
      if (task.cancelled || this.destroyed) {
        return;
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
    typeof nativeModule.synthesize !== 'function'
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

function clampNumber(value: number, minValue: number, maxValue: number): number {
  return Math.max(minValue, Math.min(maxValue, value));
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
