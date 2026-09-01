import { OfflinePunctuation, OnlineRecognizer } from 'sherpa_onnx';
import {
  AmphionLogLevel,
  AsrResult,
  Cancellable,
  SessionConfig
} from './Types';

export class DoneCancellable implements Cancellable {
  private done: boolean = false;
  private cancelled: boolean = false;

  cancel(): void { this.cancelled = true; this.done = true; }
  isCancelled(): boolean { return this.cancelled; }
  isDone(): boolean { return this.done; }
  markDone(): void { this.done = true; }
}

export class AsyncRecognizerLoad {
  recognizer: OnlineRecognizer;
  elapsedMs: number;
  ownsRecognizer: boolean;

  constructor(recognizer: OnlineRecognizer, elapsedMs: number, ownsRecognizer: boolean) {
    this.recognizer = recognizer;
    this.elapsedMs = elapsedMs;
    this.ownsRecognizer = ownsRecognizer;
  }
}

export class VadGateAdvance {
  vadEndpoint: boolean = false;
  initialSilenceTimedOut: boolean = false;
}

export class SpeakerVadInferenceRequest {
  samples: Float32Array;
  endSample: number;
  speechWasActive: boolean;

  constructor(samples: Float32Array, endSample: number, speechWasActive: boolean) {
    this.samples = samples;
    this.endSample = endSample;
    this.speechWasActive = speechWasActive;
  }
}

export class AsyncPunctuationLoad {
  punctuation?: OfflinePunctuation;
  elapsedMs: number;

  constructor(punctuation: OfflinePunctuation | undefined, elapsedMs: number) {
    this.punctuation = punctuation;
    this.elapsedMs = elapsedMs;
  }
}

export class PendingSpeakerFinal {
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
  speakerVadEnabled: boolean;
  speakerVadThreshold: number;
  speakerVadRejectCurrent: boolean;
  speakerVadTargetConfirmed: boolean;
  speakerVadLastScore?: number;
  hasEvidence: boolean;

  constructor(result: AsrResult, samples: Float32Array, endpointAtMs: number,
    decodeDurationMs: number, postProcessMs: number, utteranceIndex: number,
    utteranceDurationMs: number, firstPartialLatencyMs: number,
    utteranceStartedMs: number, pcmBytesAccepted: number, speakerScorePrepared: boolean,
    speakerVadEnabled: boolean, speakerVadThreshold: number, speakerVadRejectCurrent: boolean,
    speakerVadTargetConfirmed: boolean, speakerVadLastScore: number | undefined,
    hasEvidence: boolean) {
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
    this.speakerVadEnabled = speakerVadEnabled;
    this.speakerVadThreshold = speakerVadThreshold;
    this.speakerVadRejectCurrent = speakerVadRejectCurrent;
    this.speakerVadTargetConfirmed = speakerVadTargetConfirmed;
    this.speakerVadLastScore = speakerVadLastScore;
    this.hasEvidence = hasEvidence;
  }
}

export class Logger {
  private static level: AmphionLogLevel = AmphionLogLevel.WARN;

  static setLevel(level: AmphionLogLevel): void { Logger.level = level; }
  static d(message: string): void {
    if (Logger.level <= AmphionLogLevel.DEBUG) console.debug(`[AmphionRuntime] ${message}`);
  }
  static i(message: string): void {
    if (Logger.level <= AmphionLogLevel.INFO) console.info(`[AmphionRuntime] ${message}`);
  }
  static w(message: string): void {
    if (Logger.level <= AmphionLogLevel.WARN) console.warn(`[AmphionRuntime] ${message}`);
  }
  static e(message: string): void {
    if (Logger.level <= AmphionLogLevel.ERROR) console.error(`[AmphionRuntime] ${message}`);
  }
  static metric(line: string): void {
    if (Logger.level !== AmphionLogLevel.NONE) console.info(`[AmphionMetrics] ${line}`);
  }
}

export function validateSessionConfig(config: SessionConfig): void {
  if (config.endpointSilenceMs !== undefined &&
    (!Number.isFinite(config.endpointSilenceMs) || config.endpointSilenceMs < 0)) {
    throw new Error('SessionConfig.endpointSilenceMs must be finite and >= 0');
  }
  if (config.initialSilenceTimeoutMs !== undefined &&
    (!Number.isFinite(config.initialSilenceTimeoutMs) || config.initialSilenceTimeoutMs < 0)) {
    throw new Error('SessionConfig.initialSilenceTimeoutMs must be finite and >= 0');
  }
  if (config.initialSilenceConfirmationGraceMs !== undefined &&
    (!Number.isFinite(config.initialSilenceConfirmationGraceMs) ||
      config.initialSilenceConfirmationGraceMs < 0)) {
    throw new Error('SessionConfig.initialSilenceConfirmationGraceMs must be finite and >= 0');
  }
}

export function concatFloat32(parts: Float32Array[]): Float32Array {
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

export function cosineSimilarity(left: Float32Array, right: Float32Array): number {
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

export function average(values: number[]): number {
  if (values.length === 0) return -1;
  let sum = 0;
  for (let i = 0; i < values.length; i++) sum += values[i];
  return sum / values.length;
}

export function p95(values: number[]): number {
  if (values.length === 0) return -1;
  const sorted = values.slice().sort((a: number, b: number): number => a - b);
  const idx = Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95));
  return sorted[idx];
}
