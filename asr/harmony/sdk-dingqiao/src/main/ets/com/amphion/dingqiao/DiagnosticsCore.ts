export class DiagnosticModeValue {
  static readonly BASIC: string = 'BASIC';
  static readonly CUSTOMER_SUPPORT: string = 'CUSTOMER_SUPPORT';
  static readonly FAILURE_ONLY: string = 'FAILURE_ONLY';
}

export interface DiagnosticConfig {
  enabled: boolean;
  mode?: string;
  captureAudio: boolean;
  includeRecognitionText: boolean;
  maxSessionAudioSec: number;
  failureRingAudioSec?: number;
  maxSessionEvents?: number;
}

export interface EffectiveDiagnosticConfig {
  enabled: boolean;
  mode: string;
  captureAudio: boolean;
  includeRecognitionText: boolean;
  maxSessionAudioSec: number;
  failureRingAudioSec: number;
  maxSessionEvents: number;
}

export interface DiagnosticEvent {
  schemaVersion: number;
  sequence: number;
  wallTimeMs: number;
  monotonicTimeNs: number;
  runId: string;
  engineId: string;
  sessionId: string;
  sessionGeneration: number;
  streamGeneration: number;
  thread: string;
  event: string;
  fields: Record<string, Object>;
}

export interface DiagnosticAudioSnapshot {
  pcm: ArrayBuffer;
  bytes: number;
  frames: number;
  samples: number;
  durationMs: number;
  firstFrameTimeMs: number;
  lastFrameTimeMs: number;
  maxFrameGapMs: number;
  rms: number;
  peak: number;
  clipRate: number;
  truncated: boolean;
  ringBuffer: boolean;
  preTriggerDroppedBytes: number;
}

export interface DiagnosticSessionSnapshot {
  sessionId: string;
  events: DiagnosticEvent[];
  abnormal: boolean;
  abnormalReasons: string[];
  terminal: boolean;
  audio?: DiagnosticAudioSnapshot;
}

export interface DiagnosticsSnapshot {
  runId: string;
  config: EffectiveDiagnosticConfig;
  events: DiagnosticEvent[];
  sessions: DiagnosticSessionSnapshot[];
}

class DiagnosticAudioChunk {
  readonly pcm: ArrayBuffer;
  readonly wallTimeMs: number;

  constructor(pcm: ArrayBuffer, wallTimeMs: number) {
    this.pcm = pcm;
    this.wallTimeMs = wallTimeMs;
  }
}

class DiagnosticAudioCapture {
  private readonly maxBytes: number;
  private readonly ringBytes: number;
  private readonly chunks: DiagnosticAudioChunk[] = [];
  private bytes: number = 0;
  private frames: number = 0;
  private triggered: boolean = false;
  private truncatedValue: boolean = false;
  private droppedBytes: number = 0;

  constructor(maxSessionAudioSec: number, failureRingAudioSec: number, ringBuffer: boolean) {
    this.maxBytes = Math.max(0, Math.floor(maxSessionAudioSec * 16000 * 2));
    this.ringBytes = ringBuffer ?
      Math.min(this.maxBytes, Math.max(640, Math.floor(failureRingAudioSec * 16000 * 2))) :
      this.maxBytes;
    this.triggered = !ringBuffer;
  }

  markAbnormal(): void { this.triggered = true; }

