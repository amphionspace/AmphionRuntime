import { fileIo as fs } from '@kit.CoreFileKit';
import hilog from '@ohos.hilog';
import BuildProfile from 'BuildProfile';
import { WavIo } from './WavIo';

const TAG = 'AmphionDebug';
const KEEP_SESSIONS = 5;
const FRAME_SAMPLES = 320;

export class TimelineEntry {
  t: number = 0;
  live: string = '';
  lines: number = 0;
  event: string = '';
}

/**
 * Debug-build-only acceptance support. Release builds never construct it (see enabled()).
 * - keeps the microphone input of the last few sessions as WAV so a real utterance can be replayed;
 * - replays a WAV through the normal session pipeline at real-time pace;
 * - records what the transcript shows frame by frame, so smoothness can be measured offline.
 */
export class DebugSession {
  private dir: string;
  private chunks: Int16Array[] = [];
  private timeline: TimelineEntry[] = [];
  private startedAt: number = 0;

  static enabled(): boolean {
    return BuildProfile.DEBUG;
  }

  constructor(filesDir: string) {
    this.dir = `${filesDir}/debug`;
    if (!fs.accessSync(this.dir)) fs.mkdirSync(this.dir, true);
  }

  begin(): void {
    this.chunks = [];
    this.timeline = [];
    this.startedAt = Date.now();
  }

  capture(pcm: Int16Array): void {
    this.chunks.push(pcm.slice(0));
  }

  mark(live: string, lines: number, event: string = ''): void {
    const entry = new TimelineEntry();
    entry.t = Date.now() - this.startedAt;
    entry.live = live;
    entry.lines = lines;
    entry.event = event;
    this.timeline.push(entry);
  }

  /** Writes session-<stamp>.wav (only for microphone sessions) and the UI timeline; prunes old ones. */
  end(saveAudio: boolean, label: string): void {
    const stamp = `${Date.now()}`;
    try {
      if (saveAudio && this.chunks.length > 0) {
        let total = 0;
        this.chunks.forEach((c: Int16Array): void => { total += c.length; });
        const pcm = new Int16Array(total);
        let off = 0;
        this.chunks.forEach((c: Int16Array): void => { pcm.set(c, off); off += c.length; });
        WavIo.write(`${this.dir}/session-${stamp}.wav`, pcm);
      }
      const file = fs.openSync(`${this.dir}/timeline-${label}-${stamp}.json`,
        fs.OpenMode.CREATE | fs.OpenMode.TRUNC | fs.OpenMode.WRITE_ONLY);
      fs.writeSync(file.fd, JSON.stringify(this.timeline));
      fs.closeSync(file);
      this.prune('session-', '.wav', KEEP_SESSIONS);
      this.prune('timeline-', '.json', KEEP_SESSIONS * 4);
    } catch (e) {
      hilog.warn(0x0000, TAG, 'debug save failed: %{public}s', `${e}`);
    }
    this.chunks = [];
  }

  private prune(prefix: string, suffix: string, keep: number): void {
    // Oldest first by the trailing timestamp, not by name (timeline-cloud-* would sort before local).
    const stamp = (n: string): number => Number(n.substring(n.lastIndexOf('-') + 1, n.length - suffix.length));
    const names = fs.listFileSync(this.dir)
      .filter((n: string): boolean => n.startsWith(prefix) && n.endsWith(suffix))
      .sort((a: string, b: string): number => stamp(a) - stamp(b));
    for (let i = 0; i < names.length - keep; i++) fs.unlinkSync(`${this.dir}/${names[i]}`);
  }

  /** Feeds a 16 kHz mono WAV in 20 ms frames at real-time pace. Returns a stop function. */
  static replay(path: string, onPcm: (pcm: Int16Array) => void, onEnd: () => void): () => void {
    let pcm: Int16Array;
    try {
      pcm = WavIo.readPcm(path);
    } catch (e) {
      hilog.error(0x0000, TAG, 'replay read failed: %{public}s', `${e}`);
      setTimeout(onEnd, 0);
      return (): void => {};
    }
    const start = Date.now();
    let offset = 0;
    let stopped = false;
    const pump = (): void => {
      if (stopped) return;
      const due = Math.floor((Date.now() - start) / 20) * FRAME_SAMPLES;
      while (offset < pcm.length && offset <= due) {
        onPcm(pcm.slice(offset, Math.min(offset + FRAME_SAMPLES, pcm.length)));
        offset += FRAME_SAMPLES;
      }
      if (offset >= pcm.length) {
        stopped = true;
        onEnd();
        return;
      }
      setTimeout(pump, 10);
    };
    pump();
    return (): void => { stopped = true; };
  }
}
