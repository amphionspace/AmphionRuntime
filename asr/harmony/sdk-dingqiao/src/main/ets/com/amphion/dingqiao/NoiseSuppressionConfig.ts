/** DeepFilterNet3 is the only supported noise suppression model. */
export function noiseSuppressionModel(params: Record<string, Object>): string {
  if (params['enableGtcrn'] === true) {
    throw new Error('GTCRN was removed; select noiseSuppressionModel=deepfilternet3');
  }
  const selected = params['noiseSuppressionModel'];
  if (selected === undefined) return 'none';
  if (selected !== 'none' && selected !== 'deepfilternet3') {
    throw new Error('noiseSuppressionModel must be none or deepfilternet3');
  }
  return selected as string;
}
