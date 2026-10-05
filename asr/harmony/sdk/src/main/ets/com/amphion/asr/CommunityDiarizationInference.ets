import {
  loadCommunityDiarizationResources, processCommunityDiarization, normalizeCommunityPcm16Window,
  clusterCommunityDiarization, cancelCommunityDiarization, closeCommunityDiarization, CommunityDiarizationWindow
} from 'libamphion_asr.so';
import { AsrSchedulingConfig, asrSchedulingTokens } from './AsrSchedulingConfig';

export interface CommunityDiarizationCluster {
  speakerCount: number;
  hard: number[];
  trainingIndices: number[];
  ahc: number[];
  priors: number[];
  turns: number[][];
  scores: Array<Array<number | null>>;
  centroids: Array<Array<number | null>>;
  posteriors: number[][];
  usedKMeans: boolean;
  /** Emitted only when the caller asked for diagnostic frame labels. */
  frameHard?: number[];
  trainingRunIndices: number[];
  capacityRms: number[];
  retainedClusters: number[];
}

export class CommunityDiarizationInference {
  /** Encoder worker budget used when the caller does not state one. */
  static readonly DEFAULT_THREADS: number = 2;
  static readonly MAX_THREADS: number = 8;

  /** Normalize one PCM16 view and pad its missing right tail to the model window. */
  static normalizePcm16Window(samples: Int16Array): Float32Array {
    return normalizeCommunityPcm16Window(samples);
  }

  private handle?: number;
  private closed: boolean = false;
  private cancelled: boolean = false;
  private readonly encoderThreads: number;
  private readonly scheduling: string;

  constructor(encoderThreads: number = CommunityDiarizationInference.DEFAULT_THREADS,
    scheduling?: AsrSchedulingConfig) {
    if (!Number.isInteger(encoderThreads) || encoderThreads < 1 ||
      encoderThreads > CommunityDiarizationInference.MAX_THREADS) {
      throw new Error('Community encoder threads must be an integer in [1, 8]');
    }
    this.encoderThreads = encoderThreads;
    this.scheduling = asrSchedulingTokens(scheduling);
  }

  async load(context: Context): Promise<void> {
    if (this.closed || this.cancelled) throw new Error('Community inference is closed');
    const handle = await loadCommunityDiarizationResources(context.resourceManager,
      this.encoderThreads, this.scheduling);
    if (this.closed || this.cancelled) {
      if (this.cancelled) cancelCommunityDiarization(handle);
      closeCommunityDiarization(handle);
      return;
    }
    this.handle = handle;
  }

  async process(samples: Float32Array, windowStartSample: number = 0,
    cacheFbank: boolean = false): Promise<CommunityDiarizationWindow> {
    if (this.closed || this.cancelled || this.handle === undefined) throw new Error('Community model is not loaded');
    return processCommunityDiarization(this.handle, samples, windowStartSample, cacheFbank);
  }

  async cluster(segments: Float32Array, embeddings: Float32Array, runEmbeddings: Float32Array,
    runRanges: Float32Array, maxSpeakers: number, windowStartSamples: Float64Array,
    beginSample: number, runRms: Float32Array,
    includeFrameHard: boolean = true): Promise<CommunityDiarizationCluster> {
    if (this.closed || this.cancelled || this.handle === undefined) throw new Error('Community model is not loaded');
    const result = await clusterCommunityDiarization(this.handle, segments, embeddings, runEmbeddings,
      runRanges, maxSpeakers, windowStartSamples, beginSample, runRms, includeFrameHard);
    return JSON.parse(result) as CommunityDiarizationCluster;
  }

  cancel(): void {
    if (this.cancelled) return;
    this.cancelled = true;
    if (this.handle !== undefined) cancelCommunityDiarization(this.handle);
  }

  close(): void {
    this.closed = true;
    if (this.handle !== undefined) closeCommunityDiarization(this.handle);
    this.handle = undefined;
  }
}

export { CommunityDiarizationWindow };
