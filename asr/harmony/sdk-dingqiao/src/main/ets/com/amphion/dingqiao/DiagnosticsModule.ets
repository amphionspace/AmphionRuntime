import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import { DiagnosticOptions } from './DingqiaoModels';
import {
  DiagnosticAudioSnapshot,
  DiagnosticSessionSnapshot,
  DiagnosticsCore,
  DiagnosticsSnapshot
} from './DiagnosticsCore';

const WAV_HEADER_BYTES: number = 44;

function ensureDirectory(path: string): void {
  if (!fs.accessSync(path)) fs.mkdirSync(path, true);
}

function writeBytes(path: string, value: ArrayBuffer): void {
  const fp = fs.openSync(path, fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
  try {
    fs.writeSync(fp.fd, value);
  } finally {
    fs.closeSync(fp);
  }
}

function writeText(path: string, value: string): void {
  const encoded = new util.TextEncoder().encodeInto(value);
  const data = new ArrayBuffer(encoded.byteLength);
  new Uint8Array(data).set(encoded);
  writeBytes(path, data);
}

function writeAscii(view: DataView, offset: number, value: string): void {
  for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
}

function wavOf(pcm: ArrayBuffer): ArrayBuffer {
  const wav = new ArrayBuffer(WAV_HEADER_BYTES + pcm.byteLength);
  const view = new DataView(wav);
  writeAscii(view, 0, 'RIFF');
  view.setUint32(4, 36 + pcm.byteLength, true);
  writeAscii(view, 8, 'WAVE');
  writeAscii(view, 12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, 16000, true);
  view.setUint32(28, 32000, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, 'data');
  view.setUint32(40, pcm.byteLength, true);
  new Uint8Array(wav).set(new Uint8Array(pcm), WAV_HEADER_BYTES);
  return wav;
}

function ndjson(events: Object[]): string {
  let output = '';
  for (let i = 0; i < events.length; i++) output += `${JSON.stringify(events[i])}\n`;
  return output;
}

/** File adapter for explicit export only. Runtime capture remains memory-only. */
export class DiagnosticsModule {
  private static readonly core: DiagnosticsCore = new DiagnosticsCore();
  private static rootPath: string = '';

  static configure(options: DiagnosticOptions): void {
    DiagnosticsModule.core.configure({
      enabled: options.enabled,
      captureAudio: options.captureAudio,
      includeRecognitionText: options.includeRecognitionText,
      maxSessionAudioSec: options.maxSessionAudioSec
    });
  }

  static setRootPath(path: string): void { DiagnosticsModule.rootPath = path; }
  static nextEngineId(): string { return DiagnosticsModule.core.nextEngineId(); }
  static isEnabled(): boolean { return DiagnosticsModule.core.isEnabled(); }

  static beginSession(sessionId: string, engineId: string, config: Record<string, Object>): void {
    DiagnosticsModule.core.beginSession(sessionId, engineId, config);
  }

  static record(sessionId: string, engineId: string, event: string,
    fields: Record<string, Object> = {}): void {
    DiagnosticsModule.core.record(sessionId, engineId, event, fields);
  }

  static captureAudio(sessionId: string, audio: ArrayBuffer): void {
    DiagnosticsModule.core.captureAudio(sessionId, audio);
  }

  static export(): string {
    if (!DiagnosticsModule.core.isEnabled()) throw new Error('diagnostics are not enabled');
    if (DiagnosticsModule.rootPath.length === 0) throw new Error('diagnostics work path is not configured');
    const snapshot = DiagnosticsModule.core.snapshot();
    const root = `${DiagnosticsModule.rootPath}/asr-diagnostics`;
    const runDir = `${root}/${snapshot.runId}`;
    ensureDirectory(runDir);
    writeText(`${runDir}/events.ndjson`, ndjson(snapshot.events));
    const callbacks = snapshot.events.filter((event): boolean => event.event.indexOf('CALLBACK_') === 0);
    writeText(`${runDir}/callbacks.ndjson`, ndjson(callbacks));
    for (let i = 0; i < snapshot.sessions.length; i++) {
      DiagnosticsModule.writeSession(runDir, snapshot.sessions[i]);
    }
    const summary: Record<string, Object> = DiagnosticsModule.summaryOf(snapshot);
    writeText(`${runDir}/summary.json`, `${JSON.stringify(summary)}\n`);
    const manifest: Record<string, Object> = {};
    manifest['schemaVersion'] = 1;
    manifest['runId'] = snapshot.runId;
    manifest['createdAtMs'] = Date.now();
    manifest['privacy'] = 'audio and recognition text are independently opt-in; identifiers are opaque';
    manifest['files'] = ['events.ndjson', 'callbacks.ndjson', 'summary.json'];
    writeText(`${runDir}/manifest.json`, `${JSON.stringify(manifest)}\n`);
    return runDir;
  }

  private static writeSession(runDir: string, session: DiagnosticSessionSnapshot): void {
    const sessionDir = `${runDir}/sessions/${session.sessionId}`;
    ensureDirectory(sessionDir);
    writeText(`${sessionDir}/timeline.json`, `${JSON.stringify(session.events)}\n`);
    if (session.audio === undefined) return;
    writeBytes(`${sessionDir}/sdk-input.wav`, wavOf(session.audio.pcm));
    const audio = session.audio;
    const metadata: Record<string, Object> = {};
    metadata['sampleRate'] = 16000;
    metadata['channels'] = 1;
    metadata['sampleBit'] = 16;
    metadata['bytes'] = audio.bytes;
    metadata['frames'] = audio.frames;
    metadata['samples'] = audio.samples;
    metadata['durationMs'] = audio.durationMs;
    metadata['firstFrameTimeMs'] = audio.firstFrameTimeMs;
    metadata['lastFrameTimeMs'] = audio.lastFrameTimeMs;
    metadata['maxFrameGapMs'] = audio.maxFrameGapMs;
    metadata['rms'] = audio.rms;
    metadata['peak'] = audio.peak;
    metadata['clipRate'] = audio.clipRate;
    metadata['truncated'] = audio.truncated;
    metadata['source'] = 'public-writeAudio-input';
    metadata['includesInternalSilence'] = false;
    metadata['includesInternalReplay'] = false;
    writeText(`${sessionDir}/sdk-input.json`, `${JSON.stringify(metadata)}\n`);
  }

  private static summaryOf(snapshot: DiagnosticsSnapshot): Record<string, Object> {
    let finishRequested = 0;
    let lastCount = 0;
    let completeCount = 0;
    let errorCount = 0;
    let emptyFinalCount = 0;
    for (let i = 0; i < snapshot.events.length; i++) {
      const event = snapshot.events[i];
      if (event.event === 'FINISH_REQUESTED') finishRequested += 1;
      if (event.event === 'CALLBACK_RESULT' && event.fields['isLast'] === true) lastCount += 1;
      if (event.event === 'CALLBACK_COMPLETE') completeCount += 1;
      if (event.event === 'CALLBACK_ERROR') errorCount += 1;
      if (event.event === 'CALLBACK_RESULT' && event.fields['isFinal'] === true &&
        event.fields['textChars'] === 0) emptyFinalCount += 1;
    }
    const summary: Record<string, Object> = {};
    summary['schemaVersion'] = 1;
    summary['runId'] = snapshot.runId;
    summary['sessionCount'] = snapshot.sessions.length;
    summary['finishRequested'] = finishRequested;
    summary['lastCount'] = lastCount;
    summary['completeCount'] = completeCount;
    summary['errorCount'] = errorCount;
    summary['emptyFinalCount'] = emptyFinalCount;
    return summary;
  }
}
