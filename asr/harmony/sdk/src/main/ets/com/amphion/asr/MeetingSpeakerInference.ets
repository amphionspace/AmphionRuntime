import {
  OnlineStream,
  Samples,
  SpeakerEmbeddingExtractor,
  SpeakerEmbeddingExtractorConfig
} from 'sherpa_onnx';
import { fileIo } from '@kit.CoreFileKit';
import {
  loadSpeakerTurnSegmentationModelAsync,
  processSpeakerTurnSegmentationAsync,
  SpeakerTurnSegmentationSegment,
  unloadSpeakerTurnSegmentationModel
} from 'libamphion_asr.so';

const SAMPLE_RATE: number = 16000;
const MIN_EMBEDDING_SAMPLES: number = SAMPLE_RATE;
const MAX_EMBEDDING_SAMPLES: number = Math.round(SAMPLE_RATE * 2.5);

export class MeetingSpeakerSegment {
  startSample: number = 0;
  endSample: number = 0;
  speaker: number = 0;
  speakerMask: number = 0;
}

export class MeetingSpeakerEmbedding {
  localSpeaker: number = 0;
  speechSamples: number = 0;
  embedding: number[] = [];
}

export class MeetingSpeakerWindowResult {
  segments: MeetingSpeakerSegment[] = [];
  embeddings: MeetingSpeakerEmbedding[] = [];
  inferenceMs: number = 0;
}

/** Standalone meeting inference runtime intended to live only in the HAP child process. */
export class MeetingSpeakerInference {
  private extractor?: SpeakerEmbeddingExtractor;
  private closed: boolean = false;

  async load(segmentationModelPath: string, embeddingModelPath: string): Promise<void> {
    if (this.closed) throw new Error('meeting speaker inference is closed');
    const segmentationBytes = MeetingSpeakerInference.readBytes(segmentationModelPath);
    await loadSpeakerTurnSegmentationModelAsync(segmentationBytes);
    const config = new SpeakerEmbeddingExtractorConfig();
    config.model = embeddingModelPath;
    config.numThreads = 1;
    config.debug = false;
    this.extractor = await SpeakerEmbeddingExtractor.createAsync(
      config, undefined, SAMPLE_RATE);
  }

  async process(samples: Float32Array): Promise<MeetingSpeakerWindowResult> {
    if (this.closed || this.extractor === undefined) {
      throw new Error('meeting speaker inference is not loaded');
    }
    const startedMs = Date.now();
    const nativeSegments = await processSpeakerTurnSegmentationAsync(samples);
    const result = new MeetingSpeakerWindowResult();
    result.segments = nativeSegments.map(
      (segment: SpeakerTurnSegmentationSegment): MeetingSpeakerSegment => {
        const converted = new MeetingSpeakerSegment();
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
      const value = new MeetingSpeakerEmbedding();
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
    unloadSpeakerTurnSegmentationModel();
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

  private static readBytes(path: string): Uint8Array {
    const fp = fileIo.openSync(path);
    try {
      const size = fileIo.statSync(fp.fd).size;
      const buffer = new ArrayBuffer(size);
      fileIo.readSync(fp.fd, buffer);
      return new Uint8Array(buffer);
    } finally {
      fileIo.closeSync(fp.fd);
    }
  }
}
