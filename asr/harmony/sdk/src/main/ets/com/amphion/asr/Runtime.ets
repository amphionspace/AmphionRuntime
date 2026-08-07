import {
  OfflinePunctuation,
  OfflinePunctuationConfig,
  OnlineModelConfig,
  OnlineRecognizer,
  OnlineRecognizerConfig,
  OnlineStream,
  onlineStreamLiveCount,
  Samples,
  SileroVadConfig,
  SpeakerEmbeddingExtractor,
  SpeakerEmbeddingExtractorConfig,
  TenVadConfig,
  Vad as SherpaVad,
  VadConfig as SherpaVadConfig,
  WetextItn,
  WetextItnConfig
} from 'sherpa_onnx';
import { InstalledLayout } from './AssetRegistry';
import { AssetInstaller } from './AssetInstaller';
import {
  AmphionLogLevel,
  AmphionMetrics,
  AmphionMetricsKind,
  AmphionOptions,
  AsrCallback,
  AsrConfig,
  AsrError,
  AsrErrorCode,
  AsrLanguage,
  AsrResult,
  Cancellable,
  EndpointRules,
  LicenseEnforcement,
  SessionConfig,
  SpeakerVadConfig,
  TargetSpeakerConfig,
  VadConfig,
  VadModelType
} from './Types';
import { AmphionLicenseStatus, HarmonyLicenseVerifier } from './License';
import { InitialSilenceTracker } from './InitialSilenceTracker';
import { EffectiveSpeechBuffer } from './EffectiveSpeechBuffer';
import { SpeakerPcmBuffers } from './SpeakerPcmBuffers';
import { SpeakerVadScoreScheduler } from './SpeakerVadScoreScheduler';
import { selectSpeakerScoreSamples, speakerScoreSelectionDiagnostic } from './SpeakerScoreFallback';
import { SessionCallbackGate } from './SessionCallbackGate';
import { SessionReentryQueue } from './SessionReentryQueue';
import {
  HARMONY_SDK_MAJOR,
  HARMONY_SDK_RELEASE_DATE,
  HARMONY_SDK_VERSION
} from './RuntimeIdentity';

const ASR_SAMPLE_RATE_HZ: number = 16000;
// Advance armed initial-silence decisions in fixed 20 ms slices so caller chunking cannot move a deadline.
const INITIAL_DECISION_CHUNK_SAMPLES: number = ASR_SAMPLE_RATE_HZ / 50;
// ORT-format models are optimized and prepacked during Session creation. Device A/B testing showed
// that an eager silence decode adds ~93 ms to engine readiness but saves only ~9 ms on first audio.
const EAGER_WARMUP_DURATION_MS: number = 0;
// Hard cap on the per-utterance sample buffer used for speaker scoring, so a stuck utterance that
// never endpoints can't grow unbounded (Android UTT_MAX_SAMPLES).
const UTT_MAX_SAMPLES: number = 25 * ASR_SAMPLE_RATE_HZ;
// Manual stop often lands exactly at the speech tail. The zh-en encoder advances by a 64-frame
// chunk (~640 ms); padding two complete chunks guarantees two more decode opportunities regardless
// of the current chunk phase. This is synthetic input, not a 1.28-second wall-clock delay.
const FINAL_TAIL_SILENCE_MS: number = 1280;

class DoneCancellable implements Cancellable {
  private done: boolean = false;
  private cancelled: boolean = false;
  cancel(): void { this.cancelled = true; this.done = true; }
  isCancelled(): boolean { return this.cancelled; }
  isDone(): boolean { return this.done; }
  markDone(): void { this.done = true; }
}

class AsyncRecognizerLoad {
  recognizer: OnlineRecognizer;
  elapsedMs: number;

  constructor(recognizer: OnlineRecognizer, elapsedMs: number) {
    this.recognizer = recognizer;
    this.elapsedMs = elapsedMs;
  }
}

class AsyncPunctuationLoad {
  punctuation?: OfflinePunctuation;
  elapsedMs: number;

  constructor(punctuation: OfflinePunctuation | undefined, elapsedMs: number) {
    this.punctuation = punctuation;
    this.elapsedMs = elapsedMs;
  }
}

class PendingSpeakerFinal {
  result: AsrResult;
  samples: Float32Array;
  endpointAtMs: number;
  decodeDurationMs: number;
  postProcessMs: number;
  utteranceIndex: number;
  utteranceDurationMs: number;
  firstPartialLatencyMs: number;
  utteranceStartedMs: number;
  pcmBytesAccepted: number;

  constructor(result: AsrResult, samples: Float32Array, endpointAtMs: number,
    decodeDurationMs: number, postProcessMs: number, utteranceIndex: number,
    utteranceDurationMs: number, firstPartialLatencyMs: number,
    utteranceStartedMs: number, pcmBytesAccepted: number) {
    this.result = result;
    this.samples = samples;
    this.endpointAtMs = endpointAtMs;
    this.decodeDurationMs = decodeDurationMs;
    this.postProcessMs = postProcessMs;
    this.utteranceIndex = utteranceIndex;
    this.utteranceDurationMs = utteranceDurationMs;
    this.firstPartialLatencyMs = firstPartialLatencyMs;
    this.utteranceStartedMs = utteranceStartedMs;
    this.pcmBytesAccepted = pcmBytesAccepted;
  }
}

class Logger {
  private static level: AmphionLogLevel = AmphionLogLevel.WARN;
  static setLevel(level: AmphionLogLevel): void { Logger.level = level; }
  static d(message: string): void { if (Logger.level <= AmphionLogLevel.DEBUG) console.debug(`[AmphionRuntime] ${message}`); }
  static i(message: string): void { if (Logger.level <= AmphionLogLevel.INFO) console.info(`[AmphionRuntime] ${message}`); }
  static w(message: string): void { if (Logger.level <= AmphionLogLevel.WARN) console.warn(`[AmphionRuntime] ${message}`); }
  static e(message: string): void { if (Logger.level <= AmphionLogLevel.ERROR) console.error(`[AmphionRuntime] ${message}`); }
  static metric(line: string): void { if (Logger.level !== AmphionLogLevel.NONE) console.info(`[AmphionMetrics] ${line}`); }
}

export class AmphionRuntime {
  private static readonly SDK_VERSION: string = HARMONY_SDK_VERSION;
  private static readonly SDK_MAJOR: number = HARMONY_SDK_MAJOR;
  private static readonly SDK_RELEASE_DATE: string = HARMONY_SDK_RELEASE_DATE;
  private static initialized: boolean = false;
  private static appContext?: Context;
  private static options: AmphionOptions = new AmphionOptions();
  private static licenseStatusHolder: AmphionLicenseStatus = AmphionLicenseStatus.notInitialized();
  private static runtimeGeneration: number = 0;
  private static initTask?: Promise<void>;
  private static nextSessionId: number = 1;
  private static asrPool: Map<AsrLanguage, OnlineRecognizer> = new Map<AsrLanguage, OnlineRecognizer>();
  // 复用兼容性必须按「该语言的池化 recognizer 实际用的配置」判定,而不是一个进程级全局配置。
  // asrPool 按语言分键,poolConfigKey 也必须按语言分键——否则多语言交替使用时,A 语言的 recognizer
  // 可能被拿 B 语言最后一次的配置误判为兼容而复用,导致 hotwords/线程数等静默用错。
  private static poolConfigKey: Map<AsrLanguage, string> = new Map<AsrLanguage, string>();
  private static recognizerLoads: Map<string, Promise<OnlineRecognizer>> =
    new Map<string, Promise<OnlineRecognizer>>();
  // Pooled speaker-embedding extractor(s), keyed by `${modelPath}|${numThreads}`. eres2net (~38 MB)
  // is expensive to load into onnxruntime (~3-4 s), so build it at most once per process and share it
  // across enrollment and every recognition session — mirrors asrPool for the recognizer.
  private static speakerExtractorPool: Map<string, SpeakerEmbeddingExtractor> = new Map<string, SpeakerEmbeddingExtractor>();
  private static speakerExtractorLoads: Map<string, Promise<SpeakerEmbeddingExtractor>> =
    new Map<string, Promise<SpeakerEmbeddingExtractor>>();
  // Pooled punctuation model (ct-transformer), keyed by `${punctModel}|${numThreads}`. Rebuilt cold in
  // the AsrEngine ctor otherwise, so a verify/VAD toggle re-loads it and adds to the start freeze.
  private static punctuationPool: Map<string, OfflinePunctuation> = new Map<string, OfflinePunctuation>();
  private static punctuationLoads: Map<string, Promise<OfflinePunctuation>> =
    new Map<string, Promise<OfflinePunctuation>>();
  private static itnPool: Map<string, WetextItn> = new Map<string, WetextItn>();
  // VAD free-list, keyed by config. A SherpaVad carries cross-call state (endpoint + ring buffer),
  // so it must NOT be shared by two concurrently-active sessions — reset()/acceptWaveform from one
  // would corrupt the other's endpoint detection. But a fresh SherpaVad (silero ONNX session + a
  // multi-MB ring buffer) built per session is only reclaimed by the NAPI finalizer on GC, so under
  // sequential start/stop churn GC lags and RSS climbs. Checkout/checkin solves both: the common
  // sequential case reuses one instance (flat RSS); a rare concurrent session finds the free-list
  // empty and builds its own isolated instance. Each key maps to a list of currently-free instances.
  private static vadPool: Map<string, SherpaVad[]> = new Map<string, SherpaVad[]>();
  private static loadGeneration: number = 0;

  static async init(context: Context, options?: AmphionOptions): Promise<void> {
    if (AmphionRuntime.initialized) {
      Logger.w('AmphionRuntime.init called more than once, ignored.');
      return;
    }
    const inFlight = AmphionRuntime.initTask;
    if (inFlight !== undefined) {
      await inFlight;
      return;
    }
    const generation = AmphionRuntime.runtimeGeneration;
    const optionsSnapshot = AmphionRuntime.snapshotOptions(options);
    const task = AmphionRuntime.initializeRuntime(context, optionsSnapshot, generation);
    AmphionRuntime.initTask = task;
    try {
      await task;
    } finally {
      if (AmphionRuntime.initTask === task) AmphionRuntime.initTask = undefined;
    }
  }

  /** 完整校验 License，但不改变 Runtime 初始化状态、模型池或全局 options。 */
  static validateLicense(context: Context, options: AmphionOptions): Promise<AmphionLicenseStatus> {
    return AmphionRuntime.evaluateLicense(context, AmphionRuntime.snapshotOptions(options));
  }

  private static async initializeRuntime(context: Context, options: AmphionOptions,
    generation: number): Promise<void> {
    Logger.setLevel(options.logLevel);
    const status = await AmphionRuntime.evaluateLicense(context, options);
    if (generation !== AmphionRuntime.runtimeGeneration) {
      throw new Error(`code=${AsrErrorCode.SDK_NOT_INITIALIZED}: AmphionRuntime.init cancelled by release`);
    }
    if (!status.valid && options.licenseEnforcement === LicenseEnforcement.ENFORCE) {
      throw new Error(`code=${status.errorCode}: AmphionRuntime license check failed (${status.message}).`);
    }
    AmphionRuntime.appContext = context;
    AmphionRuntime.options = options;
    AmphionRuntime.licenseStatusHolder = status;
    AmphionRuntime.initialized = true;
    Logger.i(`AmphionRuntime Harmony init done, version=${AmphionRuntime.SDK_VERSION}, license=${status.state}`);
  }

  static preInstall(context: Context, onProgress?: (stage: string, percent: number) => void): Cancellable {
    AmphionRuntime.checkInitialized();
    const c = new DoneCancellable();
    AmphionRuntime.appContext = context;
    onProgress?.('install', 0);
    AssetInstaller.ensureInstalled(context, AsrLanguage.ZH_EN, new AsrConfig());
    AssetInstaller.ensureInstalled(context, AsrLanguage.YUE_EN, new AsrConfig());
    onProgress?.('install', 100);
    c.markDone();
    return c;
  }

