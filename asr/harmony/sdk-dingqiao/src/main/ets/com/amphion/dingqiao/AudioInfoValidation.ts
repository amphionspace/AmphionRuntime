export interface DingqiaoAudioInfo {
  audioType: string;
  sampleRate: number;
  sampleBit: number;
  soundChannel: number;
}

export function validateAudioInfo(audioInfo: DingqiaoAudioInfo): string {
  if (audioInfo.audioType !== 'pcm') return 'audioType must be pcm';
  if (audioInfo.sampleRate !== 16000) return 'sampleRate must be 16000';
  if (audioInfo.sampleBit !== 16) return 'sampleBit must be 16';
  if (audioInfo.soundChannel !== 1) return 'soundChannel must be 1';
  return '';
}
