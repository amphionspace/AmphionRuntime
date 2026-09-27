export interface CommunityIdentityAssignment {
  mapping: number[];
  votes: number[][];
  before: number;
  after: number;
}

/** Preserve published IDs using shared acoustic windows, never reference labels. */
export class CommunitySpeakerIdentity {
  private committedIds: Map<string, number> = new Map<string, number>();
  private committedActivity: Map<string, number> = new Map<string, number>();
  private enrollmentWindows: Set<string> = new Set<string>();
  private nextId: number = 0;
  private readonly maxSpeakers: number;

  constructor(maxSpeakers: number) { this.maxSpeakers = maxSpeakers; }

  fork(): CommunitySpeakerIdentity {
    const copy = new CommunitySpeakerIdentity(this.maxSpeakers);
    copy.committedIds = new Map(this.committedIds);
    copy.committedActivity = new Map(this.committedActivity);
    copy.enrollmentWindows = new Set(this.enrollmentWindows);
    copy.nextId = this.nextId;
    return copy;
  }

  /** Keep the evidence that established each identity, once per enrollment.
   * VBx depends on observation support; a single selected window is not an
   * equivalent summary of the batch that established a frozen identity.
   */
  anchorWindowIds(): string[] {
    return Array.from(this.enrollmentWindows);
  }

  retainWindows(windowIds: string[]): void {
    const retained = new Set<string>(windowIds);
    this.committedIds.forEach((_id: number, key: string): void => {
      if (retained.has(key.substring(0, key.lastIndexOf(':')))) return;
      this.committedIds.delete(key);
      this.committedActivity.delete(key);
    });
  }

  assign(windowIds: string[], hard: number[], clusterCount: number, activity: number[],
    publishedActivity: number[] = activity, visibleClusters?: boolean[]): CommunityIdentityAssignment {
    const before = this.nextId;
    const votes: number[][] = [];
    for (let cluster = 0; cluster < clusterCount; cluster++) votes.push(new Array<number>(before).fill(0));
    const keys = hard.map((_label, index) => `${windowIds[Math.floor(index / 3)]}:${index % 3}`);
    for (let index = 0; index < hard.length; index++) {
      const oldId = this.committedIds.get(keys[index]) ?? -1;
      if (oldId >= 0 && hard[index] >= 0) {
        votes[hard[index]][oldId] += this.committedActivity.get(keys[index]) ?? 0;
      }
    }
    let bestScore = -1;
    let best: number[] = new Array<number>(clusterCount).fill(-1);
    const current = best.slice();
    const visit = (cluster: number, used: number, score: number): void => {
      if (cluster === clusterCount) {
        if (score > bestScore) { bestScore = score; best = current.slice(); }
        return;
      }
      for (let id = 0; id < before; id++) {
        if ((used & (1 << id)) !== 0 || votes[cluster][id] <= 0) continue;
        current[cluster] = id;
        visit(cluster + 1, used | (1 << id), score + votes[cluster][id]);
      }
      current[cluster] = -1;
      visit(cluster + 1, used, score);
    };
    visit(0, 0, 0);
    for (let cluster = 0; cluster < clusterCount; cluster++) {
      const hasActivity = (visibleClusters === undefined || visibleClusters[cluster]) &&
        hard.some((label, index) => label === cluster && publishedActivity[index] > 0);
      if (hasActivity && best[cluster] < 0 && this.nextId < this.maxSpeakers) best[cluster] = this.nextId++;
    }
    // A later clustering may merge or rename clusters, but it cannot erase the
    // acoustic evidence that established an already published public identity.
    for (let index = 0; index < hard.length; index++) {
      const cluster = hard[index];
      if ((this.committedIds.get(keys[index]) ?? -1) >= 0 || cluster < 0 || best[cluster] < 0 ||
        publishedActivity[index] <= 0 || (visibleClusters !== undefined && !visibleClusters[cluster])) continue;
      this.committedIds.set(keys[index], best[cluster]);
      this.committedActivity.set(keys[index], publishedActivity[index]);
      if (best[cluster] >= before) this.enrollmentWindows.add(windowIds[Math.floor(index / 3)]);
    }
    return { mapping: best, votes, before, after: this.nextId };
  }
}

export interface CommunityTimelineTurn {
  beginTime: number;
  endTime: number;
  speakerId: string;
  secondarySpeakerIds: string[];
  confidence: number;
  overlap: boolean;
}

/** Turn concurrent tracks into the SDK timeline without dropping any track. */
export function communityTimeline(tracks: number[][], mapping: number[],
  beginTime: number, endTime: number): CommunityTimelineTurn[] {
  const boundaries: number[] = [beginTime, endTime];
  for (const track of tracks) {
    if (track[0] >= endTime || track[1] <= beginTime) continue;
    boundaries.push(Math.max(beginTime, track[0]), Math.min(endTime, track[1]));
  }
  boundaries.sort((a, b) => a - b);
  const unique = boundaries.filter((value, index) => index === 0 || value !== boundaries[index - 1]);
  const result: CommunityTimelineTurn[] = [];
  let previous = '';
  for (let index = 1; index < unique.length; index++) {
    const begin = unique[index - 1], end = unique[index];
    const ids: string[] = [];
    for (const track of tracks) {
      if (track[0] >= end || track[1] <= begin) continue;
      const label = mapping[track[2]] ?? -1;
      const id = label >= 0 ? `S${label + 1}` : 'UNKNOWN';
      if (!ids.includes(id)) ids.push(id);
    }
    if (ids.length === 0) { previous = ''; continue; }
    ids.sort();
    const primary = ids.includes(previous) ? previous : ids[0];
    const secondary = ids.filter(id => id !== primary);
    const overlap = tracks.filter(track => track[0] < end && track[1] > begin).length > 1;
    const last = result[result.length - 1];
    if (last !== undefined && last.endTime === begin && last.speakerId === primary &&
      last.secondarySpeakerIds.join(',') === secondary.join(',') && last.overlap === overlap) {
      last.endTime = end;
    } else result.push({ beginTime: begin, endTime: end, speakerId: primary,
      secondarySpeakerIds: secondary, confidence: 0, overlap });
    previous = primary;
  }
  return result;
}
