import { AsrResult, ResultAudioTimeline } from 'amphion_asr';
import { DiarizationCommitClock } from './DiarizationCommitClock';
import {
  DiarizedUtterance, SpeakerDiarizationDegradedReason, SpeakerDiarizationResult,
  SpeakerDiarizationUpdate, SpeakerTurn, SpeechRecognitionResult
} from '../DingqiaoModels';
import { DiarizationLocalWindowResult, SpeakerDiarizationLocalClient,
  SpeakerDiarizationLocalObserver } from './SpeakerDiarizationLocalClient';
import { SpeakerDiarizationRuntimeLease, SpeakerDiarizationRuntimeLeaseRegistry } from './SpeakerDiarizationRuntimeLease';
import { speakerIndexFromInternalId, speakerIndexesFromInternalIds } from './SpeakerDiarizationSpeakerIndex';
import { SpeakerDiarizationTranscriptState, DiarizationTranscriptUpdate,
  DiarizedTranscriptUtterance } from './SpeakerDiarizationTranscriptState';
import { CommunitySpeakerIdentity, communityTimeline } from './CommunitySpeakerIdentity';

const SAMPLE_RATE: number = 16000;
export interface SpeakerDiarizationSessionObserver {
  onSpeakerDiarizationUpdate(update: SpeakerDiarizationUpdate): void;
  onWindowResult(result: SpeakerDiarizationResult): void;
  onFinished(result: SpeakerDiarizationResult): void;
}

