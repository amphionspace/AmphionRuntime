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

interface SpeakerDiarizationEmbeddingPair {
  primary?: Float32Array;
  complementary?: Float32Array;
}

interface SpeakerDiarizationChannelPair {
  samples: Float32Array;
  pair: SpeakerDiarizationEmbeddingPair;
}

interface SpeakerDiarizationLocalFailure {
  position: number;
  error: Error;
}

export class SpeakerDiarizationSegment {
  startSample: number = 0;
  endSample: number = 0;
  speaker: number = 0;
  speakerMask: number = 0;
  queryEmbedding?: number[];
  complementaryEmbedding?: number[];
  localQueries: SpeakerDiarizationLocalIdentityQuery[] = [];
}

export interface SpeakerDiarizationLocalIdentityQuery {
  startSample: number;
  endSample: number;
  embedding: number[];
  complementaryEmbedding: number[];
}

export class SpeakerDiarizationEmbedding {
  localSpeaker: number = 0;
  speechSamples: number = 0;
  speechRms: number = 0;
  embedding: number[] = [];
  queryEmbedding?: number[];
  complementaryEmbedding?: number[];
}

export class SpeakerDiarizationWindowResult {
  segments: SpeakerDiarizationSegment[] = [];
  embeddings: SpeakerDiarizationEmbedding[] = [];
  refinements: SpeakerDiarizationBoundaryRefinement[] = [];
  inferenceMs: number = 0;
}

export interface SpeakerDiarizationBoundaryRefinement {
  startSample: number;
  cutSample: number;
  endSample: number;
  leftEmbedding: number[];
  leftComplementaryEmbedding: number[];
  rightEmbedding: number[];
  rightComplementaryEmbedding: number[];
}

/** Session-owned offline diarization executor backed by SDK-bundled models. */
export class SpeakerDiarizationInference {
  private extractor?: SpeakerEmbeddingExtractor;
  private complementaryExtractor?: SpeakerEmbeddingExtractor;
  private localQueryExtractor?: SpeakerEmbeddingExtractor;
  private localComplementaryExtractor?: SpeakerEmbeddingExtractor;
  private closed: boolean = false;
  private recentSingleSpeakerRuns: SpeakerTurnSegmentationSegment[] = [];
  private speakerLevelReference: number = 0;

  async load(context: Context, embeddingModelPath: string, complementaryModelPath: string): Promise<void> {
    if (this.closed) throw new Error('speaker diarization inference is closed');
    await AmphionRuntime.getOrCreateSpeakerTurnSegmenterAsync(context, embeddingModelPath);
    const config = new SpeakerEmbeddingExtractorConfig();
    config.model = embeddingModelPath;
    config.numThreads = 2;
    config.debug = false;
    this.extractor = await SpeakerEmbeddingExtractor.createAsync(
      config, embeddingModelPath.startsWith('/') ? undefined : context.resourceManager, SAMPLE_RATE);
    const complementaryConfig = new SpeakerEmbeddingExtractorConfig();
    complementaryConfig.model = complementaryModelPath;
    complementaryConfig.numThreads = 1;
    complementaryConfig.debug = false;
    try {
      this.complementaryExtractor = await SpeakerEmbeddingExtractor.createAsync(
        complementaryConfig, complementaryModelPath.startsWith('/') ? undefined : context.resourceManager, SAMPLE_RATE);
      this.localQueryExtractor = await SpeakerEmbeddingExtractor.createAsync(
        config, embeddingModelPath.startsWith('/') ? undefined : context.resourceManager, SAMPLE_RATE);
      this.localComplementaryExtractor = await SpeakerEmbeddingExtractor.createAsync(
        complementaryConfig, complementaryModelPath.startsWith('/') ? undefined : context.resourceManager, SAMPLE_RATE);
    } catch (error) {
      this.close();
      throw new Error(`speaker model load failed: ${error}`);
    }
  }