  static preload(context: Context, languages: AsrLanguage[], config?: AsrConfig, onProgress?: (stage: string, percent: number) => void): Cancellable {
    AmphionRuntime.checkInitialized();
    const c = new DoneCancellable();
    AmphionRuntime.appContext = context;
    const effectiveConfig = AmphionRuntime.snapshotConfig(config);
    const languageSnapshot = languages.slice();
    onProgress?.('install', 0);
    for (let i = 0; i < languageSnapshot.length; i++) {
      if (c.isCancelled()) break;
      const language = languageSnapshot[i];
      const layout = AssetInstaller.ensureInstalled(context, language, effectiveConfig).layout;
      AmphionRuntime.getOrCreateItn(language, layout, effectiveConfig);
      onProgress?.('install', Math.round(((i + 1) / Math.max(languageSnapshot.length, 1)) * 100));
      const stage = `asr-${language}`;
      onProgress?.(stage, 0);
      const preloadRecognizer = new OnlineRecognizer(AmphionRuntime.buildRecognizerConfig(layout, effectiveConfig), context.resourceManager);
      AmphionRuntime.warmUpRecognizer(preloadRecognizer);
      AmphionRuntime.asrPool.set(language, preloadRecognizer);
      AmphionRuntime.poolConfigKey.set(language, AmphionRuntime.recognizerConfigKey(effectiveConfig));
      onProgress?.(stage, 100);
    }
    c.markDone();
    return c;
  }

  /**
   * Background preload for Harmony hosts. Native model/session construction runs in N-API async
   * work and concurrent calls for the same language/config share one in-flight load.
   */
  static async preloadAsync(
    context: Context,
    languages: AsrLanguage[],
    config?: AsrConfig,
    onProgress?: (stage: string, percent: number) => void
  ): Promise<void> {
    AmphionRuntime.checkInitialized();
    const generation = AmphionRuntime.loadGeneration;
    AmphionRuntime.appContext = context;
    const effectiveConfig = AmphionRuntime.snapshotConfig(config);
    const languageSnapshot = languages.slice();
    onProgress?.('load', 0);
    for (let i = 0; i < languageSnapshot.length; i++) {
      const language = languageSnapshot[i];
      const layout = AssetInstaller.ensureInstalled(context, language, effectiveConfig).layout;
      AmphionRuntime.getOrCreateItn(language, layout, effectiveConfig);
      const recognizerTask = AmphionRuntime.getOrCreateRecognizerAsync(
        context, language, layout, effectiveConfig);
      const punctuationTask = AmphionRuntime.timedPunctuationLoadAsync(
        context, layout, effectiveConfig);
      await recognizerTask;
      await punctuationTask;
      if (generation !== AmphionRuntime.loadGeneration || !AmphionRuntime.initialized) {
        throw new Error(`code=${AsrErrorCode.SDK_NOT_INITIALIZED}: runtime released during preload`);
      }
      onProgress?.('load', Math.round(((i + 1) / Math.max(languageSnapshot.length, 1)) * 100));
    }
    if (generation !== AmphionRuntime.loadGeneration || !AmphionRuntime.initialized) {
      throw new Error(`code=${AsrErrorCode.SDK_NOT_INITIALIZED}: runtime released during preload`);
    }
  }

  static create(context: Context, language: AsrLanguage, config?: AsrConfig): AsrEngine {
    AmphionRuntime.checkInitialized();
    const effectiveConfig = AmphionRuntime.snapshotConfig(config);
    const createStartMs = Date.now();
    const layoutStartMs = Date.now();
    const layout = AssetInstaller.ensureInstalled(context, language, effectiveConfig).layout;
    const assetLayoutMs = Date.now() - layoutStartMs;
    const pooled = AmphionRuntime.asrPool.get(language);
    const requestedConfigKey = AmphionRuntime.recognizerConfigKey(effectiveConfig);
    const canReusePool = pooled !== undefined &&
      AmphionRuntime.poolConfigKey.get(language) === requestedConfigKey;
    const recognizerStartMs = Date.now();
    const recognizer = canReusePool ? pooled as OnlineRecognizer :
      new OnlineRecognizer(AmphionRuntime.buildRecognizerConfig(layout, effectiveConfig), context.resourceManager);
    const recognizerLoadMs = Date.now() - recognizerStartMs;
    let warmupMs = 0;
    if (!canReusePool) {
      // Keep the warmup hook for model profiles that need it. zhen currently passes zero because
      // ORT Session creation already pays the material initialization costs.
      const warmupStartMs = Date.now();
      AmphionRuntime.warmUpRecognizer(recognizer);
      warmupMs = Date.now() - warmupStartMs;
      // 缓存已预热的 recognizer:开启声纹/说话人VAD 会改会话级配置触发 rebuildEngine→create,
      // 但 recognizer 配置并不随之变(见 recognizerConfigKey)。缓存后 rebuild 直接复用,
      // 不再冷加载重来一遍(否则点"开始识别"卡 3~4 秒)。close() 从不释放 native recognizer,复用安全。
      AmphionRuntime.asrPool.set(language, recognizer);
      AmphionRuntime.poolConfigKey.set(language, requestedConfigKey);
    }
    let punctuation: OfflinePunctuation | undefined;
    const itn = AmphionRuntime.getOrCreateItn(language, layout, effectiveConfig);
    let punctuationLoadMs = 0;
    if (effectiveConfig.punctuation && layout.punctModel !== undefined) {
      const punctuationStartMs = Date.now();
      try {
        punctuation = AmphionRuntime.getOrCreatePunctuation(
          context, layout.punctModel, effectiveConfig.numThreads);
      } catch (e) {
        Logger.w(`punctuation disabled: ${e}`);
      } finally {
        punctuationLoadMs = Date.now() - punctuationStartMs;
      }
    }
    const engine = new AsrEngine(
      context,
      language,
      effectiveConfig,
      layout,
      recognizer,
      !canReusePool,
      -1,
      punctuation,
      itn,
      punctuationLoadMs
    );
    const engineReadyMs = Date.now() - createStartMs;
    engine.setEngineReadyMs(engineReadyMs);
    Logger.metric(
      `kind=LOAD language=${language} pooled=${canReusePool} assetLayoutMs=${assetLayoutMs} ` +
      `recognizerLoadMs=${recognizerLoadMs} warmupMs=${warmupMs} ` +
      `punctuationLoadMs=${engine.punctuationLoadDurationMs()} engineReadyMs=${engineReadyMs}`
    );
    return engine;
  }

  static async createAsync(
    context: Context,
    language: AsrLanguage,
    config?: AsrConfig
  ): Promise<AsrEngine> {
    AmphionRuntime.checkInitialized();
    const generation = AmphionRuntime.loadGeneration;
    const effectiveConfig = AmphionRuntime.snapshotConfig(config);
    const createStartMs = Date.now();
    const layoutStartMs = Date.now();
    const layout = AssetInstaller.ensureInstalled(context, language, effectiveConfig).layout;
    const assetLayoutMs = Date.now() - layoutStartMs;
    const requestedConfigKey = AmphionRuntime.recognizerConfigKey(effectiveConfig);
    const pooled = AmphionRuntime.asrPool.get(language);
    const canReusePool = pooled !== undefined &&
      AmphionRuntime.poolConfigKey.get(language) === requestedConfigKey;

    // Start the independent ASR and punctuation loads before awaiting either one. The N-API layer
    // performs native work off the ArkTS event thread; single-flight helpers prevent duplicate loads.
    const recognizerTask = AmphionRuntime.timedRecognizerLoadAsync(
      context, language, layout, effectiveConfig);
    const punctuationTask = AmphionRuntime.timedPunctuationLoadAsync(
      context, layout, effectiveConfig);
    const recognizerLoad = await recognizerTask;
    const punctuationLoad = await punctuationTask;
    const itn = AmphionRuntime.getOrCreateItn(language, layout, effectiveConfig);
    if (generation !== AmphionRuntime.loadGeneration || !AmphionRuntime.initialized) {
      throw new Error(`code=${AsrErrorCode.SDK_NOT_INITIALIZED}: runtime released during model load`);
    }

    const engine = new AsrEngine(
      context,
      language,
      effectiveConfig,
      layout,
      recognizerLoad.recognizer,
      !canReusePool,
      -1,
      punctuationLoad.punctuation,
      itn,
      punctuationLoad.elapsedMs
    );
    const engineReadyMs = Date.now() - createStartMs;
    engine.setEngineReadyMs(engineReadyMs);
    Logger.metric(
      `kind=LOAD language=${language} async=true pooled=${canReusePool} assetLayoutMs=${assetLayoutMs} ` +
      `recognizerReadyMs=${recognizerLoad.elapsedMs} punctuationReadyMs=${punctuationLoad.elapsedMs} ` +
      `engineReadyMs=${engineReadyMs}`
    );
    return engine;
  }

  // Optional one-time silence decode for model profiles where first-run latency exceeds the
  // engine-ready cost. Disabled for zhen by EAGER_WARMUP_DURATION_MS=0 after device A/B testing.
  private static warmUpRecognizer(recognizer: OnlineRecognizer): void {
    try {
      const n = Math.round(ASR_SAMPLE_RATE_HZ * EAGER_WARMUP_DURATION_MS / 1000);
      if (n <= 0) return;
      const stream = recognizer.createStream();
      try {
        const wave: Samples = { samples: new Float32Array(n), sampleRate: ASR_SAMPLE_RATE_HZ } as Samples;
        stream.acceptWaveform(wave);
        while (recognizer.isReady(stream)) recognizer.decode(stream);
        recognizer.reset(stream);
      } finally {
        stream.close();
      }
    } catch (e) {
      Logger.w(`warmUpRecognizer skipped: ${e}`);
    }
  }

  /**
   * Pooled speaker-embedding extractor. Built at most once per process and shared across enrollment
   * and every recognition session. Registration, explicit preload, and Speaker VAD use this
   * synchronous path; final-only verification uses getOrCreateSpeakerExtractorAsync instead.
   * An absolute modelPath is read from the filesystem (rm=undefined); a rawfile-relative name uses
   * the resourceManager loader — same rule as SpeakerEnroller (avoids the rawfile-loader crash).
   */
  static getOrCreateSpeakerExtractor(context: Context | undefined, modelPath: string, numThreads: number): SpeakerEmbeddingExtractor {
    AmphionRuntime.checkInitialized();
    const key = `${modelPath}|${numThreads}`;
    const cached = AmphionRuntime.speakerExtractorPool.get(key);
    if (cached !== undefined) return cached;
    const cfg = new SpeakerEmbeddingExtractorConfig();
    cfg.model = modelPath;
    cfg.numThreads = numThreads;
    cfg.debug = false;
    const rm = modelPath.startsWith('/') ? undefined : context?.resourceManager;
    const extractor = new SpeakerEmbeddingExtractor(cfg, rm);
    AmphionRuntime.warmUpExtractor(extractor);
    AmphionRuntime.speakerExtractorPool.set(key, extractor);
    return extractor;
  }

  /**
   * True background speaker-extractor load with one in-flight task per model/config. Native model
   * construction and the one-second silence warmup both run in N-API async work, so callers can
   * continue streaming ASR audio while the final-only voiceprint path becomes ready.
   */
  static async getOrCreateSpeakerExtractorAsync(context: Context | undefined,
    modelPath: string, numThreads: number): Promise<SpeakerEmbeddingExtractor> {
    AmphionRuntime.checkInitialized();
    const key = `${modelPath}|${numThreads}`;
    const cached = AmphionRuntime.speakerExtractorPool.get(key);
    if (cached !== undefined) return cached;

    let load = AmphionRuntime.speakerExtractorLoads.get(key);
    if (load === undefined) {
      const generation = AmphionRuntime.loadGeneration;
      const cfg = new SpeakerEmbeddingExtractorConfig();
      cfg.model = modelPath;
      cfg.numThreads = numThreads;
      cfg.debug = false;
      const rm = modelPath.startsWith('/') ? undefined : context?.resourceManager;
      const newLoad = SpeakerEmbeddingExtractor.createAsync(cfg, rm, ASR_SAMPLE_RATE_HZ)
        .then((extractor: SpeakerEmbeddingExtractor): SpeakerEmbeddingExtractor => {
          if (generation !== AmphionRuntime.loadGeneration || !AmphionRuntime.initialized) {
            extractor.close();
            throw new Error(`code=${AsrErrorCode.SDK_NOT_INITIALIZED}: runtime released during speaker load`);
          }
          // A synchronous registration/Speaker-VAD load may have completed while this worker was
          // running. Keep that published instance and deterministically release this late loser.
          const winner = AmphionRuntime.speakerExtractorPool.get(key);
          if (winner !== undefined) {
            extractor.close();
            return winner;
          }
          AmphionRuntime.speakerExtractorPool.set(key, extractor);
          return extractor;
        });
      AmphionRuntime.speakerExtractorLoads.set(key, newLoad);
      load = newLoad;
    }

    const activeLoad: Promise<SpeakerEmbeddingExtractor> = load;
    try {
      const extractor = await activeLoad;
      if (AmphionRuntime.speakerExtractorLoads.get(key) === activeLoad) {
        AmphionRuntime.speakerExtractorLoads.delete(key);
      }
      return extractor;
    } catch (e) {
      if (AmphionRuntime.speakerExtractorLoads.get(key) === activeLoad) {
        AmphionRuntime.speakerExtractorLoads.delete(key);
      }
      throw new Error(`speaker extractor load failed: ${e}`);
    }
  }

