export type SpeakerTurnScoreState = 'waiting-target' | 'target-confirmed' | 'target-active' |
  'below' | 'pre-target' | 'departure';

export type SpeakerRangeScorer = (samples: Float32Array, startSample: number,
  endSample: number) => number | undefined;

export type SpeakerClusterScorer = (samples: Float32Array, speaker: number) => number | undefined;

/** Keep finish/endpoint paths from publishing a suffix that never reconfirmed the target. */
export function shouldRejectSpeakerVadFinal(enabled: boolean, rejectCurrent: boolean,
  targetConfirmed: boolean): boolean {
  return enabled && (rejectCurrent || !targetConfirmed);
}

export class SpeakerTurnSegment {
  startSample: number;
  endSample: number;
  speaker: number;

  constructor(startSample: number, endSample: number, speaker: number) {
    this.startSample = Math.max(0, Math.round(startSample));
    this.endSample = Math.max(this.startSample, Math.round(endSample));
    this.speaker = Math.round(speaker);
  }
}

export class SpeakerTurnSplit {
  cutSample: number;
  prefix: Float32Array;
  suffix: Float32Array;

  constructor(cutSample: number, prefix: Float32Array, suffix: Float32Array) {
    this.cutSample = cutSample;
    this.prefix = prefix;
    this.suffix = suffix;
  }
}

/**
 * Owns the bounded PCM and score ledger needed to commit a clean target -> other boundary.
 *
 * A split is returned only after consecutive low speaker scores, a deterministic acoustic/token
 * candidate, and independent target-left/non-target-right verification. Ambiguous evidence is a
 * fail-open decision: the caller keeps the speculative stream result unchanged.
 */
export class SpeakerTurnFinalizer {
  private sampleRate: number;
  private windowSamples: number;
  private hopSamples: number;
  private consecutiveBelow: number;
  private maximumSamples: number;
  private parts: Float32Array[] = [];
  private retainedSamples: number = 0;
  private capped: boolean = false;
  private targetSeen: boolean = false;
  private belowCount: number = 0;
  private lastTargetEndSample: number = -1;
  private firstBelowEndSample: number = -1;
  private lastObservedEndSample: number = -1;
  private departureSeen: boolean = false;
  private rejectBeforeTarget: boolean = false;
  private latestScore?: number;
  private resolutionReason: string = 'not-resolved';

  constructor(sampleRate: number, windowSamples: number, hopSamples: number,
    consecutiveBelow: number, maximumSamples: number) {
    this.sampleRate = Math.max(1, Math.round(sampleRate));
    this.windowSamples = Math.max(1, Math.round(windowSamples));
    this.hopSamples = Math.max(1, Math.round(hopSamples));
    this.consecutiveBelow = Math.max(1, Math.round(consecutiveBelow));
    this.maximumSamples = Math.max(1, Math.round(maximumSamples));
  }

  accept(samples: Float32Array): void {
    if (samples.length === 0) return;
    const available = this.maximumSamples - this.retainedSamples;
    if (samples.length > available) this.capped = true;
    const retained = Math.min(samples.length, Math.max(0, available));
    if (retained > 0) {
      this.parts.push(samples.slice(0, retained));
      this.retainedSamples += retained;
    }
  }

  observeScore(endSample: number, score: number, threshold: number): SpeakerTurnScoreState {
    const end = Math.max(0, Math.round(endSample));
    this.lastObservedEndSample = end;
    this.latestScore = score;
    if (score >= threshold) {
      const firstTarget = !this.targetSeen;
      this.targetSeen = true;
      this.belowCount = 0;
      this.lastTargetEndSample = end;
      this.firstBelowEndSample = -1;
      this.departureSeen = false;
      this.rejectBeforeTarget = false;
      return firstTarget ? 'target-confirmed' : 'target-active';
    }

    this.belowCount += 1;
    if (!this.targetSeen) {
      if (this.belowCount >= this.consecutiveBelow) {
        this.rejectBeforeTarget = true;
        return 'pre-target';
      }
      return 'waiting-target';
    }
    if (this.belowCount === 1) this.firstBelowEndSample = end;
    if (this.belowCount >= this.consecutiveBelow) {
      this.departureSeen = true;
      return 'departure';
    }
    return 'below';
  }