  async process(samples: Float32Array, queryStartSample: number = 0,
    queryEndSample: number = 0, windowOriginSample: number = 0): Promise<SpeakerDiarizationWindowResult> {
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

    const channelPairs = new Map<number, SpeakerDiarizationChannelPair>();
    for (let localSpeaker = 0; localSpeaker < 3; localSpeaker++) {
      const channelSamples = this.collectSingleSpeakerSamples(
        samples, nativeSegments, localSpeaker);
      if (channelSamples.length < MIN_EMBEDDING_SAMPLES) continue;
      const pair = await this.computeEmbeddingPair(channelSamples, true);
      channelPairs.set(localSpeaker, { samples: channelSamples, pair });
      const embedding = pair.primary;
      if (embedding === undefined) continue;
      const value = new SpeakerDiarizationEmbedding();
      value.localSpeaker = localSpeaker;
      value.speechSamples = channelSamples.length;
      let squaredLevel = 0;
      for (const sample of channelSamples) squaredLevel += sample * sample;
      value.speechRms = Math.sqrt(squaredLevel / channelSamples.length);
      value.embedding = Array.from(embedding);
      if (this.complementaryExtractor !== undefined) {
        const complementary = pair.complementary;
        if (complementary !== undefined) value.complementaryEmbedding = Array.from(complementary);
      }
      const querySamples = this.collectQuerySamples(
        samples, nativeSegments, localSpeaker, queryStartSample, queryEndSample);
      if (querySamples.length >= MIN_EMBEDDING_SAMPLES) {
        const query = await this.computeEmbedding(querySamples);
        if (query !== undefined) value.queryEmbedding = Array.from(query);
      }
      result.embeddings.push(value);
    }
    for (const value of result.embeddings) this.speakerLevelReference = Math.max(this.speakerLevelReference, value.speechRms);
    for (const segment of result.segments) {
      if (segment.speakerMask !== (1 << segment.speaker) ||
        Math.max(segment.startSample, queryStartSample) >= Math.min(segment.endSample, queryEndSample)) continue;
      // A local channel can join different people across a pause. Query the
      // enclosing speech run, including its available context, independently.
      const end = Math.min(segment.endSample, segment.startSample + MAX_EMBEDDING_SAMPLES);
      if (end - segment.startSample < MIN_EMBEDDING_SAMPLES) continue;
      const runSamples = samples.slice(segment.startSample, end);
      // A continuous single-speaker channel often uses exactly the same PCM
      // as this run. Reuse only an exact match from the current window.
      const channel = channelPairs.get(segment.speaker);
      const pair = channel !== undefined && this.sameSamples(channel.samples, runSamples) ?
        channel.pair : await this.computeEmbeddingPair(runSamples);
      const query = pair.primary;
      if (query !== undefined) segment.queryEmbedding = Array.from(query);
      if (this.complementaryExtractor !== undefined) {
        const complementary = pair.complementary;
        if (complementary !== undefined) segment.complementaryEmbedding = Array.from(complementary);
      }
      const context = result.embeddings.find(value => value.localSpeaker === segment.speaker);
      if (context !== undefined && context.speechRms > 0 && context.speechRms < this.speakerLevelReference * 0.5 &&
        segment.queryEmbedding !== undefined && segment.complementaryEmbedding !== undefined) {
        segment.localQueries = await this.queryQuietLocalIdentity(samples, segment, queryStartSample, queryEndSample, windowOriginSample);
      }
    }
    result.refinements = await this.refineEarlierRuns(samples, nativeSegments, queryStartSample, windowOriginSample);
    result.inferenceMs = Date.now() - startedMs;
    return result;
  }

