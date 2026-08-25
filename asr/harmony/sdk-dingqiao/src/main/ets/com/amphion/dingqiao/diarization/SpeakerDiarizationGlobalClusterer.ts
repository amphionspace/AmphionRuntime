export interface SpeakerDiarizationEmbeddingObservation {
  embedding: number[];
  durationMs: number;
  onlineSpeakerId: string;
  endTimeMs?: number;
  evidenceKey?: string;
}

export interface SpeakerDiarizationClusterResult {
  observationSpeakerIds: string[];
  clusterCount: number;
  speakerRemap: Record<string, string>;
}

interface MutableCluster {
  indexes: number[];
  centroid: number[];
  durationMs: number;
}

const MAX_MICRO_CLUSTERS = 96;
const MICRO_CLUSTER_THRESHOLD = 0.88;

function normalize(values: number[]): number[] {
  let squaredNorm = 0;
  for (let i = 0; i < values.length; i++) squaredNorm += values[i] * values[i];
  if (squaredNorm <= 0) return values.map((_value: number): number => 0);
  const norm = Math.sqrt(squaredNorm);
  return values.map((value: number): number => value / norm);
}

function cosine(left: number[], right: number[]): number {
  if (left.length !== right.length || left.length === 0) return -1;
  let score = 0;
  for (let i = 0; i < left.length; i++) score += left[i] * right[i];
  return score;
}

/** Duration-weighted AHC with an optional weak speaker-count prior. */
export class SpeakerDiarizationGlobalClusterer {
  private readonly maxSpeakers: number;
  private readonly speakerCountHint: number;
  private readonly similarityThreshold: number;

  constructor(maxSpeakers: number = 4, speakerCountHint: number = 0,
    similarityThreshold: number = 0.72) {
    this.maxSpeakers = maxSpeakers;
    this.speakerCountHint = speakerCountHint;
    this.similarityThreshold = similarityThreshold;
  }

  cluster(observations: SpeakerDiarizationEmbeddingObservation[]): SpeakerDiarizationClusterResult {
    const clusters = this.seedMicroClusters(observations);

    while (clusters.length > 1) {
      let bestLeft = -1;
      let bestRight = -1;
      let bestScore = -1;
      for (let left = 0; left < clusters.length; left++) {
        for (let right = left + 1; right < clusters.length; right++) {
          const score = cosine(clusters[left].centroid, clusters[right].centroid);
          if (score > bestScore) {
            bestScore = score;
            bestLeft = left;
            bestRight = right;
          }
        }
      }
      const weakPriorApplies = this.speakerCountHint > 0 &&
        clusters.length > this.speakerCountHint &&
        bestScore >= this.similarityThreshold - 0.08;
      if (bestScore < this.similarityThreshold && !weakPriorApplies) break;
      this.merge(clusters, bestLeft, bestRight);
    }

    const byDuration = clusters.slice().sort(
      (left: MutableCluster, right: MutableCluster): number =>
        right.durationMs - left.durationMs);
    const observationSpeakerIds = observations.map((_value: SpeakerDiarizationEmbeddingObservation): string =>
      'UNKNOWN');
    const displayIds = this.matchDisplayIds(byDuration, observations);
    for (let clusterIndex = 0; clusterIndex < byDuration.length; clusterIndex++) {
      const cluster = byDuration[clusterIndex];
      const speakerId = displayIds[clusterIndex] ?? 'UNKNOWN';
      for (let i = 0; i < cluster.indexes.length; i++) {
        observationSpeakerIds[cluster.indexes[i]] = speakerId;
      }
    }

    const speakerRemap: Record<string, string> = {};
    const remapDurations = new Map<string, Map<string, number>>();
    for (let i = 0; i < observations.length; i++) {
      const source = observations[i].onlineSpeakerId;
      const target = observationSpeakerIds[i];
      if (source === 'UNKNOWN') continue;
      let targets = remapDurations.get(source);
      if (targets === undefined) {
        targets = new Map<string, number>();
        remapDurations.set(source, targets);
      }
      targets.set(target, (targets.get(target) ?? 0) + observations[i].durationMs);
    }
    remapDurations.forEach((targets: Map<string, number>, source: string): void => {
      let best = source;
      let bestDuration = 0;
      targets.forEach((duration: number, target: string): void => {
        if (duration > bestDuration) {
          bestDuration = duration;
          best = target;
        }
      });
      speakerRemap[source] = best;
    });
    return { observationSpeakerIds, clusterCount: clusters.length, speakerRemap };
  }

