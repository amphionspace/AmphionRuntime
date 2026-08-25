export const UNASSIGNED_SPEAKER_INDEX: number = -1;

export function speakerIndexFromInternalId(speakerId: string, maxSpeakers: number = 4): number {
  if (!speakerId.startsWith('S')) return UNASSIGNED_SPEAKER_INDEX;
  const value = Number(speakerId.substring(1));
  return Number.isInteger(value) && value > 0 && value <= maxSpeakers ?
    value - 1 : UNASSIGNED_SPEAKER_INDEX;
}

export function speakerIndexesFromInternalIds(speakerIds: string[], maxSpeakers: number = 4): number[] {
  const indexes: number[] = [];
  for (let index = 0; index < speakerIds.length; index++) {
    const value = speakerIndexFromInternalId(speakerIds[index], maxSpeakers);
    if (value >= 0 && indexes.indexOf(value) < 0) indexes.push(value);
  }
  return indexes;
}