  private async queryQuietLocalIdentity(samples: Float32Array, segment: SpeakerTurnSegmentationSegment,
    queryStartSample: number, queryEndSample: number, origin: number): Promise<SpeakerDiarizationLocalIdentityQuery[]> {
    const queries: SpeakerDiarizationLocalIdentityQuery[] = [];
    if (this.complementaryExtractor === undefined) return queries;
    const start = origin + Math.max(segment.startSample, queryStartSample);
    const end = origin + Math.min(segment.endSample, queryEndSample);
    const cells: number[] = [];
    const samplesByCell: Float32Array[] = [];
    // Fixed 250-ms output cells use 1.3 seconds of real, continuous local PCM.
    // The grid is absolute, independent of input framing and native window origin.
    for (let cell = Math.floor(start / 4000); cell < Math.ceil(end / 4000); cell++) {
      const center = cell * 4000 + 2000;
      const from = center - 10400;
      const through = center + 10400;
      if (from < Math.max(0, origin) || through > origin + samples.length) continue;
      const pcm = samples.slice(from - origin, through - origin);
      cells.push(cell);
      samplesByCell.push(pcm);
    }
    const pairs = await this.computeLocalEmbeddings(samplesByCell);
    for (let index = 0; index < cells.length; index++) {
      const cell = cells[index];
      const pair = pairs[index];
      const primary = pair.primary;
      const complementary = pair.complementary;
      if (primary === undefined || complementary === undefined) continue;
      queries.push({ startSample: Math.max(start, cell * 4000), endSample: Math.min(end, (cell + 1) * 4000),
        embedding: Array.from(primary), complementaryEmbedding: Array.from(complementary) });
    }
    return queries;
  }

  private async computeLocalEmbeddings(samples: Float32Array[]): Promise<SpeakerDiarizationEmbeddingPair[]> {
    if (samples.length === 0) return [];
    if (this.localQueryExtractor === undefined || this.localComplementaryExtractor === undefined) {
      throw new Error('local speaker models are not loaded');
    }
    // Each model has one ordered queue. The two primary copies use identical
    // weights/configuration and own disjoint cells, as do the secondary copies.
    const errors: SpeakerDiarizationLocalFailure[] = [];
    const first = this.computeEmbeddingSequence(samples, 0, 2, this.extractor, 0, errors);
    const second = this.computeEmbeddingSequence(samples, 1, 2, this.localQueryExtractor, 0, errors);
    const other = this.computeEmbeddingSequence(samples, 0, 2, this.complementaryExtractor, 1, errors);
    const localOther = this.computeEmbeddingSequence(samples, 1, 2, this.localComplementaryExtractor, 1, errors);
    // Never return/reject while another queue still owns native work.
    const values = await Promise.all([first, second, other, localOther]);
    // Preserve the error the original cell-by-cell path would encounter first.
    errors.sort((left, right): number => left.position - right.position);
    if (errors.length > 0) throw errors[0].error;
    return samples.map((_pcm: Float32Array, index: number): SpeakerDiarizationEmbeddingPair =>
      ({ primary: values[index % 2][Math.floor(index / 2)],
        complementary: values[2 + index % 2][Math.floor(index / 2)] }));
  }

  private async computeEmbeddingSequence(samples: Float32Array[], start: number, step: number,
    extractor: SpeakerEmbeddingExtractor | undefined, modelOrder: number,
    errors: SpeakerDiarizationLocalFailure[]): Promise<Array<Float32Array | undefined>> {
    const values: Array<Float32Array | undefined> = [];
    for (let index = start; index < samples.length; index += step) {
      let failed = false;
      const value = await this.computeEmbedding(samples[index], extractor)
        .catch((error: Error): undefined => {
          errors.push({ position: index * 2 + modelOrder, error });
          failed = true;
          return undefined;
        });
      if (failed) break;
      values.push(value);
    }
    return values;
  }

