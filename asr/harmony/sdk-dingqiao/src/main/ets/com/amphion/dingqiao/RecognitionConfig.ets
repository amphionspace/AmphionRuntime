import {
  AsrConfig,
  AsrLanguage,
  SessionConfig,
  SpeakerVadConfig,
  TargetSpeakerConfig
} from 'amphion_asr';
import { PoliceEngineConfig } from 'amphion_police';
import { compatibleBooleanParam } from './BooleanParam';
import { longFormMaxUtteranceSec, rule3Policy } from './EndpointRulePolicy';
import { finiteNumberParam } from './NumericParam';
import {
  CreateEngineParams,
  DINGQIAO_AUDIO_FRAME_BYTES_20MS,
  DingqiaoOnlineMode,
  StartParams
} from './DingqiaoModels';

/**
 * 声纹 extractor 线程数。注册、识别和预加载必须用同一个值：extractor 池按
 * `${modelPath}|${numThreads}` 建键，取值不一致会让同一个 ~38 MB 的 ERes2Net 模型
 * 在进程里存两份。
 *
 * Speaker VAD 每 500 ms 跳要对 1500 ms 窗口做一次嵌入；机主确认前它与 ASR 解码串行
 * （归属要先结清才允许下一片进入 utterance），换人判定还要再做数次嵌入校验候选边界。
 * 手机 80（12 逻辑核）同录音实测 1 → 4 线程：单次 inferMs median 224 → 118、
 * p90 258 → 150，整轮嵌入 9.50 s → 5.15 s，endpoint→final 机主首句 771 → 452 ms、
 * 换人切分句 1613 → 1212 ms（缺陷 #98）。进程 CPU 均值 1.55 → 1.98 核，仍有余量。
 * 注意它不改变首个 partial 的时延：那一项由流式解码右上下文决定，实测 1 → 4 线程不变。
 *
 * 同一夹具再实测 4 → 8 线程（vadEnd=800，#98 原录音 A→B→C→A）：inferMs median
 * 131 → 118、p90 178 → 143、max 228 → 148，整轮嵌入 5.28 s → 4.61 s，最差
 * endpoint→final 498 → 406 ms。进程 CPU 均值 1.81 → 2.31 核（12 逻辑核，仍有余量）。
 * 发布文本、state/decision 计数、两次非机主拒绝与 target_speaker_realtime 全部不变。
 * 8 是 TargetSpeakerConfig.numThreads 的上限，再往上没有空间。
 *
 * 这条只压缩嵌入本身的耗时。把它整个移出关键路径的是 Runtime 的投机预算：评分 PCM 截到
 * 最后一次 VAD 语音结束（finalSpeakerScoreSamples），VAD 一判出语音结束就起嵌入，端点时
 * 直接消费。同夹具实测最差 endpoint→final 406 → 63 ms，每个 vad-active 句都是
 * phase=consumed、waitMs≤1，评分 PCM 少带 826–930 ms 尾静音；发布文本、两次非机主拒绝、
 * departure 计数与 target_speaker_realtime 全部不变。0.45 下沿本来就是在干净切段上标定的
 * （fab43be7），截掉尾静音让真机分数回到那个口径。
 */
export const SPEAKER_EXTRACTOR_THREADS: number = 8;

export function languageOf(language: string): AsrLanguage {
  const normalized = language.toLowerCase();
  if (normalized === 'zh-cn' || normalized === 'zh-en' || normalized === 'zh_en') {
    return AsrLanguage.ZH_EN;
  }
  if (normalized === 'zh-yue' || normalized === 'zh_yue') return AsrLanguage.YUE_EN;
  throw new Error(`unsupported language: ${language}`);
}

export function parseLexicon(value: Object | undefined): string[] {
  if (value === undefined) return [];
  if (Array.isArray(value)) return objectArrayToStrings(value as Object[]);
  if (typeof value !== 'string' || value.length === 0) return [];
  return value.split(/[\n,，]/).map((s: string): string => s.trim())
    .filter((s: string): boolean => s.length > 0);
}

function objectArrayToStrings(arr: Object[]): string[] {
  const out: string[] = [];
  for (let i = 0; i < arr.length; i++) {
    const s = `${arr[i]}`.trim();
    if (s.length > 0) out.push(s);
  }
  return out;
}

