import { AudioInfo, StartParams } from 'amphion_dingqiao';

export type CustomerScenarioName = 'tap-vad' | 'ptt' | 'transcription';

export interface CustomerScenarioProfile {
  name: CustomerScenarioName;
  audioSource: 'voiceCommunication' | 'voiceRecognition';
  vadBegin?: number;
  vadEnd: number;
  endpointMaxUtteranceMs: number;
  maxAudioDuration: number;
  enablePartialResult: boolean;
}

export const CUSTOMER_TAP_VAD: CustomerScenarioProfile = {
  name: 'tap-vad',
  audioSource: 'voiceCommunication',
  vadBegin: 5000,
  vadEnd: 1600,
  endpointMaxUtteranceMs: 20000,
  maxAudioDuration: 20000,
  enablePartialResult: true
};

export const CUSTOMER_PTT: CustomerScenarioProfile = {
  name: 'ptt',
  audioSource: 'voiceCommunication',
  vadEnd: 1600,
  endpointMaxUtteranceMs: 55000,
  maxAudioDuration: 62000,
  enablePartialResult: true
};

export const CUSTOMER_TRANSCRIPTION: CustomerScenarioProfile = {
  name: 'transcription',
  audioSource: 'voiceRecognition',
  vadEnd: 1600,
  endpointMaxUtteranceMs: 55000,
  maxAudioDuration: 62000,
  enablePartialResult: true
};

export function customerScenarioProfile(name: CustomerScenarioName): CustomerScenarioProfile {
  if (name === 'tap-vad') return CUSTOMER_TAP_VAD;
  if (name === 'transcription') return CUSTOMER_TRANSCRIPTION;
  return CUSTOMER_PTT;
}

export function customerProfileStartParams(sessionId: string, name: CustomerScenarioName): StartParams {
  const profile = customerScenarioProfile(name);
  const params = new StartParams();
  params.sessionId = sessionId;
  params.audioInfo = new AudioInfo();
  params.extraParams['enablePartialResult'] = profile.enablePartialResult;
  params.extraParams['vadEnd'] = profile.vadEnd;
  params.extraParams['endpointMaxUtteranceMs'] = profile.endpointMaxUtteranceMs;
  params.extraParams['maxAudioDuration'] = profile.maxAudioDuration;
  if (profile.vadBegin !== undefined) params.extraParams['vadBegin'] = profile.vadBegin;
  return params;
}
