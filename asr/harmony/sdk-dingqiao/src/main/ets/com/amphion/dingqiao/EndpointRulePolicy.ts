import { finiteNumberParam } from './NumericParam';

const DEFAULT_ENDPOINT_MAX_UTTERANCE_SEC: number = 20;

export function endpointMaxUtteranceSec(extraParams: Record<string, Object>): number {
  const durationMs = finiteNumberParam(extraParams, 'endpointMaxUtteranceMs');
  if (durationMs === undefined || durationMs <= 0) {
    return DEFAULT_ENDPOINT_MAX_UTTERANCE_SEC;
  }
  return durationMs / 1000;
}

export function endpointRecognizerConfigKey(withTargetSpeaker: boolean, withSpeakerVad: boolean,
  extraParams: Record<string, Object>): string {
  return [
    `${withTargetSpeaker}`,
    `${withSpeakerVad}`,
    `${endpointMaxUtteranceSec(extraParams)}`
  ].join('|');
}