  append(audio: ArrayBuffer, nowMs: number): void {
    if (audio.byteLength === 0 || this.maxBytes === 0) return;
    this.frames += 1;
    const limit = this.triggered ? this.maxBytes : this.ringBytes;
    const evenBytes = audio.byteLength - audio.byteLength % 2;
    if (evenBytes === 0) return;
    const accepted = audio.slice(0, Math.min(evenBytes, limit));
    this.chunks.push(new DiagnosticAudioChunk(accepted, nowMs));
    this.bytes += accepted.byteLength;
    if (accepted.byteLength < evenBytes) this.truncatedValue = true;
    if (this.triggered && this.bytes > this.maxBytes) {
      const overflow = this.bytes - this.maxBytes;
      const last = this.chunks[this.chunks.length - 1];
      const keep = Math.max(0, last.pcm.byteLength - overflow);
      this.chunks.pop();
      this.bytes -= last.pcm.byteLength;
      if (keep > 0) {
        const clipped = last.pcm.slice(0, keep - keep % 2);
        this.chunks.push(new DiagnosticAudioChunk(clipped, last.wallTimeMs));
        this.bytes += clipped.byteLength;
      }
      this.truncatedValue = true;
    }
    while (!this.triggered && this.bytes > this.ringBytes && this.chunks.length > 0) {
      const removed = this.chunks.shift();
      if (removed !== undefined) {
        this.bytes -= removed.pcm.byteLength;
        this.droppedBytes += removed.pcm.byteLength;
      }
    }
  }

  snapshot(): DiagnosticAudioSnapshot {
    const merged = new ArrayBuffer(this.bytes);
    const destination = new Uint8Array(merged);
    let offset = 0;
    let squareSum = 0;
    let peakValue = 0;
    let clippedSamples = 0;
    let maxFrameGapMs = 0;
    for (let i = 0; i < this.chunks.length; i++) {
      const chunk = this.chunks[i];
      const source = new Uint8Array(chunk.pcm);
      destination.set(source, offset);
      offset += source.byteLength;
      if (i > 0) {
        maxFrameGapMs = Math.max(maxFrameGapMs,
          chunk.wallTimeMs - this.chunks[i - 1].wallTimeMs);
      }
      const pcm = new Int16Array(chunk.pcm);
      for (let j = 0; j < pcm.length; j++) {
        const sample = pcm[j];
        const magnitude = Math.abs(sample);
        squareSum += sample * sample;
        peakValue = Math.max(peakValue, magnitude);
        if (magnitude >= 32767) clippedSamples += 1;
      }
    }
    const samples = this.bytes / 2;
    return {
      pcm: merged,
      bytes: this.bytes,
      frames: this.frames,
      samples,
      durationMs: Math.round(samples * 1000 / 16000),
      firstFrameTimeMs: this.chunks.length > 0 ? this.chunks[0].wallTimeMs : -1,
      lastFrameTimeMs: this.chunks.length > 0 ? this.chunks[this.chunks.length - 1].wallTimeMs : -1,
      maxFrameGapMs,
      rms: samples > 0 ? Math.sqrt(squareSum / samples) / 32768 : 0,
      peak: peakValue / 32768,
      clipRate: samples > 0 ? clippedSamples / samples : 0,
      truncated: this.truncatedValue,
      ringBuffer: this.ringBytes < this.maxBytes,
      preTriggerDroppedBytes: this.droppedBytes
    };
  }
}

class DiagnosticSession {
  readonly publicId: string;
  readonly generation: number;
  readonly events: DiagnosticEvent[] = [];
  readonly audio?: DiagnosticAudioCapture;
  readonly abnormalReasons: string[] = [];
  abnormal: boolean = false;
  terminal: boolean = false;

  constructor(publicId: string, generation: number, config: EffectiveDiagnosticConfig) {
    this.publicId = publicId;
    this.generation = generation;
    if (config.captureAudio) {
      this.audio = new DiagnosticAudioCapture(
        config.maxSessionAudioSec,
        config.failureRingAudioSec,
        config.mode === DiagnosticModeValue.FAILURE_ONLY
      );
    }
  }

  markAbnormal(reason: string): void {
    if (this.abnormalReasons.indexOf(reason) < 0) this.abnormalReasons.push(reason);
    this.abnormal = true;
    this.audio?.markAbnormal();
  }
}

