import {
  OnlineStream,
  Samples,
  SpeakerEmbeddingExtractor,
  SpeakerEmbeddingExtractorConfig
} from 'sherpa_onnx';
import {
  clusterCommunity1Async,
  Community1ClusterResult,
  loadCommunity1Plda,
  processSpeakerTurnSegmentationAsync,
  SpeakerTurnSegmentationSegment
} from 'libamphion_asr.so';
import { AmphionRuntime } from './Runtime';
import { fileIo } from '@kit.CoreFileKit';

const SAMPLE_RATE: number = 16000;
// Community-1 WeSpeaker produces finite embeddings from 1,680 samples.
const MIN_EMBEDDING_SAMPLES: number = 1680;
const MAX_EMBEDDING_SAMPLES: number = SAMPLE_RATE * 10;
const COMMUNITY_FRAMES: number = 589;
const LOCAL_SPEAKERS: number = 3;
const EMBEDDING_DIMENSION: number = 256;

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
  /** Powerset argmax converted to one bit per active local speaker. */
  frameMasks: number[] = [];
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

export class SpeakerDiarizationCommunityClusterResult {
  hardClusters: number[] = [];
  speakerCount: number = 0;
  constraintViolated: boolean = false;
}

/** Session-owned offline diarization executor backed by SDK-bundled models. */
export class SpeakerDiarizationInference {
  private extractor?: SpeakerEmbeddingExtractor;
  private complementaryExtractor?: SpeakerEmbeddingExtractor;
  private closed: boolean = false;
  private recentSingleSpeakerRuns: SpeakerTurnSegmentationSegment[] = [];
  private speakerLevelReference: number = 0;