  // Force onnxruntime's lazy graph/weight init by computing one embedding over 1 s of silence, so the
  // first real segment during recognition doesn't pay it. Best-effort; failure never blocks.
  private static warmUpExtractor(extractor: SpeakerEmbeddingExtractor): void {
    try {
      const stream = extractor.createStream();
      try {
        const wave: Samples = {
          samples: new Float32Array(ASR_SAMPLE_RATE_HZ),
          sampleRate: ASR_SAMPLE_RATE_HZ
        } as Samples;
        stream.acceptWaveform(wave);
        extractor.compute(stream);
      } finally {
        stream.close();
      }
    } catch (e) {
      Logger.w(`warmUpExtractor skipped: ${e}`);
    }
  }

  // Pooled punctuation model. ct-transformer is a rawfile-relative asset (layout.punctModel), so the
  // resourceManager loader is correct here. Built once and shared; stateless across addPunct calls.
  static getOrCreatePunctuation(context: Context, punctModel: string, numThreads: number): OfflinePunctuation {
    const key = `${punctModel}|${numThreads}`;
    const cached = AmphionRuntime.punctuationPool.get(key);
    if (cached !== undefined) return cached;
    const pc = new OfflinePunctuationConfig();
    pc.model.ctTransformer = punctModel;
    pc.model.numThreads = numThreads;
    const punctuation = new OfflinePunctuation(pc, context.resourceManager);
    AmphionRuntime.punctuationPool.set(key, punctuation);
    return punctuation;
  }

  private static getOrCreateItn(
    language: AsrLanguage,
    layout: InstalledLayout,
    config: AsrConfig
  ): WetextItn | undefined {
    if (!config.itn || language !== AsrLanguage.ZH_EN ||
      layout.itnTagger === undefined || layout.itnVerbalizer === undefined) return undefined;
    const key = `${layout.itnTagger}|${layout.itnVerbalizer}`;
    const cached = AmphionRuntime.itnPool.get(key);
    if (cached !== undefined) return cached;
    const itnConfig = new WetextItnConfig();
    itnConfig.taggerFst = layout.itnTagger;
    itnConfig.verbalizerFst = layout.itnVerbalizer;
    const itn = new WetextItn(itnConfig);
    AmphionRuntime.itnPool.set(key, itn);
    return itn;
  }

  private static async timedRecognizerLoadAsync(
    context: Context,
    language: AsrLanguage,
    layout: InstalledLayout,
    config: AsrConfig
  ): Promise<AsyncRecognizerLoad> {
    const startedMs = Date.now();
    const recognizer = await AmphionRuntime.getOrCreateRecognizerAsync(
      context, language, layout, config);
    return new AsyncRecognizerLoad(recognizer, Date.now() - startedMs);
  }

  private static async timedPunctuationLoadAsync(
    context: Context,
    layout: InstalledLayout,
    config: AsrConfig
  ): Promise<AsyncPunctuationLoad> {
    const startedMs = Date.now();
    if (!config.punctuation || layout.punctModel === undefined) {
      return new AsyncPunctuationLoad(undefined, 0);
    }
    try {
      const punctuation = await AmphionRuntime.getOrCreatePunctuationAsync(
        context, layout.punctModel, config.numThreads);
      return new AsyncPunctuationLoad(punctuation, Date.now() - startedMs);
    } catch (e) {
      Logger.w(`punctuation disabled: ${e}`);
      return new AsyncPunctuationLoad(undefined, Date.now() - startedMs);
    }
  }

  private static async getOrCreateRecognizerAsync(
    context: Context,
    language: AsrLanguage,
    layout: InstalledLayout,
    config: AsrConfig
  ): Promise<OnlineRecognizer> {
    const configKey = AmphionRuntime.recognizerConfigKey(config);
    const cached = AmphionRuntime.asrPool.get(language);
    if (cached !== undefined && AmphionRuntime.poolConfigKey.get(language) === configKey) {
      return cached;
    }

    const loadKey = `${language}|${configKey}`;
    let load: Promise<OnlineRecognizer> | undefined =
      AmphionRuntime.recognizerLoads.get(loadKey);
    if (load === undefined) {
      const generation = AmphionRuntime.loadGeneration;
      const newLoad: Promise<OnlineRecognizer> = OnlineRecognizer.createAsync(
        AmphionRuntime.buildRecognizerConfig(layout, config),
        context.resourceManager,
        Math.round(ASR_SAMPLE_RATE_HZ * EAGER_WARMUP_DURATION_MS / 1000))
        .then((recognizer: OnlineRecognizer): OnlineRecognizer => {
          if (generation !== AmphionRuntime.loadGeneration || !AmphionRuntime.initialized) {
            throw new Error(`code=${AsrErrorCode.SDK_NOT_INITIALIZED}: runtime released during recognizer load`);
          }
          AmphionRuntime.asrPool.set(language, recognizer);
          AmphionRuntime.poolConfigKey.set(language, configKey);
          return recognizer;
        });
      AmphionRuntime.recognizerLoads.set(loadKey, newLoad);
      load = newLoad;
    }

    const activeLoad: Promise<OnlineRecognizer> = load;
    try {
      const recognizer = await activeLoad;
      if (AmphionRuntime.recognizerLoads.get(loadKey) === activeLoad) {
        AmphionRuntime.recognizerLoads.delete(loadKey);
      }
      return recognizer;
    } catch (e) {
      if (AmphionRuntime.recognizerLoads.get(loadKey) === activeLoad) {
        AmphionRuntime.recognizerLoads.delete(loadKey);
      }
      throw new Error(`recognizer load failed: ${e}`);
    }
  }

  private static async getOrCreatePunctuationAsync(
    context: Context,
    punctModel: string,
    numThreads: number
  ): Promise<OfflinePunctuation> {
    const key = `${punctModel}|${numThreads}`;
    const cached = AmphionRuntime.punctuationPool.get(key);
    if (cached !== undefined) return cached;

    let load: Promise<OfflinePunctuation> | undefined =
      AmphionRuntime.punctuationLoads.get(key);
    if (load === undefined) {
      const generation = AmphionRuntime.loadGeneration;
      const pc = new OfflinePunctuationConfig();
      pc.model.ctTransformer = punctModel;
      pc.model.numThreads = numThreads;
      const newLoad: Promise<OfflinePunctuation> =
        OfflinePunctuation.createAsync(pc, context.resourceManager)
        .then((punctuation: OfflinePunctuation): OfflinePunctuation => {
          if (generation !== AmphionRuntime.loadGeneration || !AmphionRuntime.initialized) {
            throw new Error(`code=${AsrErrorCode.SDK_NOT_INITIALIZED}: runtime released during punctuation load`);
          }
          AmphionRuntime.punctuationPool.set(key, punctuation);
          return punctuation;
        });
      AmphionRuntime.punctuationLoads.set(key, newLoad);
      load = newLoad;
    }

    const activeLoad: Promise<OfflinePunctuation> = load;
    try {
      const punctuation = await activeLoad;
      if (AmphionRuntime.punctuationLoads.get(key) === activeLoad) {
        AmphionRuntime.punctuationLoads.delete(key);
      }
      return punctuation;
    } catch (e) {
      if (AmphionRuntime.punctuationLoads.get(key) === activeLoad) {
        AmphionRuntime.punctuationLoads.delete(key);
      }
      throw new Error(`punctuation load failed: ${e}`);
    }
  }

  static vadKeyFor(
    vadModel: string,
    threshold: number,
    minSpeechDurationSec: number,
    minSilenceDurationSec: number,
    maxSpeechDurationSec: number
  ): string {
    return `${vadModel}|${threshold}|${minSpeechDurationSec}|${minSilenceDurationSec}|${maxSpeechDurationSec}`;
  }

  // Acquire a VAD for a session. Reuses a free pooled instance (flat RSS under sequential churn);
  // if none is free — i.e. another session already holds the pooled one — builds a fresh isolated
  // instance so concurrent sessions never share the stateful VAD. Caller resets it; release on close.
  // vadModel is rawfile-relative, so resourceManager is correct.
  static acquireVad(
    context: Context,
    vadModel: string,
    threshold: number,
    minSpeechDurationSec: number,
    minSilenceDurationSec: number,
    maxSpeechDurationSec: number
  ): SherpaVad {
    const key = AmphionRuntime.vadKeyFor(vadModel, threshold, minSpeechDurationSec, minSilenceDurationSec, maxSpeechDurationSec);
    const free = AmphionRuntime.vadPool.get(key);
    if (free !== undefined && free.length > 0) {
      return free.pop() as SherpaVad;
    }
    const silero = new SileroVadConfig(vadModel, threshold, minSpeechDurationSec, minSilenceDurationSec, 512, maxSpeechDurationSec);
    const ten = new TenVadConfig('', 0.5, 0.25, 0.5, 256);
    const cfg = new SherpaVadConfig(silero, ten, 16000, false, 1);
    return new SherpaVad(cfg, Math.max(60, Math.ceil(maxSpeechDurationSec + 5)), context.resourceManager);
  }

  // Return a session's VAD to the free list for reuse. The caller (AsrSession.close) guards via its
  // `closed` flag + nulling this.vad, so a given instance is pushed back at most once.
  static releaseVad(key: string, vad: SherpaVad): void {
    let free = AmphionRuntime.vadPool.get(key);
    if (free === undefined) {
      free = [];
      AmphionRuntime.vadPool.set(key, free);
    }
    free.push(vad);
  }

  static version(): string { return AmphionRuntime.SDK_VERSION; }
  static licenseStatus(): AmphionLicenseStatus {
    return AmphionRuntime.licenseStatusHolder;
  }

  /**
   * Real ECDSA signature verification of a raw .lic envelope against the injected public key.
   * Returns true on an unarmed (development) build. Callers (e.g. the Dingqiao setLicense path) invoke this
   * before init() so a forged / tampered license is rejected up front rather than trusted by binding checks.
   */
  static verifyLicenseSignature(licenseText: string | undefined): Promise<boolean> {
    return HarmonyLicenseVerifier.verifySignature(licenseText, HarmonyLicenseVerifier.publicKey());
  }

  /**
   * SN 白名单校验（对齐 Android）。true = 未绑 SN 或该设备 SN 在白名单内；
   * false = license 绑了 SN 但本机 SN 缺失 / 不在白名单。
   */
  static checkDeviceBinding(licenseText: string | undefined, deviceSerial: string | undefined): Promise<boolean> {
    return HarmonyLicenseVerifier.deviceHashOk(licenseText, deviceSerial);
  }
  /**
   * 模型级卸载(两级加载的 L2)。清空所有模型池并 bump loadGeneration,使正在进行的 async 加载失效;
   * 池化的 recognizer / punctuation / speaker extractor 会显式 close；VAD 引用清空后由 NAPI
   * finalizer 回收。区别于 release() 的是本方法**保留运行时**
   * (initialized / appContext / license 不变),下次 create 只需重付模型加载,无需重建运行时。
   */
  static unloadModel(): void {
    AmphionRuntime.loadGeneration += 1;
    // 显式释放 native session 内存(否则清 Map 只丢引用,native 权重要等 GC finalizer 才回收 → 内存不降)。
    // close() 幂等,native handle 的 Close() 防双重释放,与后续 GC 回收 wrapper 对象安全共存。
    AmphionRuntime.asrPool.forEach((r: OnlineRecognizer): void => {
      try { r.close(); } catch (e) { Logger.w(`recognizer close failed: ${e}`); }
    });
    AmphionRuntime.punctuationPool.forEach((p: OfflinePunctuation): void => {
      try { p.close(); } catch (e) { Logger.w(`punctuation close failed: ${e}`); }
    });
    AmphionRuntime.itnPool.forEach((itn: WetextItn): void => {
      try { itn.close(); } catch (e) { Logger.w(`ITN close failed: ${e}`); }
    });
    AmphionRuntime.speakerExtractorPool.forEach((extractor: SpeakerEmbeddingExtractor): void => {
      try { extractor.close(); } catch (e) { Logger.w(`speaker extractor close failed: ${e}`); }
    });
    AmphionRuntime.asrPool.clear();
    AmphionRuntime.recognizerLoads.clear();
    AmphionRuntime.speakerExtractorPool.clear();
    AmphionRuntime.speakerExtractorLoads.clear();
    AmphionRuntime.punctuationPool.clear();
    AmphionRuntime.punctuationLoads.clear();
    AmphionRuntime.itnPool.clear();
    AmphionRuntime.vadPool.clear();
    AmphionRuntime.poolConfigKey.clear();
  }