  private async refineEarlierRuns(samples: Float32Array, segments: SpeakerTurnSegmentationSegment[],
    queryStartSample: number, origin: number): Promise<SpeakerDiarizationBoundaryRefinement[]> {
    const refinements: SpeakerDiarizationBoundaryRefinement[] = [];
    for (let index = 1; index < segments.length; index++) {
      const left = segments[index - 1];
      const right = segments[index];
      const cut = origin + right.startSample;
      if (left.endSample !== right.startSample || left.speaker === right.speaker ||
        left.speakerMask !== (1 << left.speaker) || right.speakerMask !== (1 << right.speaker) ||
        right.startSample >= queryStartSample || right.endSample - right.startSample < MIN_EMBEDDING_SAMPLES) continue;
      const parents = this.recentSingleSpeakerRuns.filter(run => run.startSample >= Math.max(0, origin) &&
        run.startSample < cut && run.endSample > cut && cut - run.startSample >= MIN_EMBEDDING_SAMPLES);
      if (parents.length === 0 || this.complementaryExtractor === undefined) continue;
      const start = Math.min(...parents.map(run => run.startSample));
      const leftSamples = samples.slice(Math.max(start - origin, right.startSample - MAX_EMBEDDING_SAMPLES), right.startSample);
      const rightSamples = samples.slice(right.startSample, Math.min(right.endSample, right.startSample + MAX_EMBEDDING_SAMPLES));
      const leftPair = await this.computeEmbeddingPair(leftSamples);
      const rightPair = await this.computeEmbeddingPair(rightSamples);
      const leftEmbedding = leftPair.primary;
      const leftComplementary = leftPair.complementary;
      const rightEmbedding = rightPair.primary;
      const rightComplementary = rightPair.complementary;
      if (leftEmbedding === undefined || leftComplementary === undefined ||
        rightEmbedding === undefined || rightComplementary === undefined) continue;
      refinements.push({ startSample: start, cutSample: cut,
        endSample: origin + Math.min(right.endSample, queryStartSample),
        leftEmbedding: Array.from(leftEmbedding), leftComplementaryEmbedding: Array.from(leftComplementary),
        rightEmbedding: Array.from(rightEmbedding), rightComplementaryEmbedding: Array.from(rightComplementary) });
    }
    // Only retain native ranges still addressable by the next bounded PCM window.
    this.recentSingleSpeakerRuns = this.recentSingleSpeakerRuns.filter(run => run.endSample > origin);
    for (const segment of segments) {
      if (segment.speakerMask !== (1 << segment.speaker)) continue;
      this.recentSingleSpeakerRuns.push({ startSample: origin + segment.startSample,
        endSample: origin + segment.endSample, speaker: segment.speaker, speakerMask: segment.speakerMask });
    }
    return refinements;
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    try { this.extractor?.close(); } catch (_ignored) {}
    this.extractor = undefined;
    try { this.complementaryExtractor?.close(); } catch (_ignored) {}
    this.complementaryExtractor = undefined;
    try { this.localQueryExtractor?.close(); } catch (_ignored) {}
    this.localQueryExtractor = undefined;
    try { this.localComplementaryExtractor?.close(); } catch (_ignored) {}
    this.localComplementaryExtractor = undefined;
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

  private sameSamples(left: Float32Array, right: Float32Array): boolean {
    if (left.length !== right.length) return false;
    for (let index = 0; index < left.length; index++) {
      if (left[index] !== right[index]) return false;
    }
    return true;
  }

  private async computeEmbeddingPair(samples: Float32Array,
    skipComplementaryFailureWithoutPrimary: boolean = false): Promise<SpeakerDiarizationEmbeddingPair> {
    const primary = this.computeEmbedding(samples);
    if (this.complementaryExtractor === undefined) return { primary: await primary };
    // Each extractor owns a separate model. Keep at most one
    // call per model in flight and do not advance the window until both settle.
    let complementaryError: Error | undefined;
    const complementary = this.computeEmbedding(samples, this.complementaryExtractor)
      .catch((error: Error): undefined => { complementaryError = error; return undefined; });
    try {
      const embedding = await primary;
      const other = await complementary;
      // The channel path formerly skipped the complementary model when its
      // primary embedding was unavailable. Its speculative failure cannot
      // turn that skipped channel into a degraded window.
      if (complementaryError !== undefined &&
        !(skipComplementaryFailureWithoutPrimary && embedding === undefined)) throw complementaryError;
      return { primary: embedding, complementary: other };
    } finally {
      // A rejected primary must not release the runtime while the other model
      // still owns a native stream. Preserve the primary error if both fail.
      await complementary;
    }
  }

  private async computeEmbedding(samples: Float32Array,
    extractor: SpeakerEmbeddingExtractor | undefined = this.extractor): Promise<Float32Array | undefined> {
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
