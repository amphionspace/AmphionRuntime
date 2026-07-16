export function hasVoiceprintCapability(verificationEnabled: boolean,
  speakerVadEnabled: boolean, voiceprintIdCount: number): boolean {
  return verificationEnabled || speakerVadEnabled || voiceprintIdCount > 0;
}
