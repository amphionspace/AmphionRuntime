export const nativeVersion: () => string;
export const probe: () => string;

export interface TargetSpeakerEnhancementNativeResult {
  samples: Float32Array;
  speakerSimilarities: Float32Array;
  selectedStream: number;
  durationMs: number;
}

export type TargetSpeakerEnhancerHandle = object;

export const loadTargetSpeakerEnhancementModel: (model: Uint8Array) => void;
export const isTargetSpeakerEnhancementModelLoaded: () => boolean;
export const unloadTargetSpeakerEnhancementModel: () => void;
export const createTargetSpeakerEnhancer: (
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
