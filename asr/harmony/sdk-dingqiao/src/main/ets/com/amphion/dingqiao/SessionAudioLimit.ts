import { finiteNumberParam } from './NumericParam';

const MAX_MAX_AUDIO_DURATION_MS: number = 28800000;
const PCM_BYTES_PER_MS: number = 32;

export function maxAudioBytesOf(extraParams: Record<string, Object>): number {
  const durationMs = finiteNumberParam(extraParams, 'maxAudioDuration');
  if (durationMs === undefined || durationMs <= 0) return 0;
  const clampedMs = Math.min(durationMs, MAX_MAX_AUDIO_DURATION_MS);
  // 16 kHz mono 16-bit PCM = 32 bytes per millisecond.
  return Math.max(1, Math.round(clampedMs * PCM_BYTES_PER_MS));
}