/** Dependency-free state core. It never performs file I/O and never calls ASR code. */
export class DiagnosticsCore {
  private config: EffectiveDiagnosticConfig = {
    enabled: false,
    mode: DiagnosticModeValue.BASIC,
    captureAudio: false,
    includeRecognitionText: false,
    maxSessionAudioSec: 120,
    failureRingAudioSec: 20,
    maxSessionEvents: 512
  };
  private runId: string = '';
  private sequence: number = 0;
  private runStartedMs: number = 0;
  private lastMonotonicTimeNs: number = 0;
  private engineSequence: number = 0;
  private sessionGeneration: number = 0;
  private sessionSequence: number = 0;
  private sessions: Map<string, DiagnosticSession> = new Map<string, DiagnosticSession>();
  private sessionHistory: DiagnosticSession[] = [];
  private orphanEvents: DiagnosticEvent[] = [];

  configure(config: DiagnosticConfig, nowMs: number = Date.now()): void {
    const mode = this.normalizeMode(config.mode);
    this.config = {
      enabled: config.enabled,
      mode,
      captureAudio: mode === DiagnosticModeValue.BASIC ? false : config.captureAudio,
      includeRecognitionText: mode === DiagnosticModeValue.BASIC ? false : config.includeRecognitionText,
      maxSessionAudioSec: Math.min(600, Math.max(0.02, config.maxSessionAudioSec)),
      failureRingAudioSec: Math.min(120, Math.max(1, config.failureRingAudioSec ?? 20)),
      maxSessionEvents: Math.max(64, config.maxSessionEvents ?? 512)
    };
    if (this.config.enabled && this.runId.length === 0) {
      this.runId = `run-${nowMs}`;
      this.runStartedMs = nowMs;
    }
  }

  isEnabled(): boolean { return this.config.enabled; }
  mode(): string { return this.config.mode; }
  effectiveConfig(): EffectiveDiagnosticConfig { return this.copyConfig(); }

  nextEngineId(): string {
    this.engineSequence += 1;
    return `engine-${this.engineSequence}`;
  }

  beginSession(sourceSessionId: string, engineId: string,
    safeConfig: Record<string, Object>, nowMs: number = Date.now()): void {
    if (!this.config.enabled) return;
    this.sessionGeneration += 1;
    this.sessionSequence += 1;
    const session = new DiagnosticSession(
      `session-${this.sessionSequence}`,
      this.sessionGeneration,
      this.config
    );
    this.sessions.set(sourceSessionId, session);
    this.sessionHistory.push(session);
    this.record(sourceSessionId, engineId, 'START_LISTENING', safeConfig, nowMs);
  }

  record(sourceSessionId: string, engineId: string, event: string,
    fields: Record<string, Object> = {}, nowMs: number = Date.now(),
    streamGeneration: number = 0, thread: string = 'arkts-main'): DiagnosticEvent | undefined {
    if (!this.config.enabled) return undefined;
    const session = this.sessions.get(sourceSessionId);
    this.lastMonotonicTimeNs = Math.max(
      this.lastMonotonicTimeNs + 1,
      Math.max(0, nowMs - this.runStartedMs) * 1000000
    );
    const entry: DiagnosticEvent = {
      schemaVersion: 2,
      sequence: ++this.sequence,
      wallTimeMs: nowMs,
      monotonicTimeNs: this.lastMonotonicTimeNs,
      runId: this.runId,
      engineId,
      sessionId: session?.publicId ?? '',
      sessionGeneration: session?.generation ?? 0,
      streamGeneration,
      thread,
      event,
      fields: this.redactFields(fields)
    };
    if (session === undefined) {
      this.orphanEvents.push(entry);
      this.trimEvents(this.orphanEvents);
      return entry;
    }
    session.events.push(entry);
    const abnormalReason = this.abnormalReason(session, entry);
    if (abnormalReason.length > 0) session.markAbnormal(abnormalReason);
    if (event === 'CALLBACK_COMPLETE' || event === 'CALLBACK_ERROR' || event === 'CANCEL_REQUESTED') {
      session.terminal = true;
    }
    if (this.config.mode === DiagnosticModeValue.FAILURE_ONLY && !session.abnormal) {
      this.trimEvents(session.events);
    }
    return entry;
  }

  captureAudio(sourceSessionId: string, audio: ArrayBuffer, nowMs: number = Date.now()): void {
    if (!this.config.enabled || !this.config.captureAudio) return;
    this.sessions.get(sourceSessionId)?.audio?.append(audio, nowMs);
  }

