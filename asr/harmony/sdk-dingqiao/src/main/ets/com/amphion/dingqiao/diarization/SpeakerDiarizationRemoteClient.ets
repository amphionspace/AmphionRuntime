import { fileIo as fs } from '@kit.CoreFileKit';
import { http } from '@kit.NetworkKit';
import { SpeakerDiarizationDegradedReason } from '../DingqiaoModels';
import { DiarizationInferenceWindow, DiarizationWindowScheduler } from './DiarizationWindowScheduler';

const SAMPLE_RATE: number = 16000;
const WINDOW_SAMPLES: number = 160000;
const REQUEST_TIMEOUT_MS: number = 10000;
const PROTOCOL_VERSION: number = 1;
let nextDiarizationJobId: number = 1;

export interface DiarizationRemoteEmbedding {
  localSpeaker: number;
  speechSamples: number;
  embedding: number[];
}

export interface DiarizationRemoteSegment {
  startSample: number;
  endSample: number;
  speaker: number;
  speakerMask: number;
}

export interface DiarizationRemoteInferenceResult {
  segments: DiarizationRemoteSegment[];
  embeddings: DiarizationRemoteEmbedding[];
  inferenceMs: number;
}

export interface DiarizationRemoteWindowResult {
  protocolVersion: number;
  jobId: string;
  windowStartSample: number;
  contentStartInWindowSample: number;
  realEndSample: number;
  commitStartSample: number;
  stableEndSample: number;
  finalWindow: boolean;
  result: DiarizationRemoteInferenceResult;
}

export interface SpeakerDiarizationRemoteObserver {
  onWindow(result: DiarizationRemoteWindowResult): void;
  onDrained(): void;
  onDegraded(reason: SpeakerDiarizationDegradedReason, message: string): void;
}

interface DiarizationRemoteJob {
  jobId: string;
  offsetBytes: number;
  sampleCount: number;
  windowStartSample: number;
  contentStartInWindowSample: number;
  realEndSample: number;
  commitStartSample: number;
  stableEndSample: number;
  finalWindow: boolean;
  attempt: number;
}

class SpeakerDiarizationRemoteError extends Error {
  readonly reason: SpeakerDiarizationDegradedReason;
  readonly retryable: boolean;

  constructor(reason: SpeakerDiarizationDegradedReason, message: string, retryable: boolean) {
    super(message);
    this.reason = reason;
    this.retryable = retryable;
  }
}

function copyStringRecord(source: Record<string, string>): Record<string, string> {
  const copy: Record<string, string> = {};
  const keys = Object.keys(source);
  for (let index = 0; index < keys.length; index++) copy[keys[index]] = source[keys[index]];
  return copy;
}

export class SpeakerDiarizationStorageError extends Error {
  constructor(message: string) { super(message); }
}

/**
 * Incremental remote executor. Only one 10-second window (at most 320 KB) is
 * loaded for a request; the whole session remains in the sequential PCM spool.
 */
export class SpeakerDiarizationRemoteClient {
  private readonly scheduler: DiarizationWindowScheduler = new DiarizationWindowScheduler(SAMPLE_RATE);
  private readonly queue: DiarizationRemoteJob[] = [];
  private readonly jobDir: string;
  private readonly spoolPath: string;
  private readonly sessionId: string;
  private readonly serviceUrl: string;
  private readonly serviceHeaders: Record<string, string>;
  private readonly observer: SpeakerDiarizationRemoteObserver;
  private spoolFd: number = -1;
  private nextJobId: number = 1;
  private activeJob?: DiarizationRemoteJob;
  private activeRequest?: http.HttpRequest;
  private finishing: boolean = false;
  private closed: boolean = false;
  private degraded: boolean = false;

  constructor(workPath: string, sessionId: string, serviceUrl: string,
    serviceHeaders: Record<string, string>, observer: SpeakerDiarizationRemoteObserver) {
    this.sessionId = sessionId;
    this.serviceUrl = serviceUrl;
    this.serviceHeaders = copyStringRecord(serviceHeaders);
    this.observer = observer;
    const localJobId = nextDiarizationJobId;
    nextDiarizationJobId += 1;
    this.jobDir = `${workPath}/speaker-diarization-jobs/job-${Date.now()}-${localJobId}`;
    this.spoolPath = `${this.jobDir}/audio.pcm`;
    this.ensureDir(this.jobDir);
    const spool = fs.openSync(this.spoolPath,
      fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.APPEND);
    this.spoolFd = spool.fd;
  }