  /** 是否有已加载的模型(任一模型池非空)。 */
  static isModelLoaded(): boolean {
    return AmphionRuntime.asrPool.size > 0 ||
      AmphionRuntime.punctuationPool.size > 0 ||
      AmphionRuntime.itnPool.size > 0 ||
      AmphionRuntime.speakerExtractorPool.size > 0;
  }

  /** 运行时是否就绪(已 init)。 */
  static isRuntimeReady(): boolean { return AmphionRuntime.initialized; }

  /**
   * 运行时级卸载(两级加载的 L1)。先卸载模型(「若没卸载模型,则模型跟随卸载」),再重置运行时状态
   * 为未初始化。native .so 由 OS 保留映射,无法在进程内真正 unload。
   */
  static release(): void {
    AmphionRuntime.runtimeGeneration += 1;
    // Promise 本身不可取消；清掉 single-flight 引用允许后续 init 立即开始，旧任务会被 generation 拒绝提交。
    AmphionRuntime.initTask = undefined;
    AmphionRuntime.unloadModel();
    AmphionRuntime.initialized = false;
    AmphionRuntime.appContext = undefined;
    AmphionRuntime.options = new AmphionOptions();
    AmphionRuntime.licenseStatusHolder = AmphionLicenseStatus.notInitialized();
  }

  static allocateSessionId(): number { return AmphionRuntime.nextSessionId++; }

  static activeOnlineStreamCount(): number { return onlineStreamLiveCount(); }

  static eagerWarmupSamples(): number {
    return Math.round(ASR_SAMPLE_RATE_HZ * EAGER_WARMUP_DURATION_MS / 1000);
  }

  static buildRecognizerConfig(layout: InstalledLayout, config: AsrConfig): OnlineRecognizerConfig {
    const model = new OnlineModelConfig();
    model.transducer.encoder = layout.asrEncoder;
    model.transducer.decoder = layout.asrDecoder;
    model.transducer.joiner = layout.asrJoiner;
    model.tokens = layout.asrTokens;
    model.modelType = 'zipformer2';
    model.modelingUnit = 'bbpe';
    model.bpeVocab = layout.asrBpeVocab;
    model.numThreads = config.numThreads;
    model.debug = false;
    // provider 内联配置把「跳过 prepack」下发到 native session.cc(零 C-API/ABI 改动)。
    model.provider = config.disablePrepack ? 'cpu;DisablePrepacking=1' : 'cpu';

    const rc = new OnlineRecognizerConfig();
    rc.modelConfig = model;
    rc.decodingMethod = 'modified_beam_search';
    rc.maxActivePaths = 8;
    rc.enableEndpoint = config.endpoint;
    rc.rule1MinTrailingSilence = config.endpointRules.rule1 ? config.endpointRules.rule1MinTrailingSilenceSec : 100000.0;
    rc.rule2MinTrailingSilence = config.endpointRules.rule2 ? config.endpointRules.rule2MinTrailingSilenceSec : 100000.0;
    rc.rule3MinUtteranceLength = config.endpointRules.rule3MinUtteranceLengthSec;
    rc.hotwordsScore = config.hotwordsScore;
    rc.hotwordsBuf = config.hotwords.join('\n');
    rc.hotwordsBufSize = rc.hotwordsBuf.length;
    return rc;
  }

  private static checkInitialized(): void {
    if (!AmphionRuntime.initialized) {
      throw new Error(`code=${AsrErrorCode.SDK_NOT_INITIALIZED}: AmphionRuntime.init must be called first`);
    }
  }

  // 核心鉴权(双保险,与安卓 LicenseVerifier.verify 的内联签名校验对齐):
  //  ① 同步结构校验(cert / feature / 有效期 / SN 存在性等,见 HarmonyLicenseVerifier.verify)。
  //  ② armed build(注入了公钥)且携带 license 时,核心路径再强制 ECDSA 签名校验 + SN 白名单成员判定。
  // 任一失败即 fail-closed。这样即使调用方(非交付 wrapper)未先手动跑 verifyLicenseSignature / checkDeviceBinding,
  // init(ENFORCE) 也不会接受被伪造/篡改的 license 或非白名单设备——不再依赖 wrapper 的前置门做唯一防线。
  private static snapshotOptions(source?: AmphionOptions): AmphionOptions {
    const input = source ?? new AmphionOptions();
    const snapshot = new AmphionOptions();
    snapshot.logLevel = input.logLevel;
    snapshot.license = input.license;
    snapshot.licenseAssetName = input.licenseAssetName;
    snapshot.expiryGraceDays = input.expiryGraceDays;
    snapshot.licenseEnforcement = input.licenseEnforcement;
    snapshot.deviceIdProvider = input.deviceIdProvider;
    snapshot.bundleName = input.bundleName;
    snapshot.signingCertDigest = input.signingCertDigest;
    return snapshot;
  }

  private static async evaluateLicense(context: Context,
    options: AmphionOptions): Promise<AmphionLicenseStatus> {
    const serial = options.deviceIdProvider?.getDeviceSerial(context);
    // 单次解析快速路径:结构校验 + ECDSA 验签 + SN 白名单一遍完成,替代原先 verify()+verifySignature()+
    // deviceHashOk() 对同一份 4MB payload 的 3 次重复解析(6万台白名单尤其慢)。行为/错误码/门禁顺序等价、
    // 仍 fail-closed,详见 HarmonyLicenseVerifier.evaluate。
    return await HarmonyLicenseVerifier.evaluate(
      options.license,
      options.bundleName,
      options.signingCertDigest,
      serial,
      HarmonyLicenseVerifier.publicKey(),
      AmphionRuntime.SDK_MAJOR,
      AmphionRuntime.SDK_RELEASE_DATE
    );
  }

  // Async model construction must not observe caller mutations half-way through a load. Keep a
  // field-level snapshot rather than retaining the public, mutable config and its nested objects.
  private static snapshotConfig(config?: AsrConfig): AsrConfig {
    const source = config ?? new AsrConfig();
    const snapshot = new AsrConfig();
    snapshot.numThreads = source.numThreads;
    snapshot.punctuation = source.punctuation;
    snapshot.itn = source.itn;
    snapshot.vad = source.vad;
    snapshot.endpoint = source.endpoint;
    snapshot.disablePrepack = source.disablePrepack;
    snapshot.hotwords = source.hotwords.slice();
    snapshot.hotwordsScore = source.hotwordsScore;

    const vad = new VadConfig();
    vad.modelType = source.vadConfig.modelType;
    vad.threshold = source.vadConfig.threshold;
    vad.minSilenceDurationSec = source.vadConfig.minSilenceDurationSec;
    vad.minSpeechDurationSec = source.vadConfig.minSpeechDurationSec;
    vad.maxSpeechDurationSec = source.vadConfig.maxSpeechDurationSec;
    vad.activeEndpointSilenceMs = source.vadConfig.activeEndpointSilenceMs;
    snapshot.vadConfig = vad;

    const endpoint = new EndpointRules();
    endpoint.rule1 = source.endpointRules.rule1;
    endpoint.rule1MinTrailingSilenceSec = source.endpointRules.rule1MinTrailingSilenceSec;
    endpoint.rule2 = source.endpointRules.rule2;
    endpoint.rule2MinTrailingSilenceSec = source.endpointRules.rule2MinTrailingSilenceSec;
    endpoint.rule3MinUtteranceLengthSec = source.endpointRules.rule3MinUtteranceLengthSec;
    snapshot.endpointRules = endpoint;

    const sourceTarget = source.targetSpeaker;
    if (sourceTarget !== undefined) {
      const target = new TargetSpeakerConfig();
      target.modelPath = sourceTarget.modelPath;
      target.threshold = sourceTarget.threshold;
      target.winSec = sourceTarget.winSec;
      target.hopSec = sourceTarget.hopSec;
      target.minSegSec = sourceTarget.minSegSec;
      target.preload = sourceTarget.preload;
      target.deferLoad = sourceTarget.deferLoad;
      target.enabledByDefault = sourceTarget.enabledByDefault;
      target.numThreads = sourceTarget.numThreads;
      const sourceSpeakerVad = sourceTarget.speakerVad;
      if (sourceSpeakerVad !== undefined) {
        const speakerVad = new SpeakerVadConfig();
        speakerVad.threshold = sourceSpeakerVad.threshold;
        speakerVad.winSec = sourceSpeakerVad.winSec;
        speakerVad.hopSec = sourceSpeakerVad.hopSec;
        speakerVad.consecutiveBelow = sourceSpeakerVad.consecutiveBelow;
        speakerVad.enabledByDefault = sourceSpeakerVad.enabledByDefault;
        target.speakerVad = speakerVad;
      }
      snapshot.targetSpeaker = target;
    }
    return snapshot;
  }

  private static recognizerConfigKey(config: AsrConfig): string {
    return [
      `${config.numThreads}`,
      `${config.endpoint}`,
      `${config.endpointRules.rule1}`,
      `${config.endpointRules.rule2}`,
      `${config.endpointRules.rule1MinTrailingSilenceSec}`,
      `${config.endpointRules.rule2MinTrailingSilenceSec}`,
      `${config.endpointRules.rule3MinUtteranceLengthSec}`,
      `${config.hotwordsScore}`,
      `${config.disablePrepack}`,
      config.hotwords.join('\n')
    ].join('|');
  }
}

export class AsrEngine {
  private context: Context;
  private language: AsrLanguage;
  private config: AsrConfig;
  private layout: InstalledLayout;
  private recognizer: OnlineRecognizer;
  private punctuation?: OfflinePunctuation;
  private itn?: WetextItn;
  private targetExtractor?: SpeakerEmbeddingExtractor;
  private closed: boolean = false;
  private sessions: AsrSession[] = [];
  private ownsRecognizer: boolean = true;
  private engineReadyMs: number = -1;
  private punctuationLoadMs: number = 0;

  constructor(
    context: Context,
    language: AsrLanguage,
    config: AsrConfig,
    layout: InstalledLayout,
    recognizer: OnlineRecognizer,
    ownsRecognizer: boolean,
    engineReadyMs: number,
    punctuation?: OfflinePunctuation,
    itn?: WetextItn,
    punctuationLoadMs: number = 0
  ) {
    this.context = context;
    this.language = language;
    this.config = config;
    this.layout = layout;
    this.recognizer = recognizer;
    this.ownsRecognizer = ownsRecognizer;
    this.engineReadyMs = engineReadyMs;
    this.punctuation = punctuation;
    this.itn = itn;
    this.punctuationLoadMs = punctuationLoadMs;
    if (config.targetSpeaker !== undefined && config.targetSpeaker.preload &&
      !config.targetSpeaker.deferLoad) {
      this.targetExtractor = this.createSpeakerExtractor(config.targetSpeaker);
    }
  }

  newSession(callback: AsrCallback, sessionConfig: SessionConfig = new SessionConfig()): AsrSession {
    if (this.closed) throw new Error('AsrEngine is closed');
    validateSessionConfig(sessionConfig);
    if (this.config.targetSpeaker !== undefined && this.targetExtractor === undefined &&
      !this.config.targetSpeaker.deferLoad) {
      this.targetExtractor = this.createSpeakerExtractor(this.config.targetSpeaker);
    }
    const session = new AsrSession(
      AmphionRuntime.allocateSessionId(),
      this.context,
      this.language,
      this.config,
      this.layout,
      this.recognizer,
      this.punctuation,
      this.itn,
      this.targetExtractor,
      sessionConfig,
      callback,
      this.engineReadyMs
    );
    const targetConfig = this.config.targetSpeaker;
    if (targetConfig !== undefined && targetConfig.deferLoad && targetConfig.enabledByDefault) {
      session.setTargetSpeakerEnabled(true);
    }
    this.sessions.push(session);
    return session;
  }

