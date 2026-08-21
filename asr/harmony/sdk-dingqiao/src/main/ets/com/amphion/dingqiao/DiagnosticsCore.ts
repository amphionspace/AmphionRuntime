export interface DiagnosticConfig {
  enabled: boolean;
  captureAudio: boolean;
  includeRecognitionText: boolean;
  maxSessionAudioSec: number;
}

export interface DiagnosticEvent {
  schemaVersion: number;
  sequence: number;
  wallTimeMs: number;
  runId: string;
  engineId: string;
  sessionId: string;
  sessionGeneration: number;
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
}

export interface DiagnosticSessionSnapshot {
  sessionId: string;
  events: DiagnosticEvent[];
  audio?: DiagnosticAudioSnapshot;
}

export interface DiagnosticsSnapshot {
  runId: string;
  events: DiagnosticEvent[];
  sessions: DiagnosticSessionSnapshot[];
}

class DiagnosticAudioCapture {
  private readonly maxBytes: number;
  private readonly chunks: ArrayBuffer[] = [];
  private bytes: number = 0;
  private frames: number = 0;
  private firstFrameTimeMs: number = -1;
  private lastFrameTimeMs: number = -1;
  private maxFrameGapMs: number = 0;
  private squareSum: number = 0;
  private peakValue: number = 0;
  private clippedSamples: number = 0;
  private truncatedValue: boolean = false;

  constructor(maxSessionAudioSec: number) {
    this.maxBytes = Math.max(0, Math.floor(maxSessionAudioSec * 16000 * 2));
  }

  append(audio: ArrayBuffer, nowMs: number): void {
    if (audio.byteLength === 0) return;
    this.frames += 1;
    if (this.firstFrameTimeMs < 0) this.firstFrameTimeMs = nowMs;
    if (this.lastFrameTimeMs >= 0) {
      this.maxFrameGapMs = Math.max(this.maxFrameGapMs, nowMs - this.lastFrameTimeMs);
    }
    this.lastFrameTimeMs = nowMs;
    const remaining = Math.max(0, this.maxBytes - this.bytes);
    const acceptedBytes = Math.min(remaining, audio.byteLength);
    if (acceptedBytes < audio.byteLength) this.truncatedValue = true;
    if (acceptedBytes === 0) return;
    const accepted = audio.slice(0, acceptedBytes - acceptedBytes % 2);
    if (accepted.byteLength === 0) return;
    this.chunks.push(accepted);
    this.bytes += accepted.byteLength;
    const pcm = new Int16Array(accepted);
    for (let i = 0; i < pcm.length; i++) {
      const sample = pcm[i];
      const magnitude = Math.abs(sample);
      this.squareSum += sample * sample;
      this.peakValue = Math.max(this.peakValue, magnitude);
      if (magnitude >= 32767) this.clippedSamples += 1;
    }
  }

  snapshot(): DiagnosticAudioSnapshot {
    const merged = new ArrayBuffer(this.bytes);
    const destination = new Uint8Array(merged);
    let offset = 0;
    for (let i = 0; i < this.chunks.length; i++) {
      const source = new Uint8Array(this.chunks[i]);
      destination.set(source, offset);
      offset += source.byteLength;
    }
    const samples = this.bytes / 2;
    return {
      pcm: merged,
      bytes: this.bytes,
      frames: this.frames,
      samples,
      durationMs: Math.round(samples * 1000 / 16000),
      firstFrameTimeMs: this.firstFrameTimeMs,
      lastFrameTimeMs: this.lastFrameTimeMs,
      maxFrameGapMs: this.maxFrameGapMs,
      rms: samples > 0 ? Math.sqrt(this.squareSum / samples) / 32768 : 0,
      peak: this.peakValue / 32768,
      clipRate: samples > 0 ? this.clippedSamples / samples : 0,
      truncated: this.truncatedValue
    };
  }
}

