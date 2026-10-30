import { AsrResult, AsrTextNormalizationSpan, ResultAudioTimeline } from 'amphion_asr';
import { DiarizationCommitClock } from './DiarizationCommitClock';
import {
  DiarizedUtterance, SpeakerDiarizationDegradedReason, SpeakerDiarizationResult,
  SpeakerDiarizationUpdate, SpeakerTurn, SpeakerTextSpan, SpeechRecognitionResult
} from '../DingqiaoModels';
import { SortformerLocalClient, SortformerLocalObserver, SortformerLocalClientOptions,
  SortformerLocalFeedResult } from './SortformerLocalClient';
import { SortformerSpeakerIdentity } from './SortformerSpeakerIdentity';
import { SpeakerDiarizationRuntimeLease, SpeakerDiarizationRuntimeLeaseRegistry } from './SpeakerDiarizationRuntimeLease';
import { speakerIndexFromInternalId, speakerIndexesFromInternalIds } from './SpeakerDiarizationSpeakerIndex';
import { SpeakerDiarizationTranscriptState, DiarizationTranscriptUpdate,
  DiarizedTranscriptUtterance, TranscriptTextNormalization, TranscriptTextPresentation,
  TranscriptNormalizationSpan } from './SpeakerDiarizationTranscriptState';
import { timelineTurns, TimelineTurn } from './SpeakerTimeline';
import { PoliceTextProvenance, PoliceTextSpan } from '../PoliceEnhancementPolicy';

const SAMPLE_RATE: number = 16000;
// A speech run of one Sortformer slot: [beginTime, endTime, slot] in milliseconds.
// Final runs never change once reported; preview runs cover only the part of the
// current chunk ahead of its final result and are replaced by it.
type SortformerTrack = number[];
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

