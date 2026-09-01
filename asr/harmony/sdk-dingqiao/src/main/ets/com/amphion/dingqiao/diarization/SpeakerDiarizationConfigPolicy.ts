export interface SpeakerDiarizationConfigValue {
  maxSpeakers: number;
}

export function validateSpeakerDiarizationConfig(
  config: SpeakerDiarizationConfigValue): number {
  if (!Number.isFinite(config.maxSpeakers) || !Number.isInteger(config.maxSpeakers) ||
    config.maxSpeakers < 1 || config.maxSpeakers > 4) {
    throw new Error('SpeakerDiarizationConfig.maxSpeakers must be an integer in [1, 4]');
  }
  return config.maxSpeakers;
}