export interface SpeakerDiarizationSessionController {
  append(audio: ArrayBuffer): void;
  observeAsrFinal(payload: SpeechRecognitionResult, result: AsrResult): void;
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
  private readonly commitClock: DiarizationCommitClock = new DiarizationCommitClock();
  private readonly identities: CommunitySpeakerIdentity;
  private readonly windows: DiarizationLocalWindowResult[] = [];
  private readonly observer: SpeakerDiarizationSessionObserver;
  private readonly maxSpeakers: number;
  private readonly diagnostic?: (event: string, fields: Record<string, Object>) => void;
  private inferenceEndMs: number = 0;
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
    diagnostic?: (event: string, fields: Record<string, Object>) => void) {
    this.observer = observer;
    this.diagnostic = diagnostic;
    this.maxSpeakers = maxSpeakers;
    this.identities = new CommunitySpeakerIdentity(maxSpeakers);
    this.runtimeLease = SpeakerDiarizationRuntimeLeaseRegistry.acquire();
    try { this.client = new SpeakerDiarizationLocalClient(context, workPath, this, diagnostic); }
    catch (error) {
      this.runtimeLease.release();
      this.runtimeLease = undefined;
      throw new Error(`${error}`);
    }
  }

  append(audio: ArrayBuffer): void {
    if (this.finishRequested || this.finished) return;
    this.totalSamples += audio.byteLength / 2;
    try {
      this.client.append(audio);
    } catch (e) {
      this.onDegraded(SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
        `speaker diarization audio spool failed: ${e}`);
    }
  }

  observeAsrFinal(payload: SpeechRecognitionResult, result: AsrResult): void {
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
    const utteranceId = this.transcript.addUtterance({
      rawText: result.rawText,
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
    const queued = this.commitClock.observeProcessedAudio(endSample * 1000 / SAMPLE_RATE);
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
    this.windows.push(window);
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
        }
        break;
      }
    } catch (error) {
      if (!this.finished) {
        this.onDegraded(SpeakerDiarizationDegradedReason.INFERENCE_UNAVAILABLE,
          `Community finalization failed: ${error}`);
        if (this.finishRequested && this.processDrained && this.asrTailObserved) {
          const result = this.bestResult();
          result.isSessionFinal = true;
          this.finished = true;
          this.observer.onFinished(result);
        }
      }
    } finally { this.committing = false; }
  }

  private async commitWindow(endTime: number, evidenceEndTime: number,
    isSessionFinal: boolean, beginTime: number): Promise<SpeakerDiarizationResult> {
    // Snapshot before awaiting native work. Later windows cannot change this commit.
    const available = this.windows.filter(window => isSessionFinal ||
      (window.windowStartSample + 160000) * 1000 / SAMPLE_RATE <= evidenceEndTime);
    if (!this.confirmedInitialSilence && available.length > 0 &&
      this.degradedReason === SpeakerDiarizationDegradedReason.NONE) {
      const segments = new Float32Array(available.length * 589 * 3);
      const embeddings = new Float32Array(available.length * 3 * 256);
      const activity: number[] = new Array<number>(available.length * 3).fill(0);
      const publishedActivity: number[] = new Array<number>(available.length * 3).fill(0);
      for (let index = 0; index < available.length; index++) {
        segments.set(available[index].result.segments, index * 589 * 3);
        embeddings.set(available[index].result.embeddings, index * 3 * 256);
        for (let frame = 0; frame < 589; frame++) {
          const frameTime = (available[index].windowStartSample + 495.5 + frame * 270) * 1000 / SAMPLE_RATE;
          for (let channel = 0; channel < 3; channel++) {
            activity[index * 3 + channel] += available[index].result.segments[frame * 3 + channel];
            if (frameTime >= beginTime && frameTime < endTime) {
              publishedActivity[index * 3 + channel] += available[index].result.segments[frame * 3 + channel];
            }
          }
        }
      }
      const startedMs = Date.now();
      const clustered = await this.client.cluster(segments, embeddings, this.maxSpeakers);
      if (this.finished) return this.bestResult();
      this.inferenceMs += Date.now() - startedMs;
      const visibleClusters: boolean[] = new Array<boolean>(clustered.speakerCount).fill(false);
      for (const turn of clustered.turns) {
        if (turn[0] < endTime && turn[1] > beginTime) visibleClusters[turn[2]] = true;
      }
      const identity = this.identities.assign(clustered.hard, clustered.speakerCount,
        activity, publishedActivity, visibleClusters);
      this.finalSpeakerCount = identity.after;
      const turns = communityTimeline(clustered.turns, identity.mapping, beginTime, endTime);
      const updates = this.transcript.applySpeakerTurns(turns);
      for (const update of updates) {
        this.observer.onSpeakerDiarizationUpdate(this.toPublicUpdate(update));
        if (this.finished) return this.bestResult();
      }
      if (this.diagnostic !== undefined) {
        const fields: Record<string, Object> = {};
        fields['publicWindowIndex'] = this.windowIndex;
        fields['beginTime'] = beginTime;
        fields['endTime'] = endTime;
        fields['evidenceEndTime'] = Number.isFinite(evidenceEndTime) ? evidenceEndTime : -1;
        fields['jobIds'] = available.map(window => window.jobId);
        fields['trainingIndices'] = clustered.trainingIndices;
        fields['ahc'] = clustered.ahc;
        fields['priors'] = clustered.priors;
        fields['hard'] = clustered.hard;
        fields['model'] = 'Community-1 masked WeSpeaker / PLDA / VBx';
        fields['similarityOffset'] = 1;
        fields['embeddingToClusterScores'] = clustered.scores;
        fields['clusterCentroids'] = clustered.centroids;
        fields['trainingPosteriors'] = clustered.posteriors;
        fields['usedKMeansCap'] = clustered.usedKMeans;
        fields['activityVotes'] = identity.votes;
        fields['publishedActivity'] = publishedActivity;
        fields['visibleClusters'] = visibleClusters;
        fields['clusterToFrozenId'] = identity.mapping;
        fields['registryBefore'] = identity.before;
        fields['registryAfter'] = identity.after;
        this.recordDecision('DIARIZATION_COMMUNITY_COMMIT', fields);
      }
    }
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
    return result;
  }

  private recordDecision(event: string, fields: Record<string, Object>): void {
    try { this.diagnostic?.(event, fields); } catch (_ignored) {}
  }

  onDegraded(reason: SpeakerDiarizationDegradedReason, message: string): void {
    if (this.degradedReason !== SpeakerDiarizationDegradedReason.NONE) return;
    this.degradedReason = reason;
    this.degradedMessage = message;
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
    return result;
  }

  private releaseRuntimeLease(): void {
    this.runtimeLease?.release();
    this.runtimeLease = undefined;
  }

}
