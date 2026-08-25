import { SpeakerDiarizationInference, SpeakerDiarizationWindowResult } from 'amphion_asr';
import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import process from '@ohos.process';

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

/** Filesystem-journal worker. Only paths, offsets and small JSON metadata cross the process seam. */
export class SpeakerDiarizationChildService {
  private readonly inference: SpeakerDiarizationInference = new SpeakerDiarizationInference();
  private config?: DiarizationChildConfig;
  private polling: boolean = false;
  private timer: number = -1;

  async start(entryParams: string): Promise<void> {
    try {
      this.config = JSON.parse(entryParams) as DiarizationChildConfig;
      await this.inference.load(
        this.config.segmentationModelPath,
        this.config.embeddingModelPath);
      this.writeText(`${this.config.jobDir}/ready`, 'ready');
      this.timer = setInterval((): void => { void this.poll(); }, 100);
    } catch (e) {
      const jobDir = this.config?.jobDir;
      if (jobDir !== undefined) this.writeText(`${jobDir}/fatal`, `${e}`);
      this.stop(2);
    }
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
      const jobsDir = `${config.jobDir}/jobs`;
      const names = fs.listFileSync(jobsDir)
        .filter((name: string): boolean => name.endsWith('.json'))
        .sort();
      for (let i = 0; i < names.length; i++) {
        await this.processJob(`${jobsDir}/${names[i]}`);
      }
    } catch (e) {
      this.writeText(`${config.jobDir}/fatal`, `${e}`);
      this.stop(3);
    } finally {
      this.polling = false;
    }
  }

  private async processJob(path: string): Promise<void> {
    const config = this.config as DiarizationChildConfig;
    const job = JSON.parse(this.readText(path)) as DiarizationChildJob;
    const bytes = new ArrayBuffer(job.sampleCount * 2);
    const spool = fs.openSync(`${config.jobDir}/audio.pcm`);
    try {
      fs.readSync(spool.fd, bytes, { offset: job.offsetBytes, length: bytes.byteLength });
    } finally {
      fs.closeSync(spool.fd);
    }
    const pcm = new Int16Array(bytes);
    const samples = new Float32Array(job.sampleCount);
    for (let i = 0; i < pcm.length; i++) samples[i] = pcm[i] / 32768.0;
    const inferenceWindow = new Float32Array(160000);
    inferenceWindow.set(samples, Math.max(0, inferenceWindow.length - samples.length));
    const result: DiarizationChildResult = {
      jobId: job.jobId,
      windowStartSample: job.windowStartSample,
      contentStartInWindowSample: job.contentStartInWindowSample,
      realEndSample: job.realEndSample,
      commitStartSample: job.commitStartSample,
      stableEndSample: job.stableEndSample,
      finalWindow: job.finalWindow,
      result: await this.inference.process(inferenceWindow),
    };
    const target = `${config.jobDir}/results/${job.jobId}.json`;
    this.writeAtomic(target, JSON.stringify(result));
    fs.unlinkSync(path);
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

  private writeAtomic(path: string, text: string): void {
    const temporary = `${path}.tmp`;
    this.writeText(temporary, text);
    fs.renameSync(temporary, path);
  }
}
