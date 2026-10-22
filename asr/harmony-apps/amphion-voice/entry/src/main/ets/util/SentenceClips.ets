import { fileIo as fs } from '@kit.CoreFileKit';
import hilog from '@ohos.hilog';

const SAMPLE_RATE = 16000;
// Audio kept in memory for slicing; finals arrive within seconds of the speech, so this is ample.
const KEEP_SAMPLES = SAMPLE_RATE * 180;
const LEAD_IN_SAMPLES = Math.round(SAMPLE_RATE * 0.8);
const FRAME = 320;
const SILENCE_RMS = 32768 * Math.pow(10, -45 / 20);
const EDGE_MARGIN = Math.round(SAMPLE_RATE * 0.2);

/**
 * Keeps the audio written to the current session and cuts one clip per recognized sentence.
 * Offsets are in samples since the session started, the same clock the recognizers use.
 */
export class SentenceClips {
  private readonly dir: string;
  private chunks: Int16Array[] = [];
  private firstSample: number = 0;      // session offset of chunks[0][0]
  private total: number = 0;            // samples received this session
  private sentenceStart: number = -1;   // where the sentence currently being heard began
  private lastEnd: number = 0;

  constructor(filesDir: string) {
    this.dir = `${filesDir}/clips`;
    if (!fs.accessSync(this.dir)) fs.mkdirSync(this.dir, true);
  }

  begin(): void {
    this.chunks = [];
    this.firstSample = 0;
    this.total = 0;
    this.sentenceStart = -1;
    this.lastEnd = 0;
  }

  append(pcm: Int16Array): void {
    this.chunks.push(pcm.slice(0));
    this.total += pcm.length;
    while (this.chunks.length > 1 && this.total - this.firstSample - this.chunks[0].length > KEEP_SAMPLES) {
      this.firstSample += this.chunks[0].length;
      this.chunks.shift();
    }
  }

  /** First sign of a new sentence (its first partial): remember where it started. */
  noteSpeech(): void {
    if (this.sentenceStart < 0) this.sentenceStart = Math.max(this.lastEnd, this.total - LEAD_IN_SAMPLES);
  }

  /** Takes the current sentence's audio. Exact engine offsets win; otherwise our own clock is used. */
  take(startSample?: number, endSample?: number): Int16Array {
    const exact = startSample !== undefined && endSample !== undefined && endSample > startSample;
    const start = exact ? (startSample as number) : (this.sentenceStart >= 0 ? this.sentenceStart :
      Math.max(this.lastEnd, this.total - SAMPLE_RATE * 10));
    const end = exact ? Math.min(endSample as number, this.total) : this.total;
    this.lastEnd = end;
    this.sentenceStart = -1;
    return SentenceClips.trimSilence(this.slice(start, end));
  }

  /** Skips a withdrawn span (another speaker) so it never leaks into the next sentence's clip. */
  discardCurrent(): void {
    this.lastEnd = this.total;
    this.sentenceStart = -1;
  }

  save(id: number, pcm: Int16Array): string {
    if (pcm.length === 0) return '';
    const path = `${this.dir}/${id}.pcm`;
    try {
      const file = fs.openSync(path, fs.OpenMode.CREATE | fs.OpenMode.TRUNC | fs.OpenMode.WRITE_ONLY);
      const bytes = new ArrayBuffer(pcm.length * 2);
      new Int16Array(bytes).set(pcm);
      fs.writeSync(file.fd, bytes);
      fs.closeSync(file);
      return path;
    } catch (e) {
      hilog.warn(0x0000, 'AmphionClips', 'save failed: %{public}s', `${e}`);
      return '';
    }
  }

  static read(path: string): Int16Array {
    try {
      const size = fs.statSync(path).size;
      const bytes = new ArrayBuffer(size);
      const file = fs.openSync(path, fs.OpenMode.READ_ONLY);
      fs.readSync(file.fd, bytes);
      fs.closeSync(file);
      return new Int16Array(bytes);
    } catch (_e) {
      return new Int16Array(0);
    }
  }

  clearAll(): void {
    try {
      fs.listFileSync(this.dir).forEach((name: string): void => fs.unlinkSync(`${this.dir}/${name}`));
    } catch (_e) {
      // nothing to clear
    }
  }

  private slice(start: number, end: number): Int16Array {
    const from = Math.max(start, this.firstSample);
    const to = Math.min(end, this.total);
    if (to <= from) return new Int16Array(0);
    const out = new Int16Array(to - from);
    let offset = this.firstSample;
    let written = 0;
    for (const chunk of this.chunks) {
      const chunkEnd = offset + chunk.length;
      if (chunkEnd > from && offset < to) {
        const a = Math.max(from, offset) - offset;
        const b = Math.min(to, chunkEnd) - offset;
        out.set(chunk.subarray(a, b), written);
        written += b - a;
      }
      offset = chunkEnd;
      if (offset >= to) break;
    }
    return out;
  }

  /** Drops leading/trailing silence, keeping a short margin so words are not clipped. */
  private static trimSilence(pcm: Int16Array): Int16Array {
    const frames = Math.floor(pcm.length / FRAME);
    const loud = (i: number): boolean => {
      let sum = 0;
      for (let k = i * FRAME; k < (i + 1) * FRAME; k++) sum += pcm[k] * pcm[k];
      return Math.sqrt(sum / FRAME) > SILENCE_RMS;
    };
    let first = 0;
    while (first < frames && !loud(first)) first++;
    let last = frames - 1;
    while (last > first && !loud(last)) last--;
    if (first >= frames) return pcm;
    const a = Math.max(0, first * FRAME - EDGE_MARGIN);
    const b = Math.min(pcm.length, (last + 1) * FRAME + EDGE_MARGIN);
    return pcm.slice(a, b);
  }
}
