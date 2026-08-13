export const nativeVersion: () => string;
export const probe: () => string;

export type AgcHandle = object;
export const createAgc: (sampleRate: number) => AgcHandle;
export const processAgc: (handle: AgcHandle, samples: Float32Array) => Float32Array;
export const closeAgc: (handle: AgcHandle) => void;

export interface SpeakerTurnSegmentationSegment {
  startSample: number;
  endSample: number;
  speaker: number;
}
export const loadSpeakerTurnSegmentationModelAsync: (model: Uint8Array) => Promise<void>;
export const isSpeakerTurnSegmentationModelLoaded: () => boolean;
export const unloadSpeakerTurnSegmentationModel: () => void;
export const processSpeakerTurnSegmentation: (
  samples: Float32Array
) => SpeakerTurnSegmentationSegment[];

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
