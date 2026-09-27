export interface SpeakerAssignment {
  speakerId: string;
  confidence: number;
  created: boolean;
}

export interface SpeakerIdentitySupport {
  embedding: number[];
  queryEmbedding: number[];
}

interface SupportedIdentityMatch {
  assignment: SpeakerAssignment;
  retainAlternative: boolean;
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
  alternateCentroid?: Float32Array;
  complementaryCentroid?: Float32Array;
  complementaryReferences?: Float32Array[];
}

const UNKNOWN_SPEAKER = 'UNKNOWN';
const QUERY_SIMILARITY_THRESHOLD = 0.59;

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
    allowAdditionalSpeaker: boolean = true,
    enrollmentQueries?: number[][],
    identitySupport?: SpeakerIdentitySupport[],
  ): SpeakerAssignment {
    return this.assignBatch([rawEmbedding], [speechDurationMs], atMs, [allowAdditionalSpeaker],
      [enrollmentQueries ?? []], identitySupport)[0];
  }

  /** Assigns one window jointly so an existing centroid and observation must be mutual top-1. */
  assignBatch(rawEmbeddings: (Float32Array | undefined)[], speechDurationsMs: number[],
    atMs: number, allowAdditionalSpeaker?: boolean[], enrollmentQueries?: number[][][],
    identitySupport?: SpeakerIdentitySupport[]): SpeakerAssignment[] {
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
      // A plausible known speaker with insufficient certainty is not a new person.
      // Distinct current channels still compete for different identities.
      const novel = best === undefined || !mutual ||
        best.score < Math.min(this.similarityThreshold, QUERY_SIMILARITY_THRESHOLD) ||
        this.confirmsNovelty(embedding, enrollmentQueries?.[observation]);
      if (this.entries.length < this.maxSpeakers && novel &&
        (this.entries.length === 0 || (allowAdditionalSpeaker?.[observation] ?? true))) {
        // Only intercept a new identity. Do not broaden UNKNOWN attribution.
        const supported = this.matchSupportedIdentity(embedding, identitySupport ?? [],
          enrollmentQueries?.[observation] ?? []);
        if (supported !== undefined) {
          const entry = this.entries.find(item => item.speakerId === supported.assignment.speakerId)!;
          // One recent alternative per person; never use it to qualify more support.
          if (supported.retainAlternative) entry.alternateCentroid = embedding.slice();
          assignments[observation] = supported.assignment;
          continue;
        }
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

  private matchSupportedIdentity(embedding: Float32Array,
    support: SpeakerIdentitySupport[], ownedQueries: number[][]): SupportedIdentityMatch | undefined {
    if (ownedQueries.length === 0) return undefined;
    const sum = new Float32Array(embedding.length);
    for (const raw of ownedQueries) {
      const query = normalize(new Float32Array(raw));
      if (query === undefined || query.length !== sum.length) return undefined;
      for (let i = 0; i < sum.length; i++) sum[i] += query[i];
    }
    const owned = normalize(sum);
    if (owned === undefined) return undefined;
    const alternativeMatch = this.matchExisting(Array.from(embedding), QUERY_SIMILARITY_THRESHOLD,
      undefined, true);
    const alternative = this.entries.find(entry => entry.speakerId === alternativeMatch?.speakerId)
      ?.alternateCentroid;
    if (alternativeMatch !== undefined && alternative !== undefined &&
      cosine(embedding, alternative) >= QUERY_SIMILARITY_THRESHOLD &&
      cosine(owned, alternative) >= QUERY_SIMILARITY_THRESHOLD) {
      // Reuse this fixed reference; do not extend it with another inferred sample.
      return { assignment: alternativeMatch, retainAlternative: false };
    }
    const scores = this.entries.map(entry => cosine(entry.centroid, embedding));
    const supportedScores = this.entries.map((): number => Number.NEGATIVE_INFINITY);
    for (const item of support) {
      const context = normalize(new Float32Array(item.embedding));
      const query = normalize(new Float32Array(item.queryEmbedding));
      if (context === undefined || query === undefined ||
        cosine(context, query) < this.similarityThreshold ||
        Math.max(cosine(owned, context), cosine(owned, query)) < QUERY_SIMILARITY_THRESHOLD) continue;
      const contextMatch = this.matchExisting(item.embedding, QUERY_SIMILARITY_THRESHOLD);
      const queryMatch = this.matchExisting(item.queryEmbedding, QUERY_SIMILARITY_THRESHOLD);
      if (contextMatch === undefined || queryMatch?.speakerId !== contextMatch.speakerId) continue;
      const index = this.entries.findIndex(entry => entry.speakerId === contextMatch.speakerId);
      supportedScores[index] = Math.max(supportedScores[index], cosine(embedding, query));
      scores[index] = Math.max(scores[index], supportedScores[index]);
    }
    const ranked = this.entries.map((entry, index) => ({ entry, index, score: scores[index] }))
      .sort((left, right) => right.score - left.score);
    const best = ranked[0];
    if (best === undefined || supportedScores[best.index] < QUERY_SIMILARITY_THRESHOLD ||
      (ranked.length > 1 && best.score - ranked[1].score < this.topMargin)) return undefined;
    return { assignment: { speakerId: best.entry.speakerId,
      confidence: Math.max(0, Math.min(1, best.score)), created: false }, retainAlternative: true };
  }

  private confirmsNovelty(embedding: Float32Array, queries?: number[][]): boolean {
    if (queries === undefined || queries.length < 2) return false;
    // Final clusters may contain mixed historical context. Independent owned
    // output slices must agree with that cluster and reject every known person.
    const sum = new Float32Array(embedding.length);
    for (const query of queries) {
      const normalized = normalize(new Float32Array(query));
      if (normalized === undefined || normalized.length !== sum.length) return false;
      for (let i = 0; i < sum.length; i++) sum[i] += normalized[i];
    }
    const consensus = normalize(sum);
    return consensus !== undefined && cosine(consensus, embedding) >= this.similarityThreshold &&
      this.entries.every(entry => cosine(consensus, entry.centroid) <
        Math.min(this.similarityThreshold, QUERY_SIMILARITY_THRESHOLD));
  }

  fork(): OnlineSpeakerRegistry {
    const copy = new OnlineSpeakerRegistry(this.maxSpeakers, this.similarityThreshold, this.topMargin);
    for (const entry of this.entries) copy.entries.push({ speakerId: entry.speakerId,
      centroid: entry.centroid.slice(), speechDurationMs: entry.speechDurationMs, lastSeenMs: entry.lastSeenMs,
      alternateCentroid: entry.alternateCentroid?.slice(),
      complementaryCentroid: entry.complementaryCentroid?.slice(),
      complementaryReferences: entry.complementaryReferences?.map(value => value.slice()) });
    return copy;
  }

  matchKnown(raw: number[]): string | undefined {
    return this.matchExisting(raw, this.similarityThreshold)?.speakerId;
  }

  /** Short output queries cannot enroll roles or match context-only profiles. */
  matchQuery(raw: number[], establishedIds: Set<string>): SpeakerAssignment | undefined {
    // Independent AISHELL3 calibration: maximum impostor cosine .5392 + .05 margin.
    return this.matchExisting(raw, QUERY_SIMILARITY_THRESHOLD, establishedIds) ??
      this.matchExisting(raw, QUERY_SIMILARITY_THRESHOLD, establishedIds, true);
  }

  /** Quiet output needs strong agreement with an independently established alternative. */
  matchQuietQuery(raw: number[], context: number[], establishedIds: Set<string>): SpeakerAssignment | undefined {
    const contextMatch = this.matchExisting(context, this.similarityThreshold, establishedIds, true);
    const queryMatch = this.matchExisting(raw, this.similarityThreshold, establishedIds, true);
    if (contextMatch === undefined || queryMatch === undefined ||
      contextMatch.speakerId !== queryMatch.speakerId) return undefined;
    const alternative = this.entries.find(entry => entry.speakerId === queryMatch.speakerId)?.alternateCentroid;
    const embedding = normalize(new Float32Array(raw));
    const contextEmbedding = normalize(new Float32Array(context));
    if (alternative === undefined || embedding === undefined || contextEmbedding === undefined) return undefined;
    const confidence = Math.min(cosine(embedding, alternative), cosine(contextEmbedding, alternative),
      contextMatch.confidence, queryMatch.confidence);
    if (confidence < this.similarityThreshold) return undefined;
    return { speakerId: queryMatch.speakerId, confidence, created: false };
  }

  // Called only for a newly enrolled primary identity, using the same PCM observations.
  bindComplementaryProfile(id: string, embeddings: (number[] | undefined)[], durations: number[]): void {
    const entry = this.entries.find(item => item.speakerId === id);
    if (entry === undefined || entry.complementaryCentroid !== undefined || embeddings.length === 0 ||
      embeddings.length !== durations.length || embeddings[0] === undefined) return;
    const sum = new Float32Array(embeddings[0]!.length);
    const references: Float32Array[] = [];
    for (let i = 0; i < embeddings.length; i++) {
      const raw = embeddings[i];
      const value = raw === undefined ? undefined : normalize(new Float32Array(raw));
      if (value === undefined || value.length !== sum.length || !Number.isFinite(durations[i]) || durations[i] <= 0) return;
      for (let j = 0; j < sum.length; j++) sum[j] += value[j] * durations[i];
      if (references.length < 8) references.push(value);
    }
    entry.complementaryCentroid = normalize(sum);
    if (entry.complementaryCentroid !== undefined) entry.complementaryReferences = references;
  }

  matchComplementaryQuery(query: number[], context: number[], complementaryQuery: number[],
    complementaryContext: number[], establishedIds: Set<string>): SpeakerAssignment | undefined {
    // Primary evidence must agree on an unambiguous candidate; the second model
    // supplies its own independent, calibrated acceptance threshold.
    const primaryQuery = this.matchExisting(query, -1, establishedIds);
    const primaryContext = this.matchExisting(context, -1, establishedIds);
    if (primaryQuery === undefined || primaryContext?.speakerId !== primaryQuery.speakerId) return undefined;
    const secondaryQuery = this.matchExisting(complementaryQuery, 0.64, establishedIds, false, true);
    const secondaryContext = this.matchExisting(complementaryContext, 0.64, establishedIds, false, true);
    if (secondaryQuery?.speakerId === primaryQuery.speakerId &&
      secondaryContext?.speakerId === primaryQuery.speakerId) {
      return { speakerId: primaryQuery.speakerId,
        confidence: Math.min(secondaryQuery.confidence, secondaryContext.confidence), created: false };
    }
    // Averaging can dilute a short utterance's original reference. Keep only the
    // first eight enrollment references, frozen; their separate calibration is
    // stricter, and both current signals must match the very same reference.
    const normalizedQuery = normalize(new Float32Array(complementaryQuery));
    const normalizedContext = normalize(new Float32Array(complementaryContext));
    if (normalizedQuery === undefined || normalizedContext === undefined) return undefined;
    const ranked: { id: string; score: number }[] = [];
    for (const entry of this.entries) {
      if (!establishedIds.has(entry.speakerId)) continue;
      let score = Number.NEGATIVE_INFINITY;
      for (const reference of entry.complementaryReferences ?? []) {
        score = Math.max(score, Math.min(cosine(normalizedQuery, reference), cosine(normalizedContext, reference)));
      }
      ranked.push({ id: entry.speakerId, score });
    }
    ranked.sort((left, right): number => right.score - left.score);
    if (ranked.length === 0 || ranked[0].id !== primaryQuery.speakerId || ranked[0].score < 0.68 ||
      (ranked.length > 1 && ranked[0].score - ranked[1].score < this.topMargin)) return undefined;
    return { speakerId: primaryQuery.speakerId, confidence: Math.min(1, ranked[0].score), created: false };
  }

  /** Local quiet speech needs both calibrated models, without alternate/gallery expansion. */
  matchLocalQuery(query: number[], complementaryQuery: number[], establishedIds: Set<string>): SpeakerAssignment | undefined {
    const primary = this.matchExisting(query, QUERY_SIMILARITY_THRESHOLD, establishedIds);
    const complementary = this.matchExisting(complementaryQuery, 0.64, establishedIds, false, true);
    if (primary === undefined || complementary?.speakerId !== primary.speakerId) return undefined;
    return { speakerId: primary.speakerId, confidence: Math.min(primary.confidence, complementary.confidence), created: false };
  }

  private matchExisting(raw: number[], threshold: number,
    allowedIds?: Set<string>, includeAlternate: boolean = false,
    useComplementary: boolean = false): SpeakerAssignment | undefined {
    const embedding = normalize(new Float32Array(raw));
    if (embedding === undefined) return undefined;
    const ranked = this.entries.filter(entry => allowedIds === undefined || allowedIds.has(entry.speakerId))
      .filter(entry => !useComplementary || entry.complementaryCentroid !== undefined)
      .map(entry => ({ id: entry.speakerId, score: useComplementary ?
        cosine(entry.complementaryCentroid!, embedding) : Math.max(cosine(entry.centroid, embedding),
        includeAlternate && entry.alternateCentroid !== undefined ?
          cosine(entry.alternateCentroid, embedding) : Number.NEGATIVE_INFINITY) }))
      .sort((left, right) => right.score - left.score);
    if (ranked.length === 0 || ranked[0].score < threshold ||
      (ranked.length > 1 && ranked[0].score - ranked[1].score < this.topMargin)) return undefined;
    return { speakerId: ranked[0].id, confidence: Math.max(0, Math.min(1, ranked[0].score)), created: false };
  }

  commitKnown(id: string, embedding: number[], durationMs: number, atMs: number): void {
    const entry = this.entries.find(item => item.speakerId === id);
    const normalized = normalize(new Float32Array(embedding));
    if (entry !== undefined && normalized !== undefined) this.updateCentroid(entry, normalized, durationMs, atMs);
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
