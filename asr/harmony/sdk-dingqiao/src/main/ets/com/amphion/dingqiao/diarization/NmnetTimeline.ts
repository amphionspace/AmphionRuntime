export interface NmnetTimelineTurn {
  beginTime: number;
  endTime: number;
  speakerId: string;
  secondarySpeakerIds: string[];
  confidence: number;
  overlap: boolean;
}

/** Turn concurrent tracks into the SDK timeline without dropping any track. */
export function nmnetTimeline(tracks: number[][], mapping: number[],
  beginTime: number, endTime: number): NmnetTimelineTurn[] {
  const boundaries: number[] = [beginTime, endTime];
  for (const track of tracks) {
    if (track[0] >= endTime || track[1] <= beginTime) continue;
    boundaries.push(Math.max(beginTime, track[0]), Math.min(endTime, track[1]));
  }
  boundaries.sort((a, b) => a - b);
  // API 23 es2abc misparses `< unique.length` as a type expression.
  const uniqueBoundaries = boundaries.filter((value, index) => index === 0 || value !== boundaries[index - 1]);
  const result: NmnetTimelineTurn[] = [];
  let previous = '';
  for (let index = 1; index < uniqueBoundaries.length; index++) {
    const begin = uniqueBoundaries[index - 1], end = uniqueBoundaries[index];
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
