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
  const minimum = Math.max(0, Math.round(minSamples));
  if (!asrSpeechConfirmed) {
    return new SpeakerScoreSelection(new Float32Array(0), 'insufficient');
  }
  if (minimum > 0 && strictSamples.length >= minimum) {
    return new SpeakerScoreSelection(strictSamples, 'strict');
  }
  // minSegSec=0 removes SDK-side duration judgment, so score the whole real utterance rather than
  // an arbitrarily short strict fragment. A positive value remains only a source preference.
  if (utteranceSamples.length > 0) {
    return new SpeakerScoreSelection(utteranceSamples, 'utterance');
  }
  if (strictSamples.length > 0) {
    return new SpeakerScoreSelection(strictSamples, 'strict');
  }
  return new SpeakerScoreSelection(new Float32Array(0), 'insufficient');
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