export function stringArrayParam(params: Record<string, Object>, key: string): string[] {
  const value = params[key];
  if (value === undefined) return [];
  if (Array.isArray(value)) return objectArrayToStrings(value as Object[]);
  if (typeof value === 'string') {
    return value.split(/[\n,，]/).map((s: string): string => s.trim())
      .filter((s: string): boolean => s.length > 0);
  }
  return [];
}

export function numberParam(params: Record<string, Object>, key: string,
  defaultValue: number): number {
  return finiteNumberParam(params, key) ?? defaultValue;
}

function optionalNumberParam(params: Record<string, Object>, key: string): number | undefined {
  return finiteNumberParam(params, key);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function vadEndMs(params?: StartParams): number {
  return Math.round(clamp(numberParam(params?.extraParams ?? {}, 'vadEnd', 800), 500, 10000));
}

export function vadBeginMs(params: StartParams): number | undefined {
  if (params.extraParams['vadBegin'] === undefined) return undefined;
  const value = optionalNumberParam(params.extraParams, 'vadBegin');
  return value === undefined ? undefined : Math.round(clamp(value, 500, 10000));
}

export function isSupportedAudioFrameBytes(byteLength: number): boolean {
  return byteLength === DINGQIAO_AUDIO_FRAME_BYTES_20MS;
}

export function pcm16ToFloat(audio: ArrayBuffer): Float32Array {
  const pcm = new Int16Array(audio);
  const samples = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i++) samples[i] = pcm[i] / 32768.0;
  return samples;
}

export function validateRecognitionMode(params: StartParams): string {
  const raw = params.extraParams['recognitionMode'];
  if (raw === undefined) return '';
  const mode = optionalNumberParam(params.extraParams, 'recognitionMode');
  return mode === 1 ? '' : 'only recognitionMode=1 (external audio stream) is supported';
}

function validateRecognizerMode(params: CreateEngineParams): void {
  const raw = params.extraParams['recognizerMode'];
  if (raw === undefined) return;
  const mode = `${raw}`.trim().toLowerCase();
  if (mode !== 'short' && mode !== 'long') throw new Error('recognizerMode must be short or long');
}

export function isValidSessionId(sessionId: string): boolean {
  return /^[A-Za-z0-9_-]+$/.test(sessionId);
}

export function buildAsrConfig(context: Context, params: CreateEngineParams,
  startParams?: StartParams, withTargetSpeaker: boolean = false,
  withSpeakerVad: boolean = false, speakerModelPath?: string): AsrConfig {
  if (params.online !== DingqiaoOnlineMode.OFFLINE) throw new Error('only offline mode is supported');
  validateRecognizerMode(params);
  const config = new AsrConfig();
  const numThreads = params.numThreads ?? 4;
  if (!Number.isInteger(numThreads) || numThreads < 1 || numThreads > 8) {
    throw new Error('numThreads must be an integer in [1, 8]');
  }
  config.numThreads = numThreads;
  if (params.scheduling !== undefined) {
    config.scheduling = AsrConfig.builder().scheduling(params.scheduling).build().scheduling;
  }
  config.punctuation = true;
  config.itn = true;
  config.vad = true;
  config.endpoint = true;
  config.hotwordsScore = PoliceEngineConfig.HOTWORDS_SCORE_DEFAULT;
  config.hotwords = PoliceEngineConfig.effectiveHotwords(
    context, parseLexicon(params.extraParams['sysGeneralLexicon']));
  config.vadConfig.activeEndpointSilenceMs = vadEndMs(startParams);
  config.endpointRules.rule2MinTrailingSilenceSec = 2.0;
  const endpointRule3 = rule3Policy(params.extraParams, startParams?.extraParams ?? {});
  config.endpointRules.rule3MinUtteranceLengthSec = endpointRule3.minUtteranceSec;
  // The long-form path keeps one stream across pauses, so an endpoint that fires
  // on trailing silence with nothing decoded only costs it: it restarts the
  // stream before a sparse burst accumulates enough audio to produce text, and
  // the utterance length rule3 would have measured restarts with it. Short mode
  // keeps rule1, where cutting dead air early is what callers expect.
  config.endpointRules.rule1 = endpointRule3.mode === 'short';
  // endpointMaxUtteranceMs configures rule3, which the long-form path disables,
  // so there it used to be accepted and ignored. Carry it to the SDK's own cut
  // as well; the runtime clamps it to what the utterance buffers hold and
  // reports the effective value in kind=SESSION_CONFIG.
  const requestedCeilingSec = longFormMaxUtteranceSec(startParams?.extraParams ?? {});
  if (requestedCeilingSec !== undefined) {
    config.endpointRules.longFormMaxUtteranceSec = requestedCeilingSec;
  }
  // 默认跳过 prepack，优先降低冷启动和峰值内存；host 可显式传 false 恢复吞吐优先模式。
  config.disablePrepack = compatibleBooleanParam(params.extraParams, 'disablePrepack', true);
  if (withTargetSpeaker) {
    if (speakerModelPath === undefined) throw new Error('voiceprint model path is required');
    config.targetSpeaker = buildTargetSpeakerConfig(startParams, speakerModelPath);
  }
  return config;
}

