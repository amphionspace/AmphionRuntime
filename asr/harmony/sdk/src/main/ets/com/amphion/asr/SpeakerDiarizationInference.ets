import {
  OnlineStream,
  Samples,
  SpeakerEmbeddingExtractor,
  SpeakerEmbeddingExtractorConfig
} from 'sherpa_onnx';
import {
  processSpeakerTurnSegmentationAsync,
  SpeakerTurnSegmentationSegment
} from 'libamphion_asr.so';
import { AmphionRuntime } from './Runtime';

const SAMPLE_RATE: number = 16000;
const MIN_EMBEDDING_SAMPLES: number = SAMPLE_RATE;
// Retain later clean speech while bounding variable-length model workspace.
const MAX_EMBEDDING_SAMPLES: number = SAMPLE_RATE * 6;

export class SpeakerDiarizationSegment {
  startSample: number = 0;
  endSample: number = 0;
  speaker: number = 0;
  speakerMask: number = 0;
}

export class SpeakerDiarizationEmbedding {
  localSpeaker: number = 0;
  speechSamples: number = 0;
  speechRms: number = 0;
  embedding: number[] = [];
  queryEmbedding?: number[];
}

export class SpeakerDiarizationWindowResult {
  segments: SpeakerDiarizationSegment[] = [];
  embeddings: SpeakerDiarizationEmbedding[] = [];
  inferenceMs: number = 0;
}

/** Session-owned offline diarization executor backed by SDK-bundled models. */
export class SpeakerDiarizationInference {
  private extractor?: SpeakerEmbeddingExtractor;
  private closed: boolean = false;

  async load(context: Context, embeddingModelPath: string): Promise<void> {
    if (this.closed) throw new Error('speaker diarization inference is closed');
    await AmphionRuntime.getOrCreateSpeakerTurnSegmenterAsync(context, embeddingModelPath);
    const config = new SpeakerEmbeddingExtractorConfig();
    config.model = embeddingModelPath;
    config.numThreads = 1;
    config.debug = false;
    this.extractor = await SpeakerEmbeddingExtractor.createAsync(
      config, embeddingModelPath.startsWith('/') ? undefined : context.resourceManager, SAMPLE_RATE);
  }

  async process(samples: Float32Array, queryStartSample: number = 0,
    queryEndSample: number = 0): Promise<SpeakerDiarizationWindowResult> {
    if (this.closed || this.extractor === undefined) {
      throw new Error('speaker diarization inference is not loaded');
    }
    const startedMs = Date.now();
    const nativeSegments = await processSpeakerTurnSegmentationAsync(samples);
    const result = new SpeakerDiarizationWindowResult();
    result.segments = nativeSegments.map(
      (segment: SpeakerTurnSegmentationSegment): SpeakerDiarizationSegment => {
        const converted = new SpeakerDiarizationSegment();
        converted.startSample = segment.startSample;
        converted.endSample = segment.endSample;
        converted.speaker = segment.speaker;
        converted.speakerMask = segment.speakerMask;
        return converted;
      });

    for (let localSpeaker = 0; localSpeaker < 3; localSpeaker++) {
      const channelSamples = this.collectSingleSpeakerSamples(
        samples, nativeSegments, localSpeaker);
      if (channelSamples.length < MIN_EMBEDDING_SAMPLES) continue;
      const embedding = await this.computeEmbedding(channelSamples);
      if (embedding === undefined) continue;
      const value = new SpeakerDiarizationEmbedding();
      value.localSpeaker = localSpeaker;
      value.speechSamples = channelSamples.length;
      let squaredLevel = 0;
      for (const sample of channelSamples) squaredLevel += sample * sample;
      value.speechRms = Math.sqrt(squaredLevel / channelSamples.length);
      value.embedding = Array.from(embedding);
      const querySamples = this.collectQuerySamples(
        samples, nativeSegments, localSpeaker, queryStartSample, queryEndSample);
      if (querySamples.length >= MIN_EMBEDDING_SAMPLES) {
        const query = await this.computeEmbedding(querySamples);
        if (query !== undefined) value.queryEmbedding = Array.from(query);
      }
      result.embeddings.push(value);
    }
    result.inferenceMs = Date.now() - startedMs;
    return result;
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    try { this.extractor?.close(); } catch (_ignored) {}
    this.extractor = undefined;
  }

  private collectSingleSpeakerSamples(samples: Float32Array,
    segments: SpeakerTurnSegmentationSegment[], localSpeaker: number,
    fromSample: number = 0, throughSample: number = samples.length): Float32Array {
    const expectedMask = 1 << localSpeaker;
    const parts: Float32Array[] = [];
    let total = 0;
    for (let i = 0; i < segments.length && total < MAX_EMBEDDING_SAMPLES; i++) {
      const segment = segments[i];
      if (segment.speakerMask !== expectedMask) continue;
      const start = Math.max(0, Math.min(samples.length, Math.max(fromSample, segment.startSample)));
      const end = Math.max(start, Math.min(samples.length, throughSample, segment.endSample));
      const take = Math.min(end - start, MAX_EMBEDDING_SAMPLES - total);
      if (take <= 0) continue;
      parts.push(samples.slice(start, start + take));
      total += take;
    }
    const result = new Float32Array(total);
    let offset = 0;
    for (let i = 0; i < parts.length; i++) {
      result.set(parts[i], offset);
      offset += parts[i].length;
    }
    return result;
  }

  private collectQuerySamples(samples: Float32Array,
    segments: SpeakerTurnSegmentationSegment[], localSpeaker: number,
    fromSample: number, throughSample: number): Float32Array {
    const start = Math.max(0, Math.min(samples.length, fromSample));
    const end = Math.max(start, Math.min(samples.length, throughSample));
    const masks = new Uint8Array(end - start);
    for (let i = 0; i < segments.length; i++) {
      const segment = segments[i];
      const from = Math.max(start, segment.startSample);
      const through = Math.min(end, segment.endSample);
      if (through > from) masks.fill(segment.speakerMask, from - start, through - start);
    }
    const expectedMask = 1 << localSpeaker;
    let confirmedSpeech = 0;
    let total = 0;
    for (let i = 0; i < masks.length; i++) {
      if (masks[i] === expectedMask) confirmedSpeech++;
      if (masks[i] === 0 || masks[i] === expectedMask) total++;
    }
    if (confirmedSpeech < MIN_EMBEDDING_SAMPLES) return new Float32Array(0);
    // Segmentation can miss weak phonetic tails. Retain real unclassified PCM
    // within this output slice, excluding other speakers and overlap. These
    // samples do not count toward speech eligibility or enter enrollment.
    const result = new Float32Array(Math.min(total, MAX_EMBEDDING_SAMPLES));
    let offset = 0;
    for (let i = 0; i < masks.length && offset < result.length; i++) {
      if (masks[i] === 0 || masks[i] === expectedMask) result[offset++] = samples[start + i];
    }
    return result;
  }

  private async computeEmbedding(samples: Float32Array): Promise<Float32Array | undefined> {
    const extractor = this.extractor;
    if (extractor === undefined) return undefined;
    const stream: OnlineStream = extractor.createStream();
    try {
      const wave: Samples = { samples, sampleRate: SAMPLE_RATE } as Samples;
      stream.acceptWaveform(wave);
      if (!extractor.isReady(stream)) return undefined;
      return await extractor.computeAsync(stream);
    } finally {
      stream.close();
    }
  }
}
