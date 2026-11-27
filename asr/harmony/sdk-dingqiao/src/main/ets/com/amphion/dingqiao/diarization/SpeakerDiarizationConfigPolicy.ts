export interface SpeakerDiarizationConfigValue {
  maxSpeakers: number;
  speakerIdentityMode?: string;
}

/** 角色身份的来源。'model' 沿用 Sortformer 槽位；'voiceprint' 按发言段用声纹嵌入判。 */
export const SPEAKER_IDENTITY_MODES: string[] = ['model', 'voiceprint'];

export function validateSpeakerDiarizationConfig(
  config: SpeakerDiarizationConfigValue): number {
  if (!Number.isFinite(config.maxSpeakers) || !Number.isInteger(config.maxSpeakers) ||
    config.maxSpeakers < 1 || config.maxSpeakers > 4) {
    throw new Error('SpeakerDiarizationConfig.maxSpeakers must be an integer in [1, 4]');
  }
  validateSpeakerIdentityMode(config.speakerIdentityMode);
  return config.maxSpeakers;
}

/**
 * 校验并归一身份来源。未设置时返回 'voiceprint'（0.3.27 起的默认）；'model' 为 0.3.26 行为的显式回退。
 *
 * 拼错的值必须抛错而不是静默回落到 'model'：那会让调用方以为打开了声纹身份、
 * 而实际跑的还是模型槽位，现场排查时极难发现。
 */
export function validateSpeakerIdentityMode(mode?: string): string {
  if (mode === undefined) return 'voiceprint';
  if (!SPEAKER_IDENTITY_MODES.includes(mode)) {
    throw new Error(
      `SpeakerDiarizationConfig.speakerIdentityMode must be one of ${SPEAKER_IDENTITY_MODES.join(', ')}`);
  }
  return mode;
}
