// Concurrent per-speaker tracks ([beginTime, endTime, slot] in ms, optionally with a
// per-track identity at index 3) become the SDK's non-overlapping timeline: every
// boundary opens a turn whose primary speaker prefers continuity and whose secondaries
// carry the rest. Nothing is dropped.
//
// 为什么要支持"按段携带身份"：Sortformer 的槽位会把不同的人并进同一个槽位（依次发言场景
// 主机 4/10、真机同口径 10/10 复现），而槽位→公开 id 的映射无法拆开同槽的两个人。声纹身份
// 是按发言段判的，所以 track[3] 存在且 >= 0 时优先用它；不存在时回落到槽位映射，
// 关闭声纹身份时行为与原先完全一致。
export interface TimelineTurn {
  beginTime: number;
  endTime: number;
  speakerId: string;
  secondarySpeakerIds: string[];
  confidence: number;
  overlap: boolean;
  /**
   * 只按 Sortformer 槽位映射得到的主身份，与 speakerId 并行算出。
   *
   * 开启声纹身份后 speakerId 由声纹给出，这里保留模型自己的判断，调用方才能在现场对比与
   * 回退；关闭时两者相同。
   */
  modelSpeakerId: string;
}

/** Turn concurrent tracks into the SDK timeline without dropping any track. */
export function timelineTurns(tracks: number[][], mapping: number[],
  beginTime: number, endTime: number): TimelineTurn[] {
  const boundaries: number[] = [beginTime, endTime];
  for (const track of tracks) {
    if (track[0] >= endTime || track[1] <= beginTime) continue;
    boundaries.push(Math.max(beginTime, track[0]), Math.min(endTime, track[1]));
  }
  boundaries.sort((a, b) => a - b);
  // API 23 es2abc misparses `< unique.length` as a type expression.
  const uniqueBoundaries = boundaries.filter((value, index) => index === 0 || value !== boundaries[index - 1]);
  const result: TimelineTurn[] = [];
  let previous = '';
  for (let index = 1; index < uniqueBoundaries.length; index++) {
    const begin = uniqueBoundaries[index - 1], end = uniqueBoundaries[index];
    const ids: string[] = [];
    const modelIds: string[] = [];
    for (const track of tracks) {
      if (track[0] >= end || track[1] <= begin) continue;
      // track[3] 是声纹身份（开启 speakerIdentityMode 时由 SpeakerIdentityAssigner 给出）；
      // -1 表示该段未赋身份（例如短于最小时长），照实落到 UNKNOWN，不猜。
      const assigned = track.length > 3 ? track[3] : -2;
      const slotLabel = mapping[track[2]] ?? -1;
      const label = assigned !== -2 ? assigned : slotLabel;
      const id = label >= 0 ? `S${label + 1}` : 'UNKNOWN';
      if (!ids.includes(id)) ids.push(id);
      const modelId = slotLabel >= 0 ? `S${slotLabel + 1}` : 'UNKNOWN';
      if (!modelIds.includes(modelId)) modelIds.push(modelId);
    }
    if (ids.length === 0) { previous = ''; continue; }
    ids.sort();
    modelIds.sort();
    const primary = ids.includes(previous) ? previous : ids[0];
    const secondary = ids.filter(id => id !== primary);
    const modelPrimary = modelIds.length > 0 ? modelIds[0] : 'UNKNOWN';
    const overlap = tracks.filter(track => track[0] < end && track[1] > begin).length > 1;
    const last = result[result.length - 1];
    // 合并相邻片段时也要比 modelSpeakerId：否则一个 turn 会横跨不同的模型槽位，
    // 那个字段就失去对比价值了。
    if (last !== undefined && last.endTime === begin && last.speakerId === primary &&
      last.secondarySpeakerIds.join(',') === secondary.join(',') && last.overlap === overlap &&
      last.modelSpeakerId === modelPrimary) {
      last.endTime = end;
    } else result.push({ beginTime: begin, endTime: end, speakerId: primary,
      secondarySpeakerIds: secondary, confidence: 0, overlap, modelSpeakerId: modelPrimary });
    previous = primary;
  }
  return result;
}
