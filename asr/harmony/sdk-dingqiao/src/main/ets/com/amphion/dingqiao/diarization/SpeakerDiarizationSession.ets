import { AsrResult, ResultAudioTimeline } from 'amphion_asr';
import { DiarizationCommitClock } from './DiarizationCommitClock';
import {
  DiarizedUtterance,
  SpeakerDiarizationDegradedReason,
  SpeakerDiarizationResult,
  SpeakerDiarizationUpdate,
  SpeakerTurn,
  SpeechRecognitionResult
} from '../DingqiaoModels';
import { OnlineSpeakerRegistry } from './OnlineSpeakerRegistry';
import {
  SpeakerDiarizationEmbeddingObservation,
  SpeakerDiarizationGlobalClusterer
} from './SpeakerDiarizationGlobalClusterer';
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
  SpeakerTimelineTurn,
  SpeakerDiarizationTranscriptState,
  DiarizationTranscriptUpdate,
  DiarizedTranscriptUtterance
} from './SpeakerDiarizationTranscriptState';

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

export class SpeakerDiarizationSession implements SpeakerDiarizationLocalObserver,
  SpeakerDiarizationSessionController {
  private readonly client: SpeakerDiarizationLocalClient;
  private registry: OnlineSpeakerRegistry;
  private readonly transcript: SpeakerDiarizationTranscriptState = new SpeakerDiarizationTranscriptState();
  private readonly observer: SpeakerDiarizationSessionObserver;
  private readonly globalClusterer: SpeakerDiarizationGlobalClusterer;
  private readonly maxSpeakers: number;
  private recentEmbeddingObservations: SpeakerDiarizationEmbeddingObservation[] = [];
  private readonly commitClock: DiarizationCommitClock = new DiarizationCommitClock();
  private readonly committedRegistry: OnlineSpeakerRegistry;
  private inferenceEndMs: number = 0;
  private windowIndex: number = 0;
  private terminalPayload?: SpeechRecognitionResult;
  private totalSamples: number = 0;
  private lastAsrEndMs: number = 0;
  private inferenceMs: number = 0;
  private degradedReason: SpeakerDiarizationDegradedReason = SpeakerDiarizationDegradedReason.NONE;
  private degradedMessage?: string;
  private finishRequested: boolean = false;
  private processDrained: boolean = false;
  private asrTailObserved: boolean = false;
  private finished: boolean = false;
  private finalSpeakerCount: number = 0;
  private runtimeLease?: SpeakerDiarizationRuntimeLease;

  constructor(context: Context, workPath: string, maxSpeakers: number,
    observer: SpeakerDiarizationSessionObserver) {
    this.observer = observer;
    this.maxSpeakers = maxSpeakers;
    this.registry = new OnlineSpeakerRegistry(maxSpeakers, 0.72, 0.05);
    this.committedRegistry = new OnlineSpeakerRegistry(maxSpeakers, 0.72, 0.05);
    this.globalClusterer = new SpeakerDiarizationGlobalClusterer(
      maxSpeakers, 0, 0.72);
    this.runtimeLease = SpeakerDiarizationRuntimeLeaseRegistry.acquire();
    try {
      this.client = new SpeakerDiarizationLocalClient(context, workPath, this);
    } catch (e) {
      this.runtimeLease.release();
      this.runtimeLease = undefined;
      throw new Error(`${e}`);
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
    this.flushReadyWindows();
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
    this.inferenceMs += window.result.inferenceMs;
    this.inferenceEndMs = window.realEndSample * 1000 / SAMPLE_RATE;
    const channelIds = new Map<number, string>();
    const channelConfidences = new Map<number, number>();
    const assignments = this.registry.assignBatch(
      window.result.embeddings.map((item) => new Float32Array(item.embedding)),
      window.result.embeddings.map((item) => Math.round(item.speechSamples * 1000 / SAMPLE_RATE)),
      Math.round(window.realEndSample * 1000 / SAMPLE_RATE));
    for (let i = 0; i < window.result.embeddings.length; i++) {
      const item = window.result.embeddings[i];
      const assignment = assignments[i];
      channelIds.set(item.localSpeaker, assignment.speakerId);
      channelConfidences.set(item.localSpeaker, assignment.confidence);
      const endTimeMs = Math.round(window.realEndSample * 1000 / SAMPLE_RATE);
      const observation: SpeakerDiarizationEmbeddingObservation = {
        embedding: item.embedding.slice(),
        durationMs: Math.round(item.speechSamples * 1000 / SAMPLE_RATE),
        onlineSpeakerId: assignment.speakerId,
        endTimeMs,
        evidenceKey: `${window.jobId}:${item.localSpeaker}`,
      };
      this.recentEmbeddingObservations.push(observation);

    }

    const turns: SpeakerTimelineTurn[] = [];
    for (let i = 0; i < window.result.segments.length; i++) {
      const segment = window.result.segments[i];
      const localStart = Math.max(0,
        segment.startSample - window.contentStartInWindowSample);
      const localEnd = Math.max(localStart,
        segment.endSample - window.contentStartInWindowSample);
      const globalStart = Math.max(window.commitStartSample,
        window.windowStartSample + localStart);
      const globalEnd = Math.min(window.realEndSample, window.stableEndSample,
        window.windowStartSample + localEnd);
      if (globalEnd <= globalStart) continue;
      const primary = channelIds.get(segment.speaker) ?? 'UNKNOWN';
      const secondary: string[] = [];
      const secondaryEvidenceKeys: string[] = [];
      for (let localSpeaker = 0; localSpeaker < 3; localSpeaker++) {
        if (localSpeaker === segment.speaker ||
          (segment.speakerMask & (1 << localSpeaker)) === 0) continue;
        const id = channelIds.get(localSpeaker) ?? 'UNKNOWN_SECONDARY';
        if (id !== primary && secondary.indexOf(id) < 0) {
          secondary.push(id);
          secondaryEvidenceKeys.push(`${window.jobId}:${localSpeaker}`);
        }
      }
      turns.push({
        beginTime: Math.round(globalStart * 1000 / SAMPLE_RATE),
        endTime: Math.round(globalEnd * 1000 / SAMPLE_RATE),
        speakerId: primary,
        secondarySpeakerIds: secondary,
        confidence: channelConfidences.get(segment.speaker) ?? 0,
        overlap: (segment.speakerMask & (segment.speakerMask - 1)) !== 0,
        evidenceKey: `${window.jobId}:${segment.speaker}`,
        secondaryEvidenceKeys,
      });
    }
    const updates = this.transcript.applySpeakerTurns(turns);
    for (let i = 0; i < updates.length; i++) {
      this.observer.onSpeakerDiarizationUpdate(this.toPublicUpdate(updates[i]));
    }
    this.flushReadyWindows();
  }

  onDrained(): void {
    if (!this.finishRequested || this.finished) return;
    this.processDrained = true;
    this.finalizeIfReady();
  }

  private finalizeIfReady(): void {
    if (!this.finishRequested || this.finished || !this.processDrained ||
      !this.asrTailObserved) return;
    this.flushReadyWindows();
    if (this.finished) return;
    const result = this.commitWindow(this.totalSamples * 1000 / SAMPLE_RATE,
      Number.POSITIVE_INFINITY, true);
    this.finished = true;
    this.observer.onFinished(result);
  }

  private flushReadyWindows(): void {
    if (this.finished) return;
    const progress = this.degradedReason === SpeakerDiarizationDegradedReason.NONE ?
      this.inferenceEndMs : Number.POSITIVE_INFINITY;
    let boundary = this.commitClock.takeReady(progress);
    while (boundary !== undefined && !this.finished) {
      const result = this.commitWindow(boundary.endTime, boundary.evidenceEndTime, false,
        boundary.beginTime);
      if (result.utterances.length > 0 || result.speakerTurns.length > 0) {
        this.windowIndex += 1;
        this.observer.onWindowResult(result);
      }
      boundary = this.finished ? undefined : this.commitClock.takeReady(progress);
    }
  }

  private commitWindow(endTime: number, evidenceEndTime: number, isSessionFinal: boolean,
    beginTime: number = this.commitClock.beginTime()): SpeakerDiarizationResult {
    const observations = this.recentEmbeddingObservations.filter(item =>
      (item.endTimeMs ?? 0) <= evidenceEndTime && (item.endTimeMs ?? 0) > beginTime)
      .map((item: SpeakerDiarizationEmbeddingObservation): SpeakerDiarizationEmbeddingObservation => ({
        embedding: item.embedding, durationMs: item.durationMs, endTimeMs: item.endTimeMs,
        evidenceKey: item.evidenceKey, onlineSpeakerId: 'UNKNOWN',
        anchorId: this.committedRegistry.matchKnown(item.embedding) }));
    const clustered = this.globalClusterer.cluster(observations);
    const remap: Record<string, string> = {};
    for (const cluster of clustered.clusters) {
      const anchor = cluster.indexes.map(index => observations[index].anchorId)
        .find(id => id !== undefined);
      let id: string;
      if (anchor !== undefined) {
        id = anchor;
        this.committedRegistry.commitKnown(id, cluster.centroid, cluster.durationMs, endTime);
      } else {
        id = this.committedRegistry.assign(new Float32Array(cluster.centroid), cluster.durationMs,
          endTime).speakerId;
      }
      for (const index of cluster.indexes) {
        const key = observations[index].evidenceKey;
        if (key !== undefined) remap[key] = id;
      }
    }
    this.transcript.applyEvidenceRemap(remap);
    this.finalSpeakerCount = this.committedRegistry.speakerIds().length;
    this.registry = this.committedRegistry.fork();
    if (this.terminalPayload !== undefined) this.decoratePayload(this.terminalPayload);
    const result = this.buildResult(this.degradedReason, this.degradedMessage, endTime, beginTime);
    result.isSessionFinal = isSessionFinal;
    this.transcript.commitThrough(endTime);
    // Keep only evidence needed by a crossing inference window / later uncommitted turns.
    const needed = new Set(this.transcript.allTurns().flatMap(turn =>
      [turn.evidenceKey ?? '', ...(turn.secondaryEvidenceKeys ?? [])]));
    this.recentEmbeddingObservations = this.recentEmbeddingObservations.filter(item =>
      (item.endTimeMs ?? 0) > endTime || needed.has(item.evidenceKey ?? ''));
    return result;
  }

  onDegraded(reason: SpeakerDiarizationDegradedReason, message: string): void {
    if (this.degradedReason !== SpeakerDiarizationDegradedReason.NONE) return;
    this.degradedReason = reason;
    this.degradedMessage = message;
  }

  private buildResult(reason: SpeakerDiarizationDegradedReason,
    message?: string, endTime: number = this.totalSamples * 1000 / SAMPLE_RATE,
    beginTime: number = this.commitClock.beginTime()): SpeakerDiarizationResult {
    const result = new SpeakerDiarizationResult();
    result.windowIndex = this.windowIndex;
    result.windowBeginTime = Math.round(beginTime);
    result.windowEndTime = Math.round(endTime);
    const utterances = this.transcript.finalUtterances(endTime);
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
    return result;
  }

  private releaseRuntimeLease(): void {
    this.runtimeLease?.release();
    this.runtimeLease = undefined;
  }

}
