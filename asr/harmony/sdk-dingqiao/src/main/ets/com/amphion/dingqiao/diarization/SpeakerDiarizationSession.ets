import { AsrResult } from 'amphion_asr';
import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
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
  DiarizationProcessWindowResult,
  SpeakerDiarizationProcessClient,
  SpeakerDiarizationProcessObserver,
  SpeakerDiarizationStorageError
} from './SpeakerDiarizationProcessClient';
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
const RECENT_CORRECTION_MS: number = 60000;
const RECLUSTER_INTERVAL_MS: number = 30000;

interface DiarizationEmbeddingCheckpoint extends SpeakerDiarizationEmbeddingObservation {
  jobId: string;
  localSpeaker: number;
  speechSamples: number;
  speakerId: string;
}

export interface SpeakerDiarizationSessionObserver {
  onSpeakerDiarizationUpdate(update: SpeakerDiarizationUpdate): void;
  onFinished(result: SpeakerDiarizationResult): void;
}

export interface SpeakerDiarizationSessionController {
  append(audio: ArrayBuffer): void;
  observeAsrFinal(payload: SpeechRecognitionResult, result: AsrResult): void;
  finish(): void;
  decoratePayload(payload: SpeechRecognitionResult): void;
  bestResult(reason?: SpeakerDiarizationDegradedReason, message?: string): SpeakerDiarizationResult;
  cleanup(): void;
}

