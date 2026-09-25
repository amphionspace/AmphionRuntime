import {
  loadCommunityDiarization, processCommunityDiarization,
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
}

export class CommunityDiarizationInference {
  private handle?: number;
  private closed: boolean = false;

  async load(context: Context): Promise<void> {
    if (this.closed) throw new Error('Community inference is closed');
    const assets = context.resourceManager;
    const segmentation = await assets.getRawFileContent('amphion-dingqiao/pyannote-segmentation-3.0.onnx');
    const embedding = await assets.getRawFileContent('amphion-dingqiao/community-wespeaker-masked.fp32.onnx');
    const features = await assets.getRawFileContent('amphion-dingqiao/community-feature.f32');
    const plda = await assets.getRawFileContent('amphion-dingqiao/community-plda.f64');
    const handle = await loadCommunityDiarization(segmentation, embedding, features, plda);
    if (this.closed) { closeCommunityDiarization(handle); return; }
    this.handle = handle;
  }

  async process(samples: Float32Array): Promise<CommunityDiarizationWindow> {
    if (this.closed || this.handle === undefined) throw new Error('Community model is not loaded');
    return processCommunityDiarization(this.handle, samples);
  }

  async cluster(segments: Float32Array, embeddings: Float32Array,
    maxSpeakers: number): Promise<CommunityDiarizationCluster> {
    if (this.closed || this.handle === undefined) throw new Error('Community model is not loaded');
    const result = await clusterCommunityDiarization(this.handle, segments, embeddings, maxSpeakers);
    return JSON.parse(result) as CommunityDiarizationCluster;
  }

  close(): void {
    this.closed = true;
    if (this.handle !== undefined) closeCommunityDiarization(this.handle);
    this.handle = undefined;
  }
}

export { CommunityDiarizationWindow };
