export interface SpeakerDiarizationConfigValue {
  minSpeakers?: number;
  maxSpeakers?: number;
}

export interface ValidatedSpeakerDiarizationConfig {
  minSpeakers?: number;
  maxSpeakers?: number;
}

export function validateSpeakerDiarizationConfig(
  config: SpeakerDiarizationConfigValue): ValidatedSpeakerDiarizationConfig {
  if (config.minSpeakers !== undefined && (!Number.isFinite(config.minSpeakers) ||
    !Number.isInteger(config.minSpeakers) || config.minSpeakers < 1)) {
    throw new Error('SpeakerDiarizationConfig.minSpeakers must be a positive integer');
  }
  if (config.maxSpeakers !== undefined && (!Number.isFinite(config.maxSpeakers) ||
    !Number.isInteger(config.maxSpeakers) || config.maxSpeakers < 1)) {
    throw new Error('SpeakerDiarizationConfig.maxSpeakers must be a positive integer');
  }
  if (config.minSpeakers !== undefined && config.maxSpeakers !== undefined &&
    config.minSpeakers > config.maxSpeakers) {
    throw new Error('SpeakerDiarizationConfig.minSpeakers must not exceed maxSpeakers');
  }
  return { minSpeakers: config.minSpeakers, maxSpeakers: config.maxSpeakers };
}
