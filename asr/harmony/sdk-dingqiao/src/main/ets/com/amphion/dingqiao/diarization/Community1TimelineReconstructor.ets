import {
  SpeakerDiarizationCommunityClusterResult,
  SpeakerDiarizationWindowResult
} from 'amphion_asr';
import { DiarizationLocalWindowResult } from './SpeakerDiarizationLocalClient';
import { SpeakerTimelineTurn } from './SpeakerDiarizationTranscriptState';

const SAMPLE_RATE: number = 16000;
const WINDOW_SAMPLES: number = 160000;
const FRAME_SHIFT_SAMPLES: number = 270;
const RECEPTIVE_FIELD_SAMPLES: number = 991;
const FRAMES_PER_CHUNK: number = 589;
const LOCAL_SPEAKERS: number = 3;

export class Community1TimelineResult {
  speakerCount: number = 0;
  speakerTurns: SpeakerTimelineTurn[] = [];
  exclusiveSpeakerTurns: SpeakerTimelineTurn[] = [];
}

/** Community-1 overlap-add reconstruction and exclusive timeline generation. */
export class Community1TimelineReconstructor {
  reconstruct(windows: DiarizationLocalWindowResult[], clustering: SpeakerDiarizationCommunityClusterResult,
    audioSamples: number, maxSpeakers?: number): Community1TimelineResult {
    const result = new Community1TimelineResult();
    if (windows.length === 0 || clustering.speakerCount <= 0) return result;
    const ordered = windows.slice().sort((left, right): number =>
      left.windowStartSample - right.windowStartSample);
    const finalChunkStart = ordered[ordered.length - 1].windowStartSample;
    const globalFrames = Math.max(1,
      Math.round((finalChunkStart + WINDOW_SAMPLES) / FRAME_SHIFT_SAMPLES) + 1);
    const countSums = new Float32Array(globalFrames);
    const countWeights = new Uint16Array(globalFrames);
    let speakerCount = clustering.speakerCount;
    const activations = new Float32Array(globalFrames * speakerCount);

    for (let chunk = 0; chunk < ordered.length; chunk++) {
      const window: SpeakerDiarizationWindowResult = ordered[chunk].result;
      const offset = Math.round(ordered[chunk].windowStartSample / FRAME_SHIFT_SAMPLES);
      for (let frame = 0; frame < FRAMES_PER_CHUNK; frame++) {
        const targetFrame = offset + frame;
        if (targetFrame < 0 || targetFrame >= globalFrames) continue;
        const mask = window.frameMasks[frame] ?? 0;
        countSums[targetFrame] += this.bitCount(mask);
        countWeights[targetFrame] += 1;
        for (let local = 0; local < LOCAL_SPEAKERS; local++) {
          if ((mask & (1 << local)) === 0) continue;
          const cluster = clustering.hardClusters[chunk * LOCAL_SPEAKERS + local] ?? -2;
          if (cluster >= 0 && cluster < speakerCount) {
            activations[targetFrame * speakerCount + cluster] += 1;
          }
        }
      }
    }

    const counts = new Uint8Array(globalFrames);
    let maximumCount = 0;
    for (let frame = 0; frame < globalFrames; frame++) {
      const count = countWeights[frame] === 0 ? 0 :
        Math.round(countSums[frame] / countWeights[frame]);
      counts[frame] = Math.min(count, maxSpeakers ?? count);
      maximumCount = Math.max(maximumCount, counts[frame]);
    }
    // This mirrors Community-1's zero-column padding when segmentation counts
    // more simultaneous speakers than clustering retained.
    if (maximumCount > speakerCount) {
      const expanded = new Float32Array(globalFrames * maximumCount);
      for (let frame = 0; frame < globalFrames; frame++) {
        for (let speaker = 0; speaker < speakerCount; speaker++) {
          expanded[frame * maximumCount + speaker] =
            activations[frame * speakerCount + speaker];
        }
      }
      speakerCount = maximumCount;
      result.speakerTurns = this.buildTurns(expanded, counts, speakerCount, audioSamples, false);
      result.exclusiveSpeakerTurns = this.buildTurns(expanded, counts, speakerCount, audioSamples, true);
    } else {
      result.speakerTurns = this.buildTurns(activations, counts, speakerCount, audioSamples, false);
      result.exclusiveSpeakerTurns = this.buildTurns(activations, counts, speakerCount, audioSamples, true);
    }
    result.speakerCount = speakerCount;
    return result;
  }

  private buildTurns(activations: Float32Array, counts: Uint8Array, speakerCount: number,
    audioSamples: number, exclusive: boolean): SpeakerTimelineTurn[] {
    const turns: SpeakerTimelineTurn[] = [];
    let active: number[] = [];
    let activeStart = 0;
    for (let frame = 0; frame <= counts.length; frame++) {
      const centerSample = Math.min(audioSamples,
        Math.max(0, Math.round(RECEPTIVE_FIELD_SAMPLES / 2 + frame * FRAME_SHIFT_SAMPLES)));
      const next = frame === counts.length || centerSample >= audioSamples ? [] :
        this.activeSpeakers(activations, frame, speakerCount,
          exclusive ? Math.min(counts[frame], 1) : counts[frame]);
      if (this.sameSpeakers(active, next)) continue;
      if (active.length > 0 && centerSample > activeStart) {
        turns.push({
          beginTime: Math.round(activeStart * 1000 / SAMPLE_RATE),
          endTime: Math.round(centerSample * 1000 / SAMPLE_RATE),
          speakerId: `S${active[0] + 1}`,
          secondarySpeakerIds: active.slice(1).map((speaker: number): string => `S${speaker + 1}`),
          confidence: 1,
          overlap: active.length > 1,
        });
      }
      active = next;
      activeStart = centerSample;
      if (centerSample >= audioSamples) break;
    }
    return turns;
  }

  private activeSpeakers(activations: Float32Array, frame: number,
    speakerCount: number, count: number): number[] {
    if (count <= 0) return [];
    const indexes = new Array<number>(speakerCount);
    for (let speaker = 0; speaker < speakerCount; speaker++) indexes[speaker] = speaker;
    indexes.sort((left: number, right: number): number => {
      const difference = activations[frame * speakerCount + right] -
        activations[frame * speakerCount + left];
      return difference === 0 ? left - right : difference;
    });
    return indexes.slice(0, Math.min(count, speakerCount));
  }

  private bitCount(value: number): number {
    let count = 0;
    for (let bit = 0; bit < LOCAL_SPEAKERS; bit++) {
      if ((value & (1 << bit)) !== 0) count++;
    }
    return count;
  }

  private sameSpeakers(left: number[], right: number[]): boolean {
    if (left.length !== right.length) return false;
    for (let index = 0; index < left.length; index++) {
      if (left[index] !== right[index]) return false;
    }
    return true;
  }
}