  isTargetConfirmed(): boolean { return this.targetSeen; }
  shouldRejectCurrent(): boolean { return this.rejectBeforeTarget; }
  lastScore(): number | undefined { return this.latestScore; }
  consecutiveLowScores(): number { return this.belowCount; }
  sampleCount(): number { return this.retainedSamples; }
  samples(): Float32Array { return concatFloat32(this.parts, this.retainedSamples); }
  lastResolutionReason(): string { return this.resolutionReason; }
  deferResolution(reason: string): void { this.resolutionReason = reason; }
  needsMoreContext(): boolean {
    return this.resolutionReason === 'insufficient-refine-context' ||
      this.resolutionReason === 'diarizer-loading';
  }
  hasPendingDeparture(): boolean { return this.departureSeen; }

  resolve(tokenTimestampsSec: number[], threshold: number,
    scoreRange: SpeakerRangeScorer, boundaryHintsSamples: number[] = []): SpeakerTurnSplit | undefined {
    this.resolutionReason = 'not-ready';
    if (!this.departureSeen || this.firstBelowEndSample < 0 ||
      this.lastTargetEndSample < 0) return undefined;
    if (this.capped) {
      this.resolutionReason = 'buffer-capped';
      return undefined;
    }
    const all = concatFloat32(this.parts, this.retainedSamples);
    // Window scores locate a transition interval, not an instant. The boundary can be anywhere
    // inside the last target-positive window and must precede the first low-score deadline.
    const searchStart = Math.max(0, this.lastTargetEndSample - this.windowSamples);
    const searchEnd = Math.min(all.length, this.firstBelowEndSample);
    if (searchEnd <= searchStart) {
      this.resolutionReason = 'invalid-search-range';
      return undefined;
    }

    const frameSamples = Math.max(1, Math.round(this.sampleRate / 50));
    const refineSamples = this.windowSamples;
    const candidates: number[] = [];
    let candidateLackedContext = false;
    const addCandidate = (sample: number): void => {
      const candidate = Math.round(sample);
      if (candidate < searchStart || candidate > searchEnd ||
        candidate <= 0 || candidate >= all.length || candidates.indexOf(candidate) >= 0) return;
      if (candidate < refineSamples || all.length - candidate < refineSamples) {
        candidateLackedContext = true;
        return;
      }
      candidates.push(candidate);
    };
    for (let index = 0; index < boundaryHintsSamples.length; index++) {
      addCandidate(boundaryHintsSamples[index]);
    }
    const hintedCandidateCount = candidates.length;
    const quietRun = this.findQuietRun(all, searchStart, searchEnd, frameSamples);
    if (quietRun !== undefined) {
      addCandidate(this.alignAfterQuietRun(
        quietRun[0], quietRun[1], tokenTimestampsSec, frameSamples, all.length));
    }
    const preferredCandidateCount = candidates.length;
    for (let index = 0; index < tokenTimestampsSec.length; index++) {
      addCandidate(tokenTimestampsSec[index] * this.sampleRate);
    }
    addCandidate(this.firstBelowEndSample - Math.round(this.windowSamples / 2));
    const coarseStep = Math.max(frameSamples, Math.round(this.hopSamples / 2));
    for (let candidate = searchStart; candidate <= searchEnd; candidate += coarseStep) {
      addCandidate(candidate);
    }
    addCandidate(searchEnd);
    if (candidates.length === 0) {
      this.resolutionReason = candidateLackedContext ?
        'insufficient-refine-context' : 'no-boundary-candidates';
      return undefined;
    }

    // Speaker embedding inference is synchronous on Harmony. Scoring every grid point can block
    // the app lane long enough for the carrier to be killed. Diarization segment boundaries are
    // the strongest hints even when clustering collapses both voices to one label; otherwise rank
    // the cheap acoustic/token candidates by sustained left/right waveform contrast. Verify at
    // most two candidates with the real target-speaker model, bounding this path to four inferences.
    const hinted = candidates.slice(0, hintedCandidateCount);
    hinted.sort((left: number, right: number): number =>
      this.transitionContrast(all, right, refineSamples) -
      this.transitionContrast(all, left, refineSamples));
    const preferred = candidates.slice(hintedCandidateCount, preferredCandidateCount);
    const acoustic = candidates.slice(preferredCandidateCount);
    acoustic.sort((left: number, right: number): number =>
      this.transitionContrast(all, right, refineSamples) -
      this.transitionContrast(all, left, refineSamples));
    const ranked = hinted.slice(0, 1).concat(preferred.slice(0, 1)).concat(acoustic);
    const maximumScoredCandidates = 2;

    let bestCandidate = -1;
    let bestLeft = -Infinity;
    let bestRight = Infinity;
    let bestMargin = -Infinity;
    const evaluate = (candidate: number): void => {
      const leftStart = candidate - refineSamples;
      const rightEnd = candidate + refineSamples;
      const leftScore = scoreRange(all.slice(leftStart, candidate), leftStart, candidate);
      const rightScore = scoreRange(all.slice(candidate, rightEnd), candidate, rightEnd);
      if (leftScore === undefined || rightScore === undefined ||
        leftScore < threshold || rightScore >= threshold) return;
      const margin = leftScore - rightScore;
      if (margin > bestMargin || (margin === bestMargin && candidate > bestCandidate)) {
        bestCandidate = candidate;
        bestLeft = leftScore;
        bestRight = rightScore;
        bestMargin = margin;
      }
    };
    const scoredCandidateCount = Math.min(maximumScoredCandidates, ranked.length);
    for (let index = 0; index < scoredCandidateCount; index++) {
      evaluate(ranked[index]);
    }
    if (bestCandidate <= 0) {
      this.resolutionReason = `no-verified-boundary:scored=${scoredCandidateCount},` +
        `candidates=${candidates.length}`;
      return undefined;
    }

    this.resolutionReason = `split:candidate=${bestCandidate},left=${bestLeft.toFixed(3)},` +
      `right=${bestRight.toFixed(3)},margin=${bestMargin.toFixed(3)}`;
    return new SpeakerTurnSplit(
      bestCandidate, all.slice(0, bestCandidate), all.slice(bestCandidate));
  }

