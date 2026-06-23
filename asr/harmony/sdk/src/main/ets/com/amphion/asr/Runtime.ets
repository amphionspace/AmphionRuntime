import {
  OfflinePunctuation,
  OfflinePunctuationConfig,
  OnlineModelConfig,
  OnlineRecognizer,
  OnlineRecognizerConfig,
  OnlineStream,
  Samples
} from 'sherpa_onnx';
import { AssetRegistry, InstalledLayout } from './AssetRegistry';
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
  Cancellable
} from './Types';
import { AmphionLicenseStatus, HarmonyLicenseVerifier } from './License';

class DoneCancellable implements Cancellable {
  private done: boolean = false;
  cancel(): void { this.done = true; }
  isDone(): boolean { return this.done; }
  markDone(): void { this.done = true; }
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
  private static initialized: boolean = false;
  private static appContext?: Context;
  private static options: AmphionOptions = new AmphionOptions();
  private static nextSessionId: number = 1;

  static init(context: Context, options?: AmphionOptions): void {
    AmphionRuntime.appContext = context;
    AmphionRuntime.options = options ?? new AmphionOptions();
    Logger.setLevel(AmphionRuntime.options.logLevel);
    AmphionRuntime.initialized = true;
    Logger.i('AmphionRuntime Harmony init done');
  }

  static preInstall(context: Context, onProgress?: (doneBytes: number, totalBytes: number) => void): Cancellable {
    const c = new DoneCancellable();
    AmphionRuntime.appContext = context;
    onProgress?.(0, 0);
    // HarmonyOS 版首阶段直接从 rawfile 读取模型；如需解包到 filesDir，可在 AssetInstaller 后续扩展。
    onProgress?.(1, 1);
    c.markDone();
    return c;
  }

  static preload(context: Context, languages: AsrLanguage[], config?: AsrConfig, onProgress?: (done: number, total: number) => void): Cancellable {
    const c = new DoneCancellable();
    AmphionRuntime.appContext = context;
    onProgress?.(0, languages.length);
    // 先保持 API 语义；真正 recognizer 池化在 native 验证后补齐。
    onProgress?.(languages.length, languages.length);
    c.markDone();
    return c;
  }

  static create(context: Context, language: AsrLanguage, config?: AsrConfig): AsrEngine {
    if (!AmphionRuntime.initialized) {
      AmphionRuntime.init(context, AmphionRuntime.options);
    }
    return new AsrEngine(context, language, config ?? new AsrConfig());
  }

  static version(): string { return '0.1.0-harmony'; }
  static licenseStatus(): AmphionLicenseStatus {
    const serial = AmphionRuntime.appContext === undefined
      ? undefined
      : AmphionRuntime.options.deviceIdProvider?.getDeviceSerial(AmphionRuntime.appContext);
    return HarmonyLicenseVerifier.verify(
      AmphionRuntime.options.license,
      AmphionRuntime.options.bundleName,
      AmphionRuntime.options.signingCertDigest,
      serial
    );
  }
  static release(): void { AmphionRuntime.initialized = false; }

  static allocateSessionId(): number { return AmphionRuntime.nextSessionId++; }
}

export class AsrEngine {
  private context: Context;
  private language: AsrLanguage;
  private config: AsrConfig;
  private recognizer: OnlineRecognizer;
  private punctuation?: OfflinePunctuation;
  private closed: boolean = false;

  constructor(context: Context, language: AsrLanguage, config: AsrConfig) {
    this.context = context;
    this.language = language;
    this.config = config;
    const layout = AssetRegistry.rawfileLayout(language, config);
    this.recognizer = new OnlineRecognizer(this.buildRecognizerConfig(layout), context.resourceManager);
    if (config.punctuation && layout.punctModel !== undefined) {
      const pc = new OfflinePunctuationConfig();
      pc.model.ctTransformer = layout.punctModel;
      pc.model.numThreads = config.numThreads;
      this.punctuation = new OfflinePunctuation(pc, context.resourceManager);
    }
  }

  newSession(callback: AsrCallback): AsrSession {
    if (this.closed) throw new Error('AsrEngine is closed');
    return new AsrSession(
      AmphionRuntime.allocateSessionId(),
      this.language,
      this.config,
      this.recognizer,
      this.punctuation,
      callback
    );
  }

  isClosed(): boolean { return this.closed; }
  close(): void { this.closed = true; }

  private buildRecognizerConfig(layout: InstalledLayout): OnlineRecognizerConfig {
    const model = new OnlineModelConfig();
    model.transducer.encoder = layout.asrEncoder;
    model.transducer.decoder = layout.asrDecoder;
    model.transducer.joiner = layout.asrJoiner;
    model.tokens = layout.asrTokens;
    model.modelType = 'zipformer2';
    model.modelingUnit = 'bbpe';
    model.bpeVocab = layout.asrBpeVocab;
    model.numThreads = this.config.numThreads;
    model.debug = false;

    const rc = new OnlineRecognizerConfig();
    rc.modelConfig = model;
    rc.decodingMethod = this.config.hotwords.length > 0 ? 'modified_beam_search' : 'modified_beam_search';
    rc.maxActivePaths = 8;
    rc.enableEndpoint = this.config.endpoint;
    rc.rule1MinTrailingSilence = this.config.endpointRules.rule1MinTrailingSilenceSec;
    rc.rule2MinTrailingSilence = this.config.endpointRules.rule2MinTrailingSilenceSec;
    rc.rule3MinUtteranceLength = this.config.endpointRules.rule3MinUtteranceLengthSec;
    rc.hotwordsScore = this.config.hotwordsScore;
    rc.hotwordsBuf = this.config.hotwords.join('\n');
    rc.hotwordsBufSize = rc.hotwordsBuf.length;
    return rc;
  }
}

