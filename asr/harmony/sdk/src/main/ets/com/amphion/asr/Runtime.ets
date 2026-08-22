import {
  OfflinePunctuation,
  OfflinePunctuationConfig,
  OnlineModelConfig,
  OnlineEndpointReason,
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
import { fileIo } from '@kit.CoreFileKit';
import {
  isSpeakerTurnSegmentationModelLoaded,
  loadSpeakerTurnSegmentationModelAsync,
  processSpeakerTurnSegmentation,
  processSpeakerTurnSegmentationAsync,
  SpeakerTurnSegmentationSegment,
  unloadSpeakerTurnSegmentationModel
} from 'libamphion_asr.so';
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
import { NativeAgcBackend } from './NativeAgcBackend';
import { ProcessedAudioFrame, StreamingAgcProcessor } from './StreamingAgcProcessor';
import { AmphionLicenseStatus, HarmonyLicenseVerifier } from './License';
import { InitialSilenceTracker } from './InitialSilenceTracker';
import { EffectiveSpeechBuffer } from './EffectiveSpeechBuffer';
import { SpeakerPcmBuffers } from './SpeakerPcmBuffers';
import { SpeakerVadScoreScheduler } from './SpeakerVadScoreScheduler';
import { RecognizerPoolPolicy } from './RecognizerPoolPolicy';
import {
  NativeEndpointTransition,
  NativeEndpointTransitionPolicy,
} from './NativeEndpointTransitionPolicy';
import {
  SpeakerTurnFinalizer,
  SpeakerTurnSegment,
  SpeakerTurnSplit,
  shouldRejectSpeakerVadFinal
} from './SpeakerTurnFinalizer';
import { selectSpeakerScoreSamples, speakerScoreSelectionDiagnostic } from './SpeakerScoreFallback';
import { SessionCallbackGate } from './SessionCallbackGate';
import { SessionReentryQueue } from './SessionReentryQueue';
import { RuntimeReleaseGate, RuntimeSessionLease } from './RuntimeReleaseGate';
import { SpeakerInferenceLane } from './SpeakerInferenceLane';
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
const SPEAKER_TURN_SEGMENTATION_MODEL: string = 'pyannote-segmentation-3.0.onnx';

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
  ownsRecognizer: boolean;

  constructor(recognizer: OnlineRecognizer, elapsedMs: number, ownsRecognizer: boolean) {
    this.recognizer = recognizer;
    this.elapsedMs = elapsedMs;
    this.ownsRecognizer = ownsRecognizer;
  }
}

class VadGateAdvance {
  vadEndpoint: boolean = false;
  initialSilenceTimedOut: boolean = false;
}

class SpeakerVadInferenceRequest {
  samples: Float32Array;
  endSample: number;
  speechWasActive: boolean;

