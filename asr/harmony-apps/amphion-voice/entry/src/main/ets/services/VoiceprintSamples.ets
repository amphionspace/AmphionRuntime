import { fileIo as fs } from '@kit.CoreFileKit';
import { WavIo } from '../util/WavIo';

export type SampleSlot = 'far' | 'mid' | 'near';

export const SAMPLE_SLOTS: SampleSlot[] = ['far', 'mid', 'near'];
/** One recording satisfies both engines: the cloud wants 5–8 s per distance, on-device accepts 3–8 s. */
export const SAMPLE_MIN_SEC = 5;
export const SAMPLE_MAX_SEC = 8;
/** A sample needs this much speech above VOICED_DBFS, summed over 20 ms frames. */
export const VOICED_MIN_SEC = 2;
const VOICED_DBFS = -40;

/**
 * Seconds of 20 ms frames whose RMS is above VOICED_DBFS. A real-device test registered three
 * recordings of -50 dBFS room noise; the server rejects those (0 s of speech), the device did not.
 */
export function voicedSeconds(pcm: Int16Array): number {
  const frame = 320;
  const threshold = 32768 * Math.pow(10, VOICED_DBFS / 20);
  let voiced = 0;
  for (let start = 0; start + frame <= pcm.length; start += frame) {
    let sum = 0;
    for (let i = start; i < start + frame; i++) sum += pcm[i] * pcm[i];
    if (Math.sqrt(sum / frame) >= threshold) voiced++;
  }
  return voiced * frame / 16000;
}

export class SampleInfo {
  slot: SampleSlot = 'far';
  path: string = '';
  durationSec: number = 0;
  present: boolean = false;
  /** Enough speech in the recording; false for silence or room noise. */
  voiced: boolean = false;
  valid: boolean = false;
}

/**
 * The three enrollment recordings (far / mid / near). They are kept after registration so the
 * same audio can re-register either engine without asking the user to record again.
 */
export class VoiceprintSamples {
  private readonly dir: string;

  /** Recordings of one profile live in voiceprint/<profileId>/. */
  constructor(filesDir: string, profileId: string) {
    const root = `${filesDir}/voiceprint`;
    this.dir = `${root}/${profileId.length > 0 ? profileId : 'unnamed'}`;
    if (!fs.accessSync(this.dir)) fs.mkdirSync(this.dir, true);
    // Before profiles existed the three files sat directly in voiceprint/; they belong to the
    // migrated 'legacy' profile.
    if (profileId === 'legacy') {
      SAMPLE_SLOTS.forEach((slot: SampleSlot): void => {
        const old = `${root}/${slot}.wav`;
        try {
          if (fs.accessSync(old) && !fs.accessSync(this.pathOf(slot))) fs.moveFileSync(old, this.pathOf(slot));
        } catch (_e) {
          // keep the old file if it cannot be moved
        }
      });
    }
  }

  /** Deletes the recordings and the folder of one profile. */
  static removeProfile(filesDir: string, profileId: string): void {
    const dir = `${filesDir}/voiceprint/${profileId}`;
    try {
      if (fs.accessSync(dir)) fs.rmdirSync(dir);
    } catch (_e) {
      // nothing to remove
    }
  }

  pathOf(slot: SampleSlot): string {
    return `${this.dir}/${slot}.wav`;
  }

  info(slot: SampleSlot): SampleInfo {
    const info = new SampleInfo();
    info.slot = slot;
    info.path = this.pathOf(slot);
    try {
      if (fs.accessSync(info.path)) {
        info.present = true;
        info.durationSec = WavIo.durationSecFromBytes(fs.statSync(info.path).size);
        info.voiced = voicedSeconds(WavIo.readPcm(info.path)) >= VOICED_MIN_SEC;
        info.valid = info.voiced && info.durationSec >= SAMPLE_MIN_SEC && info.durationSec <= SAMPLE_MAX_SEC + 0.1;
      }
    } catch (_e) {
      info.present = false;
    }
    return info;
  }

  all(): SampleInfo[] {
    return SAMPLE_SLOTS.map((slot: SampleSlot): SampleInfo => this.info(slot));
  }

  complete(): boolean {
    return this.all().every((item: SampleInfo): boolean => item.valid);
  }

  save(slot: SampleSlot, pcm: Int16Array): void {
    WavIo.write(this.pathOf(slot), pcm);
  }

  read(slot: SampleSlot): Int16Array {
    return WavIo.readPcm(this.pathOf(slot));
  }

  remove(slot: SampleSlot): void {
    try {
      fs.unlinkSync(this.pathOf(slot));
    } catch (_e) {
      // already absent
    }
  }

  clear(): void {
    SAMPLE_SLOTS.forEach((slot: SampleSlot): void => this.remove(slot));
  }
}

export function slotLabel(slot: SampleSlot): string {
  if (slot === 'far') return '远距离';
  if (slot === 'mid') return '常规距离';
  return '近距离';
}

export function slotHint(slot: SampleSlot): string {
  if (slot === 'far') return '一臂距离，正常音量';
  if (slot === 'mid') return '平时握持手机的距离';
  return '贴近麦克风，轻声说';
}
