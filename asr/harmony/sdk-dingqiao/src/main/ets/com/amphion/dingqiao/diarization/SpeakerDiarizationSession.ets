import { AsrResult, AsrTextNormalizationSpan, ResultAudioTimeline } from 'amphion_asr';
import { DiarizationCommitClock } from './DiarizationCommitClock';
import {
  DiarizedUtterance, SpeakerDiarizationDegradedReason, SpeakerDiarizationResult,
  SpeakerDiarizationUpdate, SpeakerTurn, SpeakerTextSpan, SpeechRecognitionResult
} from '../DingqiaoModels';
import { DiarizationLocalWindowResult, SpeakerDiarizationLocalClient,
  SpeakerDiarizationLocalObserver, SpeakerDiarizationLocalClientOptions } from './SpeakerDiarizationLocalClient';
import { SpeakerDiarizationRuntimeLease, SpeakerDiarizationRuntimeLeaseRegistry } from './SpeakerDiarizationRuntimeLease';
import { speakerIndexFromInternalId, speakerIndexesFromInternalIds } from './SpeakerDiarizationSpeakerIndex';
import { SpeakerDiarizationTranscriptState, DiarizationTranscriptUpdate,
  DiarizedTranscriptUtterance, TranscriptTextNormalization, TranscriptTextPresentation,
  TranscriptNormalizationSpan } from './SpeakerDiarizationTranscriptState';
import { CommunitySpeakerIdentity, communityTimeline } from './CommunitySpeakerIdentity';
import { PoliceTextProvenance, PoliceTextSpan } from '../PoliceEnhancementPolicy';

const SAMPLE_RATE: number = 16000;
interface DiarizationEvidenceWindow {
  jobId: string;
  windowStartSample: number;
  realEndSample: number;
}
export interface SpeakerDiarizationSessionObserver {
  onSpeakerDiarizationUpdate(update: SpeakerDiarizationUpdate): void;
  onWindowResult(result: SpeakerDiarizationResult): void;
  onFinished(result: SpeakerDiarizationResult): void;
}

export interface SpeakerDiarizationSessionController {
  append(audio: ArrayBuffer): void;
  observeAsrFinal(payload: SpeechRecognitionResult, result: AsrResult, provenance?: PoliceTextProvenance): void;
  asrFinalDelivered(result: AsrResult): void;
  asrAudioProcessed(endSample: number): void;
  finish(confirmedInitialSilence?: boolean): void;
  decoratePayload(payload: SpeechRecognitionResult): void;
  bestResult(reason?: SpeakerDiarizationDegradedReason, message?: string): SpeakerDiarizationResult;
  cleanup(): void;
}