  append(audio: ArrayBuffer): void {
    if (this.closed || this.finishing || this.degraded) return;
    try {
      fs.writeSync(this.spoolFd, audio);
      const windows = this.scheduler.acceptSamples(audio.byteLength / 2);
      for (let index = 0; index < windows.length; index++) this.submit(windows[index]);
      this.pump();
    } catch (error) {
      this.fail(SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
        `speaker diarization spool failed: ${error}`);
    }
  }

  finish(): void {
    if (this.closed || this.finishing) return;
    this.finishing = true;
    if (!this.degraded) {
      try { this.submit(this.scheduler.finish()); } catch (error) {
        this.fail(SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
          `speaker diarization finish spool failed: ${error}`);
      }
    }
    this.pump();
    this.maybeNotifyDrained();
  }

  cancel(onQuiescent?: () => void): void {
    if (!this.closed) {
      this.closed = true;
      this.queue.splice(0, this.queue.length);
      this.activeRequest?.destroy();
      this.activeRequest = undefined;
      this.activeJob = undefined;
      this.closeSpool();
      this.removeJobFiles();
    }
    onQuiescent?.();
  }

  cleanup(onQuiescent?: () => void): void { this.cancel(onQuiescent); }

  checkpointDir(): string { return this.jobDir; }

  private submit(window: DiarizationInferenceWindow): void {
    const jobId = `w${this.nextJobId.toString().padStart(8, '0')}`;
    this.nextJobId += 1;
    const realSamples = Math.max(0, window.realEndSample - window.startSample);
    const sampleCount = Math.min(WINDOW_SAMPLES, realSamples);
    const contentStartInWindowSample = WINDOW_SAMPLES - sampleCount;
    const offsetSample = Math.max(0, window.realEndSample - sampleCount);
    this.queue.push({
      jobId,
      offsetBytes: offsetSample * 2,
      sampleCount,
      windowStartSample: Math.max(0, window.realEndSample - WINDOW_SAMPLES),
      contentStartInWindowSample,
      realEndSample: window.realEndSample,
      commitStartSample: window.commitStartSample,
      stableEndSample: window.stableEndSample,
      finalWindow: window.finalWindow,
      attempt: 0,
    });
  }

  private pump(): void {
    if (this.closed || this.degraded || this.activeJob !== undefined) return;
    const job = this.queue.shift();
    if (job === undefined) {
      this.maybeNotifyDrained();
      return;
    }
    this.activeJob = job;
    void this.execute(job);
  }

  private async execute(job: DiarizationRemoteJob): Promise<void> {
    let request: http.HttpRequest | undefined;
    try {
      const body = this.readWindow(job);
      request = http.createHttp();
      this.activeRequest = request;
      const response = await request.request(this.serviceUrl, {
        method: http.RequestMethod.POST,
        extraData: body,
        expectDataType: http.HttpDataType.STRING,
        usingCache: false,
        connectTimeout: 5000,
        readTimeout: REQUEST_TIMEOUT_MS,
        header: this.headers(job),
      });
      if (this.closed || this.degraded || this.activeJob?.jobId !== job.jobId) return;
      const responseCode = Number(response.responseCode);
      if (responseCode === 401 || responseCode === 403) {
        throw new SpeakerDiarizationRemoteError(
          SpeakerDiarizationDegradedReason.AUTHENTICATION_FAILED,
          `speaker diarization service authentication failed (${responseCode})`, false);
      }
      if (responseCode < 200 || responseCode >= 300) {
        throw new SpeakerDiarizationRemoteError(
          SpeakerDiarizationDegradedReason.SERVICE_UNAVAILABLE,
          `speaker diarization service returned HTTP ${responseCode}`, responseCode >= 500);
      }
      if (typeof response.result !== 'string') {
        throw new SpeakerDiarizationRemoteError(
          SpeakerDiarizationDegradedReason.INVALID_SERVICE_RESPONSE,
          'speaker diarization service returned non-text JSON', false);
      }
      const result = this.parseAndValidate(response.result, job);
      try { this.observer.onWindow(result); } catch (error) {
        const reason = error instanceof SpeakerDiarizationStorageError ?
          SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE :
          SpeakerDiarizationDegradedReason.INVALID_SERVICE_RESPONSE;
        throw new SpeakerDiarizationRemoteError(
          reason, `speaker diarization result handling failed: ${error}`, false);
      }
      this.activeJob = undefined;
      this.pump();
    } catch (error) {
      if (this.closed || this.degraded || this.activeJob?.jobId !== job.jobId) return;
      const classified = this.classifyError(error);
      this.activeJob = undefined;
      if (classified.retryable && job.attempt < 1) {
        job.attempt += 1;
        this.queue.unshift(job);
        setTimeout((): void => { this.pump(); }, 100);
      } else {
        this.fail(classified.reason, classified.message);
      }
    } finally {
      if (this.activeRequest === request) this.activeRequest = undefined;
      try { request?.destroy(); } catch (_ignored) {}
    }
  }