  private merge(clusters: MutableCluster[], leftIndex: number, rightIndex: number): void {
    const left = clusters[leftIndex];
    const right = clusters[rightIndex];
    const duration = left.durationMs + right.durationMs;
    const centroid = new Array<number>(left.centroid.length).fill(0);
    for (let i = 0; i < centroid.length; i++) {
      centroid[i] = (left.centroid[i] * left.durationMs +
        right.centroid[i] * right.durationMs) / Math.max(1, duration);
    }
    left.indexes.push(...right.indexes);
    left.centroid = normalize(centroid);
    left.durationMs = duration;
    clusters.splice(rightIndex, 1);
  }

  private seedMicroClusters(observations: SpeakerDiarizationEmbeddingObservation[]): MutableCluster[] {
    const clusters: MutableCluster[] = [];
    for (let index = 0; index < observations.length; index++) {
      const observation = observations[index];
      const centroid = normalize(observation.embedding.slice());
      let bestIndex = -1;
      let bestScore = -1;
      for (let clusterIndex = 0; clusterIndex < clusters.length; clusterIndex++) {
        const score = cosine(clusters[clusterIndex].centroid, centroid);
        if (score > bestScore) {
          bestScore = score;
          bestIndex = clusterIndex;
        }
      }
      if (bestIndex >= 0 &&
        (bestScore >= MICRO_CLUSTER_THRESHOLD || clusters.length >= MAX_MICRO_CLUSTERS)) {
        const temporary: MutableCluster[] = [clusters[bestIndex], {
          indexes: [index], centroid, durationMs: observation.durationMs
        }];
        this.merge(temporary, 0, 1);
        clusters[bestIndex] = temporary[0];
      } else {
        clusters.push({ indexes: [index], centroid, durationMs: observation.durationMs });
      }
    }
    return clusters;
  }

  private matchDisplayIds(clusters: MutableCluster[],
    observations: SpeakerDiarizationEmbeddingObservation[]): string[] {
    const assignable = Math.min(this.maxSpeakers, clusters.length);
    const candidates = new Array<string>(this.maxSpeakers);
    for (let index = 0; index < candidates.length; index++) candidates[index] = `S${index + 1}`;
    let bestScore = Number.NEGATIVE_INFINITY;
    let best: string[] = [];
    const search = (clusterIndex: number, remaining: string[], current: string[], score: number): void => {
      if (clusterIndex >= assignable) {
        if (score > bestScore) {
          bestScore = score;
          best = current.slice();
        }
        return;
      }
      for (let index = 0; index < remaining.length; index++) {
        const speakerId = remaining[index];
        const nextRemaining = remaining.slice();
        nextRemaining.splice(index, 1);
        search(clusterIndex + 1, nextRemaining, current.concat(speakerId),
          score + this.clusterDisplayDuration(clusters[clusterIndex], observations, speakerId));
      }
    };
    search(0, candidates, [], 0);
    while (best.length < clusters.length) best.push('UNKNOWN');
    return best;
  }

  private clusterDisplayDuration(cluster: MutableCluster,
    observations: SpeakerDiarizationEmbeddingObservation[], speakerId: string): number {
    let durationMs = 0;
    for (let index = 0; index < cluster.indexes.length; index++) {
      const observation = observations[cluster.indexes[index]];
      if (observation.onlineSpeakerId === speakerId) durationMs += observation.durationMs;
    }
    return durationMs;
  }

}
