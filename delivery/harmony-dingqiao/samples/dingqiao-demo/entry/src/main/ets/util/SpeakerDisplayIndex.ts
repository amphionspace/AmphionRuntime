/** Maps sparse SDK speaker indexes to contiguous, first-seen display indexes. */
export function compactSpeakerDisplayIndexes(speakerIndexes: number[]): number[] {
  const displayBySpeaker = new Map<number, number>();
  const result: number[] = [];
  let nextDisplayIndex = 0;
  for (let index = 0; index < speakerIndexes.length; index++) {
    const speakerIndex = speakerIndexes[index];
    if (speakerIndex < 0) {
      result.push(-1);
      continue;
    }
    let displayIndex = displayBySpeaker.get(speakerIndex);
    if (displayIndex === undefined) {
      displayIndex = nextDisplayIndex;
      nextDisplayIndex++;
      displayBySpeaker.set(speakerIndex, displayIndex);
    }
    result.push(displayIndex);
  }
  return result;
}
