import {
  loadCommunityDiarizationResources, processCommunityDiarization,
  clusterCommunityDiarization, closeCommunityDiarization, CommunityDiarizationWindow
} from 'libamphion_asr.so';

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
  static readonly DEFAULT_THREADS: number = 4;
  static readonly MAX_THREADS: number = 8;

  private handle?: number;
  private closed: boolean = false;
  private readonly encoderThreads: number;

  constructor(encoderThreads: number = CommunityDiarizationInference.DEFAULT_THREADS) {
    if (!Number.isInteger(encoderThreads) || encoderThreads < 1 ||
      encoderThreads > CommunityDiarizationInference.MAX_THREADS) {
      throw new Error('Community encoder threads must be an integer in [1, 8]');
    }
    this.encoderThreads = encoderThreads;
  }

  async load(context: Context): Promise<void> {
    if (this.closed) throw new Error('Community inference is closed');
    const handle = await loadCommunityDiarizationResources(context.resourceManager, this.encoderThreads);
    if (this.closed) { closeCommunityDiarization(handle); return; }
    this.handle = handle;
  }

  async process(samples: Float32Array): Promise<CommunityDiarizationWindow> {
    if (this.closed || this.handle === undefined) throw new Error('Community model is not loaded');
    return processCommunityDiarization(this.handle, samples);
  }

  async cluster(segments: Float32Array, embeddings: Float32Array, runEmbeddings: Float32Array,
    runRanges: Float32Array, maxSpeakers: number, windowStartSamples: Float64Array,
    beginSample: number, runRms: Float32Array,
    includeFrameHard: boolean = true): Promise<CommunityDiarizationCluster> {
    if (this.closed || this.handle === undefined) throw new Error('Community model is not loaded');
    const result = await clusterCommunityDiarization(this.handle, segments, embeddings, runEmbeddings,
      runRanges, maxSpeakers, windowStartSamples, beginSample, runRms, includeFrameHard);
    return JSON.parse(result) as CommunityDiarizationCluster;
  }

  close(): void {
    this.closed = true;
    if (this.handle !== undefined) closeCommunityDiarization(this.handle);
    this.handle = undefined;
  }
}

export { CommunityDiarizationWindow };