  isClosed(): boolean { return this.closed; }
  isPunctuationLoaded(): boolean { return this.punctuation !== undefined; }
  setEngineReadyMs(value: number): void { this.engineReadyMs = value; }
  punctuationLoadDurationMs(): number { return this.punctuationLoadMs; }
  close(): void {
    if (this.closed) return;
    this.closed = true;
    for (let i = 0; i < this.sessions.length; i++) {
      this.sessions[i].close();
    }
    this.sessions = [];
    if (this.ownsRecognizer) Logger.d('dedicated Harmony recognizer closed');
  }

  private createSpeakerExtractor(config: TargetSpeakerConfig): SpeakerEmbeddingExtractor {
    // Reuse the pooled, pre-warmed extractor (populated at registration / preload) so recognition
    // start never blocks on the ~38 MB eres2net load. The rawfile-vs-filesystem loader choice
    // (the crash fix: absolute path must NOT get a resourceManager) lives in getOrCreateSpeakerExtractor.
    return AmphionRuntime.getOrCreateSpeakerExtractor(this.context, config.modelPath, config.numThreads);
  }
}

export class AsrSession {
  private sessionId: number;
  private context: Context;
  private language: AsrLanguage;
  private config: AsrConfig;
  private layout: InstalledLayout;
  private recognizer: OnlineRecognizer;
  private stream: OnlineStream;
  private punctuation?: OfflinePunctuation;
  private itn?: WetextItn;
  private vad?: SherpaVad;
  private vadKey: string = '';
  private vadWindowSize: number = 512;
  private targetExtractor?: SpeakerEmbeddingExtractor;
  private targetExtractorLoad?: Promise<SpeakerEmbeddingExtractor>;
  private targetSpeaker?: Float32Array;
  private targetSpeakerEnabled: boolean = false;
  private speakerVadEnabled: boolean = false;
  private lastSpeakerVadScore: number = -1;
  // VAD gate state (Android-aligned): VAD only gates / drives an early active endpoint while PCM is
  // fed to the recognizer in full so partial results stay real-time.
  private vadSpeechActive: boolean = false;
  private trailingSilenceMs: number = 0;
  private vadCarry: Float32Array = new Float32Array(0);
  private initialSilenceTracker: InitialSilenceTracker = new InitialSilenceTracker(0, ASR_SAMPLE_RATE_HZ);
  // Speaker-VAD sliding-window state (Android-aligned two-phase: confirm target -> detect departure).
  private svScoreScheduler?: SpeakerVadScoreScheduler;
  private svTargetConfirmed: boolean = false;
  private svBelowCount: number = 0;
  private svRejectCurrentUtterance: boolean = false;
  private callback: AsrCallback;
  private callbackGate: SessionCallbackGate = new SessionCallbackGate();
  private reentryQueue: SessionReentryQueue = new SessionReentryQueue();
  private streamCallDepth: number = 0;
  private streamReleased: boolean = false;
  private pcmFloatScratch: Float32Array = new Float32Array(0);
  private lastPartialText: string = '';
  private pcmBytesAccepted: number = 0;
  private totalPcmBytes: number = 0;
  private utteranceIndex: number = 0;
  private recognizerResetGeneration: number = 0;
  private utteranceStartMs: number = Date.now();
  private firstPcmMs: number = -1;
  private firstPartialLatencyMs: number = -1;
  private rtfValues: number[] = [];
  private speakerPcmBuffers: SpeakerPcmBuffers = new SpeakerPcmBuffers(UTT_MAX_SAMPLES);
  private effectiveSpeechBuffer: EffectiveSpeechBuffer =
    new EffectiveSpeechBuffer(ASR_SAMPLE_RATE_HZ, UTT_MAX_SAMPLES);
  private engineReadyMs: number = -1;
  private stoppedNotified: boolean = false;
  private stopNotificationPending: boolean = false;
  private pendingSpeakerFinals: PendingSpeakerFinal[] = [];
  private sessionConfig: SessionConfig;

  constructor(sessionId: number, context: Context, language: AsrLanguage, config: AsrConfig, layout: InstalledLayout, recognizer: OnlineRecognizer, punctuation: OfflinePunctuation | undefined, itn: WetextItn | undefined, targetExtractor: SpeakerEmbeddingExtractor | undefined, sessionConfig: SessionConfig, callback: AsrCallback, engineReadyMs: number) {
    this.sessionId = sessionId;
    this.context = context;
    this.language = language;
    this.config = config;
    this.layout = layout;
    this.recognizer = recognizer;
    this.stream = recognizer.createStream();
    this.punctuation = punctuation;
    this.itn = itn;
    this.targetExtractor = targetExtractor;
    this.sessionConfig = sessionConfig;
    this.targetSpeakerEnabled = config.targetSpeaker?.enabledByDefault ?? false;
    this.speakerVadEnabled = this.effectiveSpeakerVad()?.enabledByDefault ?? false;
    this.callback = callback;
    this.engineReadyMs = engineReadyMs;
    const initialSilenceTimeoutMs = sessionConfig.initialSilenceTimeoutMs ?? 0;
    const requestedConfirmationGraceMs = sessionConfig.initialSilenceConfirmationGraceMs ?? 0;
    const maxConfirmationGraceMs = config.targetSpeaker === undefined ? 0 :
      Math.max(0, Math.round(config.targetSpeaker.minSegSec * 1000));
    const initialSilenceConfirmationGraceMs = Math.min(
      requestedConfirmationGraceMs, maxConfirmationGraceMs);
    this.initialSilenceTracker = new InitialSilenceTracker(
      initialSilenceTimeoutMs, ASR_SAMPLE_RATE_HZ, initialSilenceConfirmationGraceMs);
    if (config.vad) {
      this.vad = this.createVad();
    }
    // 预热已前移到 recognizer 创建处一次性完成(见 AmphionRuntime.warmUpRecognizer),
    // 这里不再每次 startListening 都跑 encoder,避免每次点"开始识别"卡 3~4 秒。
    this.callbackGate.invoke((): void => { this.callback.onSessionStarted?.(); });
  }

  acceptPcmShort(samples: Int16Array): void {
    if (this.callbackGate.isClosed()) return;
    const reentrant = this.shouldDeferSessionOperation();
    let converted: Float32Array;
    if (reentrant) {
      // Never overwrite the scratch buffer still owned by the outer acceptPcmShort call.
      converted = new Float32Array(samples.length);
    } else {
      if (this.pcmFloatScratch.length !== samples.length) {
        this.pcmFloatScratch = new Float32Array(samples.length);
      }
      converted = this.pcmFloatScratch;
    }
    for (let i = 0; i < samples.length; i++) converted[i] = samples[i] / 32768.0;
    this.acceptPcmFloat(converted);
  }

  acceptPcmBytes(bytes: ArrayBuffer): void {
    if (bytes.byteLength % 2 !== 0) {
      this.callbackGate.invoke((): void => {
        this.callback.onError?.(new AsrError(
          AsrErrorCode.INVALID_ARGUMENT, 'PCM byte length must be even for int16 samples'));
      });
      return;
    }
    this.acceptPcmShort(new Int16Array(bytes));
  }

  async acceptPcmBytesAsync(bytes: ArrayBuffer): Promise<void> {
    if (bytes.byteLength % 2 !== 0) {
      this.callbackGate.invoke((): void => {
        this.callback.onError?.(new AsrError(
          AsrErrorCode.INVALID_ARGUMENT, 'PCM byte length must be even for int16 samples'));
      });
      return;
    }
    const pcm = new Int16Array(bytes);
    const samples = new Float32Array(pcm.length);
    for (let i = 0; i < pcm.length; i++) samples[i] = pcm[i] / 32768.0;
    await this.acceptPcmFloatAsync(samples);
  }

  acceptPcmFloat(samples: Float32Array): void {
    if (this.callbackGate.isClosed() || samples.length === 0) return;
    if (this.shouldDeferSessionOperation()) {
      this.reentryQueue.enqueueAudio(samples);
      return;
    }
    this.acceptPcmFloatNow(samples);
  }

  async acceptPcmFloatAsync(samples: Float32Array): Promise<void> {
    if (this.callbackGate.isClosed() || samples.length === 0) return;
    await this.acceptPcmFloatNowAsync(samples);
  }

  private acceptPcmFloatNow(samples: Float32Array): void {
    if (this.callbackGate.isClosed() || samples.length === 0) return;
    if (this.firstPcmMs < 0) this.firstPcmMs = Date.now();
    this.pcmBytesAccepted += samples.length * 2;
    this.totalPcmBytes += samples.length * 2;
    this.streamCallDepth += 1;
    try {
      this.feedAndDecode(samples);
    } catch (e) {
      this.callbackGate.invoke((): void => {
        this.callback.onError?.(new AsrError(AsrErrorCode.NATIVE_CRASH, `${e}`));
      });
    } finally {
      this.streamCallDepth -= 1;
      this.drainReentryQueue();
      this.releaseStreamIfClosed();
    }
  }

  private async acceptPcmFloatNowAsync(samples: Float32Array): Promise<void> {
    if (this.callbackGate.isClosed() || samples.length === 0) return;
    if (this.firstPcmMs < 0) this.firstPcmMs = Date.now();
    this.pcmBytesAccepted += samples.length * 2;
    this.totalPcmBytes += samples.length * 2;
    this.streamCallDepth += 1;
    try {
      await this.feedAndDecodeAsync(samples);
    } catch (e) {
      this.callbackGate.invoke((): void => {
        this.callback.onError?.(new AsrError(AsrErrorCode.NATIVE_CRASH, `${e}`));
      });
    } finally {
      this.streamCallDepth -= 1;
      this.drainReentryQueue();
      this.releaseStreamIfClosed();
    }
  }

  stop(): void {
    if (this.callbackGate.isClosed()) return;
    if (this.shouldDeferSessionOperation()) {
      this.reentryQueue.enqueueStop();
      return;
    }
    this.stopNow();
  }

  async stopAsync(): Promise<void> {
    if (this.callbackGate.isClosed()) return;
    await this.stopNowAsync();
  }

  private stopNow(): void {
    if (this.callbackGate.isClosed()) return;
    this.streamCallDepth += 1;
    try {
      // PCM has been streamed to the recognizer all along; just flush the tail to a final result.
      // Don't rebuild the stream afterwards (session is ending), so a soft reset is enough.
      this.appendFinalTailSilence();
      this.stream.inputFinished();
      this.drain(true, false, true);
      if (!this.callbackGate.isClosed()) this.notifyStopped();
    } catch (e) {
      this.callbackGate.invoke((): void => {
        this.callback.onError?.(new AsrError(AsrErrorCode.NATIVE_CRASH, `${e}`));
      });
    } finally {
      this.streamCallDepth -= 1;
      this.drainReentryQueue();
      this.releaseStreamIfClosed();
    }
  }

  private async stopNowAsync(): Promise<void> {
    if (this.callbackGate.isClosed()) return;
    this.streamCallDepth += 1;
    try {
      this.appendFinalTailSilence();
      this.stream.inputFinished();
      await this.drainAsync(true, false, true);
      if (!this.callbackGate.isClosed()) this.notifyStopped();
    } catch (e) {
      this.callbackGate.invoke((): void => {
        this.callback.onError?.(new AsrError(AsrErrorCode.NATIVE_CRASH, `${e}`));
      });
    } finally {
      this.streamCallDepth -= 1;
      this.drainReentryQueue();
      this.releaseStreamIfClosed();
    }
  }

  updateHotwords(words: string[], score: number = 1.5): void {
    this.config.hotwords = words.filter((word: string): boolean => word.trim().length > 0);
    this.config.hotwordsScore = score;
    Logger.w('updateHotwords requires recreating recognizer on Harmony first implementation');
  }