export class SpeakerDiarizationSession implements SpeakerDiarizationProcessObserver,
  SpeakerDiarizationSessionController {
  private readonly client: SpeakerDiarizationProcessClient;
  private readonly registry: OnlineSpeakerRegistry;
  private readonly transcript: SpeakerDiarizationTranscriptState = new SpeakerDiarizationTranscriptState();
  private readonly observer: SpeakerDiarizationSessionObserver;
  private readonly globalClusterer: SpeakerDiarizationGlobalClusterer;
  private readonly maxSpeakers: number;
  private recentEmbeddingObservations: SpeakerDiarizationEmbeddingObservation[] = [];
  private nextReclusterMs: number = RECLUSTER_INTERVAL_MS;
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

  constructor(context: Context, workPath: string, sessionId: string, processEntry: string,
    maxSpeakers: number,
    observer: SpeakerDiarizationSessionObserver) {
    this.observer = observer;
    this.maxSpeakers = maxSpeakers;
    this.registry = new OnlineSpeakerRegistry(maxSpeakers, 0.72, 0.05);
    this.globalClusterer = new SpeakerDiarizationGlobalClusterer(
      maxSpeakers, 0, 0.72);
    this.runtimeLease = SpeakerDiarizationRuntimeLeaseRegistry.acquire();
    try {
      this.client = new SpeakerDiarizationProcessClient(
        context, workPath, sessionId, processEntry, this);
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
    if (payload.isLast) this.asrTailObserved = true;
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
    });
    payload.utteranceId = utteranceId;
    const assignment = this.transcript.currentAssignment(utteranceId);
    if (assignment !== undefined) {
      payload.speakerIndex = speakerIndexFromInternalId(assignment.speakerId, this.maxSpeakers);
      payload.secondarySpeakerIndexes = speakerIndexesFromInternalIds(
        assignment.secondarySpeakerIds, this.maxSpeakers);
      payload.speakerConfidence = assignment.confidence;
    }
    this.finalizeIfReady();
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
      assignment.secondarySpeakerIds, this.maxSpeakers);
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
    this.client.cleanup((): void => { this.releaseRuntimeLease(); });
  }

  onWindow(window: DiarizationProcessWindowResult): void {
    if (this.finished) return;
    this.inferenceMs += window.result.inferenceMs;
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
      this.appendCheckpoint('embedding-index.jsonl', JSON.stringify({
        jobId: window.jobId,
        localSpeaker: item.localSpeaker,
        speechSamples: item.speechSamples,
        speakerId: assignment.speakerId,
        durationMs: observation.durationMs,
        onlineSpeakerId: observation.onlineSpeakerId,
        endTimeMs,
        evidenceKey: observation.evidenceKey,
        embedding: item.embedding,
      }));
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
        const id = channelIds.get(localSpeaker) ?? 'UNKNOWN';
        if (id !== primary && id !== 'UNKNOWN' && secondary.indexOf(id) < 0) {
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
    this.reclusterRecent(Math.round(window.realEndSample * 1000 / SAMPLE_RATE));
    this.appendCheckpoint('window-journal.jsonl', JSON.stringify({
      jobId: window.jobId,
      commitStartSample: window.commitStartSample,
      stableEndSample: window.stableEndSample,
      finalWindow: window.finalWindow,
      turns,
      inferenceMs: window.result.inferenceMs,
    }));
    this.writeCheckpoint('speaker-registry.json', JSON.stringify(this.registry.snapshot()));
  }

  onDrained(): void {
    if (!this.finishRequested || this.finished) return;
    this.processDrained = true;
    this.finalizeIfReady();
  }

  private finalizeIfReady(): void {
    if (!this.finishRequested || this.finished || !this.processDrained ||
      !this.asrTailObserved) return;
    const observations = this.loadPersistedObservations();
    const clustered = this.globalClusterer.cluster(observations);
    this.finalSpeakerCount = Math.min(this.maxSpeakers, clustered.clusterCount);
    const finalUpdates = this.transcript.applyEvidenceRemap(
      this.evidenceRemap(observations, clustered.observationSpeakerIds));
    for (let i = 0; i < finalUpdates.length; i++) {
      this.observer.onSpeakerDiarizationUpdate(this.toPublicUpdate(finalUpdates[i]));
    }
    this.finished = true;
    this.observer.onFinished(this.buildResult(this.degradedReason, this.degradedMessage));
  }

  onDegraded(reason: SpeakerDiarizationDegradedReason, message: string): void {
    if (this.degradedReason !== SpeakerDiarizationDegradedReason.NONE) return;
    this.degradedReason = reason;
    this.degradedMessage = message;
  }

  private buildResult(reason: SpeakerDiarizationDegradedReason,
    message?: string): SpeakerDiarizationResult {
    const result = new SpeakerDiarizationResult();
    const utterances = this.transcript.finalUtterances();
    for (let i = 0; i < utterances.length; i++) {
      result.utterances.push(this.toPublicUtterance(utterances[i]));
    }
    const turns = this.transcript.allTurns();
    for (let i = 0; i < turns.length; i++) {
      const turn = new SpeakerTurn();
      turn.beginTime = turns[i].beginTime;
      turn.endTime = turns[i].endTime;
      turn.speakerIndex = speakerIndexFromInternalId(turns[i].speakerId, this.maxSpeakers);
      turn.secondarySpeakerIndexes = speakerIndexesFromInternalIds(
        turns[i].secondarySpeakerIds, this.maxSpeakers);
      turn.confidence = turns[i].confidence ?? 0;
      turn.overlap = turns[i].overlap ?? turn.secondarySpeakerIndexes.length > 0;
      result.speakerTurns.push(turn);
    }
    result.speakerCount = this.finalSpeakerCount > 0 ?
      this.finalSpeakerCount : this.registry.speakerIds().length;
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
      update.secondarySpeakerIds, this.maxSpeakers);
    result.beginTime = update.beginTime;
    result.endTime = update.endTime;
    result.confidence = update.confidence;
    return result;
  }

  private toPublicUtterance(value: DiarizedTranscriptUtterance): DiarizedUtterance {
    const result = new DiarizedUtterance();
    result.utteranceId = value.utteranceId;
    result.rawText = value.rawText;
    result.text = value.text;
    result.beginTime = value.beginTime;
    result.endTime = value.endTime;
    result.speakerIndex = speakerIndexFromInternalId(value.speakerId, this.maxSpeakers);
    result.secondarySpeakerIndexes = speakerIndexesFromInternalIds(
      value.secondarySpeakerIds, this.maxSpeakers);
    result.confidence = value.confidence ?? 0;
    result.overlap = value.overlap;
    return result;
  }

  private appendCheckpoint(name: string, line: string): void {
    const path = `${this.client.checkpointDir()}/${name}`;
    try {
      const fp = fs.openSync(path,
        fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.APPEND);
      try { fs.writeSync(fp.fd, `${line}\n`); } finally { fs.closeSync(fp.fd); }
    } catch (e) {
      throw new SpeakerDiarizationStorageError(`speaker diarization checkpoint append failed: ${e}`);
    }
  }

  private writeCheckpoint(name: string, content: string): void {
    const path = `${this.client.checkpointDir()}/${name}`;
    const temporary = `${path}.tmp`;
    try {
      const fp = fs.openSync(temporary,
        fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
      try { fs.writeSync(fp.fd, content); } finally { fs.closeSync(fp.fd); }
      fs.renameSync(temporary, path);
    } catch (e) {
      throw new SpeakerDiarizationStorageError(`speaker diarization checkpoint write failed: ${e}`);
    }
  }

  private reclusterRecent(endTimeMs: number): void {
    const fromTime = Math.max(0, endTimeMs - RECENT_CORRECTION_MS);
    this.recentEmbeddingObservations = this.recentEmbeddingObservations.filter(
      (observation: SpeakerDiarizationEmbeddingObservation): boolean =>
        (observation.endTimeMs ?? 0) >= fromTime);
    if (endTimeMs < this.nextReclusterMs) return;
    this.nextReclusterMs = endTimeMs + RECLUSTER_INTERVAL_MS;
    const clustered = this.globalClusterer.cluster(this.recentEmbeddingObservations);
    const updates = this.transcript.applyEvidenceRemap(
      this.evidenceRemap(this.recentEmbeddingObservations, clustered.observationSpeakerIds), fromTime);
    for (let i = 0; i < updates.length; i++) {
      this.observer.onSpeakerDiarizationUpdate(this.toPublicUpdate(updates[i]));
    }
  }

  private loadPersistedObservations(): SpeakerDiarizationEmbeddingObservation[] {
    const path = `${this.client.checkpointDir()}/embedding-index.jsonl`;
    if (!fs.accessSync(path)) return [];
    const fp = fs.openSync(path);
    try {
      const size = fs.statSync(fp.fd).size;
      const bytes = new Uint8Array(size);
      fs.readSync(fp.fd, bytes.buffer);
      const text = new util.TextDecoder('utf-8').decodeWithStream(bytes);
      const lines = text.split('\n');
      const observations: SpeakerDiarizationEmbeddingObservation[] = [];
      for (let i = 0; i < lines.length; i++) {
        if (lines[i].length === 0) continue;
        const checkpoint = JSON.parse(lines[i]) as DiarizationEmbeddingCheckpoint;
        observations.push({
          embedding: checkpoint.embedding,
          durationMs: checkpoint.durationMs,
          onlineSpeakerId: checkpoint.onlineSpeakerId,
          endTimeMs: checkpoint.endTimeMs,
          evidenceKey: checkpoint.evidenceKey,
        });
      }
      return observations;
    } finally {
      fs.closeSync(fp.fd);
    }
  }

  private releaseRuntimeLease(): void {
    this.runtimeLease?.release();
    this.runtimeLease = undefined;
  }

  private evidenceRemap(observations: SpeakerDiarizationEmbeddingObservation[],
    speakerIds: string[]): Record<string, string> {
    const remap: Record<string, string> = {};
    for (let index = 0; index < observations.length; index++) {
      const key = observations[index].evidenceKey;
      if (key !== undefined) remap[key] = speakerIds[index] ?? 'UNKNOWN';
    }
    return remap;
  }
}