  private headers(job: DiarizationRemoteJob): Record<string, string> {
    const headers: Record<string, string> = copyStringRecord(this.serviceHeaders);
    headers['Content-Type'] = 'application/octet-stream';
    headers['X-Amphion-Protocol-Version'] = `${PROTOCOL_VERSION}`;
    headers['X-Amphion-Session-Id'] = this.sessionId;
    headers['X-Amphion-Job-Id'] = job.jobId;
    headers['X-Amphion-Sample-Rate'] = `${SAMPLE_RATE}`;
    headers['X-Amphion-Sample-Count'] = `${job.sampleCount}`;
    headers['X-Amphion-Window-Start-Sample'] = `${job.windowStartSample}`;
    headers['X-Amphion-Content-Start-Sample'] = `${job.contentStartInWindowSample}`;
    headers['X-Amphion-Real-End-Sample'] = `${job.realEndSample}`;
    headers['X-Amphion-Commit-Start-Sample'] = `${job.commitStartSample}`;
    headers['X-Amphion-Stable-End-Sample'] = `${job.stableEndSample}`;
    headers['X-Amphion-Final-Window'] = job.finalWindow ? 'true' : 'false';
    return headers;
  }

  private readWindow(job: DiarizationRemoteJob): ArrayBuffer {
    const data = new ArrayBuffer(job.sampleCount * 2);
    const spool = fs.openSync(this.spoolPath, fs.OpenMode.READ_ONLY);
    try {
      const read = fs.readSync(spool.fd, data, { offset: job.offsetBytes, length: data.byteLength });
      if (read !== data.byteLength) throw new Error(`expected ${data.byteLength} bytes, got ${read}`);
      return data;
    } finally { fs.closeSync(spool.fd); }
  }

