import { fileIo as fs } from '@kit.CoreFileKit';
import { WavIo } from './WavIo';

/** Stores voiceprint enrollment WAV samples under a single directory (one file per recording). */
export class EnrollSampleStore {
  private dir: string;

  constructor(dir: string) {
    this.dir = dir;
    EnrollSampleStore.ensureDir(dir);
  }

  listSamples(): string[] {
    if (!fs.accessSync(this.dir)) return [];
    try {
      const names = fs.listFileSync(this.dir).filter((n: string): boolean => n.endsWith('.wav'));
      names.sort();
      return names.map((n: string): string => `${this.dir}/${n}`);
    } catch (e) {
      return [];
    }
  }

  addSample(pcm: Int16Array): string {
    const path = `${this.dir}/sample_${Date.now()}.wav`;
    WavIo.write(path, pcm);
    return path;
  }

  deleteSample(path: string): boolean {
    try {
      fs.unlinkSync(path);
      return true;
    } catch (e) {
      return false;
    }
  }

  readPcm(path: string): Int16Array {
    return WavIo.readPcm(path);
  }

  fileSize(path: string): number {
    try {
      return fs.statSync(path).size;
    } catch (e) {
      return 0;
    }
  }

  private static ensureDir(dir: string): void {
    if (fs.accessSync(dir)) return;
    const idx = dir.lastIndexOf('/');
    if (idx > 0) EnrollSampleStore.ensureDir(dir.substring(0, idx));
    if (!fs.accessSync(dir)) fs.mkdirSync(dir);
  }
}
