export const UNASSIGNED_SPEAKER_INDEX: number = -1;

export function speakerIndexFromInternalId(speakerId: string, _maxSpeakers?: number): number {
  if (!speakerId.startsWith('S')) return UNASSIGNED_SPEAKER_INDEX;
  const value = Number(speakerId.substring(1));
  return Number.isInteger(value) && value > 0 ?
    value - 1 : UNASSIGNED_SPEAKER_INDEX;
}

export function speakerIndexesFromInternalIds(speakerIds: string[], maxSpeakers?: number,
  preserveUnassigned: boolean = false): number[] {
  const indexes: number[] = [];
  for (let index = 0; index < speakerIds.length; index++) {
    const value = speakerIndexFromInternalId(speakerIds[index], maxSpeakers);
    if (value >= 0 && indexes.indexOf(value) < 0) {
      indexes.push(value);
    } else if (value < 0 && preserveUnassigned && indexes.indexOf(UNASSIGNED_SPEAKER_INDEX) < 0) {
      indexes.push(UNASSIGNED_SPEAKER_INDEX);
    }
  }
  return indexes;
}
