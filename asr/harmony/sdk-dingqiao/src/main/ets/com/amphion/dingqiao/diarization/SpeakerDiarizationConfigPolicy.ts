export interface SpeakerDiarizationConfigValue {
  maxSpeakers: number;
  numThreads?: number;
}

export const DEFAULT_SPEAKER_DIARIZATION_THREADS: number = 2;
export const MAX_SPEAKER_DIARIZATION_THREADS: number = 8;

export function validateSpeakerDiarizationConfig(
  config: SpeakerDiarizationConfigValue): number {
  if (!Number.isFinite(config.maxSpeakers) || !Number.isInteger(config.maxSpeakers) ||
    config.maxSpeakers < 1 || config.maxSpeakers > 4) {
    throw new Error('SpeakerDiarizationConfig.maxSpeakers must be an integer in [1, 4]');
  }
  return config.maxSpeakers;
}

/**
 * Community encoder worker budget. It is intentionally separate from the ASR
 * `numThreads`: the encoder builds its own pthread pool, so the ASR value does
 * not bound it, and an explicit budget is the only way to cap that pool.
 */
export function validateSpeakerDiarizationThreads(
  config: SpeakerDiarizationConfigValue): number {
  const threads = config.numThreads ?? DEFAULT_SPEAKER_DIARIZATION_THREADS;
  if (!Number.isFinite(threads) || !Number.isInteger(threads) ||
    threads < 1 || threads > MAX_SPEAKER_DIARIZATION_THREADS) {
    throw new Error('SpeakerDiarizationConfig.numThreads must be an integer in [1, 8]');
  }
  return threads;
}