  /** includePendingFailureOnly is used only by the crash journal. */
  snapshot(includePendingFailureOnly: boolean = false): DiagnosticsSnapshot {
    const sessions: DiagnosticSessionSnapshot[] = [];
    for (let i = 0; i < this.sessionHistory.length; i++) {
      const session = this.sessionHistory[i];
      if (this.config.mode === DiagnosticModeValue.FAILURE_ONLY && !session.abnormal &&
        !(includePendingFailureOnly && !session.terminal)) continue;
      const snapshot: DiagnosticSessionSnapshot = {
        sessionId: session.publicId,
        events: session.events.slice(),
        abnormal: session.abnormal,
        abnormalReasons: session.abnormalReasons.slice(),
        terminal: session.terminal
      };
      if (session.audio !== undefined) snapshot.audio = session.audio.snapshot();
      sessions.push(snapshot);
    }
    const events = this.orphanEvents.slice();
    for (let i = 0; i < sessions.length; i++) {
      for (let j = 0; j < sessions[i].events.length; j++) events.push(sessions[i].events[j]);
    }
    events.sort((left: DiagnosticEvent, right: DiagnosticEvent): number => left.sequence - right.sequence);
    return { runId: this.runId, config: this.copyConfig(), events, sessions };
  }

  private normalizeMode(mode: string | undefined): string {
    if (mode === DiagnosticModeValue.CUSTOMER_SUPPORT || mode === DiagnosticModeValue.FAILURE_ONLY) {
      return mode;
    }
    return DiagnosticModeValue.BASIC;
  }

  private copyConfig(): EffectiveDiagnosticConfig {
    return {
      enabled: this.config.enabled,
      mode: this.config.mode,
      captureAudio: this.config.captureAudio,
      includeRecognitionText: this.config.includeRecognitionText,
      maxSessionAudioSec: this.config.maxSessionAudioSec,
      failureRingAudioSec: this.config.failureRingAudioSec,
      maxSessionEvents: this.config.maxSessionEvents
    };
  }

  private trimEvents(events: DiagnosticEvent[]): void {
    while (events.length > this.config.maxSessionEvents) events.shift();
  }

  private abnormalReason(session: DiagnosticSession, entry: DiagnosticEvent): string {
    if (entry.event === 'CALLBACK_ERROR') return 'callback-error';
    if (entry.event.indexOf('TIMEOUT') >= 0) return 'timeout';
    if (entry.event === 'AUTO_FINISH_REQUESTED' && entry.fields['reason'] === 'vadBegin') {
      return 'initial-silence-timeout';
    }
    if (entry.event === 'CALLBACK_RESULT' && entry.fields['isFinal'] === true &&
      entry.fields['textChars'] === 0 && entry.fields['rejectedBySpeakerVad'] !== true) {
      return 'empty-final';
    }
    if (entry.event === 'CALLBACK_RESULT' && entry.fields['isLast'] === true &&
      !this.hasFinishIntent(session)) return 'isLast-before-finish';
    return '';
  }

  private hasFinishIntent(session: DiagnosticSession): boolean {
    for (let i = 0; i < session.events.length; i++) {
      const event = session.events[i].event;
      if (event === 'FINISH_REQUESTED' || event === 'AUTO_FINISH_REQUESTED') return true;
    }
    return false;
  }

  private redactFields(fields: Record<string, Object>): Record<string, Object> {
    const safe: Record<string, Object> = {};
    const keys = Object.keys(fields);
    for (let i = 0; i < keys.length; i++) {
      const key = keys[i];
      if (key === 'license' || key === 'licenseText' || key === 'privateKey' ||
        key === 'deviceSerial' || key === 'voiceprintId' || key === 'voiceprintIds' ||
        key === 'hotwords' || key === 'path' || key === 'modelPath' ||
        key === 'message' || key === 'errorMessage') continue;
      if ((key === 'text' || key === 'tokens') && !this.config.includeRecognitionText) continue;
      safe[key] = fields[key];
    }
    return safe;
  }
}