  setTargetSpeaker(embedding: Float32Array): void {
    if (embedding.length === 0) throw new Error('target speaker embedding must not be empty');
    if (this.targetExtractor !== undefined && embedding.length !== this.targetExtractor.dim) {
      throw new Error(`target speaker embedding dim=${embedding.length}, expected=${this.targetExtractor.dim}`);
    }
    this.targetSpeaker = embedding;
  }
  setTargetSpeakerExtractor(extractor: SpeakerEmbeddingExtractor): void {
    if (this.targetSpeaker !== undefined && this.targetSpeaker.length !== extractor.dim) {
      throw new Error(`target speaker embedding dim=${this.targetSpeaker.length}, expected=${extractor.dim}`);
    }
    this.streamCallDepth += 1;
    try {
      this.targetExtractor = extractor;
      this.flushPendingSpeakerFinals();
    } finally {
      this.streamCallDepth -= 1;
      this.drainReentryQueue();
      this.releaseStreamIfClosed();
    }
  }
  setTargetSpeakerExtractorAsync(load: Promise<SpeakerEmbeddingExtractor>): void {
    this.targetExtractorLoad = load;
    load.then((extractor: SpeakerEmbeddingExtractor): void => {
      if (this.callbackGate.isClosed() || this.targetExtractorLoad !== load) return;
      this.setTargetSpeakerExtractor(extractor);
      this.targetExtractorLoad = undefined;
    }).catch((e: Object): void => {
      if (this.callbackGate.isClosed() || this.targetExtractorLoad !== load) return;
      this.targetExtractorLoad = undefined;
      const shouldReport = this.targetSpeakerEnabled || this.speakerVadEnabled ||
        this.pendingSpeakerFinals.length > 0;
      this.pendingSpeakerFinals = [];
      const stoppedWasPending = this.stopNotificationPending;
      this.stopNotificationPending = false;
      if (shouldReport) {
        this.callbackGate.invoke((): void => {
          this.callback.onError?.(new AsrError(
            AsrErrorCode.POSTPROCESS_FAILED, `speaker extractor load failed: ${e}`));
        });
      }
      // A failed deferred load must still complete stop(). The error callback may close the session,
      // in which case close() owns the stopped notification and this branch deliberately does nothing.
      if (stoppedWasPending && !this.callbackGate.isClosed()) this.notifyStopped();
    });
  }
  ensureTargetSpeakerExtractor(): void {
    const config = this.config.targetSpeaker;
    if (config === undefined || this.targetExtractor !== undefined) return;
    this.setTargetSpeakerExtractor(AmphionRuntime.getOrCreateSpeakerExtractor(
      this.context, config.modelPath, config.numThreads));
  }
  clearTargetSpeaker(): void { this.targetSpeaker = undefined; }
  setTargetSpeakerEnabled(enabled: boolean): void {
    this.targetSpeakerEnabled = enabled;
    const config = this.config.targetSpeaker;
    if (enabled && this.targetExtractor === undefined && this.targetExtractorLoad === undefined &&
      config !== undefined && config.deferLoad) {
      this.setTargetSpeakerExtractorAsync(AmphionRuntime.getOrCreateSpeakerExtractorAsync(
        this.context, config.modelPath, config.numThreads));
    }
  }
  setSpeakerVadEnabled(enabled: boolean): void {
    if (this.effectiveSpeakerVad() === undefined) {
      this.callbackGate.invoke((): void => {
        this.callback.onDebug?.('speaker VAD is not configured for this session');
      });
      return;
    }
    this.speakerVadEnabled = enabled;
  }
  isClosed(): boolean { return this.callbackGate.isClosed(); }
  close(): void {
    if (!this.callbackGate.close()) return;
    this.reentryQueue.clear();
    this.targetExtractorLoad = undefined;
    this.pendingSpeakerFinals = [];
    this.speakerPcmBuffers.clearAll();
    this.effectiveSpeechBuffer.reset();
    // 归还 VAD 到空闲池,供后续会话复用(顺序场景保持 RSS 平)。closed 早退保证同一实例只归还一次,
    // 避免重复入池后被两个会话同时取出而重现共享污染。
    if (this.vad !== undefined) {
      AmphionRuntime.releaseVad(this.vadKey, this.vad);
      this.vad = undefined;
    }
    this.dispatchSessionMetrics();
    this.notifyStopped();
    this.releaseStreamIfClosed();
  }

  private shouldDeferSessionOperation(): boolean {
    return this.streamCallDepth > 0 || this.callbackGate.isInvoking();
  }

  private drainReentryQueue(): void {
    if (this.streamCallDepth > 0 || this.callbackGate.isInvoking()) return;
    this.reentryQueue.drain(
      (): boolean => this.callbackGate.isClosed(),
      (samples: Float32Array): void => { this.acceptPcmFloatNow(samples); },
      (): void => { this.stopNow(); });
  }

  private drain(isFinal: boolean, restartAfterFinal: boolean = true, isLastFinal: boolean = false): void {
    const decodeStartMs = Date.now();
    while (this.recognizer.isReady(this.stream)) {
      this.recognizer.decode(this.stream);
    }
    const decodeDurationMs = Date.now() - decodeStartMs;

    this.processDecodedResult(isFinal, restartAfterFinal, isLastFinal, decodeDurationMs);
  }

  private async drainAsync(isFinal: boolean, restartAfterFinal: boolean = true,
    isLastFinal: boolean = false): Promise<void> {
    const decodeDurationMs = await this.recognizer.decodeAsync(this.stream);
    if (this.callbackGate.isClosed()) return;
    this.processDecodedResult(isFinal, restartAfterFinal, isLastFinal, decodeDurationMs);
  }

  private processDecodedResult(isFinal: boolean, restartAfterFinal: boolean,
    isLastFinal: boolean, decodeDurationMs: number): void {

    if (this.recognizer.isEndpoint(this.stream)) {
      if (!this.callbackGate.invoke((): void => { this.callback.onEndpoint?.(); })) return;
      // A stop requested synchronously by this endpoint callback belongs to this exact result. It is
      // safe to promote here because the core is constructing the current final; the adapter still
      // never infers last-ness from its broader, asynchronous finishRequested flag.
      const stopAtEndpoint = this.reentryQueue.consumeStopAtEndpoint();
      this.dispatchFinal(true, decodeDurationMs, isLastFinal || stopAtEndpoint);
      if (stopAtEndpoint) {
        if (!this.callbackGate.isClosed()) this.notifyStopped();
      } else if (!this.callbackGate.isClosed()) {
        this.finishUtterance(restartAfterFinal);
      }
      return;
    }

    const r = this.recognizer.getResult(this.stream);
    this.initialSilenceTracker.observeAsrResult(r.text, r.tokens.length);
    if (isFinal) {
      this.dispatchFinal(false, decodeDurationMs, isLastFinal);
      if (!this.callbackGate.isClosed()) this.finishUtterance(restartAfterFinal);
    } else if (r.text !== this.lastPartialText) {
      this.lastPartialText = r.text;
      // When speaker VAD is on, hold partials until the target speaker is confirmed so a non-target
      // prefix never leaks to the UI (Android postPartial gate).
      if (this.speakerVadEnabled && !this.svTargetConfirmed) return;
      const result = new AsrResult();
      result.text = r.text;
      result.tokens = r.tokens;
      result.timestamps = r.timestamps;
      if (this.firstPartialLatencyMs < 0 && this.firstPcmMs >= 0) {
        this.firstPartialLatencyMs = Date.now() - this.firstPcmMs;
      }
      if (!this.callbackGate.invoke((): void => { this.callback.onPartial?.(result.text); })) return;
      this.callbackGate.invoke((): void => { this.callback.onPartialResult?.(result); });
    }
  }

  private dispatchFinal(endpointTriggered: boolean, decodeDurationMs: number,
    isLast: boolean = false): boolean {
    const native = this.recognizer.getResult(this.stream);
    const hasEvidence = native.text.length > 0 || native.tokens.length > 0;
    this.initialSilenceTracker.observeAsrResult(native.text, native.tokens.length);
    const result = new AsrResult();
    result.text = native.text;
    result.tokens = native.tokens;
    result.timestamps = native.timestamps;
    result.isLast = isLast;
    const postStartMs = Date.now();
    if (this.itn !== undefined && result.text.length > 0) {
      try {
        result.text = this.itn.normalize(result.text);
      } catch (e) {
        if (!this.callbackGate.invoke((): void => {
          this.callback.onError?.(new AsrError(AsrErrorCode.POSTPROCESS_FAILED, `ITN failed: ${e}`));
        })) return false;
      }
    }
    if (this.punctuation !== undefined && result.text.length > 0) {
      try {
        result.text = this.punctuation.addPunct(result.text);
      } catch (e) {
        if (!this.callbackGate.invoke((): void => {
          this.callback.onError?.(new AsrError(AsrErrorCode.POSTPROCESS_FAILED, `${e}`));
        })) return false;
      }
    }
    const postProcessMs = Date.now() - postStartMs;
    const boundary = this.effectiveSpeechBuffer.resolveFinal(result.text, hasEvidence, isLast);
    // Speaker VAD's raw tail belongs to the native stream. The effective scoring buffer deliberately
    // spans a suppressed token-only endpoint, but the next stream must not score this segment again.
    if (!boundary.publish) {
      if (this.speakerVadEnabled) this.speakerPcmBuffers.clearNativeSegment();
      return hasEvidence;
    }
    const targetConfig = this.config.targetSpeaker;
    const minSpeakerSamples = targetConfig === undefined ? Number.MAX_SAFE_INTEGER :
      Math.round(targetConfig.minSegSec * ASR_SAMPLE_RATE_HZ);
    const utteranceSamples = this.targetSpeakerEnabled ?
      this.speakerPcmBuffers.fallbackSamples() : new Float32Array(0);
    const scoreSelection =
      selectSpeakerScoreSamples(boundary.samples, utteranceSamples, minSpeakerSamples, hasEvidence);
    if (this.targetSpeakerEnabled) {
      Logger.d(`session ${this.sessionId} ` + speakerScoreSelectionDiagnostic(
        scoreSelection, boundary.samples.length, utteranceSamples.length,
        minSpeakerSamples, ASR_SAMPLE_RATE_HZ, hasEvidence));
    }
    if (scoreSelection.source === 'utterance') {
      if (!this.callbackGate.invoke((): void => {
        this.callback.onDebug?.(
          `speaker score fallback: effectiveSpeech=${Math.round(
            boundary.samples.length * 1000 / ASR_SAMPLE_RATE_HZ)}ms, ` +
          `utterancePcm=${Math.round(utteranceSamples.length * 1000 / ASR_SAMPLE_RATE_HZ)}ms`);
      })) return false;
    }
    this.utteranceIndex += 1;
    const pending = new PendingSpeakerFinal(
      result,
      scoreSelection.samples,
      endpointTriggered ? Date.now() : -1,
      decodeDurationMs,
      postProcessMs,
      this.utteranceIndex,
      Math.round(this.pcmBytesAccepted * 1000 / 32000),
      this.firstPartialLatencyMs,
      this.firstPcmMs < 0 ? this.utteranceStartMs : this.firstPcmMs,
      this.pcmBytesAccepted);
    this.utteranceStartMs = Date.now();
    this.pcmBytesAccepted = 0;
    this.firstPcmMs = -1;
    this.firstPartialLatencyMs = -1;
    this.speakerPcmBuffers.clearAll();

    if ((scoreSelection.samples.length > 0 || this.pendingSpeakerFinals.length > 0) &&
      this.targetSpeakerEnabled && this.targetExtractor === undefined &&
      this.targetExtractorLoad !== undefined) {
      this.pendingSpeakerFinals.push(pending);
      return hasEvidence;
    }
    this.deliverSpeakerFinal(pending);
    return hasEvidence;
  }

  private deliverSpeakerFinal(pending: PendingSpeakerFinal): void {
    this.applyTargetSpeaker(pending.result, pending.samples);
    if (this.callbackGate.isClosed()) return;
    if (this.targetSpeakerEnabled && pending.result.isTargetSpeaker === false) {
      if (!this.callbackGate.invoke((): void => {
        this.callback.onFinalRejected?.(pending.result);
      })) return;
    } else {
      if (!this.callbackGate.invoke((): void => {
        this.callback.onFinal?.(pending.result.text, pending.result.confidence);
      })) return;
      if (!this.callbackGate.invoke((): void => {
        this.callback.onFinalResult?.(pending.result);
      })) return;
    }

    const metrics = new AmphionMetrics();
    metrics.kind = AmphionMetricsKind.UTTERANCE;
    metrics.language = this.language;
    metrics.sessionId = this.sessionId;
    metrics.utteranceIndex = pending.utteranceIndex;
    metrics.utteranceDurationMs = pending.utteranceDurationMs;
    metrics.decodeDurationMs = pending.decodeDurationMs;
    metrics.postProcessMs = pending.postProcessMs;
    metrics.firstPartialLatencyMs = pending.firstPartialLatencyMs;
    metrics.endpointToFinalLatencyMs = pending.endpointAtMs >= 0 ? Date.now() - pending.endpointAtMs : -1;
    metrics.utteranceE2eLatencyMs = Date.now() - pending.utteranceStartedMs;
    metrics.rtf = metrics.utteranceDurationMs > 0 ? pending.decodeDurationMs / metrics.utteranceDurationMs : -1;
    metrics.pcmBytesAccepted = pending.pcmBytesAccepted;
    if (pending.utteranceIndex === 1) {
      metrics.engineReadyMs = this.engineReadyMs;
      metrics.assetInstallMs = 0;
      metrics.assetTotalBytes = 0;
      metrics.nativeRssMbAtReady = -1;
    }
    if (metrics.rtf >= 0) this.rtfValues.push(metrics.rtf);
    this.callbackGate.invoke((): void => { this.callback.onMetrics?.(metrics); });
    Logger.metric(metrics.toLogLine());
  }

