const SPEAKER_VAD_THRESHOLD = 0.35;
const SPEAKER_VAD_WINDOW_MS = 1500;
const SPEAKER_VAD_HOP_MS = 500;
const SPEAKER_VAD_CONSECUTIVE_BELOW = 2;

/** Per-session selection captured when the user taps Start. */
export class SpeakerPipelineConfig {
  voiceprintId: string = '';
  voiceprintVerify: boolean = false;
  speakerVad: boolean = false;
  targetSpeakerEnhancement: boolean = false;
}

export function captureSpeakerPipelineConfig(
  voiceprintId: string,
  voiceprintVerifyDesired: boolean,
  speakerVadDesired: boolean,
  targetSpeakerEnhancementDesired: boolean
): SpeakerPipelineConfig {
  const config = new SpeakerPipelineConfig();
  config.voiceprintId = voiceprintId.trim();
  if (config.voiceprintId.length === 0) return config;
  config.voiceprintVerify = voiceprintVerifyDesired;
  config.targetSpeakerEnhancement = targetSpeakerEnhancementDesired;
  // The enhancement selector depends on Speaker VAD's enrolled-speaker decision.
  config.speakerVad = speakerVadDesired || config.targetSpeakerEnhancement;
  return config;
}

export function applySpeakerPipelineConfig(
  extra: Record<string, Object>,
  config: SpeakerPipelineConfig
): void {
  if (config.voiceprintVerify) extra['enableVoiceprintVerification'] = true;
  if (config.speakerVad) {
    extra['enableSpeakerVad'] = true;
    extra['speakerVadThreshold'] = SPEAKER_VAD_THRESHOLD;
    extra['speakerVadWindowMs'] = SPEAKER_VAD_WINDOW_MS;
    extra['speakerVadHopMs'] = SPEAKER_VAD_HOP_MS;
    extra['speakerVadConsecutiveBelow'] = SPEAKER_VAD_CONSECUTIVE_BELOW;
  }
  if (config.targetSpeakerEnhancement) extra['enableTargetSpeakerEnhancement'] = true;
  if (config.voiceprintId.length > 0) extra['voiceprintIds'] = [config.voiceprintId];
}