function snapshotExtraParams(source: Record<string, Object>): Record<string, Object> {
  const snapshot: Record<string, Object> = {};
  const keys: string[] = Object.keys(source);
  for (let i = 0; i < keys.length; i++) {
    const key = keys[i];
    const value = source[key];
    if (Array.isArray(value)) {
      const sourceArray = value as Object[];
      const arraySnapshot: Object[] = [];
      for (let j = 0; j < sourceArray.length; j++) arraySnapshot.push(sourceArray[j]);
      snapshot[key] = arraySnapshot;
    } else if (value !== undefined) {
      snapshot[key] = value;
    }
  }
  return snapshot;
}

export function snapshotCreateEngineParams(source: CreateEngineParams): CreateEngineParams {
  const snapshot = new CreateEngineParams();
  snapshot.numThreads = source.numThreads;
  if (source.scheduling !== undefined) {
    snapshot.scheduling = AsrConfig.builder().scheduling(source.scheduling).build().scheduling;
  }
  snapshot.language = source.language;
  snapshot.online = source.online;
  snapshot.extraParams = snapshotExtraParams(source.extraParams);
  return snapshot;
}

function buildTargetSpeakerConfig(startParams: StartParams | undefined,
  speakerModelPath: string): TargetSpeakerConfig {
  const cfg = new TargetSpeakerConfig();
  cfg.modelPath = speakerModelPath;
  // Score-only: never reject on segment-end verification so onFinal always carries speakerSimilarity
  // (mirrors Android Dingqiao SCORE_ONLY_THRESHOLD = -1). Speaker VAD does its own gating.
  cfg.threshold = -1.0;
  cfg.minSegSec = 0;
  cfg.enabledByDefault = false;
  cfg.numThreads = SPEAKER_EXTRACTOR_THREADS;
  // Neither final-only verification nor Speaker VAD may construct the extractor on the caller's
  // ArkTS thread: customer apps commonly start AudioCapturer before startListening(). Speaker VAD
  // remains fail-open until the async extractor attaches, then scores the latest buffered window.
  cfg.deferLoad = true;
  // Keep Speaker VAD configured even when initially disabled so the Android-aligned runtime toggle
  // can enable it later in the same session.
  cfg.speakerVad = buildSpeakerVadConfig(startParams?.extraParams ?? {});
  return cfg;
}

function buildSpeakerVadConfig(extra: Record<string, Object>): SpeakerVadConfig {
  const config = new SpeakerVadConfig();
  config.threshold = clamp(numberParam(extra, 'speakerVadThreshold', 0.35), -1.0, 1.0);
  config.winSec = Math.round(clamp(numberParam(extra, 'speakerVadWindowMs', 1500), 500, 5000)) / 1000;
  config.hopSec = Math.round(clamp(numberParam(extra, 'speakerVadHopMs', 500), 100, 2000)) / 1000;
  config.consecutiveBelow = Math.round(
    clamp(numberParam(extra, 'speakerVadConsecutiveBelow', 2), 1, 5));
  config.enabledByDefault = false;
  return config;
}

export function buildSessionConfig(params: StartParams, withTargetSpeaker: boolean,
  needsVoiceprintAudio: boolean): SessionConfig {
  const config = new SessionConfig();
  config.endpointSilenceMs = vadEndMs(params);
  config.initialSilenceTimeoutMs = vadBeginMs(params);
  if (needsVoiceprintAudio) {
    const targetSpeakerDefaults = new TargetSpeakerConfig();
    config.initialSilenceConfirmationGraceMs = Math.round(targetSpeakerDefaults.minSegSec * 1000);
  }
  if (withTargetSpeaker) config.speakerVad = buildSpeakerVadConfig(params.extraParams);
  return config;
}