  private flushPendingSpeakerFinals(): void {
    if (this.targetExtractor === undefined || this.pendingSpeakerFinals.length === 0) return;
    const pending = this.pendingSpeakerFinals;
    this.pendingSpeakerFinals = [];
    for (let i = 0; i < pending.length; i++) {
      if (this.callbackGate.isClosed()) break;
      this.deliverSpeakerFinal(pending[i]);
    }
    if (this.stopNotificationPending && !this.callbackGate.isClosed()) {
      this.stopNotificationPending = false;
      this.notifyStopped();
    }
  }

  private createVad(): SherpaVad {
    if (this.layout.vadModel === undefined) throw new Error('VAD model is not packaged');
    if (this.config.vadConfig.modelType === VadModelType.TEN_VAD) {
      throw new Error('TEN_VAD is declared but ten-vad model is not packaged in Harmony HAR');
    }
    this.vadWindowSize = 512;
    const vc = this.config.vadConfig;
    // Check out a VAD from the free list (or a fresh isolated instance if a concurrent session holds
    // the pooled one). reset() drops any state left by a previous owner; released back to the pool in close().
    this.vadKey = AmphionRuntime.vadKeyFor(
      this.layout.vadModel, vc.threshold, vc.minSpeechDurationSec, vc.minSilenceDurationSec, vc.maxSpeechDurationSec);
    const vad = AmphionRuntime.acquireVad(
      this.context, this.layout.vadModel, vc.threshold, vc.minSpeechDurationSec, vc.minSilenceDurationSec, vc.maxSpeechDurationSec);
    vad.reset();
    return vad;
  }

  // Android-aligned chunk pipeline: feed every chunk to the recognizer in full (so partials stay
  // real-time) and let the VAD only gate / drive a more sensitive active endpoint. sherpa's own
  // endpoint rules stay enabled as a backstop in case the VAD active endpoint misses.
  private feedAndDecode(samples: Float32Array): void {
    let offset = 0;
    while (offset < samples.length && !this.callbackGate.isClosed() &&
      !this.initialSilenceTracker.hasTimedOut()) {
      const remaining = samples.length - offset;
      let chunkSize = this.initialSilenceTracker.isArmed() ?
        Math.min(remaining, INITIAL_DECISION_CHUNK_SAMPLES) : remaining;
      if (this.speakerVadEnabled) {
        const speakerVad = this.effectiveSpeakerVad();
        if (speakerVad !== undefined) {
          chunkSize = Math.min(chunkSize, this.speakerVadScoreScheduler(speakerVad).samplesUntilNextScore());
        }
      }
      this.feedChunkAndDecode(samples.slice(offset, offset + chunkSize));
      offset += chunkSize;
    }
  }

  private async feedAndDecodeAsync(samples: Float32Array): Promise<void> {
    let offset = 0;
    while (offset < samples.length && !this.callbackGate.isClosed() &&
      !this.initialSilenceTracker.hasTimedOut()) {
      const remaining = samples.length - offset;
      let chunkSize = this.initialSilenceTracker.isArmed() ?
        Math.min(remaining, INITIAL_DECISION_CHUNK_SAMPLES) : remaining;
      if (this.speakerVadEnabled) {
        const speakerVad = this.effectiveSpeakerVad();
        if (speakerVad !== undefined) {
          chunkSize = Math.min(chunkSize, this.speakerVadScoreScheduler(speakerVad).samplesUntilNextScore());
        }
      }
      await this.feedChunkAndDecodeAsync(samples.slice(offset, offset + chunkSize));
      offset += chunkSize;
    }
  }

  private feedChunkAndDecode(samples: Float32Array): void {
    if (this.callbackGate.isClosed() || this.initialSilenceTracker.hasTimedOut()) return;
    this.initialSilenceTracker.observeAcousticSamples(samples);
    if (this.targetSpeakerEnabled || this.speakerVadEnabled) {
      this.effectiveSpeechBuffer.observe(samples);
    }
    // Speaker VAD resets at native stream boundaries; fallback scoring resets only at a public final.
    // The two buffers must remain independent when a token-only native endpoint is suppressed.
    this.speakerPcmBuffers.observe(samples, this.speakerVadEnabled, this.targetSpeakerEnabled);

    const resetGenerationBefore = this.recognizerResetGeneration;
    this.feedRecognizer(samples, false);
    if (this.callbackGate.isClosed()) return;
    if (this.vad === undefined) return;
    if (this.recognizerResetGeneration !== resetGenerationBefore) {
      // sherpa endpoint already cut + reset the stream; resync VAD/speaker state to segment start.
      this.resetVadGateState();
      return;
    }

    // silero requires window-aligned feeds (512). Slice chunk into windows, keep the remainder.
    const merged = this.vadCarry.length === 0 ? samples : concatFloat32([this.vadCarry, samples]);
    let i = 0;
    let anySpeech = false;
    let anySilence = false;
    while (i + this.vadWindowSize <= merged.length) {
      this.vad.acceptWaveform(merged.slice(i, i + this.vadWindowSize));
      if (this.vad.isDetected()) anySpeech = true; else anySilence = true;
      i += this.vadWindowSize;
    }
    this.vadCarry = i < merged.length ? merged.slice(i, merged.length) : new Float32Array(0);

    const initialSilenceTimedOut = this.initialSilenceTracker.observeVad(i, anySpeech);
    if (anySpeech) {
      this.effectiveSpeechBuffer.confirmSpeech();
      const notifySpeechBegin = !this.vadSpeechActive;
      // Publish state before the callback. Reentrant writes are queued, but cancel/shutdown may still
      // close this session synchronously and must observe a coherent transition.
      this.vadSpeechActive = true;
      this.trailingSilenceMs = 0;
      if (notifySpeechBegin && !this.callbackGate.invoke((): void => {
        this.callback.onSpeechBegin?.();
      })) return;
    } else if (initialSilenceTimedOut) {
      if (this.initialSilenceTracker.confirmSpeechLikeActivity()) return;
      if (this.initialSilenceTracker.needsAsrProbe() && this.probeInitialSpeechAtTimeout()) return;
      if (this.initialSilenceTracker.confirmTimeout()) {
        this.callbackGate.invoke((): void => { this.callback.onInitialSilenceTimeout?.(); });
      }
      return;
    } else if (anySilence && this.vadSpeechActive) {
      this.trailingSilenceMs += Math.round(samples.length * 1000 / 16000);
      const activeEpMs = this.sessionConfig.endpointSilenceMs ?? this.config.vadConfig.activeEndpointSilenceMs;
      if (activeEpMs > 0 && this.trailingSilenceMs >= activeEpMs) {
        this.vadSpeechActive = false;
        this.trailingSilenceMs = 0;
        this.triggerVadActiveEndpoint();
        return;
      }
    }
    this.maybeTriggerSpeakerVadEndpoint(samples.length);
  }

  private async feedChunkAndDecodeAsync(samples: Float32Array): Promise<void> {
    if (this.callbackGate.isClosed() || this.initialSilenceTracker.hasTimedOut()) return;
    this.initialSilenceTracker.observeAcousticSamples(samples);
    if (this.targetSpeakerEnabled || this.speakerVadEnabled) {
      this.effectiveSpeechBuffer.observe(samples);
    }
    this.speakerPcmBuffers.observe(samples, this.speakerVadEnabled, this.targetSpeakerEnabled);

    const resetGenerationBefore = this.recognizerResetGeneration;
    await this.feedRecognizerAsync(samples, false);
    if (this.callbackGate.isClosed()) return;
    if (this.vad === undefined) return;
    if (this.recognizerResetGeneration !== resetGenerationBefore) {
      this.resetVadGateState();
      return;
    }

    const merged = this.vadCarry.length === 0 ? samples : concatFloat32([this.vadCarry, samples]);
    let i = 0;
    let anySpeech = false;
    let anySilence = false;
    while (i + this.vadWindowSize <= merged.length) {
      this.vad.acceptWaveform(merged.slice(i, i + this.vadWindowSize));
      if (this.vad.isDetected()) anySpeech = true; else anySilence = true;
      i += this.vadWindowSize;
    }
    this.vadCarry = i < merged.length ? merged.slice(i, merged.length) : new Float32Array(0);

    const initialSilenceTimedOut = this.initialSilenceTracker.observeVad(i, anySpeech);
    if (anySpeech) {
      this.effectiveSpeechBuffer.confirmSpeech();
      const notifySpeechBegin = !this.vadSpeechActive;
      this.vadSpeechActive = true;
      this.trailingSilenceMs = 0;
      if (notifySpeechBegin && !this.callbackGate.invoke((): void => {
        this.callback.onSpeechBegin?.();
      })) return;
    } else if (initialSilenceTimedOut) {
      if (this.initialSilenceTracker.confirmSpeechLikeActivity()) return;
      if (this.initialSilenceTracker.needsAsrProbe() && await this.probeInitialSpeechAtTimeoutAsync()) return;
      if (this.initialSilenceTracker.confirmTimeout()) {
        this.callbackGate.invoke((): void => { this.callback.onInitialSilenceTimeout?.(); });
      }
      return;
    } else if (anySilence && this.vadSpeechActive) {
      this.trailingSilenceMs += Math.round(samples.length * 1000 / 16000);
      const activeEpMs = this.sessionConfig.endpointSilenceMs ?? this.config.vadConfig.activeEndpointSilenceMs;
      if (activeEpMs > 0 && this.trailingSilenceMs >= activeEpMs) {
        this.vadSpeechActive = false;
        this.trailingSilenceMs = 0;
        this.triggerVadActiveEndpoint();
        return;
      }
    }
    this.maybeTriggerSpeakerVadEndpoint(samples.length);
  }

  // Acoustic activity only grants one bounded confirmation window. At its boundary, flush ASR to
  // distinguish delayed real speech from noise; real text is emitted as a non-last final.
  private probeInitialSpeechAtTimeout(): boolean {
    const decodeStartMs = Date.now();
    this.appendFinalTailSilence();
    this.stream.inputFinished();
    while (this.recognizer.isReady(this.stream)) this.recognizer.decode(this.stream);
    const hasEvidence = this.dispatchFinal(false, Date.now() - decodeStartMs);
    if (!this.callbackGate.isClosed()) {
      this.finishUtterance(true);
      this.resetVadGateState();
    }
    return hasEvidence;
  }

  private async probeInitialSpeechAtTimeoutAsync(): Promise<boolean> {
    this.appendFinalTailSilence();
    this.stream.inputFinished();
    const decodeDurationMs = await this.recognizer.decodeAsync(this.stream);
    if (this.callbackGate.isClosed()) return false;
    const hasEvidence = this.dispatchFinal(false, decodeDurationMs);
    if (!this.callbackGate.isClosed()) {
      this.finishUtterance(true);
      this.resetVadGateState();
    }
    return hasEvidence;
  }

  // VAD detected enough trailing silence: cut the utterance now and start the next one on a fresh
  // stream (Android parity), then resync the VAD/speaker gate. No inputFinished is used here, which
  // is the verified-safe native ordering on Harmony.
  private triggerVadActiveEndpoint(): void {
    if (!this.callbackGate.invoke((): void => { this.callback.onEndpoint?.(); })) return;
    const stopAtEndpoint = this.reentryQueue.consumeStopAtEndpoint();
    this.dispatchFinal(true, 0, stopAtEndpoint);
    if (this.callbackGate.isClosed()) return;
    if (stopAtEndpoint) {
      this.notifyStopped();
      return;
    }
    this.finishUtterance(true);
    if (this.callbackGate.isClosed()) return;
    this.resetVadGateState();
  }