export class AsrSession {
  private sessionId: number;
  private language: AsrLanguage;
  private config: AsrConfig;
  private recognizer: OnlineRecognizer;
  private stream: OnlineStream;
  private punctuation?: OfflinePunctuation;
  private callback: AsrCallback;
  private closed: boolean = false;
  private stopped: boolean = false;
  private lastPartialText: string = '';
  private pcmBytesAccepted: number = 0;
  private utteranceIndex: number = 0;
  private utteranceStartMs: number = Date.now();

  constructor(sessionId: number, language: AsrLanguage, config: AsrConfig, recognizer: OnlineRecognizer, punctuation: OfflinePunctuation | undefined, callback: AsrCallback) {
    this.sessionId = sessionId;
    this.language = language;
    this.config = config;
    this.recognizer = recognizer;
    this.stream = recognizer.createStream();
    this.punctuation = punctuation;
    this.callback = callback;
    this.callback.onSessionStarted?.();
  }

  acceptPcmShort(samples: Int16Array): void {
    if (this.closed || this.stopped) return;
    const floats = new Float32Array(samples.length);
    for (let i = 0; i < samples.length; i++) floats[i] = samples[i] / 32768.0;
    this.acceptPcmFloat(floats);
  }

  acceptPcmBytes(bytes: ArrayBuffer): void {
    this.acceptPcmShort(new Int16Array(bytes));
  }

  acceptPcmFloat(samples: Float32Array): void {
    if (this.closed || this.stopped) return;
    this.pcmBytesAccepted += samples.length * 2;
    const wave: Samples = { samples: samples, sampleRate: 16000 } as Samples;
    try {
      this.stream.acceptWaveform(wave);
      this.drain(false);
    } catch (e) {
      this.callback.onError?.(new AsrError(AsrErrorCode.NATIVE_CRASH, `${e}`));
    }
  }

  stop(): void {
    if (this.closed || this.stopped) return;
    this.stopped = true;
    try {
      this.stream.inputFinished();
      this.drain(true);
      this.callback.onSessionStopped?.();
    } catch (e) {
      this.callback.onError?.(new AsrError(AsrErrorCode.NATIVE_CRASH, `${e}`));
    }
  }

  updateHotwords(words: string[], score: number = 1.5): void {
    this.config.hotwords = words;
    this.config.hotwordsScore = score;
    Logger.w('updateHotwords requires recreating recognizer on Harmony first implementation');
  }

  setTargetSpeaker(embedding: Float32Array): void { Logger.d(`target speaker dim=${embedding.length}`); }
  clearTargetSpeaker(): void { Logger.d('target speaker cleared'); }
  setTargetSpeakerEnabled(enabled: boolean): void { Logger.d(`target speaker enabled=${enabled}`); }
  isClosed(): boolean { return this.closed; }
  close(): void { this.closed = true; }

  private drain(isFinal: boolean): void {
    while (this.recognizer.isReady(this.stream)) {
      this.recognizer.decode(this.stream);
    }

    if (this.recognizer.isEndpoint(this.stream)) {
      this.callback.onEndpoint?.();
      this.dispatchFinal();
      this.recognizer.reset(this.stream);
      this.lastPartialText = '';
      return;
    }

    const r = this.recognizer.getResult(this.stream);
    if (isFinal) {
      this.dispatchFinal();
      this.recognizer.reset(this.stream);
      this.lastPartialText = '';
    } else if (r.text !== this.lastPartialText) {
      this.lastPartialText = r.text;
      const result = new AsrResult();
      result.text = r.text;
      result.tokens = r.tokens;
      result.timestamps = r.timestamps;
      this.callback.onPartial?.(result.text);
      this.callback.onPartialResult?.(result);
    }
  }

  private dispatchFinal(): void {
    const native = this.recognizer.getResult(this.stream);
    const result = new AsrResult();
    result.text = native.text;
    result.tokens = native.tokens;
    result.timestamps = native.timestamps;
    if (this.punctuation !== undefined && result.text.length > 0) {
      try { result.text = this.punctuation.addPunct(result.text); } catch (_) {}
    }
    this.utteranceIndex += 1;
    this.callback.onFinal?.(result.text, result.confidence);
    this.callback.onFinalResult?.(result);

    const metrics = new AmphionMetrics();
    metrics.kind = AmphionMetricsKind.UTTERANCE;
    metrics.language = this.language;
    metrics.sessionId = this.sessionId;
    metrics.utteranceIndex = this.utteranceIndex;
    metrics.utteranceE2eLatencyMs = Date.now() - this.utteranceStartMs;
    metrics.pcmBytesAccepted = this.pcmBytesAccepted;
    this.callback.onMetrics?.(metrics);
    Logger.metric(metrics.toLogLine());
    this.utteranceStartMs = Date.now();
    this.pcmBytesAccepted = 0;
  }
}
