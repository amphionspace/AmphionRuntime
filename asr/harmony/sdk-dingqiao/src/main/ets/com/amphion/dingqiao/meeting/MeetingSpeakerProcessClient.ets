import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import childProcessManager from '@ohos.app.ability.childProcessManager';
import type { ChildProcessArgs } from '@ohos.app.ability.ChildProcessArgs';
import type { ChildProcessOptions } from '@ohos.app.ability.ChildProcessOptions';
import process from '@ohos.process';
import { MeetingInferenceWindow, MeetingWindowScheduler } from './MeetingWindowScheduler';

const EMBEDDING_MODEL_RAWFILE: string = 'amphion-dingqiao/eres2net.onnx';
const SEGMENTATION_MODEL_RAWFILE: string =
  'amphion-dingqiao/pyannote-segmentation-3.0.onnx';
const WINDOW_SAMPLES: number = 160000;
let nextMeetingJobId: number = 1;

export interface MeetingProcessEmbedding {
  localSpeaker: number;
  speechSamples: number;
  embedding: number[];
}

export interface MeetingProcessSegment {
  startSample: number;
  endSample: number;
  speaker: number;
  speakerMask: number;
}

export interface MeetingProcessWindowResult {
  jobId: string;
  windowStartSample: number;
  contentStartInWindowSample: number;
  realEndSample: number;
  commitStartSample: number;
  stableEndSample: number;
  finalWindow: boolean;
  result: MeetingProcessInferenceResult;
}

export interface MeetingProcessInferenceResult {
  segments: MeetingProcessSegment[];
  embeddings: MeetingProcessEmbedding[];
  inferenceMs: number;
}

export interface MeetingSpeakerProcessObserver {
  onWindow(result: MeetingProcessWindowResult): void;
  onDrained(): void;
  onDegraded(reason: string): void;
}

interface PendingJob {
  jobId: string;
  submittedMs: number;
}

interface MeetingChildJob {
  jobId: string;
  offsetBytes: number;
  sampleCount: number;
  windowStartSample: number;
  contentStartInWindowSample: number;
  realEndSample: number;
  commitStartSample: number;
  stableEndSample: number;
  finalWindow: boolean;
}

interface MeetingChildStartParams {
  jobDir: string;
  segmentationModelPath: string;
  embeddingModelPath: string;
}

interface StagedMeetingModels {
  segmentation: string;
  embedding: string;
}

export class MeetingSpeakerProcessClient {
  private readonly scheduler: MeetingWindowScheduler = new MeetingWindowScheduler(16000);
  private readonly pending: Map<string, PendingJob> = new Map<string, PendingJob>();
  private readonly jobDir: string;
  private readonly jobsDir: string;
  private readonly resultsDir: string;
  private readonly spoolPath: string;
  private readonly processEntry: string;
  private readonly observer: MeetingSpeakerProcessObserver;
  private readonly context: Context;
  private spoolFd: number = -1;
  private childPid: number = -1;
  private timer: number = -1;
  private nextJobId: number = 1;
  private finishing: boolean = false;
  private closed: boolean = false;
  private degraded: boolean = false;
  private restartCount: number = 0;
  private childStartedMs: number = 0;
  private readyObserved: boolean = false;
  private childStartGeneration: number = 0;
  private childStartPending: boolean = false;
  private terminationInProgress: boolean = false;
  private terminationCallbacks: (() => void)[] = [];

  constructor(context: Context, workPath: string, _sessionId: string,
    processEntry: string, observer: MeetingSpeakerProcessObserver) {
    this.context = context;
    this.processEntry = processEntry;
    this.observer = observer;
    const localJobId = nextMeetingJobId;
    nextMeetingJobId += 1;
    // sessionId is caller-controlled and must never participate in filesystem paths.
    this.jobDir = `${workPath}/meeting-jobs/job-${Date.now()}-${localJobId}`;
    this.jobsDir = `${this.jobDir}/jobs`;
    this.resultsDir = `${this.jobDir}/results`;
    this.spoolPath = `${this.jobDir}/audio.pcm`;
    this.ensureDir(this.jobsDir);
    this.ensureDir(this.resultsDir);
    const spool = fs.openSync(this.spoolPath,
      fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.APPEND);
    this.spoolFd = spool.fd;
    this.timer = setInterval((): void => { this.poll(); }, 100);
    void this.startChild();
  }

  append(audio: ArrayBuffer): void {
    if (this.closed || this.finishing || this.degraded) return;
    try {
      fs.writeSync(this.spoolFd, audio);
      const windows = this.scheduler.acceptSamples(audio.byteLength / 2);
      for (let i = 0; i < windows.length; i++) this.submit(windows[i]);
    } catch (e) {
      this.fail(`meeting speaker spool failed: ${e}`);
    }
  }

  finish(): void {
    if (this.closed || this.finishing) return;
    this.finishing = true;
    if (!this.degraded) {
      try {
        this.submit(this.scheduler.finish());
      } catch (e) {
        this.fail(`meeting speaker finish spool failed: ${e}`);
      }
    }
    this.maybeNotifyDrained();
  }