  // After a final, either rebuild the stream (when the utterance had content) or do a cheap soft
  // reset. A soft reset keeps the encoder cache, which biases the next utterance toward the trailing
  // audio of this one and can blank out the start of a quick follow-up command (the dingqiao
  // short-command case). Rebuilding gives the next utterance a clean encoder (Android parity).
  private finishUtterance(restart: boolean): void {
    if (!restart) {
      if (!this.callbackGate.isClosed()) this.recognizer.reset(this.stream);
      this.lastPartialText = '';
      this.recognizerResetGeneration += 1;
      return;
    }
    this.restartStreamAfterUtterance();
    this.recognizerResetGeneration += 1;
  }

  private restartStreamAfterUtterance(): void {
    if (this.callbackGate.isClosed()) return;
    let hadContent = false;
    try {
      const r = this.recognizer.getResult(this.stream);
      hadContent = r.text.length > 0 || r.tokens.length > 0;
    } catch (e) {
      hadContent = false;
    }
    if (hadContent) {
      this.hardRestartStream();
    } else {
      this.recognizer.reset(this.stream);
    }
    this.lastPartialText = '';
  }

  private hardRestartStream(): void {
    if (this.callbackGate.isClosed()) return;
    try {
      const next = this.recognizer.createStream();
      const previous = this.stream;
      this.stream = next;
      previous.close();
      // recognizer 已在创建时预热,新 stream 复用暖模型,无需再逐次预热。
    } catch (e) {
      // If rebuilding fails, fall back to a soft reset so the session keeps running.
      if (!this.callbackGate.invoke((): void => {
        this.callback.onError?.(new AsrError(AsrErrorCode.NATIVE_CRASH, `hardRestartStream: ${e}`));
      })) return;
      this.recognizer.reset(this.stream);
    }
    this.lastPartialText = '';
  }

  private resetVadGateState(): void {
    this.vad?.reset();
    this.vadSpeechActive = false;
    this.trailingSilenceMs = 0;
    this.vadCarry = new Float32Array(0);
    this.resetSpeakerVadState();
  }

  private feedRecognizer(samples: Float32Array, isFinal: boolean): void {
    const wave: Samples = { samples: samples, sampleRate: 16000 } as Samples;
    this.stream.acceptWaveform(wave);
    this.drain(isFinal);
  }

  private async feedRecognizerAsync(samples: Float32Array, isFinal: boolean): Promise<void> {
    const wave: Samples = { samples: samples, sampleRate: 16000 } as Samples;
    this.stream.acceptWaveform(wave);
    await this.drainAsync(isFinal);
  }

  private appendFinalTailSilence(): void {
    const n = Math.max(0, Math.round(ASR_SAMPLE_RATE_HZ * FINAL_TAIL_SILENCE_MS / 1000));
    if (n === 0) return;
    const wave: Samples = { samples: new Float32Array(n), sampleRate: ASR_SAMPLE_RATE_HZ } as Samples;
    this.stream.acceptWaveform(wave);
  }

  private applyTargetSpeaker(result: AsrResult, samples: Float32Array): void {
    const config = this.config.targetSpeaker;
    const extractor = this.targetExtractor;
    const targetSpeaker = this.targetSpeaker;
    if (config === undefined || extractor === undefined || targetSpeaker === undefined) return;
    const minSamples = Math.round(config.minSegSec * ASR_SAMPLE_RATE_HZ);
    if (samples.length < minSamples) {
      this.callbackGate.invoke((): void => {
        this.callback.onDebug?.(
          `speaker score unavailable: effectiveSpeech=${Math.round(samples.length * 1000 / ASR_SAMPLE_RATE_HZ)}ms, ` +
          `minimum=${Math.round(config.minSegSec * 1000)}ms`);
      });
      return;
    }
    const stream = extractor.createStream();
    try {
      const wave: Samples = { samples: samples, sampleRate: 16000 } as Samples;
      stream.acceptWaveform(wave);
      const embedding = extractor.compute(stream);
      const score = cosineSimilarity(embedding, targetSpeaker);
      result.speakerScore = score;
      result.isTargetSpeaker = score >= config.threshold;
    } finally {
      stream.close();
    }
  }

  // Realtime Speaker VAD over the current utterance tail (Android-aligned two-phase machine):
  // phase 1 confirm the target appears; phase 2 once confirmed, cut early when the target leaves
  // (consecutive windows below threshold). Scored every hop while the utterance is long enough.
  private maybeTriggerSpeakerVadEndpoint(samplesInChunk: number): boolean {
    if (!this.speakerVadEnabled) return false;
    const sv = this.effectiveSpeakerVad();
    if (sv === undefined) return false;
    if (!this.speakerVadScoreScheduler(sv).observe(samplesInChunk)) return false;
    if (this.targetExtractor === undefined || this.targetSpeaker === undefined) return false;
    const winSamples = Math.max(1, Math.round(sv.winSec * 16000));

    const score = this.scoreSamples(this.speakerPcmBuffers.speakerVadTail(winSamples));
    if (!this.svTargetConfirmed) {
      if (score >= sv.threshold) {
        this.svTargetConfirmed = true;
        this.svBelowCount = 0;
      } else {
        this.svBelowCount += 1;
        if (this.svBelowCount >= sv.consecutiveBelow) {
          this.svRejectCurrentUtterance = true;
          this.vadSpeechActive = false;
          this.trailingSilenceMs = 0;
          this.triggerSpeakerVadEndpoint();
          return true;
        }
      }
      return false;
    }
    if (score < sv.threshold) {
      this.svBelowCount += 1;
      if (this.vadSpeechActive && this.svBelowCount >= sv.consecutiveBelow) {
        this.vadSpeechActive = false;
        this.trailingSilenceMs = 0;
        this.triggerSpeakerVadEndpoint();
        return true;
      }
    } else {
      this.svBelowCount = 0;
    }
    return false;
  }

  private speakerVadScoreScheduler(config: SpeakerVadConfig): SpeakerVadScoreScheduler {
    const windowSamples = Math.max(1, Math.round(config.winSec * ASR_SAMPLE_RATE_HZ));
    const hopSamples = Math.max(1, Math.round(config.hopSec * ASR_SAMPLE_RATE_HZ));
    const current = this.svScoreScheduler;
    if (current !== undefined &&
      current.windowSamples === windowSamples && current.hopSamples === hopSamples) {
      return current;
    }
    const scheduler = new SpeakerVadScoreScheduler(windowSamples, hopSamples);
    this.svScoreScheduler = scheduler;
    return scheduler;
  }

  private effectiveSpeakerVad(): SpeakerVadConfig | undefined {
    return this.sessionConfig?.speakerVad ?? this.config.targetSpeaker?.speakerVad;
  }

  private triggerSpeakerVadEndpoint(): void {
    if (!this.callbackGate.invoke((): void => { this.callback.onEndpoint?.(); })) return;
    const stopAtEndpoint = this.reentryQueue.consumeStopAtEndpoint();
    if (this.svRejectCurrentUtterance) {
      // Target never showed up in this segment: drop the transcription, surface a rejected result.
      // Rebuild the stream so the rejected (non-target) audio doesn't bias the next utterance.
      const rejected = new AsrResult();
      rejected.speakerScore = this.lastSpeakerVadScore;
      rejected.isTargetSpeaker = false;
      rejected.isLast = stopAtEndpoint;
      if (!this.callbackGate.invoke((): void => {
        this.callback.onFinalRejected?.(rejected);
      })) return;
      if (stopAtEndpoint) {
        if (!this.callbackGate.isClosed()) this.notifyStopped();
        return;
      }
      this.restartStreamAfterUtterance();
      if (this.callbackGate.isClosed()) return;
      this.speakerPcmBuffers.clearAll();
      this.effectiveSpeechBuffer.reset();
      this.pcmBytesAccepted = 0;
      this.firstPcmMs = -1;
      this.firstPartialLatencyMs = -1;
    } else {
      this.dispatchFinal(true, 0, stopAtEndpoint);
      if (this.callbackGate.isClosed()) return;
      if (stopAtEndpoint) {
        this.notifyStopped();
        return;
      }
      this.restartStreamAfterUtterance();
      if (this.callbackGate.isClosed()) return;
    }
    this.resetVadGateState();
  }

  private resetSpeakerVadState(): void {
    this.svScoreScheduler?.reset();
    this.svTargetConfirmed = false;
    this.svBelowCount = 0;
    this.svRejectCurrentUtterance = false;
  }

  private scoreSamples(samples: Float32Array): number {
    if (this.targetExtractor === undefined || this.targetSpeaker === undefined) return -1;
    const stream = this.targetExtractor.createStream();
    try {
      const wave: Samples = { samples: samples, sampleRate: 16000 } as Samples;
      stream.acceptWaveform(wave);
      const embedding = this.targetExtractor.compute(stream);
      const score = cosineSimilarity(embedding, this.targetSpeaker);
      this.lastSpeakerVadScore = score;
      return score;
    } finally {
      stream.close();
    }
  }

  private dispatchSessionMetrics(): void {
    const metrics = new AmphionMetrics();
    metrics.kind = AmphionMetricsKind.SESSION;
    metrics.language = this.language;
    metrics.sessionId = this.sessionId;
    metrics.totalUtterances = this.utteranceIndex;
    metrics.totalPcmBytes = this.totalPcmBytes;
    metrics.avgRtf = average(this.rtfValues);
    metrics.p95Rtf = p95(this.rtfValues);
    this.callback.onMetrics?.(metrics);
    Logger.metric(metrics.toLogLine());
  }

  private notifyStopped(): void {
    if (this.stoppedNotified) return;
    if (this.pendingSpeakerFinals.length > 0) {
      this.stopNotificationPending = true;
      return;
    }
    this.stoppedNotified = true;
    this.callback.onSessionStopped?.();
  }

  private releaseStreamIfClosed(): void {
    if (!this.callbackGate.isClosed() || this.streamCallDepth > 0 || this.streamReleased) return;
    this.streamReleased = true;
    this.stream.close();
  }
}

function validateSessionConfig(config: SessionConfig): void {
  if (config.endpointSilenceMs !== undefined &&
    (!Number.isFinite(config.endpointSilenceMs) || config.endpointSilenceMs < 0)) {
    throw new Error('SessionConfig.endpointSilenceMs must be finite and >= 0');
  }
  if (config.initialSilenceTimeoutMs !== undefined &&
    (!Number.isFinite(config.initialSilenceTimeoutMs) || config.initialSilenceTimeoutMs < 0)) {
    throw new Error('SessionConfig.initialSilenceTimeoutMs must be finite and >= 0');
  }
  if (config.initialSilenceConfirmationGraceMs !== undefined &&
    (!Number.isFinite(config.initialSilenceConfirmationGraceMs) || config.initialSilenceConfirmationGraceMs < 0)) {
    throw new Error('SessionConfig.initialSilenceConfirmationGraceMs must be finite and >= 0');
  }
}

function concatFloat32(parts: Float32Array[]): Float32Array {
  let total = 0;
  for (let i = 0; i < parts.length; i++) total += parts[i].length;
  const out = new Float32Array(total);
  let offset = 0;
  for (let i = 0; i < parts.length; i++) {
    out.set(parts[i], offset);
    offset += parts[i].length;
  }
  return out;
}

function cosineSimilarity(left: Float32Array, right: Float32Array): number {
  const n = Math.min(left.length, right.length);
  if (n === 0) return -1.0;
  let dot = 0;
  let leftNorm = 0;
  let rightNorm = 0;
  for (let i = 0; i < n; i++) {
    dot += left[i] * right[i];
    leftNorm += left[i] * left[i];
    rightNorm += right[i] * right[i];
  }
  if (leftNorm <= 0 || rightNorm <= 0) return -1.0;
  return dot / Math.sqrt(leftNorm * rightNorm);
}

function average(values: number[]): number {
  if (values.length === 0) return -1;
  let sum = 0;
  for (let i = 0; i < values.length; i++) sum += values[i];
  return sum / values.length;
}

function p95(values: number[]): number {
  if (values.length === 0) return -1;
  const sorted = values.slice().sort((a: number, b: number): number => a - b);
  const idx = Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95));
  return sorted[idx];
}