  constructor(samples: Float32Array, endSample: number, speechWasActive: boolean) {
    this.samples = samples;
    this.endSample = endSample;
    this.speechWasActive = speechWasActive;
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
  speakerScorePrepared: boolean;

  constructor(result: AsrResult, samples: Float32Array, endpointAtMs: number,
    decodeDurationMs: number, postProcessMs: number, utteranceIndex: number,
    utteranceDurationMs: number, firstPartialLatencyMs: number,
    utteranceStartedMs: number, pcmBytesAccepted: number, speakerScorePrepared: boolean) {
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
    this.speakerScorePrepared = speakerScorePrepared;
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
  private static speakerTurnSegmenterLoad?: Promise<void>;
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
  private static releaseGate: RuntimeReleaseGate = new RuntimeReleaseGate();

  static async init(context: Context, options?: AmphionOptions): Promise<void> {
    if (AmphionRuntime.releaseGate.isReleasePending()) {
      throw new Error(`code=${AsrErrorCode.SDK_NOT_INITIALIZED}: AmphionRuntime release is pending`);
    }
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
    const poolAction = RecognizerPoolPolicy.decide(
      pooled === undefined ? undefined : AmphionRuntime.poolConfigKey.get(language),
      requestedConfigKey);
    const canReusePool = poolAction === RecognizerPoolPolicy.REUSE;
    const recognizerStartMs = Date.now();
    const recognizer = canReusePool ? pooled as OnlineRecognizer :
      new OnlineRecognizer(AmphionRuntime.buildRecognizerConfig(layout, effectiveConfig), context.resourceManager);
    let ownsRecognizer = false;
    const recognizerLoadMs = Date.now() - recognizerStartMs;
    let warmupMs = 0;
    if (!canReusePool) {
      // Keep the warmup hook for model profiles that need it. zhen currently passes zero because
      // ORT Session creation already pays the material initialization costs.
      const warmupStartMs = Date.now();
      AmphionRuntime.warmUpRecognizer(recognizer);
      warmupMs = Date.now() - warmupStartMs;
      if (poolAction === RecognizerPoolPolicy.PUBLISH) {
        AmphionRuntime.asrPool.set(language, recognizer);
        AmphionRuntime.poolConfigKey.set(language, requestedConfigKey);
      } else {
        // 与 Android 对齐：不兼容配置使用 engine-owned recognizer，不覆盖 prepareRuntime
        // 建立的默认池。engine shutdown 会在所有 session stream 关闭后释放它。
        ownsRecognizer = true;
      }
    }
    let engine: AsrEngine;
    try {
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
      engine = new AsrEngine(
        context,
        language,
        effectiveConfig,
        layout,
        recognizer,
        ownsRecognizer,
        -1,
        punctuation,
        itn,
        punctuationLoadMs
      );
    } catch (e) {
      if (ownsRecognizer) {
        try { recognizer.close(); } catch (closeError) {
          Logger.w(`dedicated recognizer cleanup failed: ${closeError}`);
        }
      }
      throw new Error(`${e}`);
    }
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
    // Start the independent ASR and punctuation loads before awaiting either one. The N-API layer
    // performs native work off the ArkTS event thread; single-flight helpers prevent duplicate loads.
    const recognizerTask = AmphionRuntime.timedRecognizerLoadAsync(
      context, language, layout, effectiveConfig);
    const punctuationTask = AmphionRuntime.timedPunctuationLoadAsync(
      context, layout, effectiveConfig);
    const recognizerLoad = await recognizerTask;
    const punctuationLoad = await punctuationTask;
    let engine: AsrEngine;
    try {
      const itn = AmphionRuntime.getOrCreateItn(language, layout, effectiveConfig);
      if (generation !== AmphionRuntime.loadGeneration || !AmphionRuntime.initialized) {
        throw new Error(`code=${AsrErrorCode.SDK_NOT_INITIALIZED}: runtime released during model load`);
      }
      engine = new AsrEngine(
        context,
        language,
        effectiveConfig,
        layout,
        recognizerLoad.recognizer,
        recognizerLoad.ownsRecognizer,
        -1,
        punctuationLoad.punctuation,
        itn,
        punctuationLoad.elapsedMs
      );
    } catch (e) {
      if (recognizerLoad.ownsRecognizer) {
        try { recognizerLoad.recognizer.close(); } catch (closeError) {
          Logger.w(`dedicated recognizer cleanup failed: ${closeError}`);
        }
      }
      throw new Error(`${e}`);
    }
    const engineReadyMs = Date.now() - createStartMs;
    engine.setEngineReadyMs(engineReadyMs);
    Logger.metric(
      `kind=LOAD language=${language} async=true pooled=${!recognizerLoad.ownsRecognizer} ` +
      `assetLayoutMs=${assetLayoutMs} ` +
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

  /** Load the small frame-level boundary model without duplicating ERes2Net. */
  static getOrCreateSpeakerTurnSegmenterAsync(context: Context,
    speakerModelPath: string): Promise<void> {
    AmphionRuntime.checkInitialized();
    if (isSpeakerTurnSegmentationModelLoaded()) return Promise.resolve();
    const inFlight = AmphionRuntime.speakerTurnSegmenterLoad;
    if (inFlight !== undefined) return inFlight;
    const separator = speakerModelPath.lastIndexOf('/');
    const parent = separator >= 0 ? speakerModelPath.substring(0, separator + 1) : '';
    const segmentationModelPath = `${parent}${SPEAKER_TURN_SEGMENTATION_MODEL}`;
    let model: Uint8Array;
    if (speakerModelPath.startsWith('/')) {
      const fp = fileIo.openSync(segmentationModelPath);
      try {
        const stat = fileIo.statSync(fp.fd);
        const buffer = new ArrayBuffer(stat.size);
        fileIo.readSync(fp.fd, buffer);
        model = new Uint8Array(buffer);
      } finally {
        fileIo.closeSync(fp);
      }
    } else {
      model = context.resourceManager.getRawFileContentSync(segmentationModelPath);
    }
    const load = loadSpeakerTurnSegmentationModelAsync(model).finally((): void => {
      if (AmphionRuntime.speakerTurnSegmenterLoad === load) {
        AmphionRuntime.speakerTurnSegmenterLoad = undefined;
      }
    });
    AmphionRuntime.speakerTurnSegmenterLoad = load;
    return load;
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
    const configKey = AmphionRuntime.recognizerConfigKey(config);
    const cached = AmphionRuntime.asrPool.get(language);
    const poolAction = RecognizerPoolPolicy.decide(
      cached === undefined ? undefined : AmphionRuntime.poolConfigKey.get(language), configKey);
    if (poolAction === RecognizerPoolPolicy.DEDICATED) {
      const recognizer = await AmphionRuntime.createRecognizerAsync(
        context, layout, config);
      return new AsyncRecognizerLoad(recognizer, Date.now() - startedMs, true);
    }
    try {
      const recognizer = await AmphionRuntime.getOrCreateRecognizerAsync(
        context, language, layout, config);
      return new AsyncRecognizerLoad(recognizer, Date.now() - startedMs, false);
    } catch (e) {
      // A concurrent incompatible preload/create may have won the empty pool after the first check.
      // Preserve that winner and give this engine its own recognizer, matching Android putIfAbsent.
      const winner = AmphionRuntime.asrPool.get(language);
      if (winner === undefined || AmphionRuntime.poolConfigKey.get(language) === configKey) {
        throw new Error(`${e}`);
      }
      const recognizer = await AmphionRuntime.createRecognizerAsync(
        context, layout, config);
      return new AsyncRecognizerLoad(recognizer, Date.now() - startedMs, true);
    }
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
    const poolAction = RecognizerPoolPolicy.decide(
      cached === undefined ? undefined : AmphionRuntime.poolConfigKey.get(language), configKey);
    if (poolAction === RecognizerPoolPolicy.REUSE) return cached as OnlineRecognizer;
    if (poolAction === RecognizerPoolPolicy.DEDICATED) {
      throw new Error(
        `recognizer pool for ${language} already has an incompatible config; ` +
        'call unloadModel before preloading a different config');
    }

    const loadKey = `${language}|${configKey}`;
    let load: Promise<OnlineRecognizer> | undefined =
      AmphionRuntime.recognizerLoads.get(loadKey);
    if (load === undefined) {
      const newLoad: Promise<OnlineRecognizer> = AmphionRuntime.createRecognizerAsync(
        context, layout, config)
        .then((recognizer: OnlineRecognizer): OnlineRecognizer => {
          const winner = AmphionRuntime.asrPool.get(language);
          if (winner === undefined) {
            AmphionRuntime.asrPool.set(language, recognizer);
            AmphionRuntime.poolConfigKey.set(language, configKey);
            return recognizer;
          }
          try { recognizer.close(); } catch (e) { Logger.w(`recognizer pool loser close failed: ${e}`); }
          if (AmphionRuntime.poolConfigKey.get(language) === configKey) return winner;
          throw new Error(`concurrent incompatible recognizer load for ${language}`);
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

  private static async createRecognizerAsync(
    context: Context,
    layout: InstalledLayout,
    config: AsrConfig
  ): Promise<OnlineRecognizer> {
    const generation = AmphionRuntime.loadGeneration;
    const recognizer = await OnlineRecognizer.createAsync(
      AmphionRuntime.buildRecognizerConfig(layout, config),
      context.resourceManager,
      Math.round(ASR_SAMPLE_RATE_HZ * EAGER_WARMUP_DURATION_MS / 1000));
    if (generation !== AmphionRuntime.loadGeneration || !AmphionRuntime.initialized) {
      try { recognizer.close(); } catch (e) { Logger.w(`cancelled recognizer close failed: ${e}`); }
      throw new Error(`code=${AsrErrorCode.SDK_NOT_INITIALIZED}: runtime released during recognizer load`);
    }
    return recognizer;
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
            try { punctuation.close(); } catch (e) {
              Logger.w(`cancelled punctuation close failed: ${e}`);
            }
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
    AmphionRuntime.releaseGate.requestModelUnload((): void => AmphionRuntime.unloadModelNow());
  }

  private static unloadModelNow(): void {
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
    AmphionRuntime.speakerTurnSegmenterLoad = undefined;
    unloadSpeakerTurnSegmentationModel();
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
      AmphionRuntime.speakerExtractorPool.size > 0 ||
      isSpeakerTurnSegmentationModelLoaded();
  }

  /** 运行时是否就绪(已 init)。 */
  static isRuntimeReady(): boolean { return AmphionRuntime.initialized; }

  static isModelPrepared(language: AsrLanguage, config?: AsrConfig): boolean {
    if (!AmphionRuntime.initialized || AmphionRuntime.asrPool.get(language) === undefined) return false;
    const effectiveConfig = AmphionRuntime.snapshotConfig(config);
    return AmphionRuntime.poolConfigKey.get(language) ===
      AmphionRuntime.recognizerConfigKey(effectiveConfig);
  }

  /**
   * 运行时级卸载(两级加载的 L1)。先卸载模型(「若没卸载模型,则模型跟随卸载」),再重置运行时状态
   * 为未初始化。native .so 由 OS 保留映射,无法在进程内真正 unload。
   */
  static release(): void {
    void AmphionRuntime.releaseAsync().catch((e: Object): void => {
      Logger.w(`AmphionRuntime release failed: ${e}`);
    });
  }

  static releaseAsync(): Promise<void> {
    return AmphionRuntime.releaseGate.requestRuntimeRelease((): void => AmphionRuntime.releaseNow());
  }

  static isReleasePending(): boolean {
    return AmphionRuntime.releaseGate.isReleasePending();
  }

  private static releaseNow(): void {
    AmphionRuntime.runtimeGeneration += 1;
    // Promise 本身不可取消；清掉 single-flight 引用允许后续 init 立即开始，旧任务会被 generation 拒绝提交。
    AmphionRuntime.initTask = undefined;
    AmphionRuntime.unloadModelNow();
    AmphionRuntime.initialized = false;
    AmphionRuntime.appContext = undefined;
    AmphionRuntime.options = new AmphionOptions();
    AmphionRuntime.licenseStatusHolder = AmphionLicenseStatus.notInitialized();
  }

  static allocateSessionId(): number { return AmphionRuntime.nextSessionId++; }

  static retainSession(): RuntimeSessionLease {
    AmphionRuntime.checkInitialized();
    const lease = AmphionRuntime.releaseGate.retainSession();
    if (lease === undefined) {
      throw new Error(`code=${AsrErrorCode.SDK_NOT_INITIALIZED}: AmphionRuntime release is pending`);
    }
    return lease;
  }

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
    if (AmphionRuntime.releaseGate.isReleasePending()) {
      throw new Error(`code=${AsrErrorCode.SDK_NOT_INITIALIZED}: AmphionRuntime release is pending`);
    }
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
  private openSessionStreams: number = 0;
  private ownedRecognizerClosed: boolean = false;
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
    const lease = AmphionRuntime.retainSession();
    this.openSessionStreams += 1;
    let session: AsrSession;
    let stream: OnlineStream | undefined;
    try {
      stream = this.recognizer.createStream();
      session = new AsrSession(
        AmphionRuntime.allocateSessionId(),
        this.context,
        this.language,
        this.config,
        this.layout,
        this.recognizer,
        stream,
        lease,
        this.punctuation,
        this.itn,
        this.targetExtractor,
        sessionConfig,
        callback,
        this.engineReadyMs,
        (): void => { this.onSessionStreamReleased(); }
      );
    } catch (e) {
      if (stream === undefined) {
        this.openSessionStreams = Math.max(0, this.openSessionStreams - 1);
        lease.release();
      } else {
        const createdStream = stream;
        if (!lease.releaseAfterClose((): void => {
          createdStream.close();
          this.onSessionStreamReleased();
        })) {
          Logger.w('session construction failed and stream close failed; Runtime lease retained');
        }
      }
      this.closeOwnedRecognizerWhenIdle();
      if (e instanceof Error) throw e;
      throw new Error(`${e}`);
    }
    if (this.closed) {
      session.close();
      throw new Error('AsrEngine closed during session creation');
    }
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
    this.closeOwnedRecognizerWhenIdle();
  }

  private onSessionStreamReleased(): void {
    this.openSessionStreams = Math.max(0, this.openSessionStreams - 1);
    this.closeOwnedRecognizerWhenIdle();
  }

  private closeOwnedRecognizerWhenIdle(): void {
    if (!this.closed || !this.ownsRecognizer || this.ownedRecognizerClosed ||
      this.openSessionStreams > 0) return;
    this.ownedRecognizerClosed = true;
    try {
      this.recognizer.close();
      Logger.d('dedicated Harmony recognizer closed');
    } catch (e) {
      Logger.w(`dedicated recognizer close failed: ${e}`);
    }
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
  private speakerTurnSegmenterLoad?: Promise<void>;
  private speakerTurnSegmenterUnavailable: boolean = false;
  private targetSpeaker?: Float32Array;
  private targetSpeakerEnabled: boolean = false;
  private speakerVadEnabled: boolean = false;
  private lastSpeakerVadScore?: number;
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
  private svAwaitingTargetAfterDeparture: boolean = false;
  private svTurnFinalizer?: SpeakerTurnFinalizer;
  private svPendingSplit?: SpeakerTurnSplit;
  private svCleanPrefixSpeakerScore?: number;
  private svSpeakerScorePrepared: boolean = false;
  private svPreparedPrefixStream?: OnlineStream;
  private svPreparedPrefixSamples: number = 0;
  private svPreparedPrefixDecodeMs: number = 0;
  private svPreparedPrefixTask?: Promise<void>;
  private svPreparedPrefixGeneration: number = 0;
  private svPrefixPreparationPending: number = 0;
  private svContextWaitStartedSample: number = -1;
  private svTurnFailOpen: boolean = false;
  private speakerInferenceLane: SpeakerInferenceLane = new SpeakerInferenceLane();
  private svInferenceLoopActive: boolean = false;
  private svQueuedInference?: SpeakerVadInferenceRequest;
  private svEndpointReady: boolean = false;
  private pendingVadStopAtEndpoint: boolean = false;
  private vadEndpointPending: boolean = false;
  private pendingNativeEndpointTransition?: NativeEndpointTransition;
  private endpointAtMs: number = -1;
  private callback: AsrCallback;
  private callbackGate: SessionCallbackGate = new SessionCallbackGate();
  private reentryQueue: SessionReentryQueue = new SessionReentryQueue();
  private streamCallDepth: number = 0;
  private speculativeTimestampsSnapshot: number[] = [];
  private streamReleased: boolean = false;
  private pcmFloatScratch: Float32Array = new Float32Array(0);
  private lastPartialText: string = '';
  private pcmBytesAccepted: number = 0;
  private totalPcmBytes: number = 0;
  private utteranceIndex: number = 0;
  private recognizerResetGeneration: number = 0;
  private streamGeneration: number = 1;
  private utteranceStartMs: number = Date.now();
  private firstPcmMs: number = -1;
  private firstPartialLatencyMs: number = -1;
  private rtfValues: number[] = [];
  private speakerPcmBuffers: SpeakerPcmBuffers = new SpeakerPcmBuffers(UTT_MAX_SAMPLES);
  private effectiveSpeechBuffer: EffectiveSpeechBuffer =
    new EffectiveSpeechBuffer(ASR_SAMPLE_RATE_HZ, UTT_MAX_SAMPLES);
  private agcProcessor: StreamingAgcProcessor;
  private engineReadyMs: number = -1;
  private stoppedNotified: boolean = false;
  private stopNotificationPending: boolean = false;
  private pendingSpeakerFinals: PendingSpeakerFinal[] = [];
  private sessionConfig: SessionConfig;
  private runtimeLease: RuntimeSessionLease;
  private onStreamReleased: () => void;
  private publicOperationTail: Promise<void> = Promise.resolve();

  constructor(sessionId: number, context: Context, language: AsrLanguage, config: AsrConfig,
    layout: InstalledLayout, recognizer: OnlineRecognizer, stream: OnlineStream,
    runtimeLease: RuntimeSessionLease,
    punctuation: OfflinePunctuation | undefined, itn: WetextItn | undefined,
    targetExtractor: SpeakerEmbeddingExtractor | undefined, sessionConfig: SessionConfig,
    callback: AsrCallback, engineReadyMs: number, onStreamReleased: () => void) {
    this.sessionId = sessionId;
    this.context = context;
    this.language = language;
    this.config = config;
    this.layout = layout;
    this.recognizer = recognizer;
    this.stream = stream;
    this.runtimeLease = runtimeLease;
    this.punctuation = punctuation;
    this.itn = itn;
    this.targetExtractor = targetExtractor;
    this.sessionConfig = sessionConfig;
    this.targetSpeakerEnabled = config.targetSpeaker?.enabledByDefault ?? false;
    this.speakerVadEnabled = this.effectiveSpeakerVad()?.enabledByDefault ?? false;
    this.callback = callback;
    this.engineReadyMs = engineReadyMs;
    this.onStreamReleased = onStreamReleased;
    this.agcProcessor = new StreamingAgcProcessor(
      ASR_SAMPLE_RATE_HZ,
      (): NativeAgcBackend => new NativeAgcBackend(ASR_SAMPLE_RATE_HZ));
    const initialSilenceTimeoutMs = sessionConfig.initialSilenceTimeoutMs ?? 0;
    const requestedConfirmationGraceMs = sessionConfig.initialSilenceConfirmationGraceMs ?? 0;
    const maxConfirmationGraceMs = config.targetSpeaker === undefined ? 0 :
      Math.max(0, Math.round(config.targetSpeaker.minSegSec * 1000));
    const initialSilenceConfirmationGraceMs = Math.min(
      requestedConfirmationGraceMs, maxConfirmationGraceMs);
    this.initialSilenceTracker = new InitialSilenceTracker(
      initialSilenceTimeoutMs, ASR_SAMPLE_RATE_HZ, initialSilenceConfirmationGraceMs);
    try {
      if (config.vad) {
        this.vad = this.createVad();
      }
      if (this.speakerVadEnabled) this.ensureSpeakerTurnSegmenterLoad();
      // 预热已前移到 recognizer 创建处一次性完成(见 AmphionRuntime.warmUpRecognizer),
      // 这里不再每次 startListening 都跑 encoder,避免每次点"开始识别"卡 3~4 秒。
      this.callbackGate.invoke((): void => { this.callback.onSessionStarted?.(); });
    } catch (e) {
      if (this.vad !== undefined) {
        AmphionRuntime.releaseVad(this.vadKey, this.vad);
        this.vad = undefined;
      }
      if (e instanceof Error) throw e;
      throw new Error(`${e}`);
    }
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
    const owned = samples.slice();
    this.schedulePublicOperation(async (): Promise<void> => {
      await this.acceptPcmFloatNowAsync(owned);
    });
  }

  async acceptPcmFloatAsync(samples: Float32Array): Promise<void> {
    if (this.callbackGate.isClosed() || samples.length === 0) return;
    const owned = samples.slice();
    await this.schedulePublicOperation(async (): Promise<void> => {
      await this.acceptPcmFloatNowAsync(owned);
    });
  }

  private acceptPcmFloatNow(samples: Float32Array): void {
    if (this.callbackGate.isClosed() || samples.length === 0) return;
    if (this.firstPcmMs < 0) this.firstPcmMs = Date.now();
    this.pcmBytesAccepted += samples.length * 2;
    this.totalPcmBytes += samples.length * 2;
    this.streamCallDepth += 1;
    try {
      const frames = this.agcProcessor.process(samples);
      for (let index = 0; index < frames.length; index++) this.feedAndDecode(frames[index]);
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
      const frames = this.agcProcessor.process(samples);
      for (let index = 0; index < frames.length; index++) await this.feedAndDecodeAsync(frames[index]);
    } catch (e) {
      this.callbackGate.invoke((): void => {
        this.callback.onError?.(new AsrError(AsrErrorCode.NATIVE_CRASH, `${e}`));
      });
    } finally {
      this.streamCallDepth -= 1;
      await this.drainReentryQueueAsync();
      this.releaseStreamIfClosed();
    }
  }

  stop(): void {
    if (this.callbackGate.isClosed()) return;
    if (this.shouldDeferSessionOperation()) {
      this.reentryQueue.enqueueStop();
      return;
    }
    this.schedulePublicOperation(async (): Promise<void> => {
      await this.stopNowAsync();
    });
  }

  requestStopFromCallback(): boolean {
    if (this.callbackGate.isClosed() || !this.callbackGate.isInvoking()) return false;
    this.reentryQueue.enqueueStop();
    return true;
  }

  async stopAsync(): Promise<void> {
    if (this.callbackGate.isClosed()) return;
    await this.schedulePublicOperation(async (): Promise<void> => {
      await this.stopNowAsync();
    });
  }

  private schedulePublicOperation(operation: () => Promise<void>): Promise<void> {
    const task = this.publicOperationTail.then(async (): Promise<void> => {
      if (this.callbackGate.isClosed()) return;
      await operation();
    });
    this.publicOperationTail = task.catch((e: Object): void => {
      if (this.callbackGate.isClosed()) return;
      this.callbackGate.invoke((): void => {
        this.callback.onError?.(new AsrError(AsrErrorCode.NATIVE_CRASH, `${e}`));
      });
    });
    return task;
  }

  private stopNow(): void {
    if (this.callbackGate.isClosed()) return;
    this.streamCallDepth += 1;
    try {
      const remainder = this.agcProcessor.flush();
      for (let index = 0; index < remainder.length; index++) this.feedAndDecode(remainder[index]);
      if (this.commitSpeakerTurnAtFinish()) return;
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
      const remainder = this.agcProcessor.flush();
      for (let index = 0; index < remainder.length; index++) {
        await this.feedAndDecodeAsync(remainder[index]);
      }
      if (await this.commitSpeakerTurnAtFinishAsync()) return;
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
      await this.drainReentryQueueAsync();
      this.releaseStreamIfClosed();
    }
  }

  updateHotwords(words: string[], score: number = 1.5): void {
    this.config.hotwords = words.filter((word: string): boolean => word.trim().length > 0);
    this.config.hotwordsScore = score;
    Logger.w('updateHotwords requires recreating recognizer on Harmony first implementation');
  }

  private commitSpeakerTurnAtFinish(): boolean {
    const finalizer = this.svTurnFinalizer;
    if (!this.speakerVadEnabled || finalizer === undefined) return false;
    const finishRecovery = finalizer.hasPendingFinishDeparture();
    const finishDiarization = finalizer.hasFinishDiarizationCandidate();
    if (!finalizer.hasPendingDeparture() && !finishRecovery && !finishDiarization) return false;
    return this.commitCleanSpeakerTurn(true, false, finishRecovery || finishDiarization);
  }

  private async commitSpeakerTurnAtFinishAsync(): Promise<boolean> {
    if (!this.speakerVadEnabled) return false;
    if (!await this.drainSpeakerInferenceAsync()) return true;
    if (!this.speakerVadEnabled) return false;
    const finalizer = this.svTurnFinalizer;
    if (finalizer === undefined) return false;
    const finishRecovery = finalizer.hasPendingFinishDeparture();
    const finishDiarization = finalizer.hasFinishDiarizationCandidate();
    if (!finalizer.hasPendingDeparture() && !finishRecovery && !finishDiarization) return false;
    return await this.commitCleanSpeakerTurnAsync(
      true, false, finishRecovery || finishDiarization);
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
    this.svAwaitingTargetAfterDeparture = false;
    if (enabled) this.ensureSpeakerTurnSegmenterLoad();
    this.resetSpeakerVadState();
  }
  private ensureSpeakerTurnSegmenterLoad(): void {
    const target = this.config.targetSpeaker;
    if (target === undefined) {
      this.speakerVadEnabled = false;
      Logger.w('speaker VAD disabled because target speaker config is missing');
      return;
    }
    if (isSpeakerTurnSegmentationModelLoaded() || this.speakerTurnSegmenterLoad !== undefined ||
      this.speakerTurnSegmenterUnavailable) return;
    let load: Promise<void>;
    try {
      load = AmphionRuntime.getOrCreateSpeakerTurnSegmenterAsync(this.context, target.modelPath);
    } catch (e) {
      this.speakerTurnSegmenterUnavailable = true;
      Logger.w(`speaker diarizer unavailable; using acoustic resolver: ${e}`);
      return;
    }
    this.speakerTurnSegmenterLoad = load;
    load.then((): void => {
      if (this.callbackGate.isClosed() || this.speakerTurnSegmenterLoad !== load) return;
      this.speakerTurnSegmenterLoad = undefined;
    }).catch((e: Object): void => {
      if (this.callbackGate.isClosed() || this.speakerTurnSegmenterLoad !== load) return;
      this.speakerTurnSegmenterLoad = undefined;
      if (!this.speakerVadEnabled) return;
      this.speakerTurnSegmenterUnavailable = true;
      Logger.w(`speaker diarizer load failed; using acoustic resolver: ${e}`);
      this.callbackGate.invoke((): void => {
        this.callback.onDebug?.(`speaker diarizer unavailable; using acoustic resolver: ${e}`);
      });
    });
  }
  isClosed(): boolean { return this.callbackGate.isClosed(); }
  close(): void {
    if (!this.callbackGate.close()) return;
    this.speakerInferenceLane.invalidate();
    this.svInferenceLoopActive = false;
    this.svQueuedInference = undefined;
    this.speakerInferenceLane.whenIdle().then((): void => {
      this.releaseStreamIfClosed();
    }).catch((e: Object): void => {
      Logger.w(`session ${this.sessionId} speaker inference quiescence failed: ${e}`);
      this.releaseStreamIfClosed();
    });
    this.agcProcessor.close();
    this.reentryQueue.clear();
    this.targetExtractorLoad = undefined;
    this.speakerTurnSegmenterLoad = undefined;
    this.pendingSpeakerFinals = [];
    this.discardPreparedSpeakerTurnPrefix();
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

  private async drainReentryQueueAsync(): Promise<void> {
    if (this.streamCallDepth > 0 || this.callbackGate.isInvoking()) return;
    await this.reentryQueue.drainAsync(
      (): boolean => this.callbackGate.isClosed(),
      async (samples: Float32Array): Promise<void> => {
        await this.acceptPcmFloatNowAsync(samples);
      },
      async (): Promise<void> => { await this.stopNowAsync(); });
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
    await this.processDecodedResultAsync(
      isFinal, restartAfterFinal, isLastFinal, decodeDurationMs);
  }

  private async drainFinalWithSpeakerScoreAsync(isLastFinal: boolean): Promise<void> {
    const scoreTask = this.prepareVadEndpointSpeakerScoreAsync();
    const decodeTask = this.recognizer.decodeAsync(this.stream);
    const settled = await Promise.all([scoreTask, decodeTask]);
    if (!settled[0] || this.callbackGate.isClosed()) return;
    await this.processDecodedResultAsync(true, false, isLastFinal, settled[1]);
  }

  private async processDecodedResultAsync(isFinal: boolean, restartAfterFinal: boolean,
    isLastFinal: boolean, decodeDurationMs: number): Promise<void> {
    const endpointReason = this.recognizer.getEndpointReason(this.stream);
    const nativeEndpoint = endpointReason !== OnlineEndpointReason.NONE;
    if (!isFinal && !isLastFinal && nativeEndpoint) {
      if (this.vadEndpointPending) return;
      if (this.speakerVadEnabled && this.svContextWaitStartedSample >= 0) {
        Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} decision=hold-native-endpoint ` +
          `waitingSinceSample=${this.svContextWaitStartedSample}`);
        // The turn resolver explicitly needs later PCM. Do not wait for its inference lane here:
        // returning lets SessionAudioDispatcher advance the sample clock with that context.
        return;
      }
      const endpointResult = this.recognizer.getResult(this.stream);
      this.rememberSpeculativeTimestamps(endpointResult.timestamps);
      const endpointTransition = NativeEndpointTransitionPolicy.decide(
        endpointReason === OnlineEndpointReason.RULE3,
        endpointResult.text.length > 0 || endpointResult.tokens.length > 0);
      if (!this.announceNativeEndpoint(endpointReason, endpointTransition)) return;
      if (!await this.drainSpeakerInferenceAsync()) return;
      // A score from this same PCM slice may have opened a bounded turn-context wait. Keep the
      // already-announced endpoint pending and let later PCM resolve it without publishing a
      // speculative final or announcing the boundary twice.
      if (this.speakerVadEnabled && this.svContextWaitStartedSample >= 0 &&
        !this.pendingVadStopAtEndpoint) return;
      if (!await this.prepareVadEndpointSpeakerScoreAsync()) return;
      await this.finalizeAnnouncedVadEndpointAsync(decodeDurationMs);
      return;
    }
    if (isFinal) {
      if (!await this.drainSpeakerInferenceAsync()) return;
      if (!await this.prepareVadEndpointSpeakerScoreAsync()) return;
    }
    this.processDecodedResult(isFinal, restartAfterFinal, isLastFinal, decodeDurationMs);
  }

  private announceNativeEndpoint(endpointReason: OnlineEndpointReason,
    endpointTransition: NativeEndpointTransition): boolean {
    const endpointResult = this.recognizer.getResult(this.stream);
    this.rememberSpeculativeTimestamps(endpointResult.timestamps);
    Logger.metric(`kind=ENDPOINT sessionId=${this.sessionId} source=native ` +
      `streamGeneration=${this.streamGeneration} totalPcmBytes=${this.totalPcmBytes} ` +
      `utterancePcmBytes=${this.pcmBytesAccepted} textChars=${endpointResult.text.length} ` +
      `tokens=${endpointResult.tokens.length} nativeEndpointReason=${endpointReason} ` +
      `transition=${endpointTransition === NativeEndpointTransition.NATIVE_CHECKPOINT ?
        'native-checkpoint' : 'hard-restart'}`);
    this.endpointAtMs = Date.now();
    if (!this.callbackGate.invoke((): void => { this.callback.onEndpoint?.(); })) return false;
    this.pendingVadStopAtEndpoint = this.reentryQueue.consumeStopAtEndpoint();
    this.pendingNativeEndpointTransition = endpointTransition;
    this.vadEndpointPending = true;
    return true;
  }

  private async drainSpeakerInferenceAsync(): Promise<boolean> {
    while (!this.callbackGate.isClosed()) {
      const generation = this.speakerInferenceLane.generation();
      await this.speakerInferenceLane.drain(generation);
      if (this.speakerInferenceLane.isCurrent(generation)) return true;
    }
    return false;
  }

  private processDecodedResult(isFinal: boolean, restartAfterFinal: boolean,
    isLastFinal: boolean, decodeDurationMs: number): void {

    const endpointReason = this.recognizer.getEndpointReason(this.stream);
    if (endpointReason !== OnlineEndpointReason.NONE) {
      if (!isFinal && this.vadEndpointPending) return;
      if (!isFinal && this.speakerVadEnabled && this.svContextWaitStartedSample >= 0) {
        Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} decision=hold-native-endpoint ` +
          `waitingSinceSample=${this.svContextWaitStartedSample}`);
        return;
      }
      const endpointResult = this.recognizer.getResult(this.stream);
      this.rememberSpeculativeTimestamps(endpointResult.timestamps);
      const endpointTransition = NativeEndpointTransitionPolicy.decide(
        endpointReason === OnlineEndpointReason.RULE3 && !isFinal,
        endpointResult.text.length > 0 || endpointResult.tokens.length > 0);
      const preserveRule3Context = endpointTransition ===
        NativeEndpointTransition.NATIVE_CHECKPOINT;
      const endpointTransitionReason = preserveRule3Context ?
        'native-rule3-continuation' : 'native-endpoint';
      Logger.metric(`kind=ENDPOINT sessionId=${this.sessionId} source=native ` +
        `streamGeneration=${this.streamGeneration} totalPcmBytes=${this.totalPcmBytes} ` +
        `utterancePcmBytes=${this.pcmBytesAccepted} textChars=${endpointResult.text.length} ` +
        `tokens=${endpointResult.tokens.length} nativeEndpointReason=${endpointReason} ` +
        `transition=${preserveRule3Context ? 'native-checkpoint' : 'hard-restart'}`);
      this.endpointAtMs = Date.now();
      if (!this.callbackGate.invoke((): void => { this.callback.onEndpoint?.(); })) return;
      // A stop requested synchronously by this endpoint callback belongs to this exact result. It is
      // safe to promote here because the core is constructing the current final; the adapter still
      // never infers last-ness from its broader, asynchronous finishRequested flag.
      const stopAtEndpoint = this.reentryQueue.consumeStopAtEndpoint();
      this.dispatchFinal(true, decodeDurationMs, isLastFinal || stopAtEndpoint);
      if (stopAtEndpoint) {
        if (!this.callbackGate.isClosed()) this.notifyStopped();
      } else if (!this.callbackGate.isClosed()) {
        if (preserveRule3Context) {
          this.commitRule3Segment(endpointTransitionReason);
        } else {
          this.finishUtterance(restartAfterFinal, endpointTransitionReason);
        }
      }
      return;
    }

    const r = this.recognizer.getResult(this.stream);
    this.rememberSpeculativeTimestamps(r.timestamps);
    this.initialSilenceTracker.observeAsrResult(r.text, r.tokens.length);
    if (isFinal) {
      this.dispatchFinal(false, decodeDurationMs, isLastFinal);
      if (!this.callbackGate.isClosed()) this.finishUtterance(restartAfterFinal);
    } else if (r.text !== this.lastPartialText) {
      this.lastPartialText = r.text;
      // Speaker VAD only corrects committed finals. Partials remain speculative so adapters can
      // preserve the caller's requested real-time callback behavior.
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
    this.rememberSpeculativeTimestamps(native.timestamps);
    // Once vadBegin has conclusively expired without speech, inputFinished() may still expose a
    // speculative decoder token from the bounded non-speech prefix. It cannot retroactively turn
    // the already-decided initial-silence session into speech.
    const discardInitialSilenceResult = this.initialSilenceTracker.shouldDiscardAsrResult();
    const hasEvidence = !discardInitialSilenceResult &&
      (native.text.length > 0 || native.tokens.length > 0);
    this.initialSilenceTracker.observeAsrResult(native.text, native.tokens.length);
    const result = new AsrResult();
    result.text = discardInitialSilenceResult ? '' : native.text;
    result.tokens = discardInitialSilenceResult ? [] : native.tokens;
    result.timestamps = discardInitialSilenceResult ? [] : native.timestamps;
    result.isLast = isLast;
    const cleanPrefixSpeakerScore = this.svCleanPrefixSpeakerScore;
    const speakerScorePrepared = this.svSpeakerScorePrepared;
    this.svCleanPrefixSpeakerScore = undefined;
    this.svSpeakerScorePrepared = false;
    if (cleanPrefixSpeakerScore !== undefined) {
      result.speakerScore = cleanPrefixSpeakerScore;
      result.isTargetSpeaker = cleanPrefixSpeakerScore >=
        (this.config.targetSpeaker?.threshold ?? Number.POSITIVE_INFINITY);
    }
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
      Logger.metric(`kind=RESULT_SUPPRESSED sessionId=${this.sessionId} ` +
        `reason=effective-speech-boundary streamGeneration=${this.streamGeneration} ` +
        `totalPcmBytes=${this.totalPcmBytes} utterancePcmBytes=${this.pcmBytesAccepted} ` +
        `hasEvidence=${hasEvidence} textChars=${native.text.length} tokens=${native.tokens.length}`);
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
    let finalSpeakerVadMatch = result.isTargetSpeaker;
    if (this.speakerVadEnabled && !this.svTargetConfirmed &&
      hasEvidence && finalSpeakerVadMatch === undefined && !speakerScorePrepared &&
      scoreSelection.samples.length > 0) {
      const finalSpeakerVadScore = this.scoreSamples(scoreSelection.samples);
      if (finalSpeakerVadScore !== undefined) {
        result.speakerScore = finalSpeakerVadScore;
        finalSpeakerVadMatch = finalSpeakerVadScore >=
          (targetConfig?.threshold ?? Number.POSITIVE_INFINITY);
        result.isTargetSpeaker = finalSpeakerVadMatch;
      }
    }
    const speakerVadReject = shouldRejectSpeakerVadFinal(
      this.speakerVadEnabled, this.svRejectCurrentUtterance, this.svTargetConfirmed,
      finalSpeakerVadMatch);
    if (this.speakerVadEnabled) {
      Logger.metric(`kind=SPEAKER_FINAL_GATE sessionId=${this.sessionId} isLast=${isLast} ` +
        `reject=${speakerVadReject} targetConfirmed=${this.svTargetConfirmed} ` +
        `rejectCurrent=${this.svRejectCurrentUtterance} hasEvidence=${hasEvidence}`);
    }
    if (speakerVadReject) {
      if (hasEvidence && result.speakerScore === undefined &&
        this.lastSpeakerVadScore !== undefined) {
        result.speakerScore = this.lastSpeakerVadScore;
      }
      result.isTargetSpeaker = false;
      // A rejected Speaker VAD final is a lifecycle signal, not a transcription result. Redact
      // every textual/token field so direct Runtime clients cannot recover a known-uncertain tail.
      result.text = '';
      result.tokens = [];
      result.timestamps = [];
      result.tokenConfidences = [];
    }
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
      endpointTriggered ? this.endpointAtMs : -1,
      decodeDurationMs,
      postProcessMs,
      this.utteranceIndex,
      Math.round(this.pcmBytesAccepted * 1000 / 32000),
      this.firstPartialLatencyMs,
      this.firstPcmMs < 0 ? this.utteranceStartMs : this.firstPcmMs,
      this.pcmBytesAccepted,
      speakerScorePrepared);
    this.utteranceStartMs = Date.now();
    this.pcmBytesAccepted = 0;
    this.firstPcmMs = -1;
    this.firstPartialLatencyMs = -1;
    if (endpointTriggered) this.endpointAtMs = -1;
    this.speakerPcmBuffers.clearAll();

    if (result.isTargetSpeaker !== false &&
      (scoreSelection.samples.length > 0 || this.pendingSpeakerFinals.length > 0) &&
      this.targetSpeakerEnabled && this.targetExtractor === undefined &&
      this.targetExtractorLoad !== undefined) {
      this.pendingSpeakerFinals.push(pending);
      return hasEvidence;
    }
    this.deliverSpeakerFinal(pending);
    return hasEvidence;
  }

  private deliverSpeakerFinal(pending: PendingSpeakerFinal): void {
    if (!pending.speakerScorePrepared && pending.result.isTargetSpeaker !== false &&
      pending.result.speakerScore === undefined) {
      this.applyTargetSpeaker(pending.result, pending.samples);
    }
    if (this.callbackGate.isClosed()) return;
    if (pending.result.isTargetSpeaker === false) {
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
  private feedAndDecode(frame: ProcessedAudioFrame): void {
    let offset = 0;
    while (offset < frame.raw.length && !this.callbackGate.isClosed() &&
      !this.initialSilenceTracker.hasTimedOut()) {
      const remaining = frame.raw.length - offset;
      let chunkSize = this.initialSilenceTracker.isArmed() ?
        Math.min(remaining, INITIAL_DECISION_CHUNK_SAMPLES) : remaining;
      if (this.speakerVadEnabled) {
        const speakerVad = this.effectiveSpeakerVad();
        if (speakerVad !== undefined) {
          chunkSize = Math.min(chunkSize, this.speakerVadScoreScheduler(speakerVad).samplesUntilNextScore());
        }
      }
      this.feedChunkAndDecode(
        frame.raw.slice(offset, offset + chunkSize),
        frame.processed.slice(offset, offset + chunkSize));
      offset += chunkSize;
    }
  }

  private async feedAndDecodeAsync(frame: ProcessedAudioFrame): Promise<void> {
    let offset = 0;
    while (offset < frame.raw.length && !this.callbackGate.isClosed() &&
      !this.initialSilenceTracker.hasTimedOut()) {
      const remaining = frame.raw.length - offset;
      let chunkSize = this.initialSilenceTracker.isArmed() ?
        Math.min(remaining, INITIAL_DECISION_CHUNK_SAMPLES) : remaining;
      if (this.speakerVadEnabled) {
        const speakerVad = this.effectiveSpeakerVad();
        if (speakerVad !== undefined) {
          chunkSize = Math.min(chunkSize, this.speakerVadScoreScheduler(speakerVad).samplesUntilNextScore());
        }
      }
      await this.feedChunkAndDecodeAsync(
        frame.raw.slice(offset, offset + chunkSize),
        frame.processed.slice(offset, offset + chunkSize));
      offset += chunkSize;
    }
  }

  private feedChunkAndDecode(rawSamples: Float32Array, processedSamples: Float32Array,
    replay: boolean = false): void {
    if (this.callbackGate.isClosed() ||
      (!replay && this.initialSilenceTracker.hasTimedOut())) return;
    if (!replay) this.initialSilenceTracker.observeAcousticSamples(rawSamples);
    if (this.targetSpeakerEnabled || this.speakerVadEnabled) {
      this.effectiveSpeechBuffer.observe(rawSamples);
    }
    // Speaker VAD resets at native stream boundaries; fallback scoring resets only at a public final.
    // The two buffers must remain independent when a token-only native endpoint is suppressed.
    this.speakerPcmBuffers.observe(
      rawSamples, this.speakerVadEnabled, this.targetSpeakerEnabled || this.speakerVadEnabled);
    if (this.speakerVadEnabled) {
      const speakerVad = this.effectiveSpeakerVad();
      if (speakerVad !== undefined) {
        this.speakerTurnFinalizer(speakerVad).accept(rawSamples, processedSamples);
        // Score before feeding this deadline slice to the speculative ASR stream. If a departure is
        // confirmed, clean replay owns the slice and a simultaneous native endpoint cannot publish
        // the already contaminated speculative result first.
        if (this.maybeTriggerSpeakerVadEndpoint(rawSamples.length)) return;
      }
    }

    const resetGenerationBefore = this.recognizerResetGeneration;
    this.feedRecognizer(processedSamples, false);
    if (this.callbackGate.isClosed()) return;
    if (this.vad === undefined) return;
    if (this.recognizerResetGeneration !== resetGenerationBefore) {
      // sherpa endpoint already cut + reset the stream; resync VAD/speaker state to segment start.
      this.resetVadGateState();
      return;
    }

    // Keep Silero on caller PCM so AGC cannot move VAD/endpoint boundaries. Silero requires
    // window-aligned feeds (512); slice into windows and retain the remainder.
    const merged = this.vadCarry.length === 0 ? rawSamples :
      concatFloat32([this.vadCarry, rawSamples]);
    let i = 0;
    let anySpeech = false;
    let anySilence = false;
    while (i + this.vadWindowSize <= merged.length) {
      this.vad.acceptWaveform(merged.slice(i, i + this.vadWindowSize));
      if (this.vad.isDetected()) anySpeech = true; else anySilence = true;
      i += this.vadWindowSize;
    }
    this.vadCarry = i < merged.length ? merged.slice(i, merged.length) : new Float32Array(0);

    const initialSilenceTimedOut = replay ? false :
      this.initialSilenceTracker.observeVad(i, anySpeech);
    if (anySpeech) {
      this.effectiveSpeechBuffer.confirmSpeech();
      const notifySpeechBegin = !this.vadSpeechActive;
      // Publish state before the callback. Reentrant writes are queued, but cancel/shutdown may still
      // close this session synchronously and must observe a coherent transition.
      this.vadSpeechActive = true;
      this.trailingSilenceMs = 0;
      if (!replay && notifySpeechBegin && !this.callbackGate.invoke((): void => {
        this.callback.onSpeechBegin?.();
      })) return;
    } else if (!replay && initialSilenceTimedOut) {
      if (this.initialSilenceTracker.confirmSpeechLikeActivity()) return;
      if (this.initialSilenceTracker.needsAsrProbe() && this.probeInitialSpeechAtTimeout()) return;
      if (this.initialSilenceTracker.confirmTimeout()) {
        this.callbackGate.invoke((): void => { this.callback.onInitialSilenceTimeout?.(); });
      }
      return;
    } else if (anySilence && this.vadSpeechActive) {
      this.trailingSilenceMs += Math.round(rawSamples.length * 1000 / 16000);
      const activeEpMs = this.sessionConfig.endpointSilenceMs ?? this.config.vadConfig.activeEndpointSilenceMs;
      if (activeEpMs > 0 && this.trailingSilenceMs >= activeEpMs) {
        this.vadSpeechActive = false;
        this.trailingSilenceMs = 0;
        this.triggerVadActiveEndpoint();
        return;
      }
    }
  }

  private async feedChunkAndDecodeAsync(rawSamples: Float32Array,
    processedSamples: Float32Array, replay: boolean = false): Promise<void> {
    if (this.callbackGate.isClosed() ||
      (!replay && this.initialSilenceTracker.hasTimedOut())) return;
    if (!replay && this.svEndpointReady) {
      // The async scorer can settle between public audio submissions. Close that boundary before
      // observing this slice, then feed the slice into the freshly reset/replayed stream.
      await this.finalizeReadySpeakerEndpointAsync();
      if (this.callbackGate.isClosed() || this.svEndpointReady) return;
      await this.feedChunkAndDecodeAsync(rawSamples, processedSamples, replay);
      return;
    }
    if (!replay) this.initialSilenceTracker.observeAcousticSamples(rawSamples);
    if (this.targetSpeakerEnabled || this.speakerVadEnabled) {
      this.effectiveSpeechBuffer.observe(rawSamples);
    }
    this.speakerPcmBuffers.observe(
      rawSamples, this.speakerVadEnabled, this.targetSpeakerEnabled || this.speakerVadEnabled);
    if (this.speakerVadEnabled) {
      const speakerVad = this.effectiveSpeakerVad();
      if (speakerVad !== undefined) {
        this.speakerTurnFinalizer(speakerVad).accept(rawSamples, processedSamples);
      }
    }

    // Advance the PCM clock before any speaker ONNX or ASR decode. Expensive speaker work is queued
    // without awaiting it, so a 1600 ms trailing-silence deadline is a property of sample position,
    // not of inference wall time.
    const speakerInferenceNeedsAsrEvidence = !replay && this.initialSilenceTracker.isArmed();
    const vadAdvance = await this.advanceVadGateAsync(rawSamples, replay);
    if (this.callbackGate.isClosed()) return;
    if (!speakerInferenceNeedsAsrEvidence) this.enqueueSpeakerVadInference(rawSamples.length);
    if (!vadAdvance.vadEndpoint && this.svEndpointReady) {
      await this.finalizeReadySpeakerEndpointAsync();
      return;
    }

    const resetGenerationBefore = this.recognizerResetGeneration;
    await this.feedRecognizerAsync(processedSamples, false);
    if (this.callbackGate.isClosed()) return;
    if (speakerInferenceNeedsAsrEvidence && !this.initialSilenceTracker.isArmed()) {
      this.enqueueSpeakerVadInference(rawSamples.length);
    }
    if (this.recognizerResetGeneration !== resetGenerationBefore) {
      this.resetVadGateState();
      return;
    }
    if (vadAdvance.initialSilenceTimedOut) {
      if (this.initialSilenceTracker.confirmSpeechLikeActivity()) return;
      if (this.initialSilenceTracker.needsAsrProbe() &&
        await this.probeInitialSpeechAtTimeoutAsync()) return;
      if (this.initialSilenceTracker.confirmTimeout()) {
        this.callbackGate.invoke((): void => { this.callback.onInitialSilenceTimeout?.(); });
      }
      return;
    }
    if (vadAdvance.vadEndpoint) {
      if (!await this.drainSpeakerInferenceAsync()) return;
      if (!await this.prepareVadEndpointSpeakerScoreAsync()) return;
      await this.finalizeAnnouncedVadEndpointAsync();
    }
  }

  private async finalizeReadySpeakerEndpointAsync(): Promise<void> {
    if (this.vadEndpointPending) {
      if (!await this.drainSpeakerInferenceAsync()) return;
      if (!await this.prepareVadEndpointSpeakerScoreAsync()) return;
      await this.finalizeAnnouncedVadEndpointAsync();
    } else {
      await this.triggerSpeakerVadEndpointAsync();
    }
  }

  private async advanceVadGateAsync(rawSamples: Float32Array,
    replay: boolean = false): Promise<VadGateAdvance> {
    const advance = new VadGateAdvance();
    if (this.vad === undefined) return advance;
    const merged = this.vadCarry.length === 0 ? rawSamples :
      concatFloat32([this.vadCarry, rawSamples]);
    let index = 0;
    let anySpeech = false;
    let anySilence = false;
    while (index + this.vadWindowSize <= merged.length) {
      this.vad.acceptWaveform(merged.slice(index, index + this.vadWindowSize));
      if (this.vad.isDetected()) anySpeech = true; else anySilence = true;
      index += this.vadWindowSize;
    }
    this.vadCarry = index < merged.length ? merged.slice(index) : new Float32Array(0);
    const initialSilenceTimedOut = replay ? false :
      this.initialSilenceTracker.observeVad(index, anySpeech);
    if (anySpeech) {
      this.effectiveSpeechBuffer.confirmSpeech();
      const notifySpeechBegin = !this.vadSpeechActive;
      this.vadSpeechActive = true;
      this.trailingSilenceMs = 0;
      if (!replay && notifySpeechBegin && !this.callbackGate.invoke((): void => {
        this.callback.onSpeechBegin?.();
      })) return advance;
    } else if (!replay && initialSilenceTimedOut) {
      // Do not commit timeout yet. The current boundary slice has advanced the sample clock but has
      // not reached ASR. feedChunkAndDecodeAsync feeds it next so text/token evidence from that exact
      // slice permanently disarms vadBegin before the timeout decision is confirmed.
      advance.initialSilenceTimedOut = true;
    } else if (anySilence && this.vadSpeechActive) {
      this.trailingSilenceMs += Math.round(rawSamples.length * 1000 / ASR_SAMPLE_RATE_HZ);
      const activeEpMs = this.sessionConfig.endpointSilenceMs ??
        this.config.vadConfig.activeEndpointSilenceMs;
      if (activeEpMs > 0 && this.trailingSilenceMs >= activeEpMs && !this.vadEndpointPending) {
        this.vadSpeechActive = false;
        this.trailingSilenceMs = 0;
        Logger.metric(`kind=ENDPOINT sessionId=${this.sessionId} source=vad-active ` +
          `streamGeneration=${this.streamGeneration} totalPcmBytes=${this.totalPcmBytes} ` +
          `utterancePcmBytes=${this.pcmBytesAccepted}`);
        this.endpointAtMs = Date.now();
        if (!this.callbackGate.invoke((): void => { this.callback.onEndpoint?.(); })) return advance;
        this.pendingVadStopAtEndpoint = this.reentryQueue.consumeStopAtEndpoint();
        this.vadEndpointPending = true;
        advance.vadEndpoint = true;
        return advance;
      }
    }
    return advance;
  }

  private async prepareVadEndpointSpeakerScoreAsync(): Promise<boolean> {
    while (!this.callbackGate.isClosed()) {
      if ((!this.targetSpeakerEnabled && !this.speakerVadEnabled) ||
        this.svSpeakerScorePrepared) return true;
      const generation = this.speakerInferenceLane.generation();
      this.svSpeakerScorePrepared = true;
      const samples = this.speakerPcmBuffers.fallbackSamples();
      if (samples.length === 0) return true;
      const score = await this.scoreSamplesAsync(samples);
      if (this.callbackGate.isClosed()) return false;
      if (this.speakerInferenceLane.isCurrent(generation)) {
        this.svCleanPrefixSpeakerScore = score;
        return true;
      }
      // A live setSpeakerVadEnabled() reset invalidated this score and cleared the prepared flag.
      // Re-evaluate under the new generation so dispatchFinal never falls back to synchronous ONNX.
    }
    return false;
  }

  private finalizeAnnouncedVadEndpoint(): void {
    this.vadEndpointPending = false;
    const stopAtEndpoint = this.pendingVadStopAtEndpoint;
    this.pendingVadStopAtEndpoint = false;
    if (this.svEndpointReady && this.svRejectCurrentUtterance) {
      const rejected = new AsrResult();
      rejected.speakerScore = this.lastSpeakerVadScore;
      rejected.isTargetSpeaker = false;
      rejected.isLast = stopAtEndpoint;
      this.callbackGate.invoke((): void => { this.callback.onFinalRejected?.(rejected); });
      if (stopAtEndpoint) this.notifyStopped(); else this.restartStreamAfterUtterance('vad-speaker-rejected');
    } else if (this.svEndpointReady && this.commitCleanSpeakerTurn(stopAtEndpoint, true)) {
      return;
    } else {
      this.dispatchFinal(true, 0, stopAtEndpoint);
      if (this.callbackGate.isClosed()) return;
      if (stopAtEndpoint) this.notifyStopped(); else this.finishUtterance(true, 'vad-active-endpoint');
    }
    if (!this.callbackGate.isClosed()) this.resetVadGateState();
  }

  private async finalizeAnnouncedVadEndpointAsync(decodeDurationMs: number = 0): Promise<void> {
    this.vadEndpointPending = false;
    const stopAtEndpoint = this.pendingVadStopAtEndpoint;
    this.pendingVadStopAtEndpoint = false;
    const nativeEndpointTransition = this.pendingNativeEndpointTransition;
    this.pendingNativeEndpointTransition = undefined;
    if (this.svEndpointReady && this.svRejectCurrentUtterance) {
      const rejected = new AsrResult();
      rejected.speakerScore = this.lastSpeakerVadScore;
      rejected.isTargetSpeaker = false;
      rejected.isLast = stopAtEndpoint;
      this.callbackGate.invoke((): void => { this.callback.onFinalRejected?.(rejected); });
      if (stopAtEndpoint) this.notifyStopped(); else this.restartStreamAfterUtterance('vad-speaker-rejected');
    } else {
      if (this.svEndpointReady &&
        await this.commitCleanSpeakerTurnAsync(stopAtEndpoint, true)) return;
      // A supported live Speaker VAD reset can invalidate clean-turn work while it is awaiting
      // native inference. Re-prepare under the new generation before falling back to the full final.
      if (!await this.prepareVadEndpointSpeakerScoreAsync()) return;
      this.dispatchFinal(true, decodeDurationMs, stopAtEndpoint);
      if (this.callbackGate.isClosed()) return;
      if (stopAtEndpoint) {
        this.notifyStopped();
      } else if (nativeEndpointTransition === NativeEndpointTransition.NATIVE_CHECKPOINT) {
        this.commitRule3Segment('native-rule3-continuation');
      } else {
        this.finishUtterance(true, nativeEndpointTransition === undefined ?
          'vad-active-endpoint' : 'native-endpoint');
      }
    }
    if (!this.callbackGate.isClosed()) this.resetVadGateState();
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
    await this.prepareVadEndpointSpeakerScoreAsync();
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
    Logger.metric(`kind=ENDPOINT sessionId=${this.sessionId} source=vad-active ` +
      `streamGeneration=${this.streamGeneration} totalPcmBytes=${this.totalPcmBytes} ` +
      `utterancePcmBytes=${this.pcmBytesAccepted}`);
    this.endpointAtMs = Date.now();
    if (!this.callbackGate.invoke((): void => { this.callback.onEndpoint?.(); })) return;
    const stopAtEndpoint = this.reentryQueue.consumeStopAtEndpoint();
    this.dispatchFinal(true, 0, stopAtEndpoint);
    if (this.callbackGate.isClosed()) return;
    if (stopAtEndpoint) {
      this.notifyStopped();
      return;
    }
    this.finishUtterance(true, 'vad-active-endpoint');
    if (this.callbackGate.isClosed()) return;
    this.resetVadGateState();
  }

  // Restarting endpoints start a fresh stream, including endpoints whose native result is empty.
  // Empty, silence, Rule1 and Rule2 endpoints always rebuild the stream. Retaining their stale
  // encoder cache can keep later real speech tokenless. Rule3 continuation uses the dedicated
  // native checkpoint above and never enters this generic reset path.
  private finishUtterance(restart: boolean, reason: string = 'final'): void {
    if (!restart) {
      if (!this.callbackGate.isClosed()) this.recognizer.reset(this.stream);
      this.speculativeTimestampsSnapshot = [];
      Logger.metric(`kind=STREAM_TRANSITION sessionId=${this.sessionId} action=soft-reset ` +
        `reason=${reason} streamGeneration=${this.streamGeneration} totalPcmBytes=${this.totalPcmBytes}`);
      this.lastPartialText = '';
      this.recognizerResetGeneration += 1;
      return;
    }
    this.restartStreamAfterUtterance(reason);
    this.recognizerResetGeneration += 1;
  }

  private commitRule3Segment(reason: string): void {
    if (this.callbackGate.isClosed()) return;
    if (!this.recognizer.commitRule3Segment(this.stream)) {
      Logger.metric(`kind=STREAM_TRANSITION sessionId=${this.sessionId} ` +
        `action=native-checkpoint-rejected reason=${reason} ` +
        `streamGeneration=${this.streamGeneration} totalPcmBytes=${this.totalPcmBytes}`);
      this.restartStreamAfterUtterance(`${reason}-checkpoint-rejected`);
      this.recognizerResetGeneration += 1;
      return;
    }
    Logger.metric(`kind=STREAM_TRANSITION sessionId=${this.sessionId} action=native-checkpoint ` +
      `reason=${reason} streamGeneration=${this.streamGeneration} totalPcmBytes=${this.totalPcmBytes}`);
    this.lastPartialText = '';
    this.speculativeTimestampsSnapshot = [];
    this.recognizerResetGeneration += 1;
  }

  private restartStreamAfterUtterance(reason: string = 'endpoint'): void {
    if (this.callbackGate.isClosed()) return;
    this.hardRestartStream(reason);
    this.lastPartialText = '';
  }

  private hardRestartStream(reason: string): void {
    if (this.callbackGate.isClosed()) return;
    try {
      const next = this.recognizer.createStream();
      const previous = this.stream;
      const previousGeneration = this.streamGeneration;
      this.stream = next;
      this.streamGeneration += 1;
      this.speculativeTimestampsSnapshot = [];
      previous.close();
      Logger.metric(`kind=STREAM_TRANSITION sessionId=${this.sessionId} action=hard-restart ` +
        `reason=${reason} fromGeneration=${previousGeneration} toGeneration=${this.streamGeneration} ` +
        `totalPcmBytes=${this.totalPcmBytes}`);
      // recognizer 已在创建时预热,新 stream 复用暖模型,无需再逐次预热。
    } catch (e) {
      // If rebuilding fails, fall back to a soft reset so the session keeps running.
      if (!this.callbackGate.invoke((): void => {
        this.callback.onError?.(new AsrError(AsrErrorCode.NATIVE_CRASH, `hardRestartStream: ${e}`));
      })) return;
      this.recognizer.reset(this.stream);
      this.speculativeTimestampsSnapshot = [];
      Logger.metric(`kind=STREAM_TRANSITION sessionId=${this.sessionId} action=soft-reset-fallback ` +
        `reason=${reason} streamGeneration=${this.streamGeneration} totalPcmBytes=${this.totalPcmBytes}`);
    }
    this.lastPartialText = '';
  }

  private resetVadGateState(): void {
    this.vad?.reset();
    this.vadEndpointPending = false;
    this.pendingVadStopAtEndpoint = false;
    this.pendingNativeEndpointTransition = undefined;
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

  private appendFinalTailSilence(durationMs: number = FINAL_TAIL_SILENCE_MS): void {
    const n = Math.max(0, Math.round(ASR_SAMPLE_RATE_HZ * durationMs / 1000));
    if (n === 0) return;
    const wave: Samples = { samples: new Float32Array(n), sampleRate: ASR_SAMPLE_RATE_HZ } as Samples;
    this.stream.acceptWaveform(wave);
  }

  private applyTargetSpeaker(result: AsrResult, samples: Float32Array): void {
    const config = this.config.targetSpeaker;
    const extractor = this.targetExtractor;
    const targetSpeaker = this.targetSpeaker;
    if (config === undefined || extractor === undefined || targetSpeaker === undefined) return;
    const stream = extractor.createStream();
    try {
      const wave: Samples = { samples: samples, sampleRate: 16000 } as Samples;
      stream.acceptWaveform(wave);
      if (!extractor.isReady(stream)) {
        this.callbackGate.invoke((): void => {
          this.callback.onDebug?.(
            `speaker score unavailable: extractor-not-ready pcmMs=${Math.round(
              samples.length * 1000 / ASR_SAMPLE_RATE_HZ)}`);
        });
        return;
      }
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
    const scheduler = this.speakerVadScoreScheduler(sv);
    if (!scheduler.observe(samplesInChunk)) return false;
    if (this.svTurnFailOpen) return false;
    if (this.targetExtractor === undefined || this.targetSpeaker === undefined) return false;
    const winSamples = Math.max(1, Math.round(sv.winSec * 16000));

    const scoreStartMs = Date.now();
    const score = this.scoreSamples(this.speakerPcmBuffers.speakerVadTail(winSamples));
    if (score === undefined) return false;
    const scoreElapsedMs = Date.now() - scoreStartMs;
    const finalizer = this.speakerTurnFinalizer(sv);
    const state = finalizer.observeScore(scheduler.totalSamples(), score, sv.threshold);
    this.syncSpeakerTurnState(finalizer);
    const windowMs = Math.max(1, sv.winSec * 1000);
    Logger.metric(`kind=SPEAKER_VAD sessionId=${this.sessionId} speaker_vad state=${state} ` +
      `score=${score.toFixed(3)} threshold=${sv.threshold.toFixed(2)} inferMs=${scoreElapsedMs} ` +
      `rtf=${(scoreElapsedMs / windowMs).toFixed(3)} confirmed=${this.svTargetConfirmed} ` +
      `below=${this.svBelowCount} endSample=${scheduler.totalSamples()}`);
    if (state === 'pre-target') {
      this.discardPreparedSpeakerTurnPrefix();
      this.vadSpeechActive = false;
      this.trailingSilenceMs = 0;
      this.triggerSpeakerVadEndpoint();
      return true;
    }
    if (state === 'target-active' || state === 'target-confirmed') {
      this.discardPreparedSpeakerTurnPrefix();
    } else if (state === 'below' || state === 'departure') {
      this.prepareSpeakerTurnPrefix(finalizer);
    }
    if (state === 'departure' && this.vadSpeechActive) {
      let split = this.resolveSpeakerTurnSplit(finalizer, sv);
      if (split === undefined && finalizer.needsMoreContext()) {
        if (this.svContextWaitStartedSample < 0) {
          this.svContextWaitStartedSample = scheduler.totalSamples();
        }
        const waitedSamples = scheduler.totalSamples() - this.svContextWaitStartedSample;
        if (finalizer.lastResolutionReason() === 'diarizer-loading') {
          if (waitedSamples < scheduler.hopSamples * 4) {
            Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} decision=await-model ` +
              `waitedSamples=${waitedSamples}`);
            return false;
          }
          this.speakerTurnSegmenterUnavailable = true;
          this.speakerTurnSegmenterLoad = undefined;
          Logger.w('speaker diarizer did not become ready; using acoustic resolver');
          split = this.resolveSpeakerTurnSplit(finalizer, sv);
        }
        if (waitedSamples < scheduler.hopSamples * 2) {
          Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} decision=await-context ` +
            `waitedSamples=${waitedSamples} reason=${finalizer.lastResolutionReason()}`);
          return false;
        }
      }
      if (split === undefined) {
        const unresolvedReason = finalizer.lastResolutionReason();
        const containmentSupported = this.canContainSpeakerTurn(unresolvedReason);
        split = this.resolveSpeakerTurnContainment(finalizer, unresolvedReason);
        if (split === undefined) {
          this.discardPreparedSpeakerTurnPrefix();
          this.svContextWaitStartedSample = -1;
          if (!containmentSupported) {
            this.svTurnFailOpen = true;
            Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} decision=fail-open ` +
              `reason=${unresolvedReason}`);
            return false;
          }
          // A sequential departure is confirmed, but no target-only prefix can be proven. Reject the
          // speculative utterance instead of exposing a known-uncertain target/other mixture.
          this.svRejectCurrentUtterance = true;
          Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} decision=fail-closed ` +
            `reason=${finalizer.lastResolutionReason()} unresolvedReason=${unresolvedReason}`);
          this.vadSpeechActive = false;
          this.trailingSilenceMs = 0;
          this.triggerSpeakerVadEndpoint();
          return true;
        }
      }
      this.svPendingSplit = split;
      this.prepareCleanPrefixSpeakerScore(split);
      this.svContextWaitStartedSample = -1;
      this.vadSpeechActive = false;
      this.trailingSilenceMs = 0;
      this.triggerSpeakerVadEndpoint();
      return true;
    }
    return false;
  }

  private enqueueSpeakerVadInference(samplesInChunk: number): void {
    if (!this.speakerVadEnabled || this.svTurnFailOpen) return;
    const sv = this.effectiveSpeakerVad();
    if (sv === undefined) return;
    const scheduler = this.speakerVadScoreScheduler(sv);
    if (!scheduler.observe(samplesInChunk) ||
      this.targetExtractor === undefined || this.targetSpeaker === undefined) return;
    const winSamples = Math.max(1, Math.round(sv.winSec * ASR_SAMPLE_RATE_HZ));
    const request = new SpeakerVadInferenceRequest(
      this.speakerPcmBuffers.speakerVadTail(winSamples).slice(),
      scheduler.totalSamples(),
      this.vadSpeechActive || this.vadEndpointPending);
    if (this.svInferenceLoopActive) {
      // Keep one immutable latest-window snapshot behind the running scorer. Replacing an obsolete
      // hop bounds memory and Promise growth without discarding the result already in flight.
      this.svQueuedInference = request;
      Logger.metric(`kind=SPEAKER_VAD sessionId=${this.sessionId} decision=coalesce ` +
        `endSample=${request.endSample} pending=${this.speakerInferenceLane.pending()}`);
      return;
    }
    this.svInferenceLoopActive = true;
    const generation = this.speakerInferenceLane.generation();
    this.speakerInferenceLane.submit(generation, async (): Promise<boolean> => {
      let current = request;
      try {
        while (this.speakerInferenceLane.isCurrent(generation) && !this.svTurnFailOpen) {
          const endpointReady = await this.evaluateSpeakerVadInferenceAsync(
            current, sv, scheduler, generation);
          if (endpointReady || !this.speakerInferenceLane.isCurrent(generation) ||
            this.svTurnFailOpen) return endpointReady;
          const queued = this.svQueuedInference;
          this.svQueuedInference = undefined;
          if (queued === undefined) return false;
          current = queued;
        }
        return false;
      } finally {
        if (this.speakerInferenceLane.isCurrent(generation)) {
          this.svInferenceLoopActive = false;
          this.svQueuedInference = undefined;
        }
      }
    }, (_ready: boolean): void => {}, (e: Object): void => {
      if (!this.callbackGate.isClosed()) {
        Logger.w(`speaker inference lane failed: ${e}`);
        this.svTurnFailOpen = true;
      }
    });
  }

  private async evaluateSpeakerVadInferenceAsync(request: SpeakerVadInferenceRequest,
    sv: SpeakerVadConfig, scheduler: SpeakerVadScoreScheduler,
    generation: number): Promise<boolean> {
    const scoreStartedMs = Date.now();
    const score = await this.scoreSamplesAsync(request.samples);
    if (!this.speakerInferenceLane.isCurrent(generation) || this.svTurnFailOpen ||
      score === undefined) return false;
    const finalizer = this.speakerTurnFinalizer(sv);
    const state = finalizer.observeScore(request.endSample, score, sv.threshold);
    this.syncSpeakerTurnState(finalizer);
    const scoreElapsedMs = Date.now() - scoreStartedMs;
    const windowMs = Math.max(1, sv.winSec * 1000);
    Logger.metric(`kind=SPEAKER_VAD sessionId=${this.sessionId} speaker_vad state=${state} ` +
      `score=${score.toFixed(3)} threshold=${sv.threshold.toFixed(2)} inferMs=${scoreElapsedMs} ` +
      `rtf=${(scoreElapsedMs / windowMs).toFixed(3)} confirmed=${this.svTargetConfirmed} ` +
      `below=${this.svBelowCount} endSample=${request.endSample} lane=async`);
    if (state === 'pre-target') {
      this.svRejectCurrentUtterance = true;
      this.svEndpointReady = true;
      return true;
    }
    if (state === 'target-active' || state === 'target-confirmed') {
      this.discardPreparedSpeakerTurnPrefix();
    } else if (state === 'below') {
      this.startSpeakerTurnPrefixPreparationAsync(finalizer);
    }
    if (state !== 'departure' || !request.speechWasActive) return false;
    let split = await this.resolveSpeakerTurnSplitAsync(
      finalizer, sv, false, (): boolean => this.speakerInferenceLane.isCurrent(generation));
    if (!this.speakerInferenceLane.isCurrent(generation) || this.svTurnFailOpen) return false;
    if (split === undefined && finalizer.needsMoreContext()) {
      if (this.svContextWaitStartedSample < 0) {
        this.svContextWaitStartedSample = request.endSample;
      }
      const waitedSamples = request.endSample - this.svContextWaitStartedSample;
      if (finalizer.lastResolutionReason() === 'diarizer-loading') {
        if (waitedSamples < scheduler.hopSamples * 4) {
          Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} decision=await-model ` +
            `waitedSamples=${waitedSamples} lane=async`);
          return false;
        }
        this.speakerTurnSegmenterUnavailable = true;
        this.speakerTurnSegmenterLoad = undefined;
        Logger.w('speaker diarizer did not become ready; using acoustic resolver');
        split = await this.resolveSpeakerTurnSplitAsync(
          finalizer, sv, false, (): boolean =>
            this.speakerInferenceLane.isCurrent(generation));
        if (!this.speakerInferenceLane.isCurrent(generation) || this.svTurnFailOpen) return false;
      }
      if (split === undefined && waitedSamples < scheduler.hopSamples * 2) {
        Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} decision=await-context ` +
          `waitedSamples=${waitedSamples} reason=${finalizer.lastResolutionReason()} lane=async`);
        return false;
      }
    }
    if (split === undefined) {
      const unresolvedReason = finalizer.lastResolutionReason();
      const containmentSupported = this.canContainSpeakerTurn(unresolvedReason);
      split = this.resolveSpeakerTurnContainment(finalizer, unresolvedReason);
      if (split === undefined) {
        this.svContextWaitStartedSample = -1;
        if (!containmentSupported) {
          this.svTurnFailOpen = true;
          this.svEndpointReady = this.vadEndpointPending;
          return this.svEndpointReady;
        }
        this.svRejectCurrentUtterance = true;
        this.svEndpointReady = true;
        return true;
      }
    }
    this.svPendingSplit = split;
    const cleanPrefixScore = await this.computeCleanPrefixSpeakerScoreAsync(split);
    if (!this.speakerInferenceLane.isCurrent(generation)) return false;
    this.svCleanPrefixSpeakerScore = cleanPrefixScore;
    this.svSpeakerScorePrepared = true;
    this.svContextWaitStartedSample = -1;
    this.svEndpointReady = true;
    return true;
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
    Logger.metric(`kind=ENDPOINT sessionId=${this.sessionId} source=speaker-vad ` +
      `streamGeneration=${this.streamGeneration} totalPcmBytes=${this.totalPcmBytes} ` +
      `utterancePcmBytes=${this.pcmBytesAccepted}`);
    this.endpointAtMs = Date.now();
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
      this.restartStreamAfterUtterance('speaker-vad-rejected');
      if (this.callbackGate.isClosed()) return;
      this.speakerPcmBuffers.clearAll();
      this.effectiveSpeechBuffer.reset();
      this.pcmBytesAccepted = 0;
      this.firstPcmMs = -1;
      this.firstPartialLatencyMs = -1;
    } else {
      if (this.commitCleanSpeakerTurn(stopAtEndpoint, true)) return;
      this.dispatchFinal(true, 0, stopAtEndpoint);
      if (this.callbackGate.isClosed()) return;
      if (stopAtEndpoint) {
        this.notifyStopped();
        return;
      }
      this.restartStreamAfterUtterance('speaker-vad-endpoint');
      if (this.callbackGate.isClosed()) return;
    }
    this.resetVadGateState();
  }

  private async triggerSpeakerVadEndpointAsync(): Promise<void> {
    Logger.metric(`kind=ENDPOINT sessionId=${this.sessionId} source=speaker-vad ` +
      `streamGeneration=${this.streamGeneration} totalPcmBytes=${this.totalPcmBytes} ` +
      `utterancePcmBytes=${this.pcmBytesAccepted}`);
    this.endpointAtMs = Date.now();
    if (!this.callbackGate.invoke((): void => { this.callback.onEndpoint?.(); })) return;
    const stopAtEndpoint = this.reentryQueue.consumeStopAtEndpoint();
    if (this.svRejectCurrentUtterance) {
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
      this.restartStreamAfterUtterance('speaker-vad-rejected');
      if (this.callbackGate.isClosed()) return;
      this.speakerPcmBuffers.clearAll();
      this.effectiveSpeechBuffer.reset();
      this.pcmBytesAccepted = 0;
      this.firstPcmMs = -1;
      this.firstPartialLatencyMs = -1;
    } else {
      if (await this.commitCleanSpeakerTurnAsync(stopAtEndpoint, true)) return;
      if (!await this.prepareVadEndpointSpeakerScoreAsync()) return;
      this.dispatchFinal(true, 0, stopAtEndpoint);
      if (this.callbackGate.isClosed()) return;
      if (stopAtEndpoint) {
        this.notifyStopped();
        return;
      }
      this.restartStreamAfterUtterance('speaker-vad-endpoint');
      if (this.callbackGate.isClosed()) return;
    }
    this.resetVadGateState();
  }

  private resetSpeakerVadState(): void {
    this.speakerInferenceLane.invalidate();
    this.svInferenceLoopActive = false;
    this.svQueuedInference = undefined;
    this.svScoreScheduler?.reset();
    this.svTurnFinalizer?.reset();
    this.svPendingSplit = undefined;
    this.svCleanPrefixSpeakerScore = undefined;
    this.svSpeakerScorePrepared = false;
    this.discardPreparedSpeakerTurnPrefix();
    this.svContextWaitStartedSample = -1;
    this.svTurnFailOpen = false;
    this.svEndpointReady = false;
    this.svTargetConfirmed = false;
    this.svBelowCount = 0;
    this.svRejectCurrentUtterance = this.svAwaitingTargetAfterDeparture;
    this.lastSpeakerVadScore = undefined;
  }

  private speakerTurnFinalizer(config: SpeakerVadConfig): SpeakerTurnFinalizer {
    if (this.svTurnFinalizer !== undefined) return this.svTurnFinalizer;
    const windowSamples = Math.max(1, Math.round(config.winSec * ASR_SAMPLE_RATE_HZ));
    const hopSamples = Math.max(1, Math.round(config.hopSec * ASR_SAMPLE_RATE_HZ));
    const finalizer = new SpeakerTurnFinalizer(
      ASR_SAMPLE_RATE_HZ, windowSamples, hopSamples, config.consecutiveBelow, UTT_MAX_SAMPLES);
    this.svTurnFinalizer = finalizer;
    return finalizer;
  }

  /** Decode the immutable target prefix while the second low-score window is still arriving. */
  private prepareSpeakerTurnPrefix(finalizer: SpeakerTurnFinalizer): void {
    if (this.svPreparedPrefixStream !== undefined) return;
    const safeEnd = finalizer.safePrefixEndSample();
    if (safeEnd <= 0) return;
    const samples = finalizer.processedSamples();
    if (safeEnd > samples.length) return;
    const stream = this.recognizer.createStream();
    try {
      const wave: Samples = {
        samples: samples.slice(0, safeEnd), sampleRate: ASR_SAMPLE_RATE_HZ
      } as Samples;
      stream.acceptWaveform(wave);
      const started = Date.now();
      while (this.recognizer.isReady(stream)) this.recognizer.decode(stream);
      this.svPreparedPrefixDecodeMs = Date.now() - started;
      this.svPreparedPrefixSamples = safeEnd;
      this.svPreparedPrefixStream = stream;
      Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} decision=prepare-prefix ` +
        `samples=${safeEnd} decodeMs=${this.svPreparedPrefixDecodeMs}`);
    } catch (e) {
      stream.close();
      this.svPreparedPrefixDecodeMs = 0;
      this.svPreparedPrefixSamples = 0;
      Logger.w(`speaker turn prefix preparation failed; using full clean decode: ${e}`);
    }
  }

  /** Start decoding the proven target-only prefix without delaying the remaining turn decision. */
  private startSpeakerTurnPrefixPreparationAsync(finalizer: SpeakerTurnFinalizer): void {
    if (this.svPreparedPrefixStream !== undefined || this.svPreparedPrefixTask !== undefined) return;
    const safeEnd = finalizer.safePrefixEndSample();
    if (safeEnd <= 0) return;
    const samples = finalizer.processedSamples();
    if (safeEnd > samples.length) return;
    const stream = this.recognizer.createStream();
    const wave: Samples = {
      samples: samples.slice(0, safeEnd), sampleRate: ASR_SAMPLE_RATE_HZ
    } as Samples;
    stream.acceptWaveform(wave);
    const generation = this.svPreparedPrefixGeneration + 1;
    this.svPreparedPrefixGeneration = generation;
    this.svPreparedPrefixStream = stream;
    this.svPreparedPrefixSamples = safeEnd;
    this.svPreparedPrefixDecodeMs = 0;
    this.svPrefixPreparationPending += 1;
    let task: Promise<void>;
    task = this.recognizer.decodeAsync(stream).then((decodeMs: number): void => {
      if (generation !== this.svPreparedPrefixGeneration || this.callbackGate.isClosed()) {
        stream.close();
        return;
      }
      this.svPreparedPrefixDecodeMs = decodeMs;
      Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} decision=prepare-prefix-async ` +
        `samples=${safeEnd} decodeMs=${decodeMs}`);
    }).catch((e: Object): void => {
      stream.close();
      if (generation === this.svPreparedPrefixGeneration &&
        this.svPreparedPrefixStream === stream) {
        this.svPreparedPrefixStream = undefined;
        this.svPreparedPrefixSamples = 0;
        this.svPreparedPrefixDecodeMs = 0;
      }
      Logger.w(`speaker turn async prefix preparation failed; using full clean decode: ${e}`);
    }).finally((): void => {
      this.svPrefixPreparationPending -= 1;
      if (this.svPreparedPrefixTask === task) this.svPreparedPrefixTask = undefined;
      this.releaseStreamIfClosed();
    });
    this.svPreparedPrefixTask = task;
  }

  /** Extend the prepared stream only to the prefix shared by every boundary being scored. */
  private extendSpeakerTurnPrefixPreparationAsync(finalizer: SpeakerTurnFinalizer): void {
    const safeEnd = finalizer.candidatePrefixEndSample();
    if (safeEnd <= this.svPreparedPrefixSamples) return;
    const pending = this.svPreparedPrefixTask;
    if (pending !== undefined) {
      const generation = this.svPreparedPrefixGeneration;
      pending.then((): void => {
        if (generation === this.svPreparedPrefixGeneration && !this.callbackGate.isClosed()) {
          this.extendSpeakerTurnPrefixPreparationAsync(finalizer);
        }
      }).catch((_e: Object): void => {});
      return;
    }
    const stream = this.svPreparedPrefixStream;
    if (stream === undefined) return;
    const samples = finalizer.processedSamples();
    if (safeEnd > samples.length) return;
    const wave: Samples = {
      samples: samples.slice(this.svPreparedPrefixSamples, safeEnd),
      sampleRate: ASR_SAMPLE_RATE_HZ
    } as Samples;
    stream.acceptWaveform(wave);
    const generation = this.svPreparedPrefixGeneration;
    this.svPreparedPrefixSamples = safeEnd;
    this.svPrefixPreparationPending += 1;
    let task: Promise<void>;
    task = this.recognizer.decodeAsync(stream).then((decodeMs: number): void => {
      if (generation !== this.svPreparedPrefixGeneration || this.callbackGate.isClosed()) {
        stream.close();
        return;
      }
      this.svPreparedPrefixDecodeMs += decodeMs;
      Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} ` +
        `decision=extend-prefix-async samples=${safeEnd} decodeMs=${decodeMs}`);
    }).catch((e: Object): void => {
      stream.close();
      if (generation === this.svPreparedPrefixGeneration &&
        this.svPreparedPrefixStream === stream) {
        this.svPreparedPrefixStream = undefined;
        this.svPreparedPrefixSamples = 0;
        this.svPreparedPrefixDecodeMs = 0;
      }
      Logger.w(`speaker turn async prefix extension failed; using full clean decode: ${e}`);
    }).finally((): void => {
      this.svPrefixPreparationPending -= 1;
      if (this.svPreparedPrefixTask === task) this.svPreparedPrefixTask = undefined;
      this.releaseStreamIfClosed();
    });
    this.svPreparedPrefixTask = task;
  }

  private discardPreparedSpeakerTurnPrefix(): void {
    this.svPreparedPrefixGeneration += 1;
    const stream = this.svPreparedPrefixStream;
    const task = this.svPreparedPrefixTask;
    this.svPreparedPrefixStream = undefined;
    this.svPreparedPrefixSamples = 0;
    this.svPreparedPrefixDecodeMs = 0;
    this.svPreparedPrefixTask = undefined;
    // decodeAsync owns the stream until it settles. Its generation check closes an invalidated
    // in-flight stream; a completed preparation can be closed immediately.
    if (task === undefined) stream?.close();
  }

  /**
   * Speaker similarity is part of the public final, but it does not depend on the clean ASR text.
   * Compute the exact score selection before publishing the endpoint so endpoint-to-final latency is
   * reserved for the unavoidable clean prefix decode. dispatchFinal consumes this value once.
   */
  private prepareCleanPrefixSpeakerScore(split: SpeakerTurnSplit): void {
    this.svCleanPrefixSpeakerScore = undefined;
    this.svSpeakerScorePrepared = false;
    const config = this.config.targetSpeaker;
    if (config === undefined || this.targetExtractor === undefined || this.targetSpeaker === undefined) return;
    const effective = new EffectiveSpeechBuffer(ASR_SAMPLE_RATE_HZ, UTT_MAX_SAMPLES);
    effective.observe(split.prefix);
    effective.confirmSpeech();
    const effectiveSamples = effective.take(true);
    const minimum = Math.round(config.minSegSec * ASR_SAMPLE_RATE_HZ);
    const selection = selectSpeakerScoreSamples(effectiveSamples, split.prefix, minimum, true);
    if (selection.samples.length === 0) return;
    this.svCleanPrefixSpeakerScore = this.scoreSamples(selection.samples);
  }

  private async computeCleanPrefixSpeakerScoreAsync(
    split: SpeakerTurnSplit): Promise<number | undefined> {
    const config = this.config.targetSpeaker;
    if (config === undefined || this.targetExtractor === undefined || this.targetSpeaker === undefined) {
      return undefined;
    }
    const effective = new EffectiveSpeechBuffer(ASR_SAMPLE_RATE_HZ, UTT_MAX_SAMPLES);
    effective.observe(split.prefix);
    effective.confirmSpeech();
    const effectiveSamples = effective.take(true);
    const minimum = Math.round(config.minSegSec * ASR_SAMPLE_RATE_HZ);
    const selection = selectSpeakerScoreSamples(effectiveSamples, split.prefix, minimum, true);
    if (selection.samples.length === 0) return undefined;
    return await this.scoreSamplesAsync(selection.samples);
  }

  private syncSpeakerTurnState(finalizer: SpeakerTurnFinalizer): void {
    this.svTargetConfirmed = finalizer.isTargetConfirmed();
    if (this.svTargetConfirmed) this.svAwaitingTargetAfterDeparture = false;
    this.svBelowCount = finalizer.consecutiveLowScores();
    this.svRejectCurrentUtterance = finalizer.shouldRejectCurrent() ||
      this.svAwaitingTargetAfterDeparture;
    this.lastSpeakerVadScore = finalizer.lastScore();
  }

  /**
   * Replace a contaminated speculative final with a prefix decoded by a fresh stream, then replay
   * the untouched suffix into another fresh stream. Any failure terminates the exceptional session;
   * a known contaminated result is never used as an error fallback.
   */
  private commitCleanSpeakerTurn(isLast: boolean, endpointTriggered: boolean,
    finishTriggered: boolean = false): boolean {
    const config = this.effectiveSpeakerVad();
    const finalizer = this.svTurnFinalizer;
    if (config === undefined || finalizer === undefined) return false;
    let split = this.svPendingSplit ??
      this.resolveSpeakerTurnSplit(finalizer, config, finishTriggered);
    this.svPendingSplit = undefined;
    if (split === undefined) {
      const unresolvedReason = finalizer.lastResolutionReason();
      const containmentSupported = this.canContainSpeakerTurn(unresolvedReason);
      split = this.resolveSpeakerTurnContainment(finalizer, unresolvedReason);
      if (split !== undefined) {
        Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} decision=contain ` +
          `cutSample=${split.cutSample} unresolvedReason=${unresolvedReason}`);
      } else if (containmentSupported) {
        this.svRejectCurrentUtterance = true;
        Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} decision=fail-closed ` +
          `reason=${finalizer.lastResolutionReason()} unresolvedReason=${unresolvedReason}`);
        this.callbackGate.invoke((): void => {
          this.callback.onDebug?.(`speaker turn boundary unsafe (${unresolvedReason}); rejecting speculative final`);
        });
        return false;
      }
    }
    if (split === undefined) {
      const reason = finalizer.lastResolutionReason();
      Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} decision=fail-open reason=${reason}`);
      this.callbackGate.invoke((): void => {
        this.callback.onDebug?.(`speaker turn boundary ambiguous (${reason}); keeping speculative final`);
      });
      return false;
    }
    Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} decision=split ` +
      `cutSample=${split.cutSample} reason=${finalizer.lastResolutionReason()}`);

    const speculativeStream = this.stream;
    let prefixStream: OnlineStream | undefined;
    try {
      const preparedSamples = this.svPreparedPrefixSamples <= split.cutSample ?
        this.svPreparedPrefixSamples : 0;
      const preparedDecodeMs = preparedSamples > 0 ? this.svPreparedPrefixDecodeMs : 0;
      if (preparedSamples > 0) prefixStream = this.svPreparedPrefixStream;
      if (prefixStream === undefined) prefixStream = this.recognizer.createStream();
      this.svPreparedPrefixStream = undefined;
      this.svPreparedPrefixSamples = 0;
      this.svPreparedPrefixDecodeMs = 0;
      this.stream = prefixStream;
      const decodeStartMs = Date.now();
      if (preparedSamples < split.prefix.length) {
        const prefixWave: Samples = {
          samples: split.processedPrefix.slice(preparedSamples), sampleRate: ASR_SAMPLE_RATE_HZ
        } as Samples;
        prefixStream.acceptWaveform(prefixWave);
      }
      this.appendFinalTailSilence();
      prefixStream.inputFinished();
      while (this.recognizer.isReady(prefixStream)) this.recognizer.decode(prefixStream);
      const clean = this.recognizer.getResult(prefixStream);
      if (clean.text.length === 0 && clean.tokens.length === 0) {
        throw new Error('clean prefix re-decode produced no ASR evidence');
      }

      this.speakerPcmBuffers.clearAll();
      this.speakerPcmBuffers.observe(
        split.prefix, true, this.targetSpeakerEnabled || this.speakerVadEnabled);
      this.effectiveSpeechBuffer.reset();
      this.effectiveSpeechBuffer.observe(split.prefix);
      this.effectiveSpeechBuffer.confirmSpeech();
      this.pcmBytesAccepted = split.prefix.length * 2;
      this.svTargetConfirmed = true;
      this.svRejectCurrentUtterance = false;
      speculativeStream.close();
      // A split discovered only at finish still represents a public utterance boundary. Publish
      // its endpoint before the proven target prefix, and consume a redundant finish requested
      // reentrantly from that callback because this stop operation already owns session shutdown.
      if (finishTriggered && !endpointTriggered) {
        this.endpointAtMs = Date.now();
        if (!this.callbackGate.invoke((): void => { this.callback.onEndpoint?.(); })) return true;
        this.reentryQueue.consumeStopAtEndpoint();
      }
      // Let the replayed non-target suffix own the session's unique last result. Marking the clean
      // prefix last here would stop before the suffix is gated.
      const prefixIsLast = isLast && !finishTriggered;
      this.dispatchFinal(endpointTriggered || finishTriggered,
        preparedDecodeMs + Date.now() - decodeStartMs, prefixIsLast);
      if (this.callbackGate.isClosed()) return true;
      if (prefixIsLast) {
        this.notifyStopped();
        return true;
      }

      const suffixStream = this.recognizer.createStream();
      prefixStream.close();
      prefixStream = undefined;
      this.stream = suffixStream;
      this.speculativeTimestampsSnapshot = [];
      this.recognizerResetGeneration += 1;
      this.resetVadGateState();
      this.pcmBytesAccepted = split.suffix.length * 2;
      this.firstPcmMs = Date.now();
      this.svAwaitingTargetAfterDeparture = true;
      this.svRejectCurrentUtterance = true;
      if (finishTriggered) {
        this.replaySpeakerSuffixForFinish(split);
      } else {
        this.replaySpeakerSuffix(split);
      }
      if (finishTriggered && !this.callbackGate.isClosed()) {
        this.appendFinalTailSilence();
        this.stream.inputFinished();
        this.drain(true, false, true);
        if (!this.callbackGate.isClosed()) this.notifyStopped();
        return true;
      }
      const splitDebugMessage = `speaker turn clean split: cutSample=${split.cutSample} ` +
        `prefix=${split.prefix.length} suffix=${split.suffix.length}`;
      this.callbackGate.invoke((): void => {
        this.callback.onDebug?.(splitDebugMessage);
      });
      return true;
    } catch (e) {
      if (prefixStream !== undefined) prefixStream.close();
      if (this.stream !== speculativeStream && !this.callbackGate.isClosed()) {
        this.stream = speculativeStream;
      }
      this.callbackGate.invoke((): void => {
        this.callback.onError?.(new AsrError(
          AsrErrorCode.DECODE_FAILED, `speaker turn clean re-decode failed: ${e}`));
      });
      this.close();
      return true;
    }
  }

  private async commitCleanSpeakerTurnAsync(isLast: boolean, endpointTriggered: boolean,
    finishTriggered: boolean = false): Promise<boolean> {
    const config = this.effectiveSpeakerVad();
    const finalizer = this.svTurnFinalizer;
    if (config === undefined || finalizer === undefined) return false;
    const generation = this.speakerInferenceLane.generation();
    const isCurrent = (): boolean => this.speakerInferenceLane.isCurrent(generation);
    let split = this.svPendingSplit;
    if (split === undefined) {
      split = await this.resolveSpeakerTurnSplitAsync(
        finalizer, config, finishTriggered, isCurrent);
      if (this.callbackGate.isClosed()) return true;
      // setSpeakerVadEnabled() is a supported live reset. Its generation change discards this old
      // decision; the caller falls back to the current configuration instead of killing the session.
      if (!isCurrent()) return false;
    }
    this.svPendingSplit = undefined;
    if (split === undefined) {
      const unresolvedReason = finalizer.lastResolutionReason();
      const containmentSupported = this.canContainSpeakerTurn(unresolvedReason);
      split = this.resolveSpeakerTurnContainment(finalizer, unresolvedReason);
      if (split !== undefined) {
        Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} decision=contain ` +
          `cutSample=${split.cutSample} unresolvedReason=${unresolvedReason}`);
      } else if (containmentSupported) {
        this.svRejectCurrentUtterance = true;
        Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} decision=fail-closed ` +
          `reason=${finalizer.lastResolutionReason()} unresolvedReason=${unresolvedReason}`);
        this.callbackGate.invoke((): void => {
          this.callback.onDebug?.(`speaker turn boundary unsafe (${unresolvedReason}); rejecting speculative final`);
        });
        return false;
      }
    }
    if (split === undefined) {
      const reason = finalizer.lastResolutionReason();
      Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} decision=fail-open reason=${reason}`);
      this.callbackGate.invoke((): void => {
        this.callback.onDebug?.(`speaker turn boundary ambiguous (${reason}); keeping speculative final`);
      });
      return false;
    }
    let cleanPrefixScore = this.svCleanPrefixSpeakerScore;
    let cleanPrefixScoreError: Object | undefined;
    let cleanPrefixScoreTask: Promise<void> = Promise.resolve();
    Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} decision=split ` +
      `cutSample=${split.cutSample} reason=${finalizer.lastResolutionReason()}`);

    const speculativeStream = this.stream;
    let prefixStream: OnlineStream | undefined;
    try {
      if (this.svPreparedPrefixTask !== undefined) await this.svPreparedPrefixTask;
      const preparedSamples = this.svPreparedPrefixSamples <= split.cutSample ?
        this.svPreparedPrefixSamples : 0;
      const preparedDecodeMs = preparedSamples > 0 ? this.svPreparedPrefixDecodeMs : 0;
      if (preparedSamples > 0) prefixStream = this.svPreparedPrefixStream;
      if (prefixStream === undefined) prefixStream = this.recognizer.createStream();
      this.svPreparedPrefixStream = undefined;
      this.svPreparedPrefixSamples = 0;
      this.svPreparedPrefixDecodeMs = 0;
      this.stream = prefixStream;
      if (preparedSamples < split.prefix.length) {
        const prefixWave: Samples = {
          samples: split.processedPrefix.slice(preparedSamples), sampleRate: ASR_SAMPLE_RATE_HZ
        } as Samples;
        prefixStream.acceptWaveform(prefixWave);
      }
      this.appendFinalTailSilence();
      prefixStream.inputFinished();
      if (!this.svSpeakerScorePrepared) {
        cleanPrefixScoreTask = this.computeCleanPrefixSpeakerScoreAsync(split)
          .then((score: number | undefined): void => { cleanPrefixScore = score; })
          .catch((e: Object): void => { cleanPrefixScoreError = e; });
      }
      let decodeDurationMs = 0;
      let decodeError: Object | undefined;
      const decodeTask = this.recognizer.decodeAsync(prefixStream)
        .then((durationMs: number): void => { decodeDurationMs = durationMs; })
        .catch((e: Object): void => { decodeError = e; });
      await Promise.all([cleanPrefixScoreTask, decodeTask]);
      if (decodeError !== undefined) throw new Error(`${decodeError}`);
      if (cleanPrefixScoreError !== undefined) throw new Error(`${cleanPrefixScoreError}`);
      if (this.callbackGate.isClosed()) {
        speculativeStream.close();
        return true;
      }
      if (!isCurrent()) {
        prefixStream.close();
        prefixStream = undefined;
        this.stream = speculativeStream;
        return false;
      }
      if (!this.svSpeakerScorePrepared) {
        this.svCleanPrefixSpeakerScore = cleanPrefixScore;
        this.svSpeakerScorePrepared = true;
      }
      const clean = this.recognizer.getResult(prefixStream);
      if (clean.text.length === 0 && clean.tokens.length === 0) {
        throw new Error('clean prefix re-decode produced no ASR evidence');
      }

      this.speakerPcmBuffers.clearAll();
      this.speakerPcmBuffers.observe(
        split.prefix, true, this.targetSpeakerEnabled || this.speakerVadEnabled);
      this.effectiveSpeechBuffer.reset();
      this.effectiveSpeechBuffer.observe(split.prefix);
      this.effectiveSpeechBuffer.confirmSpeech();
      this.pcmBytesAccepted = split.prefix.length * 2;
      this.svTargetConfirmed = true;
      this.svRejectCurrentUtterance = false;
      speculativeStream.close();
      if (finishTriggered && !endpointTriggered) {
        this.endpointAtMs = Date.now();
        if (!this.callbackGate.invoke((): void => { this.callback.onEndpoint?.(); })) return true;
        this.reentryQueue.consumeStopAtEndpoint();
      }
      const prefixIsLast = isLast && !finishTriggered;
      this.dispatchFinal(endpointTriggered || finishTriggered,
        preparedDecodeMs + decodeDurationMs, prefixIsLast);
      if (this.callbackGate.isClosed()) return true;
      if (prefixIsLast) {
        this.notifyStopped();
        return true;
      }

      const suffixStream = this.recognizer.createStream();
      prefixStream.close();
      prefixStream = undefined;
      this.stream = suffixStream;
      this.speculativeTimestampsSnapshot = [];
      this.recognizerResetGeneration += 1;
      this.resetVadGateState();
      this.pcmBytesAccepted = split.suffix.length * 2;
      this.firstPcmMs = Date.now();
      this.svAwaitingTargetAfterDeparture = true;
      this.svRejectCurrentUtterance = true;
      if (finishTriggered) {
        this.replaySpeakerSuffixForFinish(split);
      } else {
        await this.replaySpeakerSuffixAsync(split);
      }
      if (finishTriggered && !this.callbackGate.isClosed()) {
        this.appendFinalTailSilence();
        this.stream.inputFinished();
        await this.drainFinalWithSpeakerScoreAsync(true);
        if (!this.callbackGate.isClosed()) this.notifyStopped();
        return true;
      }
      const splitDebugMessage = `speaker turn clean split: cutSample=${split.cutSample} ` +
        `prefix=${split.prefix.length} suffix=${split.suffix.length}`;
      this.callbackGate.invoke((): void => {
        this.callback.onDebug?.(splitDebugMessage);
      });
      return true;
    } catch (e) {
      if (this.stream !== speculativeStream) speculativeStream.close();
      if (prefixStream !== undefined && this.stream !== prefixStream) prefixStream.close();
      if (this.callbackGate.isClosed()) return true;
      this.callbackGate.invoke((): void => {
        this.callback.onError?.(new AsrError(
          AsrErrorCode.DECODE_FAILED, `speaker turn clean re-decode failed: ${e}`));
      });
      this.close();
      return true;
    }
  }

  private resolveSpeakerTurnContainment(finalizer: SpeakerTurnFinalizer,
    unresolvedReason: string): SpeakerTurnSplit | undefined {
    if (!this.canContainSpeakerTurn(unresolvedReason)) return undefined;
    const split = finalizer.resolveContainment();
    Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} resolver=containment ` +
      `decision=${split === undefined ? 'reject' : 'split'} unresolvedReason=${unresolvedReason} ` +
      `reason=${finalizer.lastResolutionReason()}`);
    return split;
  }

  private canContainSpeakerTurn(unresolvedReason: string): boolean {
    // A falling target score alone cannot distinguish sequential speech from overlap. Containment
    // is allowed only when diarization already found target -> other and merely disagreed on the
    // exact cut with the independent score-transition band.
    return unresolvedReason.startsWith('sequential-boundary-ambiguous:') &&
      isSpeakerTurnSegmentationModelLoaded();
  }

  private resolveSpeakerTurnSplit(finalizer: SpeakerTurnFinalizer,
    config: SpeakerVadConfig, finishTriggered: boolean = false): SpeakerTurnSplit | undefined {
    if (!isSpeakerTurnSegmentationModelLoaded()) {
      if (!this.speakerTurnSegmenterUnavailable) {
        finalizer.deferResolution('diarizer-loading');
        return undefined;
      }
      return this.resolveSpeakerTurnAcoustic(finalizer, config, [], 'unavailable');
    }
    const diarizationStartMs = Date.now();
    const segments = processSpeakerTurnSegmentation(finalizer.samples());
    const diarizationMs = Date.now() - diarizationStartMs;
    const resolvedSegments = segments.map(
      (segment: SpeakerTurnSegmentationSegment): SpeakerTurnSegment => new SpeakerTurnSegment(
        segment.startSample,
        segment.endSample,
        segment.speaker));
    const scoreCluster = (samples: Float32Array, _speaker: number): number | undefined => {
      if (samples.length === 0) return undefined;
      return this.scoreSamples(samples);
    };
    const diarizedSplit = finishTriggered ?
      finalizer.resolveDiarizedAtFinish(resolvedSegments, config.threshold, scoreCluster, false) :
      finalizer.resolveDiarized(resolvedSegments, config.threshold, scoreCluster, true);
    const diarizationReason = finalizer.lastResolutionReason();
    const audioMs = finalizer.sampleCount() * 1000 / ASR_SAMPLE_RATE_HZ;
    Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} resolver=diarization ` +
      `segments=${resolvedSegments.length} inferMs=${diarizationMs} ` +
      `rtf=${(diarizationMs / Math.max(1, audioMs)).toFixed(3)} ` +
      `decision=${diarizedSplit === undefined ? 'ambiguous' : 'split'} ` +
      `reason=${diarizationReason}`);
    if (diarizedSplit !== undefined) return diarizedSplit;
    // Finish-time recovery is deliberately high-confidence-only. If diarization cannot prove a
    // simple target -> other sequence, keep the speculative result in balanced mode.
    if (finishTriggered) return undefined;
    // Overlap is explicitly outside this feature's contract. For every other ambiguous or
    // contradictory diarization result, fall back to the independently bounded acoustic/token
    // resolver instead of either trusting a false local-speaker change or abandoning the endpoint.
    if (diarizationReason === 'unsupported-overlap') return undefined;
    const boundaryHints = resolvedSegments.slice(1).map(
      (segment: SpeakerTurnSegment): number => segment.startSample);
    const acousticSplit = this.resolveSpeakerTurnAcoustic(
      finalizer, config, boundaryHints, diarizationReason);
    if (acousticSplit !== undefined) return acousticSplit;
    // Preserve the independently confirmed target -> other classification while the acoustic
    // resolver waits for right-side context. Otherwise the timeout/finish path would see only
    // "insufficient context" and incorrectly fall back to publishing the mixed speculative final.
    if (diarizationReason.startsWith('diarization-boundary-after-score-transition:')) {
      const acousticReason = finalizer.lastResolutionReason();
      finalizer.deferResolution(
        `sequential-boundary-ambiguous:${diarizationReason}:${acousticReason}`);
    }
    return undefined;
  }

  private resolveSpeakerTurnAcoustic(finalizer: SpeakerTurnFinalizer,
    config: SpeakerVadConfig, boundaryHints: number[], diarizationReason: string): SpeakerTurnSplit | undefined {
    const fallbackStartMs = Date.now();
    const speculative = this.recognizer.getResult(this.stream);
    const fallback = finalizer.resolve(speculative.timestamps, config.threshold,
      (samples: Float32Array, _start: number, _end: number): number | undefined => {
        if (samples.length === 0) return undefined;
        return this.scoreSamples(samples);
      }, boundaryHints);
    Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} resolver=acoustic-fallback ` +
      `inferMs=${Date.now() - fallbackStartMs} ` +
      `decision=${fallback === undefined ? 'ambiguous' : 'split'} ` +
      `diarizationReason=${diarizationReason} reason=${finalizer.lastResolutionReason()}`);
    return fallback;
  }

  private replaySpeakerSuffix(split: SpeakerTurnSplit): void {
    let offset = 0;
    while (offset < split.suffix.length && !this.callbackGate.isClosed()) {
      let chunkSize = split.suffix.length - offset;
      const config = this.effectiveSpeakerVad();
      if (config !== undefined) {
        chunkSize = Math.min(chunkSize,
          this.speakerVadScoreScheduler(config).samplesUntilNextScore());
      }
      this.feedChunkAndDecode(
        split.suffix.slice(offset, offset + chunkSize),
        split.processedSuffix.slice(offset, offset + chunkSize), true);
      offset += chunkSize;
    }
  }

  private async replaySpeakerSuffixAsync(split: SpeakerTurnSplit): Promise<void> {
    let offset = 0;
    while (offset < split.suffix.length && !this.callbackGate.isClosed()) {
      let chunkSize = split.suffix.length - offset;
      const config = this.effectiveSpeakerVad();
      if (config !== undefined) {
        chunkSize = Math.min(chunkSize,
          this.speakerVadScoreScheduler(config).samplesUntilNextScore());
      }
      await this.feedChunkAndDecodeAsync(
        split.suffix.slice(offset, offset + chunkSize),
        split.processedSuffix.slice(offset, offset + chunkSize), true);
      offset += chunkSize;
    }
  }

  // A finish-triggered split has already established that the suffix belongs to a non-target
  // speaker. Seed the fresh stream directly so shutdown performs one final ASR decode instead of
  // replaying the real-time Speaker VAD and online decode pipeline first.
  private replaySpeakerSuffixForFinish(split: SpeakerTurnSplit): void {
    if (this.callbackGate.isClosed()) return;
    this.effectiveSpeechBuffer.observe(split.suffix);
    this.speakerPcmBuffers.observe(
      split.suffix, true, this.targetSpeakerEnabled || this.speakerVadEnabled);
    const wave: Samples = {
      samples: split.processedSuffix,
      sampleRate: ASR_SAMPLE_RATE_HZ
    } as Samples;
    this.stream.acceptWaveform(wave);
  }

  private scoreSamples(samples: Float32Array): number | undefined {
    if (this.targetExtractor === undefined || this.targetSpeaker === undefined || samples.length === 0) {
      return undefined;
    }
    const stream = this.targetExtractor.createStream();
    try {
      const wave: Samples = { samples: samples, sampleRate: 16000 } as Samples;
      stream.acceptWaveform(wave);
      if (!this.targetExtractor.isReady(stream)) return undefined;
      const embedding = this.targetExtractor.compute(stream);
      const score = cosineSimilarity(embedding, this.targetSpeaker);
      this.lastSpeakerVadScore = score;
      return score;
    } finally {
      stream.close();
    }
  }

  private async scoreSamplesAsync(samples: Float32Array): Promise<number | undefined> {
    const extractor = this.targetExtractor;
    const targetSpeaker = this.targetSpeaker;
    if (extractor === undefined || targetSpeaker === undefined || samples.length === 0) {
      return undefined;
    }
    const stream = extractor.createStream();
    try {
      const wave: Samples = { samples: samples, sampleRate: ASR_SAMPLE_RATE_HZ } as Samples;
      stream.acceptWaveform(wave);
      if (!extractor.isReady(stream)) return undefined;
      const embedding = await extractor.computeAsync(stream);
      const score = cosineSimilarity(embedding, targetSpeaker);
      return score;
    } finally {
      stream.close();
    }
  }

  private async scoreSamplesBatchAsync(
    requests: Float32Array[]): Promise<(number | undefined)[]> {
    const extractor = this.targetExtractor;
    const targetSpeaker = this.targetSpeaker;
    const scores: (number | undefined)[] = [];
    if (extractor === undefined || targetSpeaker === undefined || requests.length === 0) {
      for (let index = 0; index < requests.length; index++) scores.push(undefined);
      return scores;
    }
    const streams: OnlineStream[] = [];
    try {
      for (let index = 0; index < requests.length; index++) {
        const samples = requests[index];
        if (samples.length === 0) {
          for (let fill = 0; fill < requests.length; fill++) scores.push(undefined);
          return scores;
        }
        const stream = extractor.createStream();
        streams.push(stream);
        const wave: Samples = { samples, sampleRate: ASR_SAMPLE_RATE_HZ } as Samples;
        stream.acceptWaveform(wave);
        if (!extractor.isReady(stream)) {
          for (let fill = 0; fill < requests.length; fill++) scores.push(undefined);
          return scores;
        }
      }
      const embeddings = await extractor.computeBatchAsync(streams);
      for (let index = 0; index < requests.length; index++) {
        const embedding = index < embeddings.length ? embeddings[index] : undefined;
        scores.push(embedding === undefined ? undefined :
          cosineSimilarity(embedding, targetSpeaker));
      }
      return scores;
    } finally {
      for (let index = 0; index < streams.length; index++) streams[index].close();
    }
  }

  private async resolveWithAsyncSpeakerScores(
    resolver: (score: (samples: Float32Array) => number | undefined) => SpeakerTurnSplit | undefined,
    isCurrent: () => boolean = (): boolean => true,
    beforeScores?: () => void
  ): Promise<SpeakerTurnSplit | undefined> {
    const scores: (number | undefined)[] = [];
    for (let pass = 0; pass < 8; pass++) {
      if (!isCurrent()) return undefined;
      let cursor = 0;
      const requests: Float32Array[] = [];
      const split = resolver((samples: Float32Array): number | undefined => {
        const index = cursor++;
        if (index < scores.length) return scores[index];
        requests.push(samples.slice());
        return undefined;
      });
      if (requests.length === 0) return split;
      beforeScores?.();
      const resolvedScores = await this.scoreSamplesBatchAsync(requests);
      if (!isCurrent()) return undefined;
      for (let index = 0; index < resolvedScores.length; index++) {
        scores.push(resolvedScores[index]);
      }
    }
    return undefined;
  }

  private async resolveSpeakerTurnSplitAsync(finalizer: SpeakerTurnFinalizer,
    config: SpeakerVadConfig, finishTriggered: boolean = false,
    isCurrent: () => boolean = (): boolean => true): Promise<SpeakerTurnSplit | undefined> {
    if (!isSpeakerTurnSegmentationModelLoaded()) {
      if (!this.speakerTurnSegmenterUnavailable) {
        finalizer.deferResolution('diarizer-loading');
        return undefined;
      }
      return this.resolveSpeakerTurnAcousticAsync(
        finalizer, config, [], 'unavailable', isCurrent);
    }
    const diarizationStartMs = Date.now();
    const segments = await processSpeakerTurnSegmentationAsync(finalizer.samples());
    if (!isCurrent()) return undefined;
    const diarizationMs = Date.now() - diarizationStartMs;
    const resolvedSegments = segments.map(
      (segment: SpeakerTurnSegmentationSegment): SpeakerTurnSegment => new SpeakerTurnSegment(
        segment.startSample, segment.endSample, segment.speaker));
    const diarizedSplit = await this.resolveWithAsyncSpeakerScores(
      (score: (samples: Float32Array) => number | undefined): SpeakerTurnSplit | undefined => {
        const cluster = (samples: Float32Array, _speaker: number): number | undefined =>
          score(samples);
        return finishTriggered ?
          finalizer.resolveDiarizedAtFinish(resolvedSegments, config.threshold, cluster, false) :
          finalizer.resolveDiarized(resolvedSegments, config.threshold, cluster, true);
      }, isCurrent);
    if (!isCurrent()) return undefined;
    const diarizationReason = finalizer.lastResolutionReason();
    const audioMs = finalizer.sampleCount() * 1000 / ASR_SAMPLE_RATE_HZ;
    Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} resolver=diarization-async ` +
      `segments=${resolvedSegments.length} inferMs=${diarizationMs} ` +
      `rtf=${(diarizationMs / Math.max(1, audioMs)).toFixed(3)} ` +
      `decision=${diarizedSplit === undefined ? 'ambiguous' : 'split'} ` +
      `reason=${diarizationReason}`);
    if (diarizedSplit !== undefined || finishTriggered ||
      diarizationReason === 'unsupported-overlap') return diarizedSplit;
    const boundaryHints = resolvedSegments.slice(1).map(
      (segment: SpeakerTurnSegment): number => segment.startSample);
    const acousticSplit = await this.resolveSpeakerTurnAcousticAsync(
      finalizer, config, boundaryHints, diarizationReason, isCurrent);
    if (!isCurrent()) return undefined;
    if (acousticSplit !== undefined) return acousticSplit;
    if (diarizationReason.startsWith('diarization-boundary-after-score-transition:')) {
      const acousticReason = finalizer.lastResolutionReason();
      finalizer.deferResolution(
        `sequential-boundary-ambiguous:${diarizationReason}:${acousticReason}`);
    }
    return undefined;
  }

  private async resolveSpeakerTurnAcousticAsync(finalizer: SpeakerTurnFinalizer,
    config: SpeakerVadConfig, boundaryHints: number[],
    diarizationReason: string,
    isCurrent: () => boolean = (): boolean => true): Promise<SpeakerTurnSplit | undefined> {
    const fallbackStartMs = Date.now();
    const speculativeTimestamps = this.speculativeTimestampsSnapshot.slice();
    const fallback = await this.resolveWithAsyncSpeakerScores(
      (score: (samples: Float32Array) => number | undefined): SpeakerTurnSplit | undefined =>
        finalizer.resolve(speculativeTimestamps, config.threshold,
          (samples: Float32Array, _start: number, _end: number): number | undefined =>
          score(samples), boundaryHints), isCurrent,
      (): void => { this.extendSpeakerTurnPrefixPreparationAsync(finalizer); });
    if (!isCurrent()) return undefined;
    Logger.metric(`kind=SPEAKER_TURN sessionId=${this.sessionId} resolver=acoustic-fallback-async ` +
      `inferMs=${Date.now() - fallbackStartMs} ` +
      `decision=${fallback === undefined ? 'ambiguous' : 'split'} ` +
      `diarizationReason=${diarizationReason} reason=${finalizer.lastResolutionReason()}`);
    return fallback;
  }

  private rememberSpeculativeTimestamps(timestamps: number[]): void {
    this.speculativeTimestampsSnapshot = timestamps.slice();
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
    if (!this.callbackGate.isClosed() || this.streamCallDepth > 0 ||
      this.speakerInferenceLane.pending() > 0 || this.svPrefixPreparationPending > 0 ||
      this.streamReleased) return;
    if (!this.runtimeLease.releaseAfterClose((): void => {
      this.stream.close();
      this.streamReleased = true;
      this.onStreamReleased();
    })) {
      Logger.w(`session ${this.sessionId} stream close failed; Runtime lease retained`);
    }
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
