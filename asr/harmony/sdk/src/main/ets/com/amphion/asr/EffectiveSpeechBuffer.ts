export const ACOUSTIC_WINDOWS_PER_SECOND: number = 50;
export const ACOUSTIC_ACTIVE_RMS_THRESHOLD: number = 0.01;
export const MIN_SPEECH_ZERO_CROSSING_RATE: number = 0.005;
export const MAX_SPEECH_ZERO_CROSSING_RATE: number = 0.35;
export const REQUIRED_SPEECH_LIKE_WINDOWS: number = 3;
export const MIN_SPEECH_ENERGY_RATIO: number = 3;
const MIN_EDGE_SILENCE_MS: number = 5;
const MAX_EDGE_SILENCE_AMPLITUDE: number = ACOUSTIC_ACTIVE_RMS_THRESHOLD / 2;
const MAX_VAD_EVIDENCE_LAG_WINDOWS: number = 3;

class EffectiveSpeechRun {
  parts: Float32Array[] = [];
  sampleCount: number = 0;
  windowCount: number = 0;
  acousticallyConfirmed: boolean = false;
  externallyConfirmed: boolean = false;
}

export class EffectiveSpeechFinalDecision {
  publish: boolean;
  samples: Float32Array;

  constructor(publish: boolean, samples: Float32Array) {
    this.publish = publish;
    this.samples = samples;
  }
}

export function acousticRms(squareSum: number, sampleCount: number): number {
  return sampleCount > 0 ? Math.sqrt(squareSum / sampleCount) : 0;
}

export function isAcousticallyActive(rms: number): boolean {
  return rms >= ACOUSTIC_ACTIVE_RMS_THRESHOLD;
}

export function isSpeechShapedWindow(rms: number, zeroCrossingRate: number): boolean {
  return isAcousticallyActive(rms) &&
    zeroCrossingRate >= MIN_SPEECH_ZERO_CROSSING_RATE &&
    zeroCrossingRate <= MAX_SPEECH_ZERO_CROSSING_RATE;
}

// Selects speech-shaped 20 ms windows for final speaker scoring. Native VAD or ASR evidence admits
// a scale-invariant low-volume or constant-envelope run. Evidence stays bound to that contiguous run,
// while the acoustic-only fallback still requires both envelope movement and speech-shaped energy.
export class EffectiveSpeechBuffer {
  private window: Float32Array;
  private samplesInWindow: number = 0;
  private runs: EffectiveSpeechRun[] = [];
  private currentRun?: EffectiveSpeechRun;
  private latestRun?: EffectiveSpeechRun;
  private retainedSamples: number = 0;
  private pendingEvidenceWindows: number = 0;
  private windowsSinceLatestRun: number = Number.MAX_SAFE_INTEGER;
  private acousticRunWindows: number = 0;
  private acousticRunMinRms: number = Number.MAX_VALUE;
  private acousticRunMaxRms: number = 0;
  private maxSamples: number;
  private minEdgeSilenceSamples: number;

  constructor(sampleRate: number, maxSamples: number) {
    const windowSamples = Math.max(1, Math.round(sampleRate / ACOUSTIC_WINDOWS_PER_SECOND));
    this.window = new Float32Array(windowSamples);
    this.maxSamples = Math.max(0, Math.round(maxSamples));
    this.minEdgeSilenceSamples = Math.max(1, Math.round(sampleRate * MIN_EDGE_SILENCE_MS / 1000));
  }

  observe(samples: Float32Array): void {
    let offset = 0;
    while (offset < samples.length) {
      const count = Math.min(samples.length - offset, this.window.length - this.samplesInWindow);
      this.window.set(samples.slice(offset, offset + count), this.samplesInWindow);
      this.samplesInWindow += count;
      offset += count;
      if (this.samplesInWindow === this.window.length) {
        this.processWindow(this.window.slice());
        this.samplesInWindow = 0;
      }
    }
  }

  // VAD evidence normally arrives after observe() for the same native window. A bounded lag accepts
  // detector latency without allowing evidence to reach across a real gap into an older candidate.
  confirmSpeech(): void {
    const run = this.currentRun ??
      (this.windowsSinceLatestRun <= MAX_VAD_EVIDENCE_LAG_WINDOWS ? this.latestRun : undefined);
    if (run !== undefined) {
      run.externallyConfirmed = true;
    } else {
      this.pendingEvidenceWindows = MAX_VAD_EVIDENCE_LAG_WINDOWS;
    }
  }

  // ASR text/token evidence belongs to the latest candidate preceding the final, even when trailing
  // silence has already closed that run. Other runs still need their own evidence or envelope change.
  take(asrSpeechConfirmed: boolean = false): Float32Array {
    this.confirmLatestRun(asrSpeechConfirmed);
    const output = this.collectConfirmedRuns();
    this.reset();
    return output;
  }

  // A token-only endpoint is recognizer evidence, not a public utterance boundary. Keep its audio for
  // the next result with public text. A terminal result consumes confirmed effective speech even when
  // text is empty: speaker-score availability depends on usable speech duration, not ASR text quality.
  resolveFinal(publicText: string, asrSpeechConfirmed: boolean,
    isLast: boolean): EffectiveSpeechFinalDecision {
    if (publicText.length === 0) {
      if (!isLast) {
        this.confirmLatestRun(asrSpeechConfirmed);
        return new EffectiveSpeechFinalDecision(false, new Float32Array(0));
      }
      return new EffectiveSpeechFinalDecision(true, this.take(asrSpeechConfirmed));
    }
    return new EffectiveSpeechFinalDecision(true, this.take(asrSpeechConfirmed));
  }