  async load(context: Context, embeddingModelPath: string, pldaRuntimePath: string,
    complementaryModelPath?: string): Promise<void> {
    if (this.closed) throw new Error('speaker diarization inference is closed');
    await AmphionRuntime.getOrCreateSpeakerTurnSegmenterAsync(context, embeddingModelPath);
    loadCommunity1Plda(await this.readBytes(context, pldaRuntimePath));
    const config = new SpeakerEmbeddingExtractorConfig();
    config.model = embeddingModelPath;
    config.numThreads = 1;
    config.debug = false;
    this.extractor = await SpeakerEmbeddingExtractor.createAsync(
      config, embeddingModelPath.startsWith('/') ? undefined : context.resourceManager, SAMPLE_RATE);
    if (complementaryModelPath !== undefined) {
      const complementaryConfig = new SpeakerEmbeddingExtractorConfig();
      complementaryConfig.model = complementaryModelPath;
      complementaryConfig.numThreads = 1;
      complementaryConfig.debug = false;
      try {
        this.complementaryExtractor = await SpeakerEmbeddingExtractor.createAsync(
          complementaryConfig, complementaryModelPath.startsWith('/') ? undefined : context.resourceManager, SAMPLE_RATE);
      } catch (error) {
        this.close();
        throw new Error(`complementary speaker model load failed: ${error}`);
      }
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
    result.frameMasks = new Array<number>(COMMUNITY_FRAMES).fill(0);
    result.segments = nativeSegments.map(
      (segment: SpeakerTurnSegmentationSegment): SpeakerDiarizationSegment => {
        const converted = new SpeakerDiarizationSegment();
        converted.startSample = segment.startSample;
        converted.endSample = segment.endSample;
        converted.speaker = segment.speaker;
        converted.speakerMask = segment.speakerMask;
        for (let frame = Math.max(0, segment.startFrame);
          frame < Math.min(COMMUNITY_FRAMES, segment.endFrame); frame++) {
          result.frameMasks[frame] = segment.speakerMask;
        }
        return converted;
      });

    for (let localSpeaker = 0; localSpeaker < LOCAL_SPEAKERS; localSpeaker++) {
      const value = new SpeakerDiarizationEmbedding();
      value.localSpeaker = localSpeaker;
      const weights = this.buildCommunityEmbeddingMask(result.frameMasks, localSpeaker);
      let weightedFrames = 0;
      for (let frame = 0; frame < weights.length; frame++) {
        if (weights[frame] > 0) weightedFrames++;
      }
      value.speechSamples = Math.floor(weightedFrames * SAMPLE_RATE * 10 / COMMUNITY_FRAMES);
      if (weightedFrames * SAMPLE_RATE * 10 / COMMUNITY_FRAMES >= MIN_EMBEDDING_SAMPLES) {
        const embedding = await this.computeWeightedEmbedding(samples, weights);
        if (embedding !== undefined) value.embedding = Array.from(embedding);
        let squaredLevel = 0;
        for (const sample of samples) squaredLevel += sample * sample;
        value.speechRms = samples.length > 0 ? Math.sqrt(squaredLevel / samples.length) : 0;
      }
      result.embeddings.push(value);
    }
    result.inferenceMs = Date.now() - startedMs;
    return result;
  }

  async cluster(windows: SpeakerDiarizationWindowResult[], minSpeakers?: number,
    maxSpeakers?: number): Promise<SpeakerDiarizationCommunityClusterResult> {
    const embeddings = new Float32Array(windows.length * LOCAL_SPEAKERS * EMBEDDING_DIMENSION);
    embeddings.fill(Number.NaN);
    const frameMasks = new Int32Array(windows.length * COMMUNITY_FRAMES);
    for (let chunk = 0; chunk < windows.length; chunk++) {
      for (let frame = 0; frame < COMMUNITY_FRAMES; frame++) {
        frameMasks[chunk * COMMUNITY_FRAMES + frame] = windows[chunk].frameMasks[frame] ?? 0;
      }
      for (const embedding of windows[chunk].embeddings) {
        if (embedding.embedding.length !== EMBEDDING_DIMENSION) continue;
        embeddings.set(embedding.embedding,
          (chunk * LOCAL_SPEAKERS + embedding.localSpeaker) * EMBEDDING_DIMENSION);
      }
    }
    const native: Community1ClusterResult = await clusterCommunity1Async(
      embeddings, frameMasks, windows.length, minSpeakers ?? 0, maxSpeakers ?? 0);
    const result = new SpeakerDiarizationCommunityClusterResult();
    result.hardClusters = native.hardClusters;
    result.speakerCount = native.speakerCount;
    result.constraintViolated = native.constraintViolated;
    return result;
  }

  private async queryQuietLocalIdentity(samples: Float32Array, segment: SpeakerTurnSegmentationSegment,
    queryStartSample: number, queryEndSample: number, origin: number): Promise<SpeakerDiarizationLocalIdentityQuery[]> {
    const queries: SpeakerDiarizationLocalIdentityQuery[] = [];
    if (this.complementaryExtractor === undefined) return queries;
    const start = origin + Math.max(segment.startSample, queryStartSample);
    const end = origin + Math.min(segment.endSample, queryEndSample);
    // Fixed 250-ms output cells use 1.3 seconds of real, continuous local PCM.
    // The grid is absolute, independent of input framing and native window origin.
    for (let cell = Math.floor(start / 4000); cell < Math.ceil(end / 4000); cell++) {
      const center = cell * 4000 + 2000;
      const from = center - 10400;
      const through = center + 10400;
      if (from < Math.max(0, origin) || through > origin + samples.length) continue;
      const pcm = samples.slice(from - origin, through - origin);
      const primary = await this.computeEmbedding(pcm);
      const complementary = await this.computeEmbedding(pcm, this.complementaryExtractor);
      if (primary === undefined || complementary === undefined) continue;
      queries.push({ startSample: Math.max(start, cell * 4000), endSample: Math.min(end, (cell + 1) * 4000),
        embedding: Array.from(primary), complementaryEmbedding: Array.from(complementary) });
    }
    return queries;
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
      const leftEmbedding = await this.computeEmbedding(leftSamples);
      const leftComplementary = await this.computeEmbedding(leftSamples, this.complementaryExtractor);
      const rightEmbedding = await this.computeEmbedding(rightSamples);
      const rightComplementary = await this.computeEmbedding(rightSamples, this.complementaryExtractor);
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
        endSample: origin + segment.endSample, speaker: segment.speaker, speakerMask: segment.speakerMask,
        startFrame: segment.startFrame, endFrame: segment.endFrame });
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
  }

  private async readBytes(context: Context, path: string): Promise<Uint8Array> {
    if (!path.startsWith('/')) return context.resourceManager.getRawFileContent(path);
    const file = await fileIo.open(path);
    try {
      const stat = await fileIo.stat(file.fd);
      const buffer = new ArrayBuffer(stat.size);
      await fileIo.read(file.fd, buffer);
      return new Uint8Array(buffer);
    } finally {
      fileIo.closeSync(file);
    }
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

  private buildCommunityEmbeddingMask(frameMasks: number[], localSpeaker: number): Float32Array {
    const weights = new Float32Array(COMMUNITY_FRAMES);
    const expectedMask = 1 << localSpeaker;
    let cleanFrames = 0;
    for (let frame = 0; frame < COMMUNITY_FRAMES; frame++) {
      const mask = frameMasks[frame] ?? 0;
      let active = 0;
      if ((mask & 1) !== 0) active++;
      if ((mask & 2) !== 0) active++;
      if ((mask & 4) !== 0) active++;
      if (active < 2 && mask === expectedMask) cleanFrames++;
    }
    // pyannote uses clean speaker masks only when enough clean frames remain;
    // otherwise it falls back to the original (possibly overlapping) mask.
    const useClean = cleanFrames > Math.ceil(COMMUNITY_FRAMES * MIN_EMBEDDING_SAMPLES /
      (SAMPLE_RATE * 10));
    for (let frame = 0; frame < COMMUNITY_FRAMES; frame++) {
      const mask = frameMasks[frame] ?? 0;
      let active = 0;
      if ((mask & 1) !== 0) active++;
      if ((mask & 2) !== 0) active++;
      if ((mask & 4) !== 0) active++;
      if (mask === expectedMask && (!useClean || active < 2)) weights[frame] = 1.0;
    }
    return weights;
  }

  private async computeWeightedEmbedding(samples: Float32Array,
    weights: Float32Array): Promise<Float32Array | undefined> {
    if (this.extractor === undefined) return undefined;
    const fullWindow = new Float32Array(MAX_EMBEDDING_SAMPLES);
    fullWindow.set(samples.subarray(0, Math.min(samples.length, fullWindow.length)));
    const stream: OnlineStream = this.extractor.createStream();
    try {
      const wave: Samples = { samples: fullWindow, sampleRate: SAMPLE_RATE } as Samples;
      stream.acceptWaveform(wave);
      if (!this.extractor.isReady(stream)) return undefined;
      return await this.extractor.computeWeightedAsync(stream, weights);
    } finally {
      stream.close();
    }
  }
}