  /** Resolve the last stable, non-overlapping target -> other turn reported by diarization. */
  resolveDiarized(segments: SpeakerTurnSegment[], threshold: number,
    scoreCluster: SpeakerClusterScorer): SpeakerTurnSplit | undefined {
    this.resolutionReason = 'diarization-not-ready';
    if (!this.departureSeen || this.capped) {
      if (this.capped) this.resolutionReason = 'buffer-capped';
      return undefined;
    }
    const all = concatFloat32(this.parts, this.retainedSamples);
    const minimumStableSamples = Math.max(1, Math.round(this.sampleRate * 0.2));
    const stable = segments
      .map((segment: SpeakerTurnSegment): SpeakerTurnSegment => new SpeakerTurnSegment(
        Math.min(all.length, segment.startSample),
        Math.min(all.length, segment.endSample),
        segment.speaker))
      .filter((segment: SpeakerTurnSegment): boolean =>
        segment.endSample - segment.startSample >= minimumStableSamples)
      .sort((a: SpeakerTurnSegment, b: SpeakerTurnSegment): number =>
        a.startSample - b.startSample || a.endSample - b.endSample);
    if (stable.length < 2) {
      this.resolutionReason = 'diarization-insufficient-segments';
      return undefined;
    }
    for (let index = 1; index < stable.length; index++) {
      if (stable[index].speaker !== stable[index - 1].speaker &&
        stable[index].startSample < stable[index - 1].endSample) {
        this.resolutionReason = 'unsupported-overlap';
        return undefined;
      }
    }

    const speakerIds: number[] = [];
    for (let index = 0; index < stable.length; index++) {
      if (speakerIds.indexOf(stable[index].speaker) < 0) speakerIds.push(stable[index].speaker);
    }
    if (speakerIds.length !== 2) {
      this.resolutionReason = `diarization-speaker-count:${speakerIds.length}`;
      return undefined;
    }
    const scores: Map<number, number> = new Map<number, number>();
    for (let index = 0; index < speakerIds.length; index++) {
      const speaker = speakerIds[index];
      const score = scoreCluster(concatSpeakerSegments(all, stable, speaker), speaker);
      if (score === undefined) {
        this.resolutionReason = `diarization-score-unavailable:${speaker}`;
        return undefined;
      }
      scores.set(speaker, score);
    }
    const targetIds = speakerIds.filter((speaker: number): boolean =>
      (scores.get(speaker) ?? -1) >= threshold);
    if (targetIds.length !== 1) {
      this.resolutionReason = `diarization-target-count:${targetIds.length}`;
      return undefined;
    }
    const targetSpeaker = targetIds[0];
    let candidate = -1;
    for (let index = 1; index < stable.length; index++) {
      const left = stable[index - 1];
      const right = stable[index];
      if (left.speaker === targetSpeaker && right.speaker !== targetSpeaker) {
        candidate = right.startSample;
      }
    }
    if (candidate <= 0 || candidate >= all.length) {
      this.resolutionReason = 'diarization-no-sequential-departure';
      return undefined;
    }
    // A score describes a whole trailing window, not its end instant. A real change may be anywhere
    // inside the last target-positive window; a diarized boundary before that window contradicts
    // the independent target evidence and must not truncate the target prefix.
    const transitionStart = Math.max(0, this.lastTargetEndSample - this.windowSamples);
    const transitionEnd = Math.min(all.length, this.lastTargetEndSample);
    if (transitionEnd <= transitionStart || candidate < transitionStart || candidate > transitionEnd) {
      this.resolutionReason = `diarization-outside-score-transition:${candidate}:not-in:` +
        `${transitionStart}-${transitionEnd}`;
      return undefined;
    }
    const otherSpeaker = speakerIds.find((speaker: number): boolean => speaker !== targetSpeaker) ?? -1;
    this.resolutionReason = `diarization-split:left=${(scores.get(targetSpeaker) ?? -1).toFixed(3)},` +
      `right=${(scores.get(otherSpeaker) ?? -1).toFixed(3)}`;
    return new SpeakerTurnSplit(candidate, all.slice(0, candidate), all.slice(candidate));
  }

