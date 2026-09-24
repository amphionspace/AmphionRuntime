import { AsrResult, ResultAudioTimeline } from 'amphion_asr';
import {
  DiarizedUtterance,
  SpeakerDiarizationDegradedReason,
  SpeakerDiarizationResult,
  SpeakerDiarizationUpdate,
  SpeakerTurn,
  SpeechRecognitionResult
} from '../DingqiaoModels';
import {
  DiarizationLocalWindowResult,
  SpeakerDiarizationLocalClient,
  SpeakerDiarizationLocalObserver
} from './SpeakerDiarizationLocalClient';
import { SpeakerDiarizationRuntimeLease, SpeakerDiarizationRuntimeLeaseRegistry } from './SpeakerDiarizationRuntimeLease';
import {
  speakerIndexFromInternalId,
  speakerIndexesFromInternalIds
} from './SpeakerDiarizationSpeakerIndex';
import {
  DiarizationTranscriptUpdate,
  DiarizedTranscriptUtterance,
  SpeakerDiarizationTranscriptState,
  SpeakerTimelineTurn
} from './SpeakerDiarizationTranscriptState';
import {
  Community1TimelineReconstructor,
  Community1TimelineResult
} from './Community1TimelineReconstructor';

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
  finish(): void;
  decoratePayload(payload: SpeechRecognitionResult): void;
  bestResult(reason?: SpeakerDiarizationDegradedReason, message?: string): SpeakerDiarizationResult;
  cleanup(): void;
}

