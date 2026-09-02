import {
  AsrConfig,
  AsrLanguage,
  SessionConfig,
  SpeakerVadConfig,
  TargetSpeakerConfig
} from 'amphion_asr';
import { PoliceEngineConfig } from 'amphion_police';
import { compatibleBooleanParam } from './BooleanParam';
import { rule3Policy } from './EndpointRulePolicy';
import { finiteNumberParam } from './NumericParam';
import {
  CreateEngineParams,
  DINGQIAO_AUDIO_FRAME_BYTES_20MS,
  DingqiaoOnlineMode,
  StartParams
} from './DingqiaoModels';

const DEFAULT_ASR_NUM_THREADS: number = 4;
const DEFAULT_HOTWORDS_SCORE: number = 3.0;

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
  config.numThreads = DEFAULT_ASR_NUM_THREADS;
  config.punctuation = true;
  config.itn = true;
  config.vad = true;
  config.endpoint = true;
  config.hotwordsScore = DEFAULT_HOTWORDS_SCORE;
  config.hotwords = PoliceEngineConfig.effectiveHotwords(
    context, parseLexicon(params.extraParams['sysGeneralLexicon']));
  config.vadConfig.activeEndpointSilenceMs = vadEndMs(startParams);
  config.endpointRules.rule2MinTrailingSilenceSec = 2.0;
  const endpointRule3 = rule3Policy(params.extraParams, startParams?.extraParams ?? {});
  config.endpointRules.rule3MinUtteranceLengthSec = endpointRule3.minUtteranceSec;
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
  cfg.numThreads = 1;
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