  cancel(onQuiescent?: () => void): void {
    if (this.closed) return;
    this.closed = true;
    this.stopPolling();
    this.closeSpool();
    this.terminateChild((): void => {
      this.removeJobFiles();
      onQuiescent?.();
    }, true);
  }

  cleanup(onQuiescent?: () => void): void {
    if (!this.closed) {
      this.closed = true;
      this.stopPolling();
      this.closeSpool();
    }
    this.terminateChild((): void => {
      this.removeJobFiles();
      onQuiescent?.();
    }, true);
  }

  checkpointDir(): string { return this.jobDir; }

  private async startChild(): Promise<void> {
    if (this.closed || this.degraded) return;
    const generation = this.childStartGeneration + 1;
    this.childStartGeneration = generation;
    this.childStartPending = true;
    try {
      const models = this.stageModels();
      const startParams: MeetingChildStartParams = {
        jobDir: this.jobDir,
        segmentationModelPath: models.segmentation,
        embeddingModelPath: models.embedding,
      };
      const args: ChildProcessArgs = { entryParams: JSON.stringify(startParams) };
      const options: ChildProcessOptions = { isolationMode: false };
      const stopped = `${this.jobDir}/stopped`;
      if (fs.accessSync(stopped)) fs.unlinkSync(stopped);
      this.childStartedMs = Date.now();
      this.readyObserved = false;
      const startedPid = await childProcessManager.startArkChildProcess(
        this.processEntry, args, options);
      this.childStartPending = false;
      if (this.closed || this.degraded || generation !== this.childStartGeneration) {
        this.childPid = startedPid;
        this.terminateChild(undefined, false);
        return;
      }
      this.childPid = startedPid;
    } catch (e) {
      this.childStartPending = false;
      if (this.closed) {
        this.terminateChild();
        return;
      }
      if (this.closed || this.degraded || generation !== this.childStartGeneration) return;
      this.handleProcessFailure(`meeting speaker process start failed: ${e}`);
    }
  }

  private submit(window: MeetingInferenceWindow): void {
    const jobId = `w${this.nextJobId.toString().padStart(8, '0')}`;
    this.nextJobId += 1;
    const realSamples = Math.max(0, window.realEndSample - window.startSample);
    const sampleCount = Math.min(WINDOW_SAMPLES, realSamples);
    const contentStartInWindowSample = WINDOW_SAMPLES - sampleCount;
    const offsetSample = Math.max(0, window.realEndSample - sampleCount);
    const job: MeetingChildJob = {
      jobId,
      offsetBytes: offsetSample * 2,
      sampleCount,
      windowStartSample: Math.max(0, window.realEndSample - WINDOW_SAMPLES),
      contentStartInWindowSample,
      realEndSample: window.realEndSample,
      commitStartSample: window.commitStartSample,
      stableEndSample: window.stableEndSample,
      finalWindow: window.finalWindow,
    };
    this.writeAtomic(`${this.jobsDir}/${jobId}.json`, JSON.stringify(job));
    this.pending.set(jobId, { jobId, submittedMs: Date.now() });
  }

  private poll(): void {
    if (this.closed || this.degraded) return;
    if (fs.accessSync(`${this.jobDir}/fatal`)) {
      this.handleProcessFailure(`meeting speaker child failed: ${this.readText(`${this.jobDir}/fatal`)}`);
      return;
    }
    const now = Date.now();
    if (!this.readyObserved && fs.accessSync(`${this.jobDir}/ready`)) {
      this.readyObserved = true;
      this.pending.forEach((pending: PendingJob): void => { pending.submittedMs = now; });
    }
    if (!this.readyObserved) {
      if (this.childStartedMs > 0 && now - this.childStartedMs > 10_000) {
        this.handleProcessFailure('meeting speaker child start timed out');
      }
      return;
    }
    const completed: string[] = [];
    this.pending.forEach((_pending: PendingJob, jobId: string): void => {
      const resultPath = `${this.resultsDir}/${jobId}.json`;
      if (!fs.accessSync(resultPath)) return;
      try {
        const result = JSON.parse(this.readText(resultPath)) as MeetingProcessWindowResult;
        this.observer.onWindow(result);
        // A successfully completed window breaks the consecutive-failure streak.
        this.restartCount = 0;
        completed.push(jobId);
        fs.unlinkSync(resultPath);
      } catch (e) {
        this.handleProcessFailure(`meeting speaker result invalid: ${e}`);
      }
    });
    for (let i = 0; i < completed.length; i++) this.pending.delete(completed[i]);
    if (this.degraded) return;

    let timedOut = false;
    this.pending.forEach((pending: PendingJob): void => {
      if (now - pending.submittedMs > 10_000) timedOut = true;
    });
    if (timedOut) {
      this.handleProcessFailure('meeting speaker window timed out');
      return;
    }
    this.maybeNotifyDrained();
  }

