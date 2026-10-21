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
import { nmnetTimeline } from './NmnetTimeline';
import { NmnetDiarizationDelta } from 'amphion_asr';
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
  /** Finish timeout: freeze speakers for audio already inferred instead of discarding them. */
  salvage(): void;
  /** Work the finish inherited and how long clearing it took; -1 where unreached. */
  finishProgress(): SpeakerDiarizationFinishProgress;
  cleanup(): void;
}

/** Reported, never acted on: the terms behind one session's stop-to-roles wait. */
export interface SpeakerDiarizationFinishProgress {
  stopToDrainedMs: number;
  backlogWindowsAtStop: number;
  pendingCommitsAtStop: number;
  inferredWindows: number;
  lastCommitClusterMs: number;
  inferenceEndMs: number;
  audioEndMs: number;
  encoderBackend: string;
}

export class SpeakerDiarizationSession implements SpeakerDiarizationLocalObserver,
  SpeakerDiarizationSessionController {
  private readonly client: SpeakerDiarizationLocalClient;
  private readonly transcript: SpeakerDiarizationTranscriptState = new SpeakerDiarizationTranscriptState();
  private readonly commitClock: DiarizationCommitClock;
  private rolesCommittedEndMs: number = 0;
  private readonly committedTracks: number[][] = [];
  private readonly windows: DiarizationEvidenceWindow[] = [];
  private readonly observer: SpeakerDiarizationSessionObserver;
  private readonly maxSpeakers: number;
  private readonly diagnostic?: (event: string, fields: Record<string, Object>) => void;
  private inferenceEndMs: number = 0;
  private processedThroughMs: number = 0;
  private static readonly PREVIEW_INTERVAL_MS: number = 10000;
  // Timeline projection cost grows with the number of pending turns.
  // Space previews so that their wall time stays within a tenth of the audio they
  // cover. Short sessions keep a preview every 10 s; commits are unaffected.
  private static readonly PREVIEW_COST_RATIO: number = 20;
  private previewThroughMs: number = 0;
  private lastPreviewClusterMs: number = 0;
  private inferenceMs: number = 0;
  private totalSamples: number = 0;
  private lastAsrEndMs: number = 0;
  private publishedThrough: number = 0;
  private windowIndex: number = 0;
  private finalSpeakerCount: number = 0;
  // Last backend the encoder reported; 'auto' resolves per load, not per window.
  private encoderBackend: string = '';
  private terminalPayload?: SpeechRecognitionResult;
  private degradedReason: SpeakerDiarizationDegradedReason = SpeakerDiarizationDegradedReason.NONE;
  private degradedMessage?: string;
  private finishRequested: boolean = false;
  private confirmedInitialSilence: boolean = false;
  private processDrained: boolean = false;
  private asrTailObserved: boolean = false;
  private finished: boolean = false;
  private committing: boolean = false;
  // Audio end covered by inferred windows when a finish timeout stopped inference.
  private salvagedThroughMs?: number;
  // Finish decomposition, reported once per session so a slow finish names its
  // own dominant term instead of being inferred from the total.
  private finishAtMs: number = 0;
  private drainedAtMs: number = 0;
  private backlogWindowsAtFinish: number = -1;
  private pendingCommitsAtFinish: number = -1;
  private lastCommitClusterMs: number = -1;
  // Windows inference actually returned. this.windows is emptied on the final
  // commit and windowIndex counts published results, so neither can stand in.
  private inferredWindowCount: number = 0;
  private runtimeLease?: SpeakerDiarizationRuntimeLease;

  constructor(context: Context, workPath: string, maxSpeakers: number,
    observer: SpeakerDiarizationSessionObserver,
    diagnostic?: (event: string, fields: Record<string, Object>) => void,
    clientOptions?: SpeakerDiarizationLocalClientOptions, commitPeriodMs: number = 120000) {
    this.observer = observer;
    this.diagnostic = diagnostic;
    this.maxSpeakers = maxSpeakers;
    this.commitClock = new DiarizationCommitClock(commitPeriodMs);
    this.runtimeLease = SpeakerDiarizationRuntimeLeaseRegistry.acquire();
    try {
      this.client = new SpeakerDiarizationLocalClient(context, workPath, this, diagnostic, clientOptions, maxSpeakers);
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
    // Sampled before anything drains: this is the work the finish inherited.
    this.finishAtMs = Date.now();
    this.backlogWindowsAtFinish = this.client.pendingWindowCount();
    this.pendingCommitsAtFinish = this.commitClock.pendingCount();
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

  salvage(): void {
    // A drained session already owns a complete final commit; let it finish normally.
    if (this.finished || !this.finishRequested || this.processDrained ||
      this.salvagedThroughMs !== undefined) return;
    this.salvagedThroughMs = this.rolesCommittedEndMs;
    if (this.diagnostic !== undefined) {
      const fields: Record<string, Object> = {};
      fields['inferenceEndMs'] = this.inferenceEndMs;
      fields['audioEndSample'] = this.totalSamples;
      fields['windows'] = this.windows.length;
      this.recordDecision('DIARIZATION_FINISH_SALVAGE', fields);
    }
    this.client.stopInference();
    this.transcript.limitEvidence(this.rolesCommittedEndMs);
    this.processDrained = true;
    this.finalizeIfReady();
  }

  finishProgress(): SpeakerDiarizationFinishProgress {
    return {
      stopToDrainedMs: this.drainedAtMs > 0 && this.finishAtMs > 0 ?
        this.drainedAtMs - this.finishAtMs : -1,
      backlogWindowsAtStop: this.backlogWindowsAtFinish,
      pendingCommitsAtStop: this.pendingCommitsAtFinish,
      inferredWindows: this.inferredWindowCount,
      lastCommitClusterMs: this.lastCommitClusterMs,
      inferenceEndMs: Math.round(this.inferenceEndMs),
      audioEndMs: Math.round(this.totalSamples * 1000 / SAMPLE_RATE),
      encoderBackend: this.encoderBackend.length > 0 ? this.encoderBackend : 'unknown',
    };
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
    if (this.finished || this.confirmedInitialSilence || this.salvagedThroughMs !== undefined) return;
    this.inferredWindowCount += 1;
    this.inferenceEndMs = window.result.inferenceThroughSample / 16;
    this.inferenceMs += window.inferenceWallMs;
    this.acceptDelta(window.result);
    this.flushReadyWindows();
  }

  private acceptDelta(delta: NmnetDiarizationDelta): void {
    this.rolesCommittedEndMs = delta.rolesCommittedThroughSample / 16;
    this.finalSpeakerCount = delta.speakerCount;
    this.encoderBackend = 'cpu';
    for (const turn of delta.turns) this.committedTracks.push(turn);
  }

  onFlushed(delta: NmnetDiarizationDelta): void {
    if (this.finished || this.confirmedInitialSilence || this.salvagedThroughMs !== undefined) return;
    this.acceptDelta(delta);
  }

  onDrained(): void {
    if (!this.finishRequested || this.finished) return;
    this.processDrained = true;
    if (this.drainedAtMs === 0) this.drainedAtMs = Date.now();
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
          this.rolesCommittedEndMs : Number.POSITIVE_INFINITY;
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
        // Preview only completed audio snapshots, at most once per 10 s of audio
        // and less often once a preview gets expensive. It never advances the
        // public commit clock or enrolls frozen IDs.
        const interval = SpeakerDiarizationSession.PREVIEW_INTERVAL_MS;
        const previewEnd = Math.floor(Math.min(this.rolesCommittedEndMs, this.processedThroughMs) / interval) * interval;
        const previewGap = Math.max(interval,
          SpeakerDiarizationSession.PREVIEW_COST_RATIO * this.lastPreviewClusterMs);
        if (!this.finishRequested && this.degradedReason === SpeakerDiarizationDegradedReason.NONE &&
          this.lastAsrEndMs > this.publishedThrough &&
          previewEnd >= Math.max(this.previewThroughMs, this.publishedThrough) + previewGap) {
          this.previewThroughMs = previewEnd;
          await this.updateSpeakers(previewEnd, previewEnd, false, this.publishedThrough, true);
          continue;
        }
        break;
      }
    } catch (error) {
      if (!this.finished) {
        this.onDegraded(SpeakerDiarizationDegradedReason.INFERENCE_UNAVAILABLE,
          `NMNet finalization failed: ${error}`);
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
    if (this.confirmedInitialSilence || this.degradedReason !== SpeakerDiarizationDegradedReason.NONE) return;
    const safeEnd = Math.min(endTime, this.rolesCommittedEndMs);
    const mapping: number[] = [];
    for (let id = 0; id < this.finalSpeakerCount; id++) mapping.push(id);
    const turns = nmnetTimeline(this.committedTracks, mapping, beginTime, safeEnd);
    const updates = this.transcript.applySpeakerTurns(turns, true);
    for (const update of updates) {
      this.observer.onSpeakerDiarizationUpdate(this.toPublicUpdate(update));
      if (this.finished) return;
    }
    this.lastCommitClusterMs = 0;
  }

  private async commitWindow(endTime: number, evidenceEndTime: number,
    isSessionFinal: boolean, beginTime: number): Promise<SpeakerDiarizationResult> {
    await this.updateSpeakers(endTime, evidenceEndTime, isSessionFinal, beginTime);
    if (this.finished) return this.bestResult();
    if (this.terminalPayload !== undefined) this.decoratePayload(this.terminalPayload);
    const salvaged = isSessionFinal && this.degradedReason === SpeakerDiarizationDegradedReason.NONE ?
      this.salvagedThroughMs : undefined;
    const result = salvaged === undefined ?
      this.buildResult(this.degradedReason, this.degradedMessage, endTime, beginTime) :
      this.buildResult(SpeakerDiarizationDegradedReason.FINISH_TIMEOUT,
        `speaker diarization finish timeout; speakers cover audio before ${Math.round(salvaged)}ms` +
          `; encoder backend ${this.encoderBackend.length > 0 ? this.encoderBackend : 'unknown'}`,
        endTime, beginTime);
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
    for (let i = this.committedTracks.length - 1; i >= 0; i--) {
      if (this.committedTracks[i][1] <= endTime) this.committedTracks.splice(i, 1);
    }
    // History is owned by native state and survives public display commits.
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
    result.encoderBackend = this.encoderBackend;
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
