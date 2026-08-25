import { finiteNumberParam } from './NumericParam';

const DEFAULT_ENDPOINT_MAX_UTTERANCE_SEC: number = 20;

export interface Rule3Policy {
  mode: string;
  enabled: boolean;
  minUtteranceSec: number;
}

export function endpointMaxUtteranceSec(extraParams: Record<string, Object>): number {
  const durationMs = finiteNumberParam(extraParams, 'endpointMaxUtteranceMs');
  if (durationMs === undefined || durationMs <= 0) {
    return DEFAULT_ENDPOINT_MAX_UTTERANCE_SEC;
  }
  return durationMs / 1000;
}

export function rule3Policy(engineExtraParams: Record<string, Object>,
  sessionExtraParams: Record<string, Object>): Rule3Policy {
  const rawMode = sessionExtraParams['recognizerMode'] ?? engineExtraParams['recognizerMode'];
  const mode = rawMode === undefined ? 'long' : `${rawMode}`.trim().toLowerCase();
  if (mode !== 'short' && mode !== 'long') {
    throw new Error('recognizerMode must be short or long');
  }
  return {
    mode: mode,
    enabled: mode === 'short',
    minUtteranceSec: mode === 'short' ? endpointMaxUtteranceSec(sessionExtraParams) : -1
  };
}

export function endpointRecognizerConfigKey(withTargetSpeaker: boolean, withSpeakerVad: boolean,
  engineExtraParams: Record<string, Object>, sessionExtraParams: Record<string, Object>): string {
  const policy = rule3Policy(engineExtraParams, sessionExtraParams);
  return [
    `${withTargetSpeaker}`,
    `${withSpeakerVad}`,
    policy.mode,
    `${policy.enabled}`,
    `${policy.minUtteranceSec}`
  ].join('|');
}