/** Whole-session Community-1 pipeline with final-only stable role labels. */
export class SpeakerDiarizationSession implements SpeakerDiarizationLocalObserver,
  SpeakerDiarizationSessionController {
  private readonly client: SpeakerDiarizationLocalClient;
  private readonly transcript: SpeakerDiarizationTranscriptState = new SpeakerDiarizationTranscriptState();
  private readonly observer: SpeakerDiarizationSessionObserver;
  private readonly minSpeakers?: number;
  private readonly maxSpeakers?: number;
  private readonly windows: DiarizationLocalWindowResult[] = [];
  private readonly reconstructor: Community1TimelineReconstructor = new Community1TimelineReconstructor();
  private standardTurns: SpeakerTimelineTurn[] = [];
  private exclusiveTurns: SpeakerTimelineTurn[] = [];
  private terminalPayload?: SpeechRecognitionResult;
  private totalSamples: number = 0;
  private lastAsrEndMs: number = 0;
  private inferenceMs: number = 0;
  private finalSpeakerCount: number = 0;
  private degradedReason: SpeakerDiarizationDegradedReason = SpeakerDiarizationDegradedReason.NONE;
  private degradedMessage?: string;
  private finishRequested: boolean = false;
  private processDrained: boolean = false;
  private asrTailObserved: boolean = false;
  private finished: boolean = false;
  private finalizing: boolean = false;
  private runtimeLease?: SpeakerDiarizationRuntimeLease;
  private readonly diagnostic?: (event: string, fields: Record<string, Object>) => void;

  constructor(context: Context, workPath: string, minSpeakers: number | undefined,
    maxSpeakers: number | undefined, observer: SpeakerDiarizationSessionObserver,
    diagnostic?: (event: string, fields: Record<string, Object>) => void) {
    this.observer = observer;
    this.diagnostic = diagnostic;
    this.minSpeakers = minSpeakers;
    this.maxSpeakers = maxSpeakers;
    this.runtimeLease = SpeakerDiarizationRuntimeLeaseRegistry.acquire();
    try {
      this.client = new SpeakerDiarizationLocalClient(context, workPath, this);
    } catch (error) {
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
    } catch (error) {
      this.onDegraded(SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
        `speaker diarization audio spool failed: ${error}`);
    }
  }

  observeAsrFinal(payload: SpeechRecognitionResult, result: AsrResult): void {
    if (payload.isLast) {
      this.asrTailObserved = true;
      this.terminalPayload = payload;
    }
    if (payload.result.length > 0) {
      const timestampMs = result.timestamps.map(
        (timestamp: number): number => Math.round(timestamp * 1000));
      const beginTime = payload.beginTime ?? timestampMs[0] ?? this.lastAsrEndMs;
      const endTime = payload.endTime ?? timestampMs[timestampMs.length - 1] ??
        Math.round(this.totalSamples * 1000 / SAMPLE_RATE);
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
      this.decoratePayload(payload);
    }
    this.finalizeIfReady();
  }

  asrFinalDelivered(_result: AsrResult): void {
    // Community-1 jointly estimates identities after all chunks are available.
  }

  finish(): void {
    if (this.finishRequested || this.finished) return;
    this.finishRequested = true;
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
    if (this.finished) return;
    this.windows.push(window);
    this.inferenceMs += window.result.inferenceMs;
  }

  onDrained(): void {
    if (!this.finishRequested || this.finished || this.finalizing) return;
    this.finalizing = true;
    void this.finalizeCommunity();
  }

  onDegraded(reason: SpeakerDiarizationDegradedReason, message: string): void {
    if (this.degradedReason !== SpeakerDiarizationDegradedReason.NONE) return;
    this.degradedReason = reason;
    this.degradedMessage = message;
    if (this.diagnostic !== undefined) {
      const fields: Record<string, Object> = {};
      fields['reason'] = reason;
      fields['message'] = message;
      this.diagnostic('COMMUNITY1_DIARIZATION_DEGRADED', fields);
    }
  }

  private async finalizeCommunity(): Promise<void> {
    try {
      if (this.windows.length > 0 &&
        this.degradedReason === SpeakerDiarizationDegradedReason.NONE) {
        const clustering = await this.client.clusterCommunity(
          this.windows.map(window => window.result), this.minSpeakers, this.maxSpeakers);
        const timeline: Community1TimelineResult = this.reconstructor.reconstruct(
          this.windows, clustering, this.totalSamples, this.maxSpeakers);
        this.standardTurns = timeline.speakerTurns;
        this.exclusiveTurns = timeline.exclusiveSpeakerTurns;
        this.finalSpeakerCount = timeline.speakerCount;
        const updates = this.transcript.applySpeakerTurns(this.exclusiveTurns);
        for (let index = 0; index < updates.length; index++) {
          this.observer.onSpeakerDiarizationUpdate(this.toPublicUpdate(updates[index]));
        }
        if (clustering.constraintViolated ||
          (this.minSpeakers !== undefined && this.finalSpeakerCount < this.minSpeakers) ||
          (this.maxSpeakers !== undefined && this.finalSpeakerCount > this.maxSpeakers)) {
          this.onDegraded(SpeakerDiarizationDegradedReason.SPEAKER_LIMIT_EXCEEDED,
            `automatic speaker count ${this.finalSpeakerCount} is outside configured range ` +
            `[${this.minSpeakers ?? 1}, ${this.maxSpeakers ?? 'unbounded'}]`);
        }
      }
    } catch (error) {
      this.onDegraded(SpeakerDiarizationDegradedReason.INFERENCE_UNAVAILABLE,
        `Community-1 PLDA/VBx finalization failed: ${error}`);
    }
    this.processDrained = true;
    this.finalizeIfReady();
  }

  private finalizeIfReady(): void {
    if (!this.finishRequested || this.finished || !this.processDrained || !this.asrTailObserved) return;
    if (this.terminalPayload !== undefined) this.decoratePayload(this.terminalPayload);
    const result = this.buildResult(this.degradedReason, this.degradedMessage);
    result.isSessionFinal = true;
    this.finished = true;
    this.observer.onFinished(result);
  }

  private buildResult(reason: SpeakerDiarizationDegradedReason,
    message?: string): SpeakerDiarizationResult {
    const result = new SpeakerDiarizationResult();
    result.windowBeginTime = 0;
    result.windowEndTime = Math.round(this.totalSamples * 1000 / SAMPLE_RATE);
    const utterances = this.transcript.sentenceUtterances();
    for (let index = 0; index < utterances.length; index++) {
      result.utterances.push(this.toPublicUtterance(utterances[index]));
    }
    result.speakerTurns = this.standardTurns.map(
      (turn: SpeakerTimelineTurn): SpeakerTurn => this.toPublicTurn(turn));
    result.exclusiveSpeakerTurns = this.exclusiveTurns.map(
      (turn: SpeakerTimelineTurn): SpeakerTurn => this.toPublicTurn(turn));
    result.speakerCount = this.finalSpeakerCount;
    result.degraded = reason !== SpeakerDiarizationDegradedReason.NONE;
    result.degradedReason = reason;
    result.degradedMessage = message;
    result.inferenceMs = this.inferenceMs;
    result.rtf = this.inferenceMs /
      Math.max(1, this.totalSamples * 1000 / SAMPLE_RATE);
    return result;
  }

  private toPublicTurn(value: SpeakerTimelineTurn): SpeakerTurn {
    const turn = new SpeakerTurn();
    turn.beginTime = value.beginTime;
    turn.endTime = value.endTime;
    turn.speakerIndex = speakerIndexFromInternalId(value.speakerId, this.maxSpeakers);
    turn.secondarySpeakerIndexes = speakerIndexesFromInternalIds(
      value.secondarySpeakerIds, this.maxSpeakers, true);
    turn.confidence = value.confidence ?? 0;
    turn.overlap = value.overlap ?? turn.secondarySpeakerIndexes.length > 0;
    return turn;
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
