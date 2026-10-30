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
/**
 * Sortformer-66M-4spk streaming speaker diarization. One handle is one
 * session: audio is fed in order, the engine cuts 9.92 s chunks (124 encoder
 * frames) against its speaker cache and reports per-slot speech runs at 10 ms.
 * `previewFrames` > 0 (mel frames, a multiple of 8 below 992) adds one
 * cache-preserving pass over the first part of every chunk, reported as a
 * "preview" event before that chunk's "final" event replaces it. Slots are the
 * model's arrival-ordered identities and stay stable for the session.
 * `threads` is the encoder's intra-op thread count; `recognizerQos` and
 * `roleQos` place the owned worker like the Community chain's role workers.
 */
export function loadSortformerDiarizationResources(resourceManager: Object,
  threads?: number, recognizerQos?: string, roleQos?: string, previewFrames?: number): Promise<number>;
/**
 * Feeds 16 kHz mono PCM in [-1, 1) and resolves a JSON document
 * `{events:[{kind:"final"|"preview",beginFrame,frames,inferenceMs,runs:[[[b,e],...]x4]}],melFrames,samples}`
 * with absolute 10 ms frame indexes. `flush` ends the stream: the tail chunk
 * is inferred without right context and no later feed is accepted.
 */
export function feedSortformerDiarization(handle: number, pcm: Float32Array, flush: boolean): Promise<string>;
export function closeSortformerDiarization(handle: number): void;

/**
 * Diagnostics-only MindSpore Lite backend probe. Builds the MindIR at
 * `modelPath` with `backend` ("cpu", "npu", or an NNRt device-name substring),
 * then runs `iterations` Predict calls on zero-filled inputs and resolves a JSON
 * report of build and Predict timings. Zero inputs make the outputs meaningless:
 * this measures backend acceptance and latency, never accuracy.
 */
export function probeMindSporeModel(modelPath: string, backend?: string,
  iterations?: number): Promise<string>;

export function probeMindSporeChain(modelPaths: string, backend?: string,
  paceMs?: number, durationMs?: number): Promise<string>;

export function probeOrtModel(modelPath: string, threads?: number,
  iterations?: number): Promise<string>;
