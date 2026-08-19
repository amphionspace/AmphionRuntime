import { AudioInfo, StartParams } from 'amphion_dingqiao';

export type CustomerScenarioName =
  'tap-vad' | 'ptt' | 'transcription' | 'form' | 'meeting-minutes';

export interface CustomerScenarioProfile {
  name: CustomerScenarioName;
  audioSource: 'mic' | 'voiceCommunication' | 'voiceRecognition';
  vadBegin?: number;
  vadEnd: number;
  maxAudioDuration: number;
  endpointMaxUtteranceMs: number;
  enablePartialResult: boolean;
  allowVoiceprint: boolean;
  rotateSession: boolean;
  lockAudioSource: boolean;
}

export const CUSTOMER_TAP_VAD: CustomerScenarioProfile = {
  name: 'tap-vad',
  audioSource: 'voiceCommunication',
  vadBegin: 5000,
  vadEnd: 1600,
  maxAudioDuration: 20000,
  endpointMaxUtteranceMs: 20000,
  enablePartialResult: true,
  allowVoiceprint: true,
  rotateSession: true,
  lockAudioSource: false
};

export const CUSTOMER_PTT: CustomerScenarioProfile = {
  name: 'ptt',
  audioSource: 'voiceCommunication',
  vadEnd: 1600,
  maxAudioDuration: 62000,
  endpointMaxUtteranceMs: 20000,
  enablePartialResult: true,
  allowVoiceprint: true,
  rotateSession: true,
  lockAudioSource: false
};

export const CUSTOMER_TRANSCRIPTION: CustomerScenarioProfile = {
  name: 'transcription',
  audioSource: 'voiceRecognition',
  vadEnd: 1600,
  maxAudioDuration: 62000,
  endpointMaxUtteranceMs: 60000,
  enablePartialResult: true,
  allowVoiceprint: true,
  rotateSession: true,
  lockAudioSource: false
};

export const CUSTOMER_FORM: CustomerScenarioProfile = {
  name: 'form',
  audioSource: 'mic',
  vadEnd: 1500,
  maxAudioDuration: 28800000,
  endpointMaxUtteranceMs: 60000,
  enablePartialResult: true,
  allowVoiceprint: false,
  rotateSession: false,
  lockAudioSource: true
};

export const CUSTOMER_MEETING_MINUTES: CustomerScenarioProfile = {
  name: 'meeting-minutes',
  audioSource: 'mic',
  vadEnd: 1500,
  maxAudioDuration: 18000000,
  endpointMaxUtteranceMs: 60000,
  enablePartialResult: true,
  allowVoiceprint: false,
  rotateSession: false,
  lockAudioSource: true
};

export function customerScenarioProfile(name: CustomerScenarioName): CustomerScenarioProfile {
  if (name === 'tap-vad') return CUSTOMER_TAP_VAD;
  if (name === 'transcription') return CUSTOMER_TRANSCRIPTION;
  if (name === 'form') return CUSTOMER_FORM;
  if (name === 'meeting-minutes') return CUSTOMER_MEETING_MINUTES;
  return CUSTOMER_PTT;
}

export function customerProfileStartParams(sessionId: string, name: CustomerScenarioName): StartParams {
  const profile = customerScenarioProfile(name);
  const params = new StartParams();
  params.sessionId = sessionId;
  params.audioInfo = new AudioInfo();
  params.extraParams['enablePartialResult'] = profile.enablePartialResult;
  params.extraParams['vadEnd'] = profile.vadEnd;
  params.extraParams['maxAudioDuration'] = profile.maxAudioDuration;
  params.extraParams['endpointMaxUtteranceMs'] = profile.endpointMaxUtteranceMs;
  if (profile.vadBegin !== undefined) params.extraParams['vadBegin'] = profile.vadBegin;
  return params;
}
