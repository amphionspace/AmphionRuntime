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
export interface CommunityDiarizationWindow {
  segments: Float32Array;
  embeddings: Float32Array;
  runEmbeddings: Float32Array;
  runRanges: Float32Array;
  runRms: Float32Array;
  segmentationMs: number;
  featureMs: number;
  embeddingMs: number;
  /** Encoder Run only; embeddingMs still includes encoding and all pooling. */
  encoderMs: number;
  /** "cpu" or "npu": the backend that produced this window's vectors. */
  encoderBackend: string;
  /** Actual selected NNRt device name, or "cpu" for the ORT encoder. */
  encoderDevice: string;
}
/**
 * encoderBackend: "cpu" (default) keeps the ORT encoder; "npu" requires a
 * Kirin-named NNRt accelerator and the MindIR encoder asset; "auto" can fall back
 * to CPU only if NPU construction fails, never after inference has started.
 */
export function loadCommunityDiarization(segmentation: Uint8Array, encoder: Uint8Array,
  pooling: Uint8Array, features: Uint8Array, plda: Uint8Array, lanes?: number,
  recognizerQos?: string, encoderBackend?: string): Promise<number>;
export function loadCommunityDiarizationResources(resourceManager: Object, lanes?: number,
  recognizerQos?: string, encoderBackend?: string): Promise<number>;
export function processCommunityDiarization(handle: number, pcm: Float32Array): Promise<CommunityDiarizationWindow>;
export function processCommunityDiarizationBatch(handle: number,
  pcm: Float32Array[]): Promise<CommunityDiarizationWindow[]>;
export function clusterCommunityDiarization(handle: number, segments: Float32Array,
  embeddings: Float32Array, runEmbeddings: Float32Array, runRanges: Float32Array,
  maxSpeakers: number, windowStartSamples: Float64Array, beginSample: number,
  runRms: Float32Array): Promise<string>;
export function closeCommunityDiarization(handle: number): void;

