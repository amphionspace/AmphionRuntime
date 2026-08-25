export interface SpeakerAssignment {
  speakerId: string;
  confidence: number;
  created: boolean;
}

export interface SpeakerRegistrySnapshotEntry {
  speakerId: string;
  centroid: number[];
  speechDurationMs: number;
  lastSeenMs: number;
}

interface MutableSpeakerEntry {
  speakerId: string;
  centroid: Float32Array;
  speechDurationMs: number;
  lastSeenMs: number;
}

const UNKNOWN_SPEAKER = 'UNKNOWN';

function normalize(embedding: Float32Array): Float32Array | undefined {
  let squaredNorm = 0;
  for (let i = 0; i < embedding.length; i++) {
    const value = embedding[i];
    if (!Number.isFinite(value)) {
      return undefined;
    }
    squaredNorm += value * value;
  }
  if (embedding.length === 0 || squaredNorm <= 0) {
    return undefined;
  }
  const norm = Math.sqrt(squaredNorm);
  const result = new Float32Array(embedding.length);
  for (let i = 0; i < embedding.length; i++) {
    result[i] = embedding[i] / norm;
  }
  return result;
}

function cosine(left: Float32Array, right: Float32Array): number {
  if (left.length !== right.length) {
    return Number.NEGATIVE_INFINITY;
  }
  let score = 0;
  for (let i = 0; i < left.length; i++) {
    score += left[i] * right[i];
  }
  return score;
}

export class OnlineSpeakerRegistry {
  private readonly entries: MutableSpeakerEntry[] = [];
  private readonly maxSpeakers: number;
  private readonly similarityThreshold: number;
  private readonly topMargin: number;

  constructor(
    maxSpeakers: number = 4,
    similarityThreshold: number = 0.72,
    topMargin: number = 0.05,
  ) {
    if (!Number.isInteger(maxSpeakers) || maxSpeakers < 1) {
      throw new Error('maxSpeakers must be a positive integer');
    }
    this.maxSpeakers = maxSpeakers;
    this.similarityThreshold = similarityThreshold;
    this.topMargin = topMargin;
  }

  assign(
    rawEmbedding: Float32Array | undefined,
    speechDurationMs: number,
    atMs: number,
  ): SpeakerAssignment {
    return this.assignBatch([rawEmbedding], [speechDurationMs], atMs)[0];
  }

  /** Assigns one window jointly so an existing centroid and observation must be mutual top-1. */
  assignBatch(rawEmbeddings: (Float32Array | undefined)[], speechDurationsMs: number[],
    atMs: number): SpeakerAssignment[] {
    if (rawEmbeddings.length !== speechDurationsMs.length) {
      throw new Error('embedding and duration counts must match');
    }
    const embeddings = rawEmbeddings.map(
      (embedding: Float32Array | undefined, index: number): Float32Array | undefined =>
        embedding === undefined || speechDurationsMs[index] < 1_000 ? undefined : normalize(embedding));
    const entryBestObservation = new Array<number>(this.entries.length).fill(-1);
    const entryBestScore = new Array<number>(this.entries.length).fill(Number.NEGATIVE_INFINITY);
    const rankedByObservation: { entryIndex: number; score: number }[][] = [];
    for (let observation = 0; observation < embeddings.length; observation++) {
      const embedding = embeddings[observation];
      const ranked: { entryIndex: number; score: number }[] = [];
      if (embedding !== undefined) {
        for (let entryIndex = 0; entryIndex < this.entries.length; entryIndex++) {
          const score = cosine(this.entries[entryIndex].centroid, embedding);
          ranked.push({ entryIndex, score });
          if (score > entryBestScore[entryIndex]) {
            entryBestScore[entryIndex] = score;
            entryBestObservation[entryIndex] = observation;
          }
        }
        ranked.sort((left, right): number => right.score - left.score);
      }
      rankedByObservation.push(ranked);
    }

    const assignments: SpeakerAssignment[] = embeddings.map(
      (): SpeakerAssignment => ({ speakerId: UNKNOWN_SPEAKER, confidence: 0, created: false }));
    for (let observation = 0; observation < embeddings.length; observation++) {
      const embedding = embeddings[observation];
      if (embedding === undefined) continue;
      const ranked = rankedByObservation[observation];
      const best = ranked[0];
      const second = ranked[1];
      const mutual = best !== undefined && entryBestObservation[best.entryIndex] === observation;
      const unambiguous = mutual && best.score >= this.similarityThreshold &&
        (second === undefined || best.score - second.score >= this.topMargin);
      if (unambiguous) {
        const entry = this.entries[best.entryIndex];
        this.updateCentroid(entry, embedding, speechDurationsMs[observation], atMs);
        assignments[observation] = {
          speakerId: entry.speakerId,
          confidence: Math.max(0, Math.min(1, best.score)),
          created: false,
        };
        continue;
      }
      if (this.entries.length < this.maxSpeakers) {
        const entry: MutableSpeakerEntry = {
          speakerId: `S${this.entries.length + 1}`,
          centroid: embedding,
          speechDurationMs: speechDurationsMs[observation],
          lastSeenMs: atMs,
        };
        this.entries.push(entry);
        assignments[observation] = { speakerId: entry.speakerId, confidence: 1, created: true };
      } else if (best !== undefined) {
        assignments[observation].confidence = Math.max(0, Math.min(1, best.score));
      }
    }
    return assignments;
  }

  speakerIds(): string[] {
    return this.entries.map((entry) => entry.speakerId);
  }

  snapshot(): SpeakerRegistrySnapshotEntry[] {
    return this.entries.map((entry) => ({
      speakerId: entry.speakerId,
      centroid: Array.from(entry.centroid),
      speechDurationMs: entry.speechDurationMs,
      lastSeenMs: entry.lastSeenMs,
    }));
  }

  private updateCentroid(
    entry: MutableSpeakerEntry,
    embedding: Float32Array,
    speechDurationMs: number,
    atMs: number,
  ): void {
    const oldWeight = entry.speechDurationMs;
    const newWeight = oldWeight + speechDurationMs;
    const mixed = new Float32Array(embedding.length);
    for (let i = 0; i < embedding.length; i++) {
      mixed[i] = (entry.centroid[i] * oldWeight + embedding[i] * speechDurationMs) / newWeight;
    }
    entry.centroid = normalize(mixed) ?? entry.centroid;
    entry.speechDurationMs = newWeight;
    entry.lastSeenMs = atMs;
  }
}
