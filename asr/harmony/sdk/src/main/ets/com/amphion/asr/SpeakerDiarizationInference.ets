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
const MAX_EMBEDDING_SAMPLES: number = Math.round(SAMPLE_RATE * 2.5);

export class SpeakerDiarizationSegment {
  startSample: number = 0;
  endSample: number = 0;
  speaker: number = 0;
  speakerMask: number = 0;
}

export class SpeakerDiarizationEmbedding {
  localSpeaker: number = 0;
  speechSamples: number = 0;
  embedding: number[] = [];
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

  async process(samples: Float32Array): Promise<SpeakerDiarizationWindowResult> {
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
      value.embedding = Array.from(embedding);
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
    segments: SpeakerTurnSegmentationSegment[], localSpeaker: number): Float32Array {
    const expectedMask = 1 << localSpeaker;
    const parts: Float32Array[] = [];
    let total = 0;
    for (let i = 0; i < segments.length && total < MAX_EMBEDDING_SAMPLES; i++) {
      const segment = segments[i];
      if (segment.speakerMask !== expectedMask) continue;
      const start = Math.max(0, Math.min(samples.length, segment.startSample));
      const end = Math.max(start, Math.min(samples.length, segment.endSample));
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