  private parseAndValidate(text: string, job: DiarizationRemoteJob): DiarizationRemoteWindowResult {
    let result: DiarizationRemoteWindowResult;
    try { result = JSON.parse(text) as DiarizationRemoteWindowResult; } catch (error) {
      throw new SpeakerDiarizationRemoteError(
        SpeakerDiarizationDegradedReason.INVALID_SERVICE_RESPONSE,
        `speaker diarization service JSON is invalid: ${error}`, false);
    }
    if (result.protocolVersion !== PROTOCOL_VERSION || result.jobId !== job.jobId ||
      result.windowStartSample !== job.windowStartSample ||
      result.contentStartInWindowSample !== job.contentStartInWindowSample ||
      result.realEndSample !== job.realEndSample ||
      result.commitStartSample !== job.commitStartSample ||
      result.stableEndSample !== job.stableEndSample ||
      result.finalWindow !== job.finalWindow || result.result === undefined ||
      !Array.isArray(result.result.segments) || !Array.isArray(result.result.embeddings) ||
      !this.isFiniteNonNegative(result.result.inferenceMs)) {
      throw new SpeakerDiarizationRemoteError(
        SpeakerDiarizationDegradedReason.INVALID_SERVICE_RESPONSE,
        'speaker diarization service response metadata is invalid', false);
    }
    for (let index = 0; index < result.result.segments.length; index++) {
      const segment = result.result.segments[index];
      if (!Number.isInteger(segment.startSample) || !Number.isInteger(segment.endSample) ||
        segment.startSample < 0 || segment.endSample <= segment.startSample ||
        segment.endSample > WINDOW_SAMPLES || !Number.isInteger(segment.speaker) ||
        segment.speaker < 0 || segment.speaker > 2 || !Number.isInteger(segment.speakerMask) ||
        segment.speakerMask < 1 || segment.speakerMask > 7 ||
        (segment.speakerMask & (1 << segment.speaker)) === 0) {
        throw new SpeakerDiarizationRemoteError(
          SpeakerDiarizationDegradedReason.INVALID_SERVICE_RESPONSE,
          'speaker diarization service segment is invalid', false);
      }
    }
    for (let index = 0; index < result.result.embeddings.length; index++) {
      const embedding = result.result.embeddings[index];
      if (!Number.isInteger(embedding.localSpeaker) || embedding.localSpeaker < 0 ||
        embedding.localSpeaker > 2 || !Number.isInteger(embedding.speechSamples) ||
        embedding.speechSamples < SAMPLE_RATE || !Array.isArray(embedding.embedding) ||
        embedding.embedding.length === 0) {
        throw new SpeakerDiarizationRemoteError(
          SpeakerDiarizationDegradedReason.INVALID_SERVICE_RESPONSE,
          'speaker diarization service embedding is invalid', false);
      }
      for (let valueIndex = 0; valueIndex < embedding.embedding.length; valueIndex++) {
        if (!Number.isFinite(embedding.embedding[valueIndex])) {
          throw new SpeakerDiarizationRemoteError(
            SpeakerDiarizationDegradedReason.INVALID_SERVICE_RESPONSE,
            'speaker diarization service embedding contains non-finite values', false);
        }
      }
    }
    return result;
  }

  private classifyError(error: Object): SpeakerDiarizationRemoteError {
    if (error instanceof SpeakerDiarizationRemoteError) return error;
    const message = `${error}`;
    const timeout = message.toLowerCase().indexOf('timeout') >= 0 || message.indexOf('2300028') >= 0;
    return new SpeakerDiarizationRemoteError(
      timeout ? SpeakerDiarizationDegradedReason.INFERENCE_TIMEOUT :
        SpeakerDiarizationDegradedReason.SERVICE_UNAVAILABLE,
      `speaker diarization request failed: ${message}`, true);
  }

  private isFiniteNonNegative(value: number): boolean {
    return Number.isFinite(value) && value >= 0;
  }

  private fail(reason: SpeakerDiarizationDegradedReason, message: string): void {
    if (this.degraded || this.closed) return;
    this.degraded = true;
    this.queue.splice(0, this.queue.length);
    this.activeRequest?.destroy();
    this.activeRequest = undefined;
    this.activeJob = undefined;
    this.observer.onDegraded(reason, message);
    this.maybeNotifyDrained();
  }

  private maybeNotifyDrained(): void {
    if (this.finishing && this.activeJob === undefined && this.queue.length === 0) {
      this.observer.onDrained();
    }
  }

  private closeSpool(): void {
    if (this.spoolFd < 0) return;
    fs.closeSync(this.spoolFd);
    this.spoolFd = -1;
  }

  private removeJobFiles(): void {
    try {
      const names = ['audio.pcm', 'window-journal.jsonl', 'embedding-index.jsonl',
        'speaker-registry.json'];
      for (let index = 0; index < names.length; index++) {
        const path = `${this.jobDir}/${names[index]}`;
        if (fs.accessSync(path)) fs.unlinkSync(path);
      }
      if (fs.accessSync(this.jobDir)) fs.rmdirSync(this.jobDir);
    } catch (_ignored) {}
  }

  private ensureDir(path: string): void {
    if (fs.accessSync(path)) return;
    const index = path.lastIndexOf('/');
    if (index > 0) this.ensureDir(path.substring(0, index));
    if (!fs.accessSync(path)) fs.mkdirSync(path);
  }
}
