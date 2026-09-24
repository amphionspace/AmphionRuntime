export const nativeVersion: () => string;
export const probe: () => string;

export type AgcHandle = object;
export const createAgc: (sampleRate: number) => AgcHandle;
export const processAgc: (handle: AgcHandle, samples: Float32Array) => Float32Array;
export const closeAgc: (handle: AgcHandle) => void;

export interface LacPersonSpan {
  start: number;
  end: number;
}
export type LacPersonNerHandle = object;
export const createLacPersonNer: (
  modelPath: string,
  transitionsPath: string,
  wordPath: string,
  tagPath: string,
  q2bPath: string
) => LacPersonNerHandle;
export const findLacPersonSpans: (
  handle: LacPersonNerHandle,
  text: string
) => LacPersonSpan[];
export const closeLacPersonNer: (handle: LacPersonNerHandle) => void;

export interface SpeakerTurnSegmentationSegment {
  startSample: number;
  endSample: number;
  speaker: number;
  /** Bit mask of active local channels; more than one bit means overlap. */
  speakerMask: number;
  /** Inclusive Community-1 frame index in [0, 589). */
  startFrame: number;
  /** Exclusive Community-1 frame index in (0, 589]. */
  endFrame: number;
}
export const loadSpeakerTurnSegmentationModelAsync: (model: Uint8Array) => Promise<void>;
export const isSpeakerTurnSegmentationModelLoaded: () => boolean;
export const unloadSpeakerTurnSegmentationModel: () => void;
export const processSpeakerTurnSegmentation: (
  samples: Float32Array
) => SpeakerTurnSegmentationSegment[];
export const processSpeakerTurnSegmentationAsync: (
  samples: Float32Array
) => Promise<SpeakerTurnSegmentationSegment[]>;

export interface Community1ClusterResult {
  hardClusters: number[];
  speakerCount: number;
  constraintViolated: boolean;
}
export const loadCommunity1Plda: (parameters: Uint8Array) => void;
export const clusterCommunity1Async: (
  embeddings: Float32Array,
  frameMasks: Int32Array,
  numChunks: number,
  minSpeakers: number,
  maxSpeakers: number
) => Promise<Community1ClusterResult>;

export interface TargetSpeakerEnhancementNativeResult {
  samples: Float32Array;
  speakerSimilarities: Float32Array;
  selectedStream: number;
  durationMs: number;
}

export type TargetSpeakerEnhancerHandle = object;

export const createTargetSpeakerEnhancer: (
  separatorModel: Uint8Array,
  speakerModel: string,
  resourceManager: object,
  targetEmbedding: Float32Array,
  threshold?: number
) => TargetSpeakerEnhancerHandle;
export const processTargetSpeakerChunk: (
  handle: TargetSpeakerEnhancerHandle,
  samples: Float32Array
) => Promise<TargetSpeakerEnhancementNativeResult>;
export const closeTargetSpeakerEnhancer: (handle: TargetSpeakerEnhancerHandle) => void;