export class SpeakerDiarizationSession implements SortformerLocalObserver,
  SpeakerDiarizationSessionController {
  private readonly client: SortformerLocalClient;
  private readonly transcript: SpeakerDiarizationTranscriptState = new SpeakerDiarizationTranscriptState();
  private readonly commitClock: DiarizationCommitClock;
  private readonly identities: SortformerSpeakerIdentity;
  private readonly finalTracks: SortformerTrack[] = [];
  private previewTracks: SortformerTrack[] = [];
  // Turns of every published commit, frozen: a commit only ever appends to
  // this list, so a provisional refresh costs the uncommitted span, not the meeting.
  private committedTurns: TimelineTurn[] = [];
  private readonly observer: SpeakerDiarizationSessionObserver;
  private readonly maxSpeakers: number;
  private readonly diagnostic?: (event: string, fields: Record<string, Object>) => void;
  private inferenceEndMs: number = 0;
  private processedThroughMs: number = 0;
  private inferenceMs: number = 0;
  private totalSamples: number = 0;
  private lastAsrEndMs: number = 0;
  private publishedThrough: number = 0;
  private windowIndex: number = 0;
  private finalSpeakerCount: number = 0;
  // The Sortformer chain runs on the CPU; reported once the first chunk returns.
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
  // Final chunks the engine returned; windowIndex counts published results.
  private inferredWindowCount: number = 0;
  private runtimeLease?: SpeakerDiarizationRuntimeLease;

  constructor(context: Context, workPath: string, maxSpeakers: number,
    observer: SpeakerDiarizationSessionObserver,
    diagnostic?: (event: string, fields: Record<string, Object>) => void,
    clientOptions?: SortformerLocalClientOptions, commitPeriodMs: number = 120000) {
    this.observer = observer;
    this.diagnostic = diagnostic;
    this.maxSpeakers = maxSpeakers;
    this.commitClock = new DiarizationCommitClock(commitPeriodMs);
    this.identities = new SortformerSpeakerIdentity(maxSpeakers);
    this.runtimeLease = SpeakerDiarizationRuntimeLeaseRegistry.acquire();
    // workPath stays in the signature for the SDK entry point; the engine keeps
    // its state natively and spools nothing.
    try {
      this.client = new SortformerLocalClient(context, this, diagnostic, clientOptions);
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
    this.salvagedThroughMs = this.inferenceEndMs;
    if (this.diagnostic !== undefined) {
      const fields: Record<string, Object> = {};
      fields['inferenceEndMs'] = this.inferenceEndMs;
      fields['audioEndSample'] = this.totalSamples;
      fields['chunks'] = this.inferredWindowCount;
      this.recordDecision('DIARIZATION_FINISH_SALVAGE', fields);
    }
    this.client.stopInference();
    this.transcript.limitEvidence(this.inferenceEndMs);
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

  onFeedResult(result: SortformerLocalFeedResult): void {
    if (this.finished || this.confirmedInitialSilence || this.salvagedThroughMs !== undefined) return;
    // Outside the diagnostic block on purpose: a caller on a release build reads
    // where role work ran from the public result.
    this.encoderBackend = 'cpu';
    let changed = false;
    for (const event of result.events) {
      this.inferenceMs += event.inferenceMs;
      if (event.kind === 'final') {
        this.inferredWindowCount += 1;
        this.lastCommitClusterMs = Math.round(event.inferenceMs);
        const firstSpeech: number[] = [-1, -1, -1, -1];
        for (let slot = 0; slot < event.runs.length && slot < 4; slot++) {
          for (const run of event.runs[slot]) {
            this.finalTracks.push([run[0], run[1], slot]);
            if (firstSpeech[slot] < 0) firstSpeech[slot] = run[0];
          }
        }
        const identity = this.identities.commit(firstSpeech);
        this.finalSpeakerCount = identity.after;
        // A final chunk supersedes any preview of the same audio.
        this.previewTracks = this.previewTracks.filter((track: SortformerTrack): boolean =>
          track[0] >= event.endTime);
        this.inferenceEndMs = Math.max(this.inferenceEndMs, event.endTime);
        changed = true;
        if (this.diagnostic !== undefined) {
          const fields: Record<string, Object> = {};
          fields['jobId'] = result.jobId;
          fields['model'] = 'Sortformer-66M-4spk';
          fields['beginTime'] = event.beginTime;
          fields['endTime'] = event.endTime;
          fields['inferenceMs'] = event.inferenceMs;
          fields['runs'] = event.runs;
          fields['firstSpeechTimes'] = firstSpeech;
          fields['slotToPublicId'] = identity.mapping;
          fields['registryBefore'] = identity.before;
          fields['registryAfter'] = identity.after;
          fields['encoderBackend'] = 'cpu';
          fields['inferenceWallMs'] = result.inferenceWallMs;
          this.recordDecision('DIARIZATION_SORTFORMER_CHUNK', fields);
        }
      } else {
        const tracks: SortformerTrack[] = [];
        for (let slot = 0; slot < event.runs.length && slot < 4; slot++) {
          for (const run of event.runs[slot]) tracks.push([run[0], run[1], slot]);
        }
        this.previewTracks = tracks;
        changed = true;
        if (this.diagnostic !== undefined) {
          const fields: Record<string, Object> = {};
          fields['jobId'] = result.jobId;
          fields['beginTime'] = event.beginTime;
          fields['endTime'] = event.endTime;
          fields['inferenceMs'] = event.inferenceMs;
          fields['runs'] = event.runs;
          fields['slotToPublicId'] = this.identities.mapping();
          this.recordDecision('DIARIZATION_SORTFORMER_PREVIEW', fields);
        }
      }
    }
    // The flushed tail shorter than one encoder frame is never inferred; let the
    // commit clock treat the stream as complete through the last mel frame.
    if (result.flushed) this.inferenceEndMs = Math.max(this.inferenceEndMs, result.melEndTime);
    if (changed && this.degradedReason === SpeakerDiarizationDegradedReason.NONE) this.refreshProvisional();
    this.flushReadyWindows();
  }

  /** Timeline turns for [beginTime, endTime) from final runs, plus previews when asked. */
  private timelineFrom(beginTime: number, endTime: number, includePreview: boolean): TimelineTurn[] {
    const tracks: SortformerTrack[] = [];
    for (const track of this.finalTracks) {
      if (track[1] > beginTime && track[0] < endTime) tracks.push(track);
    }
    if (includePreview) {
      for (const track of this.previewTracks) {
        if (track[1] > beginTime && track[0] < endTime) tracks.push(track);
      }
    }
    return timelineTurns(tracks, this.identities.mapping(), beginTime, endTime);
  }

  // Provisional roles for the uncommitted span, refreshed on every engine
  // report. Committed turns are reused as frozen; nothing here advances the
  // commit clock or the published boundary.
  private refreshProvisional(): void {
    const turns = this.committedTurns.concat(
      this.timelineFrom(this.publishedThrough, Number.POSITIVE_INFINITY, true));
    const updates = this.transcript.applySpeakerTurns(turns, true);
    for (const update of updates) {
      this.observer.onSpeakerDiarizationUpdate(this.toPublicUpdate(update));
      if (this.finished) return;
    }
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
        break;
      }
    } catch (error) {
      if (!this.finished) {
        this.onDegraded(SpeakerDiarizationDegradedReason.INFERENCE_UNAVAILABLE,
          `Sortformer finalization failed: ${error}`);
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
    isSessionFinal: boolean, beginTime: number): Promise<void> {
    if (this.confirmedInitialSilence || this.degradedReason !== SpeakerDiarizationDegradedReason.NONE) return;
    const startedMs = Date.now();
    // Only final runs enter a commit: the commit clock waits until the chunk
    // covering evidenceEndTime is final, so the span is fully decided.
    const frozen = this.timelineFrom(beginTime, endTime, false);
    this.committedTurns = this.committedTurns.concat(frozen);
    const turns = isSessionFinal ? this.committedTurns :
      this.committedTurns.concat(this.timelineFrom(endTime, Number.POSITIVE_INFINITY, true));
    const updates = this.transcript.applySpeakerTurns(turns, true);
    for (const update of updates) {
      this.observer.onSpeakerDiarizationUpdate(this.toPublicUpdate(update));
      if (this.finished) return;
    }
    this.finalSpeakerCount = this.identities.publishedCount();
    if (this.diagnostic !== undefined) {
      const fields: Record<string, Object> = {};
      fields['publicWindowIndex'] = this.windowIndex;
      fields['beginTime'] = beginTime;
      fields['endTime'] = endTime;
      fields['evidenceEndTime'] = Number.isFinite(evidenceEndTime) ? evidenceEndTime : -1;
      fields['model'] = 'Sortformer-66M-4spk';
      fields['frozenTurns'] = frozen.length;
      fields['committedTurns'] = this.committedTurns.length;
      fields['slotToPublicId'] = this.identities.mapping();
      fields['registryAfter'] = this.identities.publishedCount();
      fields['assembleMs'] = Date.now() - startedMs;
      this.recordDecision('DIARIZATION_SORTFORMER_COMMIT', fields);
    }
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
    const utterances = this.transcript.aggregatedUtterances(endTime);
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
    result.sourceUtteranceIds = (value.sourceUtteranceIds ?? [value.sourceUtteranceId]).slice();
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
