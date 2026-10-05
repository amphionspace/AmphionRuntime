import {
  loadCommunityDiarizationResources, processCommunityDiarization, processCommunityDiarizationBatch,
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
  frameHard: number[];
  trainingRunIndices: number[];
  capacityRms: number[];
  retainedClusters: number[];
}

export class CommunityDiarizationInference {
  private handle?: number;
  private closed: boolean = false;
  private readonly lanes: number;

  /**
   * lanes == 0 keeps one window per call on a four-thread encoder pool. lanes > 0
   * lets processBatch run up to `lanes` windows at once on single-threaded
   * encoders and model-owned low-priority workers; the outputs are identical.
   */
  constructor(lanes: number = 0) {
    if (!Number.isInteger(lanes) || lanes < 0 || lanes > 4) throw new Error('lanes must be an integer in [0, 4]');
    this.lanes = lanes;
  }

  async load(context: Context): Promise<void> {
    if (this.closed) throw new Error('Community inference is closed');
    const handle = this.lanes > 0 ?
      await loadCommunityDiarizationResources(context.resourceManager, this.lanes) :
      await loadCommunityDiarizationResources(context.resourceManager);
    if (this.closed) { closeCommunityDiarization(handle); return; }
    this.handle = handle;
  }

  async process(samples: Float32Array): Promise<CommunityDiarizationWindow> {
    if (this.closed || this.handle === undefined) throw new Error('Community model is not loaded');
    return processCommunityDiarization(this.handle, samples);
  }

  /** Results keep the input order; at most max(lanes, 1) windows per call. */
  async processBatch(samples: Float32Array[]): Promise<CommunityDiarizationWindow[]> {
    if (this.closed || this.handle === undefined) throw new Error('Community model is not loaded');
    return processCommunityDiarizationBatch(this.handle, samples);
  }

  async cluster(segments: Float32Array, embeddings: Float32Array, runEmbeddings: Float32Array,
    runRanges: Float32Array, maxSpeakers: number, windowStartSamples: Float64Array,
    beginSample: number, runRms: Float32Array): Promise<CommunityDiarizationCluster> {
    if (this.closed || this.handle === undefined) throw new Error('Community model is not loaded');
    const result = await clusterCommunityDiarization(this.handle, segments, embeddings, runEmbeddings,
      runRanges, maxSpeakers, windowStartSamples, beginSample, runRms);
    return JSON.parse(result) as CommunityDiarizationCluster;
  }

  close(): void {
    this.closed = true;
    if (this.handle !== undefined) closeCommunityDiarization(this.handle);
    this.handle = undefined;
  }
}

export { CommunityDiarizationWindow };