  reset(): void {
    this.samplesInWindow = 0;
    this.runs = [];
    this.currentRun = undefined;
    this.latestRun = undefined;
    this.retainedSamples = 0;
    this.pendingEvidenceWindows = 0;
    this.windowsSinceLatestRun = Number.MAX_SAFE_INTEGER;
    this.resetAcousticRun();
  }

  private processWindow(samples: Float32Array): void {
    if (this.pendingEvidenceWindows > 0) this.pendingEvidenceWindows -= 1;
    // The sample cap is also the metadata cap. Without this early return, an utterance that never
    // endpoints could keep allocating empty run objects after the retained audio reached 25 seconds.
    if (this.retainedSamples >= this.maxSamples) return;
    let squareSum = 0;
    let zeroCrossings = 0;
    for (let i = 0; i < samples.length; i++) {
      squareSum += samples[i] * samples[i];
      if (i > 0 && (samples[i] >= 0) !== (samples[i - 1] >= 0)) zeroCrossings += 1;
    }
    const rms = acousticRms(squareSum, samples.length);
    const zcr = zeroCrossings / Math.max(1, samples.length - 1);
    const evidenceCandidate = rms > 0 &&
      zcr >= MIN_SPEECH_ZERO_CROSSING_RATE && zcr <= MAX_SPEECH_ZERO_CROSSING_RATE;
    if (!evidenceCandidate) {
      this.currentRun = undefined;
      this.resetAcousticRun();
      if (this.windowsSinceLatestRun !== Number.MAX_SAFE_INTEGER) {
        this.windowsSinceLatestRun += 1;
      }
      return;
    }

    const edgeSilenceAmplitude = Math.min(MAX_EDGE_SILENCE_AMPLITUDE, rms / 4);
    const effectiveSamples = this.trimLongSilentEdges(samples, edgeSilenceAmplitude);
    if (this.currentRun === undefined) {
      const run = new EffectiveSpeechRun();
      if (this.pendingEvidenceWindows > 0) {
        run.externallyConfirmed = true;
        this.pendingEvidenceWindows = 0;
      }
      this.runs.push(run);
      this.currentRun = run;
      this.latestRun = run;
    }
    this.appendToRun(this.currentRun, effectiveSamples);
    this.currentRun.windowCount += 1;
    this.windowsSinceLatestRun = 0;

    if (!isSpeechShapedWindow(rms, zcr)) {
      this.resetAcousticRun();
      return;
    }
    this.acousticRunWindows += 1;
    this.acousticRunMinRms = Math.min(this.acousticRunMinRms, rms);
    this.acousticRunMaxRms = Math.max(this.acousticRunMaxRms, rms);
    if (this.acousticRunWindows >= REQUIRED_SPEECH_LIKE_WINDOWS &&
      this.acousticRunMaxRms >= this.acousticRunMinRms * MIN_SPEECH_ENERGY_RATIO) {
      this.currentRun.acousticallyConfirmed = true;
    }
  }

  private appendToRun(run: EffectiveSpeechRun, samples: Float32Array): void {
    const remaining = this.maxSamples - this.retainedSamples;
    if (remaining <= 0) return;
    const retained = samples.length <= remaining ? samples : samples.slice(0, remaining);
    run.parts.push(retained);
    run.sampleCount += retained.length;
    this.retainedSamples += retained.length;
  }

  private collectConfirmedRuns(): Float32Array {
    const parts: Float32Array[] = [];
    let total = 0;
    for (let i = 0; i < this.runs.length; i++) {
      const run = this.runs[i];
      if (run.windowCount < REQUIRED_SPEECH_LIKE_WINDOWS) continue;
      if (!run.externallyConfirmed && !run.acousticallyConfirmed) continue;
      for (let j = 0; j < run.parts.length; j++) parts.push(run.parts[j]);
      total += run.sampleCount;
    }
    return concatSamples(parts, total);
  }

  private confirmLatestRun(confirmed: boolean): void {
    if (confirmed && this.latestRun !== undefined) {
      this.latestRun.externallyConfirmed = true;
    }
  }

  // A speech-shaped window can straddle the true start/end of an utterance. Remove only a sustained
  // quiet edge (at least 5 ms) after the multi-signal window has been accepted; individual zero
  // crossings inside voiced audio are retained and cannot shorten an otherwise valid 1.5 s segment.
  private trimLongSilentEdges(samples: Float32Array, silenceAmplitude: number): Float32Array {
    let start = 0;
    while (start < samples.length && Math.abs(samples[start]) < silenceAmplitude) start += 1;
    if (start < this.minEdgeSilenceSamples) start = 0;

    let end = samples.length;
    while (end > start && Math.abs(samples[end - 1]) < silenceAmplitude) end -= 1;
    if (samples.length - end < this.minEdgeSilenceSamples) end = samples.length;
    return start === 0 && end === samples.length ? samples : samples.slice(start, end);
  }

  private resetAcousticRun(): void {
    this.acousticRunWindows = 0;
    this.acousticRunMinRms = Number.MAX_VALUE;
    this.acousticRunMaxRms = 0;
  }
}

function concatSamples(parts: Float32Array[], total: number): Float32Array {
  const output = new Float32Array(total);
  let offset = 0;
  for (let i = 0; i < parts.length; i++) {
    output.set(parts[i], offset);
    offset += parts[i].length;
  }
  return output;
}
