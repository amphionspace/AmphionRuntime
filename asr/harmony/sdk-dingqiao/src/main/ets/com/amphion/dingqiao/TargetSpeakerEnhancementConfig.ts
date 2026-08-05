export interface TargetSpeakerEnhancementConfig {
  enabled: boolean;
}

/**
 * Public policy for the optional target-speaker front end.
 *
 * The switch is deliberately strict: only a boolean true enables it. The
 * feature is an enhancement to Speaker VAD, so it cannot silently create a
 * second target-speaker state machine.
 */
export function targetSpeakerEnhancementConfig(
  extraParams: Record<string, Object>,
  voiceprintIds: string[]
): TargetSpeakerEnhancementConfig {
  const enabled = extraParams['enableTargetSpeakerEnhancement'] === true;
  if (!enabled) return { enabled: false };
  if (extraParams['enableSpeakerVad'] !== true) {
    throw new Error('enableSpeakerVad=true required when enableTargetSpeakerEnhancement=true');
  }
  if (voiceprintIds.length === 0) {
    throw new Error('voiceprintIds required when enableTargetSpeakerEnhancement=true');
  }
  return { enabled: true };
}