  private handleProcessFailure(reason: string): void {
    if (this.restartCount >= 1) {
      this.fail(reason);
      return;
    }
    this.restartCount += 1;
    this.terminateChild((): void => { void this.startChild(); }, false);
    const ready = `${this.jobDir}/ready`;
    if (fs.accessSync(ready)) fs.unlinkSync(ready);
    const fatal = `${this.jobDir}/fatal`;
    if (fs.accessSync(fatal)) fs.unlinkSync(fatal);
    const now = Date.now();
    this.pending.forEach((pending: PendingJob): void => { pending.submittedMs = now; });
  }

  private fail(reason: string): void {
    if (this.degraded || this.closed) return;
    this.degraded = true;
    this.pending.clear();
    this.terminateChild(undefined, false);
    this.observer.onDegraded(reason);
    this.maybeNotifyDrained();
  }

  private maybeNotifyDrained(): void {
    if (this.finishing && this.pending.size === 0) this.observer.onDrained();
  }

  private stageModels(): StagedMeetingModels {
    const modelsDir = `${this.jobDir.substring(0, this.jobDir.lastIndexOf('/'))}/models`;
    this.ensureDir(modelsDir);
    const segmentation = `${modelsDir}/pyannote-segmentation-3.0.onnx`;
    const embedding = `${modelsDir}/eres2net.onnx`;
    this.stageRawFile(SEGMENTATION_MODEL_RAWFILE, segmentation);
    this.stageRawFile(EMBEDDING_MODEL_RAWFILE, embedding);
    return { segmentation, embedding };
  }

  private stageRawFile(rawfile: string, target: string): void {
    if (fs.accessSync(target)) return;
    const bytes = this.context.resourceManager.getRawFileContentSync(rawfile);
    const temporary = `${target}.tmp`;
    const fp = fs.openSync(temporary,
      fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
    try { fs.writeSync(fp.fd, bytes.buffer); } finally { fs.closeSync(fp.fd); }
    fs.renameSync(temporary, target);
  }

  private stopPolling(): void {
    if (this.timer >= 0) {
      clearInterval(this.timer);
      this.timer = -1;
    }
  }

  private terminateChild(onQuiescent?: () => void, graceful: boolean = false): void {
    if (onQuiescent !== undefined) this.terminationCallbacks.push(onQuiescent);
    if (this.terminationInProgress) return;
    if (this.childPid <= 0) {
      if (!this.childStartPending) this.drainTerminationCallbacks();
      return;
    }
    this.terminationInProgress = true;
    const pid = this.childPid;
    this.childPid = -1;
    const stoppedPath = `${this.jobDir}/stopped`;
    const startedMs = Date.now();
    if (graceful) {
      try { this.writeText(`${this.jobDir}/stop`, 'stop'); } catch (_ignored) {}
    } else {
      try { process.kill(9, pid); } catch (_ignored) {}
    }
    const pollExit = (): void => {
      const stopped = fs.accessSync(stoppedPath);
      let alive = false;
      try { alive = process.kill(0, pid); } catch (_ignored) {}
      if (stopped || !alive) {
        this.terminationInProgress = false;
        if (stopped && fs.accessSync(stoppedPath)) fs.unlinkSync(stoppedPath);
        this.drainTerminationCallbacks();
        return;
      }
      if (graceful && Date.now() - startedMs >= 500) {
        try { process.kill(9, pid); } catch (_ignored) {}
        graceful = false;
      }
      setTimeout(pollExit, 25);
    };
    pollExit();
  }

  private drainTerminationCallbacks(): void {
    const callbacks = this.terminationCallbacks.splice(0, this.terminationCallbacks.length);
    for (let index = 0; index < callbacks.length; index++) callbacks[index]();
  }

  private closeSpool(): void {
    if (this.spoolFd < 0) return;
    fs.closeSync(this.spoolFd);
    this.spoolFd = -1;
  }

  private removeJobFiles(): void {
    try {
      const dirs = [this.jobsDir, this.resultsDir];
      for (let i = 0; i < dirs.length; i++) {
        if (!fs.accessSync(dirs[i])) continue;
        const names = fs.listFileSync(dirs[i]);
        for (let j = 0; j < names.length; j++) fs.unlinkSync(`${dirs[i]}/${names[j]}`);
        fs.rmdirSync(dirs[i]);
      }
      const rootFiles = ['audio.pcm', 'ready', 'fatal', 'stop', 'stopped', 'window-journal.jsonl',
        'embedding-index.jsonl', 'speaker-registry.json'];
      for (let i = 0; i < rootFiles.length; i++) {
        const path = `${this.jobDir}/${rootFiles[i]}`;
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

  private readText(path: string): string {
    const fp = fs.openSync(path);
    try {
      const size = fs.statSync(fp.fd).size;
      const buffer = new ArrayBuffer(size);
      fs.readSync(fp.fd, buffer);
      return new util.TextDecoder('utf-8').decodeWithStream(new Uint8Array(buffer));
    } finally { fs.closeSync(fp.fd); }
  }

  private writeText(path: string, text: string): void {
    const fp = fs.openSync(path,
      fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
    try { fs.writeSync(fp.fd, text); } finally { fs.closeSync(fp.fd); }
  }

  private writeAtomic(path: string, text: string): void {
    const temporary = `${path}.tmp`;
    this.writeText(temporary, text);
    fs.renameSync(temporary, path);
  }
}
