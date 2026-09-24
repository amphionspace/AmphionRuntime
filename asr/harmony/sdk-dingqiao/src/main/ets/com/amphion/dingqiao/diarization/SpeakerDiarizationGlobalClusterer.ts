export interface SpeakerDiarizationEmbeddingObservation {
  embedding: number[];
  durationMs: number;
  onlineSpeakerId: string;
  endTimeMs?: number;
  evidenceKey?: string;
  anchorId?: string;
  queryEmbedding?: number[];
  complementaryEmbedding?: number[];
  speechRms?: number;
  levelEligibleAtObservation?: boolean;
}

export interface SpeakerDiarizationClusterResult {
  observationSpeakerIds: string[];
  clusterCount: number;
  speakerRemap: Record<string, string>;
  clusters: MutableCluster[];
}

export interface MutableCluster {
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
  private readonly speakerCountHint: number;
  private readonly similarityThreshold: number;

  constructor(_maxSpeakers?: number, speakerCountHint: number = 0,
    similarityThreshold: number = 0.6) {
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
          if (!this.compatible(clusters[left].indexes, clusters[right].indexes, observations)) continue;
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
    return { observationSpeakerIds, clusterCount: clusters.length, speakerRemap, clusters: byDuration };
  }

  private compatible(left: number[], right: number[], observations: SpeakerDiarizationEmbeddingObservation[]): boolean {
    let anchor: string | undefined;
    for (const index of left.concat(right)) {
      const id = observations[index].anchorId;
      if (id === undefined) continue;
      if (anchor !== undefined && anchor !== id) return false;
      anchor = id;
    }
    return true;
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
        if (!this.compatible(clusters[clusterIndex].indexes, [index], observations)) continue;
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
    const observed = new Set<string>();
    for (const item of observations) {
      if (item.onlineSpeakerId.startsWith('S')) observed.add(item.onlineSpeakerId);
    }
    const used = new Set<string>();
    const result: string[] = [];
    for (const cluster of clusters) {
      let best = '';
      let bestDuration = 0;
      observed.forEach((speakerId: string): void => {
        if (used.has(speakerId)) return;
        const duration = this.clusterDisplayDuration(cluster, observations, speakerId);
        if (duration > bestDuration) { bestDuration = duration; best = speakerId; }
      });
      if (best.length === 0) {
        let index = 1;
        while (used.has(`S${index}`) || observed.has(`S${index}`)) index += 1;
        best = `S${index}`;
      }
      used.add(best);
      result.push(best);
    }
    return result;
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
