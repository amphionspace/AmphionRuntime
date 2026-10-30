import {
  loadSortformerDiarizationResources, feedSortformerDiarization, closeSortformerDiarization
} from 'libamphion_asr.so';

/** One inference pass reported by the engine; frame indexes are absolute 10 ms frames. */
export class SortformerDiarizationEvent {
  /** 'final' advances the speaker cache; 'preview' is a cache-preserving look at the current chunk. */
  kind: string = 'final';
  beginFrame: number = 0;
  frames: number = 0;
  inferenceMs: number = 0;
  /** Per slot (4), contiguous active spans as [beginFrame, endFrame) pairs. */
  runs: number[][][] = [];
}

export class SortformerDiarizationFeedResult {
  events: SortformerDiarizationEvent[] = [];
  melFrames: number = 0;
  samples: number = 0;
}

/** Mel frames per preview pass for a refresh period in milliseconds; 0 disables previews. */
export function sortformerPreviewFrames(previewMs: number): number {
  if (!Number.isFinite(previewMs) || previewMs <= 0) return 0;
  // The pre-encoder consumes 8 mel frames (80 ms) per encoder frame.
  return Math.max(8, Math.min(984, Math.floor(previewMs / 80) * 8));
}

/**
 * Session-owned Sortformer diarization engine. Audio is fed in order and the
 * native side keeps the whole streaming state; this class only moves bytes.
 * threads is the encoder's intra-op count; recognizerQos/roleQos place the
 * owned worker exactly as the role workers were placed before.
 */
export class SortformerDiarizationInference {
  private handle?: number;
  private closed: boolean = false;
  private readonly threads: number;
  private readonly recognizerQos: string;
  private readonly roleQos: string;
  private readonly previewFrames: number;

  constructor(threads: number = 2, recognizerQos: string = 'default', roleQos: string = 'inherit',
    previewMs: number = 5000) {
    if (!Number.isInteger(threads) || threads < 1 || threads > 8) throw new Error('threads must be an integer in [1, 8]');
    if (roleQos !== 'inherit' && roleQos !== 'background' && roleQos !== 'utility' && roleQos !== 'default') {
      throw new Error('roleQos must be inherit, background, utility, or default');
    }
    this.threads = threads;
    this.recognizerQos = recognizerQos;
    this.roleQos = roleQos;
    this.previewFrames = sortformerPreviewFrames(previewMs);
  }

  async load(context: Context): Promise<void> {
    if (this.closed) throw new Error('Sortformer inference is closed');
    const handle = await loadSortformerDiarizationResources(context.resourceManager, this.threads,
      this.recognizerQos, this.roleQos, this.previewFrames);
    if (this.closed) { closeSortformerDiarization(handle); return; }
    this.handle = handle;
  }

  async feed(samples: Float32Array, flush: boolean): Promise<SortformerDiarizationFeedResult> {
    if (this.closed || this.handle === undefined) throw new Error('Sortformer model is not loaded');
    const result = await feedSortformerDiarization(this.handle, samples, flush);
    return JSON.parse(result) as SortformerDiarizationFeedResult;
  }

  close(): void {
    this.closed = true;
    if (this.handle !== undefined) closeSortformerDiarization(this.handle);
    this.handle = undefined;
  }
}
