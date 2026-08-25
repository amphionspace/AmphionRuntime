import { SpeakerDiarizationInference, SpeakerDiarizationWindowResult } from 'amphion_asr';
import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import process from '@ohos.process';
import { SpeakerDiarizationDegradedReason } from '../DingqiaoModels';

interface DiarizationChildConfig {
  jobDir: string;
  segmentationModelPath: string;
  embeddingModelPath: string;
}

interface DiarizationChildJob {
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

interface DiarizationChildResult {
  jobId: string;
  windowStartSample: number;
  contentStartInWindowSample: number;
  realEndSample: number;
  commitStartSample: number;
  stableEndSample: number;
  finalWindow: boolean;
  result: SpeakerDiarizationWindowResult;
}

interface DiarizationChildFailure {
  reason: SpeakerDiarizationDegradedReason;
  message: string;
}

/** Filesystem-journal worker. Only paths, offsets and small JSON metadata cross the process seam. */
export class SpeakerDiarizationChildService {
  private readonly inference: SpeakerDiarizationInference = new SpeakerDiarizationInference();
  private config?: DiarizationChildConfig;
  private polling: boolean = false;
  private timer: number = -1;

  async start(entryParams: string): Promise<void> {
    try {
      this.config = JSON.parse(entryParams) as DiarizationChildConfig;
    } catch (_e) {
      this.stop(2);
      return;
    }
    try {
      await this.inference.load(
        this.config.segmentationModelPath,
        this.config.embeddingModelPath);
    } catch (e) {
      this.writeFatal(SpeakerDiarizationDegradedReason.MODEL_UNAVAILABLE,
        `speaker diarization model load failed: ${e}`);
      this.stop(2);
      return;
    }
    try {
      this.writeText(`${this.config.jobDir}/ready`, 'ready');
    } catch (e) {
      this.writeFatal(SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
        `speaker diarization ready journal failed: ${e}`);
      this.stop(2);
      return;
    }
    this.timer = setInterval((): void => { void this.poll(); }, 100);
  }

  private async poll(): Promise<void> {
    const config = this.config;
    if (config === undefined || this.polling) return;
    if (fs.accessSync(`${config.jobDir}/stop`)) {
      this.stop(0);
      return;
    }
    this.polling = true;
    try {
      let names: string[];
      try {
        names = fs.listFileSync(`${config.jobDir}/jobs`)
          .filter((name: string): boolean => name.endsWith('.json'))
          .sort();
      } catch (e) {
        this.writeFatal(SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
          `speaker diarization child storage failed while listing jobs: ${e}`);
        this.stop(3);
        return;
      }
      for (let i = 0; i < names.length; i++) {
        const failure = await this.processJob(`${config.jobDir}/jobs/${names[i]}`);
        if (failure === undefined) continue;
        this.writeFatal(failure.reason, failure.message);
        this.stop(3);
        return;
      }
    } finally {
      this.polling = false;
    }
  }

  private async processJob(path: string): Promise<DiarizationChildFailure | undefined> {
    const config = this.config as DiarizationChildConfig;
    let jobText: string;
    try {
      jobText = this.readText(path);
    } catch (e) {
      return this.storageFailure(`reading job ${path}`, e);
    }
    let job: DiarizationChildJob;
    try {
      job = JSON.parse(jobText) as DiarizationChildJob;
    } catch (e) {
      return {
        reason: SpeakerDiarizationDegradedReason.PROCESS_UNAVAILABLE,
        message: `speaker diarization child job invalid (${path}): ${e}`,
      };
    }
    const bytes = new ArrayBuffer(job.sampleCount * 2);
    try {
      const spool = fs.openSync(`${config.jobDir}/audio.pcm`);
      try {
        fs.readSync(spool.fd, bytes, { offset: job.offsetBytes, length: bytes.byteLength });
      } finally {
        fs.closeSync(spool.fd);
      }
    } catch (e) {
      return this.storageFailure(`reading PCM for ${job.jobId}`, e);
    }
    const pcm = new Int16Array(bytes);
    const samples = new Float32Array(job.sampleCount);
    for (let i = 0; i < pcm.length; i++) samples[i] = pcm[i] / 32768.0;
    const inferenceWindow = new Float32Array(160000);
    inferenceWindow.set(samples, Math.max(0, inferenceWindow.length - samples.length));
    let inferenceResult: SpeakerDiarizationWindowResult;
    try {
      inferenceResult = await this.inference.process(inferenceWindow);
    } catch (e) {
      return {
        reason: SpeakerDiarizationDegradedReason.PROCESS_UNAVAILABLE,
        message: `speaker diarization child inference failed (${job.jobId}): ${e}`,
      };
    }
    const result: DiarizationChildResult = {
      jobId: job.jobId,
      windowStartSample: job.windowStartSample,
      contentStartInWindowSample: job.contentStartInWindowSample,
      realEndSample: job.realEndSample,
      commitStartSample: job.commitStartSample,
      stableEndSample: job.stableEndSample,
      finalWindow: job.finalWindow,
      result: inferenceResult,
    };
    const target = `${config.jobDir}/results/${job.jobId}.json`;
    try {
      this.writeAtomic(target, JSON.stringify(result));
      fs.unlinkSync(path);
    } catch (e) {
      return this.storageFailure(`writing result for ${job.jobId}`, e);
    }
    return undefined;
  }

  private storageFailure(operation: string, error: Object): DiarizationChildFailure {
    return {
      reason: SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
      message: `speaker diarization child storage failed while ${operation}: ${error}`,
    };
  }

  private stop(code: number): void {
    if (this.timer >= 0) clearInterval(this.timer);
    this.inference.close();
    const jobDir = this.config?.jobDir;
    if (jobDir !== undefined) this.writeText(`${jobDir}/stopped`, 'stopped');
    process.exit(code);
  }

  private readText(path: string): string {
    const fp = fs.openSync(path);
    try {
      const size = fs.statSync(fp.fd).size;
      const bytes = new Uint8Array(size);
      fs.readSync(fp.fd, bytes.buffer);
      return new util.TextDecoder('utf-8').decodeWithStream(bytes);
    } finally {
      fs.closeSync(fp.fd);
    }
  }

  private writeText(path: string, text: string): void {
    const fp = fs.openSync(path,
      fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
    try { fs.writeSync(fp.fd, text); } finally { fs.closeSync(fp.fd); }
  }

  private writeFatal(reason: SpeakerDiarizationDegradedReason, message: string): void {
    const jobDir = this.config?.jobDir;
    if (jobDir === undefined) return;
    try {
      this.writeText(`${jobDir}/fatal`, JSON.stringify({ reason, message }));
    } catch (_ignored) {}
  }

  private writeAtomic(path: string, text: string): void {
    const temporary = `${path}.tmp`;
    this.writeText(temporary, text);
    fs.renameSync(temporary, path);
  }
}
