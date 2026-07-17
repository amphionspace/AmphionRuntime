export class SpeakerScoreSelection {
  samples: Float32Array;
  source: string;

  constructor(samples: Float32Array, source: string) {
    this.samples = samples;
    this.source = source;
  }
}

export function selectSpeakerScoreSamples(strictSamples: Float32Array,
  utteranceSamples: Float32Array, minSamples: number,
  asrSpeechConfirmed: boolean): SpeakerScoreSelection {
  const minimum = Math.max(1, Math.round(minSamples));
  if (strictSamples.length >= minimum) {
    return new SpeakerScoreSelection(strictSamples, 'strict');
  }
  if (asrSpeechConfirmed && utteranceSamples.length >= minimum) {
    return new SpeakerScoreSelection(utteranceSamples, 'utterance');
  }
  return new SpeakerScoreSelection(strictSamples, 'insufficient');
}