class DiagnosticSession {
  readonly publicId: string;
  readonly generation: number;
  readonly events: DiagnosticEvent[] = [];
  readonly audio?: DiagnosticAudioCapture;

  constructor(publicId: string, generation: number, captureAudio: boolean, maxSessionAudioSec: number) {
    this.publicId = publicId;
    this.generation = generation;
    if (captureAudio) this.audio = new DiagnosticAudioCapture(maxSessionAudioSec);
  }
}

/**
 * Dependency-free state core. It never performs file I/O and never calls ASR code, so diagnostics
 * cannot participate in recognition state decisions or callback ordering.
 */
export class DiagnosticsCore {
  private config: DiagnosticConfig = {
    enabled: false,
    captureAudio: false,
    includeRecognitionText: false,
    maxSessionAudioSec: 120
  };
  private runId: string = '';
  private sequence: number = 0;
  private engineSequence: number = 0;
  private sessionGeneration: number = 0;
  private sessionSequence: number = 0;
  private sessions: Map<string, DiagnosticSession> = new Map<string, DiagnosticSession>();
  private sessionHistory: DiagnosticSession[] = [];
  private allEvents: DiagnosticEvent[] = [];

  configure(config: DiagnosticConfig, nowMs: number = Date.now()): void {
    this.config = {
      enabled: config.enabled,
      captureAudio: config.captureAudio,
      includeRecognitionText: config.includeRecognitionText,
      maxSessionAudioSec: Math.max(0.02, config.maxSessionAudioSec)
    };
    if (this.config.enabled && this.runId.length === 0) this.runId = `run-${nowMs}`;
  }

  isEnabled(): boolean { return this.config.enabled; }

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
      this.config.captureAudio,
      this.config.maxSessionAudioSec
    );
    this.sessions.set(sourceSessionId, session);
    this.sessionHistory.push(session);
    this.record(sourceSessionId, engineId, 'START_LISTENING', safeConfig, nowMs);
  }

  record(sourceSessionId: string, engineId: string, event: string,
    fields: Record<string, Object> = {}, nowMs: number = Date.now()): void {
    if (!this.config.enabled) return;
    const session = this.sessions.get(sourceSessionId);
    const entry: DiagnosticEvent = {
      schemaVersion: 1,
      sequence: ++this.sequence,
      wallTimeMs: nowMs,
      runId: this.runId,
      engineId,
      sessionId: session?.publicId ?? '',
      sessionGeneration: session?.generation ?? 0,
      event,
      fields: this.redactFields(fields)
    };
    this.allEvents.push(entry);
    session?.events.push(entry);
  }

  captureAudio(sourceSessionId: string, audio: ArrayBuffer, nowMs: number = Date.now()): void {
    if (!this.config.enabled || !this.config.captureAudio) return;
    this.sessions.get(sourceSessionId)?.audio?.append(audio, nowMs);
  }

  snapshot(): DiagnosticsSnapshot {
    const sessions: DiagnosticSessionSnapshot[] = [];
    for (let i = 0; i < this.sessionHistory.length; i++) {
      const session = this.sessionHistory[i];
      const snapshot: DiagnosticSessionSnapshot = {
        sessionId: session.publicId,
        events: session.events.slice()
      };
      if (session.audio !== undefined) snapshot.audio = session.audio.snapshot();
      sessions.push(snapshot);
    }
    return { runId: this.runId, events: this.allEvents.slice(), sessions };
  }

  private redactFields(fields: Record<string, Object>): Record<string, Object> {
    const safe: Record<string, Object> = {};
    const keys = Object.keys(fields);
    for (let i = 0; i < keys.length; i++) {
      const key = keys[i];
      if (key === 'license' || key === 'licenseText' || key === 'deviceSerial' ||
        key === 'voiceprintId' || key === 'voiceprintIds' || key === 'hotwords') continue;
      if ((key === 'text' || key === 'tokens') && !this.config.includeRecognitionText) continue;
      safe[key] = fields[key];
    }
    return safe;
  }
}