export class SpeakerDiarizationSession implements SpeakerDiarizationLocalObserver,
  SpeakerDiarizationSessionController {
  private readonly client: SpeakerDiarizationLocalClient;
  private readonly transcript: SpeakerDiarizationTranscriptState = new SpeakerDiarizationTranscriptState();
  private readonly commitClock: DiarizationCommitClock;
  private readonly identities: CommunitySpeakerIdentity;
  private readonly windows: DiarizationEvidenceWindow[] = [];
  /** Whole-window activity per retained window, folded in once. Indexed as `windows`. */
  private readonly windowActivity: number[][] = [];
  private readonly observer: SpeakerDiarizationSessionObserver;
  private readonly maxSpeakers: number;
  private readonly diagnostic?: (event: string, fields: Record<string, Object>) => void;
  private inferenceEndMs: number = 0;
  private processedThroughMs: number = 0;
  private previewThroughMs: number = 0;
  private inferenceMs: number = 0;
  private totalSamples: number = 0;
  private lastAsrEndMs: number = 0;
  private publishedThrough: number = 0;
  private windowIndex: number = 0;
  private finalSpeakerCount: number = 0;
  private terminalPayload?: SpeechRecognitionResult;
  private degradedReason: SpeakerDiarizationDegradedReason = SpeakerDiarizationDegradedReason.NONE;
  private degradedMessage?: string;
  private finishRequested: boolean = false;
  private confirmedInitialSilence: boolean = false;
  private processDrained: boolean = false;
  private asrTailObserved: boolean = false;
  private finished: boolean = false;
  private committing: boolean = false;
  private runtimeLease?: SpeakerDiarizationRuntimeLease;

  constructor(context: Context, workPath: string, maxSpeakers: number,
    observer: SpeakerDiarizationSessionObserver,
    diagnostic?: (event: string, fields: Record<string, Object>) => void,
    clientOptions?: SpeakerDiarizationLocalClientOptions, commitPeriodMs: number = 120000) {
    this.observer = observer;
    this.diagnostic = diagnostic;
    this.maxSpeakers = maxSpeakers;
    this.commitClock = new DiarizationCommitClock(commitPeriodMs);
    this.identities = new CommunitySpeakerIdentity(maxSpeakers);
    this.runtimeLease = SpeakerDiarizationRuntimeLeaseRegistry.acquire();
    try {
      this.client = new SpeakerDiarizationLocalClient(context, workPath, this, diagnostic, clientOptions);
    }
    catch (error) {
      this.runtimeLease.release();
      this.runtimeLease = undefined;
      throw new Error(`${error}`);
    }
  }

  append(audio: ArrayBuffer): void {
    if (this.finishRequested || this.finished) return;
    this.totalSamples += audio.byteLength / 2;
    if (this.diagnostic !== undefined) {
      const fields: Record<string, Object> = {};
      fields['audioEndSample'] = this.totalSamples;
      this.recordDecision('DIARIZATION_AUDIO_APPENDED', fields);
    }
    try {
      this.client.append(audio);
    } catch (e) {
      this.onDegraded(SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
        `speaker diarization audio spool failed: ${e}`);
    }
  }

  observeAsrFinal(payload: SpeechRecognitionResult, result: AsrResult, provenance?: PoliceTextProvenance): void {
    if (payload.isLast) { this.asrTailObserved = true; this.terminalPayload = payload; }
    if (payload.result.length === 0) {
      this.finalizeIfReady();
      return;
    }
    const timestampMs = result.timestamps.map(
      (timestamp: number): number => Math.round(timestamp * 1000));
    const beginTime = payload.beginTime ?? timestampMs[0] ?? this.lastAsrEndMs;
    const endTime = payload.endTime ??
      timestampMs[timestampMs.length - 1] ?? Math.round(this.totalSamples * 1000 / SAMPLE_RATE);
    this.lastAsrEndMs = Math.max(this.lastAsrEndMs, endTime);
    const normalization: TranscriptTextNormalization | undefined = result.textNormalization === undefined ?
      undefined : {
        text: result.textNormalization.text,
        spans: result.textNormalization.spans.map((span: AsrTextNormalizationSpan): TranscriptNormalizationSpan => ({
          sourceBegin: span.sourceBegin, sourceEnd: span.sourceEnd,
          textBegin: span.textBegin, textEnd: span.textEnd,
        })),
      };
    const presentation: TranscriptTextPresentation | undefined = provenance === undefined ? undefined : {
      sourceText: provenance.sourceText,
      spans: provenance.spans.map((span: PoliceTextSpan): TranscriptNormalizationSpan => ({
        sourceBegin: span.sourceBegin, sourceEnd: span.sourceEnd,
        textBegin: span.textBegin, textEnd: span.textEnd,
      })),
    };
    const utteranceId = this.transcript.addUtterance({
      rawText: result.rawText,
      textNormalization: normalization,
      presentation,
      text: payload.result,
      tokens: result.tokens,
      tokenTimesMs: timestampMs,
      beginTime,
      endTime,
      audioEndTime: (ResultAudioTimeline.endSample(result) ?? this.totalSamples) * 1000 / SAMPLE_RATE,
    });
    payload.utteranceId = utteranceId;
    if (this.diagnostic !== undefined) {
      const fields: Record<string, Object> = {};
      fields['utteranceId'] = utteranceId;
      fields['rawText'] = result.rawText ?? '';
      if (result.textNormalization !== undefined) fields['textNormalization'] = result.textNormalization;
      if (provenance !== undefined) fields['presentation'] = provenance;
      fields['text'] = payload.result;
      fields['tokens'] = result.tokens.slice();
      fields['tokenTimesMs'] = timestampMs.slice();
      fields['beginTime'] = beginTime;
      fields['endTime'] = endTime;
      fields['audioEndSample'] = ResultAudioTimeline.endSample(result) ?? this.totalSamples;
      fields['isLast'] = payload.isLast;
      this.recordDecision('DIARIZATION_ASR_ALIGNMENT', fields);
    }
    const assignment = this.transcript.currentAssignment(utteranceId);
    if (assignment !== undefined) {
      payload.speakerIndex = speakerIndexFromInternalId(assignment.speakerId, this.maxSpeakers);
      payload.secondarySpeakerIndexes = speakerIndexesFromInternalIds(
        assignment.secondarySpeakerIds, this.maxSpeakers, true);
      payload.speakerConfidence = assignment.confidence;
    }
    this.finalizeIfReady();
  }

  asrFinalDelivered(result: AsrResult): void {
    if (this.finished || result.isLast) return;
    const endSample = ResultAudioTimeline.endSample(result);
    if (endSample === undefined) return;
    this.commitClock.observeEndpoint(endSample * 1000 / SAMPLE_RATE);
    if (this.diagnostic !== undefined) {
      const fields: Record<string, Object> = {};
      fields['audioEndSample'] = endSample;
      fields['endTime'] = endSample * 1000 / SAMPLE_RATE;
      fields['committedThrough'] = this.commitClock.beginTime();
      fields['reason'] = 'WAIT_PROCESSED_AUDIO_DEADLINE';
      this.recordDecision('DIARIZATION_ASR_ENDPOINT', fields);
    }
    this.flushReadyWindows();
  }

  asrAudioProcessed(endSample: number): void {
    if (this.finished) return;
    this.processedThroughMs = Math.max(this.processedThroughMs, endSample * 1000 / SAMPLE_RATE);
    if (this.diagnostic !== undefined) {
      const fields: Record<string, Object> = {};
      fields['audioEndSample'] = endSample;
      this.recordDecision('DIARIZATION_ASR_PROCESSED', fields);
    }
    const queued = this.commitClock.observeProcessedAudio(this.processedThroughMs);
    if (queued && this.diagnostic !== undefined) {
      const fields: Record<string, Object> = {};
      fields['audioEndSample'] = endSample;
      fields['committedThrough'] = this.commitClock.beginTime();
      this.recordDecision('DIARIZATION_COMMIT_PLANNED', fields);
    }
    this.flushReadyWindows();
  }

  finish(confirmedInitialSilence: boolean = false): void {
    if (this.finishRequested || this.finished) return;
    this.finishRequested = true;
    this.confirmedInitialSilence = confirmedInitialSilence;
    if (this.diagnostic !== undefined) {
      const fields: Record<string, Object> = {};
      fields['confirmedInitialSilence'] = confirmedInitialSilence;
      this.recordDecision('DIARIZATION_FINISH', fields);
    }
    if (confirmedInitialSilence) {
      // The recognizer has already closed the initial-silence decision. A padded
      // model tail must not delay that deadline or invent speech after it.
      // Public completion still waits for ASR; native teardown retains its lease.
      this.client.cancel((): void => { this.releaseRuntimeLease(); });
      this.processDrained = true;
      this.finalizeIfReady();
      return;
    }
    this.client.finish();
  }

  decoratePayload(payload: SpeechRecognitionResult): void {
    if (payload.utteranceId === undefined) return;
    const assignment = this.transcript.currentAssignment(payload.utteranceId);
    if (assignment === undefined) return;
    payload.speakerIndex = speakerIndexFromInternalId(assignment.speakerId, this.maxSpeakers);
    payload.secondarySpeakerIndexes = speakerIndexesFromInternalIds(
      assignment.secondarySpeakerIds, this.maxSpeakers, true);
    payload.speakerConfidence = assignment.confidence;
  }

  bestResult(reason?: SpeakerDiarizationDegradedReason, message?: string): SpeakerDiarizationResult {
    if (reason !== undefined && reason !== SpeakerDiarizationDegradedReason.NONE) {
      // A finish timeout must not promote provisional identities to frozen ones.
      this.transcript.applySpeakerTurns([], true);
    }
    return this.buildResult(reason ?? this.degradedReason, message ?? this.degradedMessage);
  }

  cancel(): void {
    this.finished = true;
    this.client.cancel((): void => { this.releaseRuntimeLease(); });
  }

  cleanup(): void {
    this.finished = true;
    this.client.cleanup((): void => { this.releaseRuntimeLease(); });
  }

  onWindow(window: DiarizationLocalWindowResult): void {
    if (this.finished || this.confirmedInitialSilence) return;
    this.client.retainEvidence(window.result);
    this.windows.push({ jobId: window.jobId, windowStartSample: window.windowStartSample,
      realEndSample: window.realEndSample });
    this.inferenceEndMs = window.realEndSample * 1000 / SAMPLE_RATE;
    this.inferenceMs += window.result.segmentationMs + window.result.featureMs + window.result.embeddingMs;
    if (this.diagnostic !== undefined) {
      const fields: Record<string, Object> = {};
      fields['jobId'] = window.jobId;
      fields['model'] = 'Community-1';
      fields['windowStartSample'] = window.windowStartSample;
      fields['realEndSample'] = window.realEndSample;
      fields['paddedEndSample'] = window.windowStartSample + 160000;
      fields['frameCenterSample'] = 495.5;
      fields['frameStepSamples'] = 270;
      fields['frameReceptiveSamples'] = 991;
      // Keep independent snapshots without retaining boxed copies of every tensor.
      fields['segmentations'] = window.result.segments.slice();
      fields['embeddings'] = window.result.embeddings.slice();
      // Older test doubles and persisted diagnostic fixtures may predate the
      // per-run evidence fields. Keep their snapshots readable as empty run
      // evidence while native production windows always provide the arrays.
      fields['runRanges'] = (window.result.runRanges ?? new Float32Array(0)).slice();
      fields['runEmbeddings'] = (window.result.runEmbeddings ?? new Float32Array(0)).slice();
      fields['runRms'] = (window.result.runRms ?? new Float32Array(0)).slice();
      fields['segmentationMs'] = window.result.segmentationMs;
      fields['featureMs'] = window.result.featureMs;
      fields['embeddingMs'] = window.result.embeddingMs;
      this.recordDecision('DIARIZATION_COMMUNITY_WINDOW', fields);
    }
    this.flushReadyWindows();
  }

  onDrained(): void {
    if (!this.finishRequested || this.finished) return;
    this.processDrained = true;
    this.recordDecision('DIARIZATION_DRAINED', {});
    this.finalizeIfReady();
  }

  private finalizeIfReady(): void { this.flushReadyWindows(); }

  private flushReadyWindows(): void {
    if (this.finished || this.committing) return;
    void this.drainReadyCommits();
  }

  private async drainReadyCommits(): Promise<void> {
    this.committing = true;
    try {
      while (!this.finished) {
        const progress = this.degradedReason === SpeakerDiarizationDegradedReason.NONE ?
          this.inferenceEndMs : Number.POSITIVE_INFINITY;
        const boundary = this.commitClock.takeReady(progress);
        if (boundary !== undefined) {
          const result = await this.commitWindow(boundary.endTime, boundary.evidenceEndTime,
            false, boundary.beginTime);
          if (this.finished) break;
          if (result.utterances.length > 0 || result.speakerTurns.length > 0) {
            this.windowIndex += 1;
            this.observer.onWindowResult(result);
          }
          continue;
        }
        if (this.finishRequested && this.processDrained && this.asrTailObserved) {
          const result = await this.commitWindow(this.totalSamples * 1000 / SAMPLE_RATE,
            Number.POSITIVE_INFINITY, true, this.publishedThrough);
          if (this.finished) break;
          this.finished = true;
          this.observer.onFinished(result);
          break;
        }
        // Preview only completed audio snapshots, at most once per 10 s of
        // audio. It never advances the public commit clock or enrolls frozen IDs.
        const previewEnd = Math.floor(Math.min(this.inferenceEndMs, this.processedThroughMs) / 10000) * 10000;
        if (!this.finishRequested && this.degradedReason === SpeakerDiarizationDegradedReason.NONE &&
          this.lastAsrEndMs > this.publishedThrough &&
          previewEnd >= Math.max(this.previewThroughMs, this.publishedThrough) + 10000) {
          this.previewThroughMs = previewEnd;
          await this.updateSpeakers(previewEnd, previewEnd, false, this.publishedThrough, true);
          continue;
        }
        break;
      }
    } catch (error) {
      if (!this.finished) {
        this.onDegraded(SpeakerDiarizationDegradedReason.INFERENCE_UNAVAILABLE,
          `Community finalization failed: ${error}`);
        if (!this.finished && this.finishRequested && this.processDrained && this.asrTailObserved) {
          const result = this.bestResult();
          result.isSessionFinal = true;
          this.finished = true;
          this.observer.onFinished(result);
        }
      }
    } finally { this.committing = false; }
  }

  private async updateSpeakers(endTime: number, evidenceEndTime: number,
    isSessionFinal: boolean, beginTime: number, provisional: boolean = false): Promise<void> {
    // Snapshot before awaiting native work. Later windows cannot change this commit.
    const available = this.windows.filter(window => isSessionFinal ||
      (window.windowStartSample + 160000) * 1000 / SAMPLE_RATE <= evidenceEndTime);
    if (!this.confirmedInitialSilence && available.length > 0 &&
      this.degradedReason === SpeakerDiarizationDegradedReason.NONE) {
      // Completed windows arrive in order; the evidence cutoff selects a prefix.
      // Read exactly that prefix, including history already frozen for callers.
      const evidence = this.client.readEvidence(available.length);
      const segments = evidence.segments;
      const embeddings = evidence.embeddings;
      const activity: number[] = new Array<number>(available.length * 3).fill(0);
      const publishedActivity: number[] = new Array<number>(available.length * 3).fill(0);
      // A window's whole-window activity is a fixed property of that window's own
      // segmentation evidence, so fold each window in once and reuse it. Only the
      // public interval has to be re-derived per call, and a window whose frame
      // centres all fall outside that interval contributes exactly zero.
      for (let index = 0; index < available.length; index++) {
        let summed = this.windowActivity[index];
        if (summed === undefined) {
          summed = [0, 0, 0];
          for (let frame = 0; frame < 589; frame++) {
            for (let channel = 0; channel < 3; channel++) {
              summed[channel] += segments[(index * 589 + frame) * 3 + channel];
            }
          }
          this.windowActivity[index] = summed;
        }
        activity[index * 3] = summed[0];
        activity[index * 3 + 1] = summed[1];
        activity[index * 3 + 2] = summed[2];
      }
      for (let index = 0; index < available.length; index++) {
        const start = available[index].windowStartSample;
        const firstFrameTime = (start + 495.5) * 1000 / SAMPLE_RATE;
        const lastFrameTime = (start + 495.5 + 588 * 270) * 1000 / SAMPLE_RATE;
        if (lastFrameTime < beginTime || firstFrameTime >= endTime) continue;
        for (let frame = 0; frame < 589; frame++) {
          const frameTime = (start + 495.5 + frame * 270) * 1000 / SAMPLE_RATE;
          if (frameTime < beginTime || frameTime >= endTime) continue;
          for (let channel = 0; channel < 3; channel++) {
            publishedActivity[index * 3 + channel] += segments[(index * 589 + frame) * 3 + channel];
          }
        }
      }
      const windowIds = available.map(window => window.jobId);
      const starts = new Float64Array(available.map(window => window.windowStartSample));
      const startedMs = Date.now();
      const clustered = await this.client.cluster(segments, embeddings, this.maxSpeakers,
        starts, beginTime * SAMPLE_RATE / 1000, evidence.runEmbeddings, evidence.runRanges, evidence.runRms,
        this.diagnostic !== undefined);
      const clusterElapsedMs = Date.now() - startedMs;
      if (this.finished || this.confirmedInitialSilence ||
        this.degradedReason !== SpeakerDiarizationDegradedReason.NONE) return;
      this.inferenceMs += clusterElapsedMs;
      const visibleClusters: boolean[] = new Array<boolean>(clustered.speakerCount).fill(false);
      const firstAppearanceTimes: number[] =
        new Array<number>(clustered.speakerCount).fill(Number.POSITIVE_INFINITY);
      for (const turn of clustered.turns) {
        if (turn[0] < endTime && turn[1] > beginTime) {
          visibleClusters[turn[2]] = true;
          firstAppearanceTimes[turn[2]] = Math.min(firstAppearanceTimes[turn[2]], Math.max(beginTime, turn[0]));
        }
      }
      const registry = provisional ? this.identities.fork() : this.identities;
      const identity = registry.assign(windowIds, clustered.hard, clustered.speakerCount,
        activity, publishedActivity, visibleClusters, firstAppearanceTimes);
      if (!provisional) this.finalSpeakerCount = identity.after;
      const turns = communityTimeline(clustered.turns, identity.mapping, beginTime, endTime);
      const updates = this.transcript.applySpeakerTurns(turns, true);
      for (const update of updates) {
        this.observer.onSpeakerDiarizationUpdate(this.toPublicUpdate(update));
        if (this.finished) return;
      }
      if (this.diagnostic !== undefined) {
        const fields: Record<string, Object> = {};
        fields['publicWindowIndex'] = this.windowIndex;
        fields['beginTime'] = beginTime;
        fields['endTime'] = endTime;
        fields['evidenceEndTime'] = Number.isFinite(evidenceEndTime) ? evidenceEndTime : -1;
        fields['jobIds'] = windowIds;
        fields['windowStartSamples'] = available.map(window => window.windowStartSample);
        fields['trainingIndices'] = clustered.trainingIndices;
        fields['ahc'] = clustered.ahc;
        fields['priors'] = clustered.priors;
        fields['hard'] = clustered.hard;
        fields['frameHard'] = clustered.frameHard ?? [];
        fields['trainingRunIndices'] = clustered.trainingRunIndices;
        fields['model'] = 'Community-1 masked WeSpeaker / PLDA / VBx';
        fields['similarityOffset'] = 1;
        fields['embeddingToClusterScores'] = clustered.scores;
        fields['clusterCentroids'] = clustered.centroids;
        fields['trainingPosteriors'] = clustered.posteriors;
        fields['usedKMeansCap'] = clustered.usedKMeans;
        fields['capacityRms'] = clustered.capacityRms;
        fields['retainedClusters'] = clustered.retainedClusters;
        fields['activityVotes'] = identity.votes;
        fields['publishedActivity'] = publishedActivity;
        fields['visibleClusters'] = visibleClusters;
        fields['firstAppearanceTimes'] = firstAppearanceTimes.map(time => Number.isFinite(time) ? time : -1);
        fields['clusterToFrozenId'] = identity.mapping;
        fields['registryBefore'] = identity.before;
        fields['registryAfter'] = identity.after;
        fields['clusterElapsedMs'] = clusterElapsedMs;
        this.recordDecision(provisional ? 'DIARIZATION_COMMUNITY_PREVIEW' : 'DIARIZATION_COMMUNITY_COMMIT', fields);
      }
    }
  }

  private async commitWindow(endTime: number, evidenceEndTime: number,
    isSessionFinal: boolean, beginTime: number): Promise<SpeakerDiarizationResult> {
    await this.updateSpeakers(endTime, evidenceEndTime, isSessionFinal, beginTime);
    if (this.finished) return this.bestResult();
    if (this.terminalPayload !== undefined) this.decoratePayload(this.terminalPayload);
    const result = this.buildResult(this.degradedReason, this.degradedMessage, endTime, beginTime);
    result.isSessionFinal = isSessionFinal;
    if (this.diagnostic !== undefined) {
      const fields: Record<string, Object> = {};
      fields['publicWindowIndex'] = this.windowIndex;
      fields['beginTime'] = beginTime;
      fields['endTime'] = endTime;
      fields['isSessionFinal'] = isSessionFinal;
      fields['speakerCount'] = result.speakerCount;
      fields['degraded'] = result.degraded;
      fields['degradedReason'] = result.degradedReason;
      fields['degradedMessage'] = result.degradedMessage ?? '';
      fields['speakerTurns'] = result.speakerTurns;
      fields['utterances'] = result.utterances;
      this.recordDecision('DIARIZATION_PUBLIC_RESULT', fields);
    }
    this.transcript.commitThrough(endTime);
    this.publishedThrough = endTime;
    // Public commitment freezes display state, not the input distribution of
    // the unchanged batch clusterer. Evidence stays on disk until client cleanup.
    if (isSessionFinal) {
      this.windows.splice(0, this.windows.length);
    }
    return result;
  }

  private recordDecision(event: string, fields: Record<string, Object>): void {
    try { this.diagnostic?.(event, fields); } catch (_ignored) {}
  }

  onDegraded(reason: SpeakerDiarizationDegradedReason, message: string): void {
    if (this.finished || this.degradedReason !== SpeakerDiarizationDegradedReason.NONE) return;
    this.degradedReason = reason;
    this.degradedMessage = message;
    this.transcript.applySpeakerTurns([], true);
  }

  private buildResult(reason: SpeakerDiarizationDegradedReason,
    message?: string, endTime: number = this.totalSamples * 1000 / SAMPLE_RATE,
    beginTime: number = this.publishedThrough): SpeakerDiarizationResult {
    const result = new SpeakerDiarizationResult();
    result.windowIndex = this.windowIndex;
    result.windowBeginTime = Math.round(beginTime);
    result.windowEndTime = Math.round(endTime);
    const utterances = this.transcript.sentenceUtterances(endTime);
    for (let i = 0; i < utterances.length; i++) {
      result.utterances.push(this.toPublicUtterance(utterances[i]));
    }
    const turns = this.transcript.allTurns();
    for (let i = 0; i < turns.length; i++) {
      if (turns[i].endTime <= beginTime || turns[i].beginTime >= endTime) continue;
      const turn = new SpeakerTurn();
      turn.beginTime = Math.max(beginTime, turns[i].beginTime);
      turn.endTime = Math.min(endTime, turns[i].endTime);
      turn.speakerIndex = speakerIndexFromInternalId(turns[i].speakerId, this.maxSpeakers);
      turn.secondarySpeakerIndexes = speakerIndexesFromInternalIds(
        turns[i].secondarySpeakerIds, this.maxSpeakers, true);
      turn.confidence = turns[i].confidence ?? 0;
      turn.overlap = turns[i].overlap ?? turn.secondarySpeakerIndexes.length > 0;
      result.speakerTurns.push(turn);
    }
    result.speakerCount = this.finalSpeakerCount;
    result.degraded = reason !== SpeakerDiarizationDegradedReason.NONE;
    result.degradedReason = reason;
    result.degradedMessage = message;
    result.inferenceMs = this.inferenceMs;
    const audioMs = Math.max(1, this.totalSamples * 1000 / SAMPLE_RATE);
    result.rtf = this.inferenceMs / audioMs;
    return result;
  }

  private toPublicUpdate(update: DiarizationTranscriptUpdate): SpeakerDiarizationUpdate {
    const result = new SpeakerDiarizationUpdate();
    result.utteranceId = update.utteranceId;
    result.revision = update.revision;
    result.speakerIndex = speakerIndexFromInternalId(update.speakerId, this.maxSpeakers);
    result.secondarySpeakerIndexes = speakerIndexesFromInternalIds(
      update.secondarySpeakerIds, this.maxSpeakers, true);
    result.beginTime = update.beginTime;
    result.endTime = update.endTime;
    result.confidence = update.confidence;
    return result;
  }

  private toPublicUtterance(value: DiarizedTranscriptUtterance): DiarizedUtterance {
    const result = new DiarizedUtterance();
    result.utteranceId = value.utteranceId;
    result.sourceUtteranceId = value.sourceUtteranceId;
    result.rawText = value.rawText;
    result.text = value.text;
    result.beginTime = value.beginTime;
    result.endTime = value.endTime;
    result.speakerIndex = speakerIndexFromInternalId(value.speakerId, this.maxSpeakers);
    result.secondarySpeakerIndexes = speakerIndexesFromInternalIds(
      value.secondarySpeakerIds, this.maxSpeakers, true);
    result.confidence = value.confidence ?? 0;
    result.overlap = value.overlap;
    result.speakerInferred = value.speakerInferred ?? false;
    result.speakerTextSpans = (value.speakerTextSpans ?? []).map(span => {
      const item = new SpeakerTextSpan();
      item.sourceBegin = span.sourceBegin;
      item.sourceEnd = span.sourceEnd;
      item.textBegin = span.textBegin;
      item.textEnd = span.textEnd;
      item.speakerIndex = speakerIndexFromInternalId(span.speakerId, this.maxSpeakers);
      item.secondarySpeakerIndexes = speakerIndexesFromInternalIds(span.secondarySpeakerIds, this.maxSpeakers, true);
      item.confidence = span.confidence;
      item.overlap = span.overlap;
      item.speakerInferred = span.speakerInferred;
      return item;
    });
    return result;
  }

  private releaseRuntimeLease(): void {
    this.runtimeLease?.release();
    this.runtimeLease = undefined;
  }

}