  reset(): void {
    this.parts = [];
    this.retainedSamples = 0;
    this.capped = false;
    this.targetSeen = false;
    this.belowCount = 0;
    this.lastTargetEndSample = -1;
    this.firstBelowEndSample = -1;
    this.lastObservedEndSample = -1;
    this.departureSeen = false;
    this.rejectBeforeTarget = false;
    this.latestScore = undefined;
    this.resolutionReason = 'not-resolved';
  }

  private findQuietRun(samples: Float32Array, start: number, end: number,
    frameSamples: number): number[] | undefined {
    let referenceRms = 0;
    const frames: number[] = [];
    for (let offset = start; offset + frameSamples <= end; offset += frameSamples) {
      const rms = rangeRms(samples, offset, offset + frameSamples);
      frames.push(rms);
      referenceRms = Math.max(referenceRms, rms);
    }
    if (frames.length === 0 || referenceRms <= 0) return undefined;
    const quietThreshold = Math.min(0.01, referenceRms * 0.15);
    const minimumQuietFrames = Math.max(1, Math.ceil(this.sampleRate * 0.08 / frameSamples));
    let runStart = -1;
    let bestStart = -1;
    let bestEnd = -1;
    for (let index = 0; index <= frames.length; index++) {
      const quiet = index < frames.length && frames[index] <= quietThreshold;
      if (quiet && runStart < 0) runStart = index;
      if (quiet) continue;
      if (runStart >= 0 && index - runStart >= minimumQuietFrames) {
        const candidateStart = start + runStart * frameSamples;
        const candidateEnd = Math.min(end, start + index * frameSamples);
        if (candidateEnd - candidateStart > bestEnd - bestStart) {
          bestStart = candidateStart;
          bestEnd = candidateEnd;
        }
      }
      runStart = -1;
    }
    return bestStart >= 0 ? [bestStart, bestEnd] : undefined;
  }

