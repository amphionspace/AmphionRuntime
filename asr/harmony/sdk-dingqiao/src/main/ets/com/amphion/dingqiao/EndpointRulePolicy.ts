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

/**
 * The caller's utterance ceiling for the long-form path, or undefined to keep
 * the SDK default.
 *
 * endpointMaxUtteranceMs configures rule3, which the long-form path disables,
 * so before this the value was accepted and then ignored there. Reading it for
 * the long-form cut as well keeps one knob meaning one thing - how long a
 * caller waits for a final - instead of silently applying to one mode only.
 * Undefined rather than a default, because the long-form default is the SDK's
 * buffer bound and not rule3's 20 s.
 */
export function longFormMaxUtteranceSec(
  sessionExtraParams: Record<string, Object>): number | undefined {
  const durationMs = finiteNumberParam(sessionExtraParams, 'endpointMaxUtteranceMs');
  if (durationMs === undefined || durationMs <= 0) return undefined;
  return durationMs / 1000;
}

export function rule3Policy(engineExtraParams: Record<string, Object>,
  sessionExtraParams: Record<string, Object>): Rule3Policy {
  const rawMode = sessionExtraParams['recognizerMode'] ?? engineExtraParams['recognizerMode'];
  // Preserve legacy hard endpoints for ordinary callers that never supplied a mode. The existing
  // continuous-session opt-in already promises one model session with retained context, so it must
  // use the lossless long-form path unless the caller explicitly selects short.
  const defaultMode = sessionExtraParams['enableContinuousRecognition'] === true ? 'long' : 'short';
  const mode = rawMode === undefined ? defaultMode : `${rawMode}`.trim().toLowerCase();
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
  return [
    `${withTargetSpeaker}`,
    `${withSpeakerVad}`,
    endpointRecognizerRuntimeConfigKey(engineExtraParams, sessionExtraParams)
  ].join('|');
}

/** Configuration that is baked into OnlineRecognizer and therefore requires a model rebuild. */
export function endpointRecognizerRuntimeConfigKey(engineExtraParams: Record<string, Object>,
  sessionExtraParams: Record<string, Object>): string {
  const policy = rule3Policy(engineExtraParams, sessionExtraParams);
  return [
    policy.mode,
    `${policy.enabled}`,
    `${policy.minUtteranceSec}`
  ].join('|');
}
