import { loadNmnetDiarization, processNmnetDiarization, finishNmnetDiarization,
  closeNmnetDiarization } from 'libamphion_asr.so';

export interface NmnetDiarizationDelta {
  inferenceThroughSample: number;
  rolesCommittedThroughSample: number;
  turns: number[][];
  speakerCount: number;
  segmentationMs: number;
  embeddingMs: number;
  embeddingFeaturesMs?: number;
  embeddingEncoderMs?: number;
  encoderBackend: string;
  historyChunks: number;
  historyCompressed: boolean;
}

/** One native state belongs to exactly one SDK session; callers serialize work. */
export class NmnetDiarizationInference {
  private handle?: number;
  private closed: boolean = false;
  private readonly maxSpeakers: number;
  private readonly roleQos: string;
  constructor(maxSpeakers: number = 0, roleQos: string = 'inherit') {
    this.maxSpeakers = maxSpeakers; this.roleQos = roleQos;
  }
  async load(context: Context): Promise<void> {
    if (this.closed) throw new Error('NMNet inference is closed');
    const handle = await loadNmnetDiarization(context.resourceManager, this.maxSpeakers, this.roleQos);
    if (this.closed) { closeNmnetDiarization(handle); return; }
    this.handle = handle;
  }
  async process(samples: Float32Array, validSamples: number, chunkIndex: number): Promise<NmnetDiarizationDelta> {
    if (this.closed || this.handle === undefined) throw new Error('NMNet model is not loaded');
    return JSON.parse(await processNmnetDiarization(this.handle, samples, validSamples, chunkIndex)) as NmnetDiarizationDelta;
  }
  async finish(): Promise<NmnetDiarizationDelta> {
    if (this.closed || this.handle === undefined) throw new Error('NMNet model is not loaded');
    return JSON.parse(await finishNmnetDiarization(this.handle)) as NmnetDiarizationDelta;
  }
  close(): void {
    this.closed = true;
    if (this.handle !== undefined) closeNmnetDiarization(this.handle);
    this.handle = undefined;
  }
}