  private alignAfterQuietRun(start: number, end: number, tokenTimestampsSec: number[],
    frameSamples: number, totalSamples: number): number {
    const latestAligned = Math.min(totalSamples - 1, end + frameSamples * 2);
    const tokens = tokenTimestampsSec.map((timestamp: number): number =>
      Math.round(timestamp * this.sampleRate));
    for (let index = 0; index < tokens.length; index++) {
      if (tokens[index] >= start && tokens[index] <= latestAligned) return tokens[index];
    }
    return end;
  }

  private transitionContrast(samples: Float32Array, candidate: number, span: number): number {
    const leftStart = Math.max(0, candidate - span);
    const rightEnd = Math.min(samples.length, candidate + span);
    const leftRms = rangeRms(samples, leftStart, candidate);
    const rightRms = rangeRms(samples, candidate, rightEnd);
    const rmsContrast = Math.abs(Math.log((leftRms + 1e-6) / (rightRms + 1e-6)));
    const leftZcr = rangeZeroCrossingRate(samples, leftStart, candidate);
    const rightZcr = rangeZeroCrossingRate(samples, candidate, rightEnd);
    return rmsContrast + Math.abs(leftZcr - rightZcr);
  }

  private scoreChangeTokenBoundary(tokenTimestampsSec: number[], searchStart: number,
    searchEnd: number): number {
    const estimate = Math.max(searchStart, Math.min(searchEnd,
      this.firstBelowEndSample - Math.round(this.windowSamples / 2)));
    const latest = Math.min(searchEnd + this.hopSamples, this.retainedSamples - 1);
    const tokens = tokenTimestampsSec.map((timestamp: number): number =>
      Math.round(timestamp * this.sampleRate));
    for (let index = 0; index < tokens.length; index++) {
      if (tokens[index] >= estimate && tokens[index] <= latest) return tokens[index];
    }
    return -1;
  }
}

function rangeRms(samples: Float32Array, start: number, end: number): number {
  let squareSum = 0;
  for (let index = start; index < end; index++) squareSum += samples[index] * samples[index];
  return end > start ? Math.sqrt(squareSum / (end - start)) : 0;
}

function rangeZeroCrossingRate(samples: Float32Array, start: number, end: number): number {
  if (end - start < 2) return 0;
  let crossings = 0;
  for (let index = start + 1; index < end; index++) {
    if ((samples[index - 1] < 0 && samples[index] >= 0) ||
      (samples[index - 1] >= 0 && samples[index] < 0)) crossings += 1;
  }
  return crossings / (end - start - 1);
}

function concatFloat32(parts: Float32Array[], total: number): Float32Array {
  const output = new Float32Array(total);
  let offset = 0;
  for (let index = 0; index < parts.length; index++) {
    output.set(parts[index], offset);
    offset += parts[index].length;
  }
  return output;
}

function concatSpeakerSegments(samples: Float32Array, segments: SpeakerTurnSegment[],
  speaker: number): Float32Array {
  let total = 0;
  for (let index = 0; index < segments.length; index++) {
    if (segments[index].speaker === speaker) {
      total += segments[index].endSample - segments[index].startSample;
    }
  }
  const output = new Float32Array(total);
  let offset = 0;
  for (let index = 0; index < segments.length; index++) {
    const segment = segments[index];
    if (segment.speaker !== speaker) continue;
    const part = samples.slice(segment.startSample, segment.endSample);
    output.set(part, offset);
    offset += part.length;
  }
  return output;
}
