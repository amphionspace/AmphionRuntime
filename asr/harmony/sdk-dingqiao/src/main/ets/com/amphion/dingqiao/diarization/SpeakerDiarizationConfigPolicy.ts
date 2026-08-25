export interface SpeakerDiarizationConfigValue {
  maxSpeakers: number;
}

export const SPEAKER_DIARIZATION_PROCESS_ENTRY: string =
  './ets/diarization/SpeakerDiarizationChild.ets';

export function resolveSpeakerDiarizationProcessEntry(moduleName: string): string {
  if (moduleName.length === 0) throw new Error('speaker diarization host module name is empty');
  return `${moduleName}/${SPEAKER_DIARIZATION_PROCESS_ENTRY}`;
}

export function validateSpeakerDiarizationConfig(config: SpeakerDiarizationConfigValue): number {
  if (!Number.isFinite(config.maxSpeakers) || !Number.isInteger(config.maxSpeakers) ||
    config.maxSpeakers < 1 || config.maxSpeakers > 4) {
    throw new Error('SpeakerDiarizationConfig.maxSpeakers must be an integer in [1, 4]');
  }
  return config.maxSpeakers;
}
