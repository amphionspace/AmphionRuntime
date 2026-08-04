export class SpeakerScoreSelection {
  samples: Float32Array;
  source: string;

  constructor(samples: Float32Array, source: string) {
    this.samples = samples;
    this.source = source;
  }
}

function sampleDurationMs(samples: number, sampleRate: number): number {
  const rate = Math.max(1, Math.round(sampleRate));
  return Math.floor(Math.max(0, Math.round(samples)) * 1000 / rate);
}

export function selectSpeakerScoreSamples(strictSamples: Float32Array,
  utteranceSamples: Float32Array, minSamples: number,
  asrSpeechConfirmed: boolean): SpeakerScoreSelection {
  const minimum = Math.max(1, Math.round(minSamples));
  if (!asrSpeechConfirmed) {
    return new SpeakerScoreSelection(new Float32Array(0), 'insufficient');
  }
  if (strictSamples.length >= minimum) {
    return new SpeakerScoreSelection(strictSamples, 'strict');
  }
  if (asrSpeechConfirmed && utteranceSamples.length >= minimum) {
    return new SpeakerScoreSelection(utteranceSamples, 'utterance');
  }
  return new SpeakerScoreSelection(strictSamples, 'insufficient');
}

export function speakerScoreSelectionDiagnostic(selection: SpeakerScoreSelection,
  strictSampleCount: number, utteranceSampleCount: number, minimumSampleCount: number,
  sampleRate: number, asrSpeechConfirmed: boolean): string {
  return `voiceprint score selection: source=${selection.source} ` +
    `effectiveSpeechMs=${sampleDurationMs(strictSampleCount, sampleRate)} ` +
    `utterancePcmMs=${sampleDurationMs(utteranceSampleCount, sampleRate)} ` +
    `minimumMs=${sampleDurationMs(minimumSampleCount, sampleRate)} ` +
    `asrEvidence=${asrSpeechConfirmed}`;
}
