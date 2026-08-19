const DEFAULT_ENDPOINT_MAX_UTTERANCE_SEC: number = 20;

export function endpointMaxUtteranceSec(extraParams: Record<string, Object>): number {
  const value = extraParams['endpointMaxUtteranceMs'];
  let durationMs: number | undefined;
  if (typeof value === 'number') {
    durationMs = Number.isFinite(value) ? value : undefined;
  } else if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number(value.trim());
    durationMs = Number.isFinite(parsed) ? parsed : undefined;
  }
  if (durationMs === undefined || durationMs <= 0) {
    return DEFAULT_ENDPOINT_MAX_UTTERANCE_SEC;
  }
  return durationMs / 1000;
}
