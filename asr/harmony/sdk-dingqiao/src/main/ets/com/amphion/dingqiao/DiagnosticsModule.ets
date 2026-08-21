import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import deviceInfo from '@ohos.deviceInfo';
import { AmphionRuntime, RuntimeDiagnosticObserver } from 'amphion_asr';
import { DEBUG } from '../../../../../../BuildProfile';
import { DiagnosticMode, DiagnosticOptions } from './DingqiaoModels';
import {
  DiagnosticEvent,
  DiagnosticSessionSnapshot,
  DiagnosticsCore,
  DiagnosticsSnapshot,
  EffectiveDiagnosticConfig
} from './DiagnosticsCore';
import { HilogDiagnosticSink, NdjsonDiagnosticSink } from './DiagnosticSinks';

const WAV_HEADER_BYTES: number = 44;
const DEFAULT_MAX_DIRECTORY_BYTES: number = 200 * 1024 * 1024;
const DEFAULT_MAX_RETAINED_RUNS: number = 3;
const JOURNAL_INTERVAL_MS: number = 5000;

class ResourceSample {
  wallTimeMs: number = Date.now();
  rssKb: number = -1;
  anonymousRssKb: number = -1;
  fileRssKb: number = -1;
  threadCount: number = -1;
  fdCount: number = -1;
  activeSessionCount: number = 0;
  audioQueueDepth: number = -1;
  maxAudioQueueDepth: number = -1;
  nativeCallsInFlight: number = -1;
  nativeHeapKb: number = -1;
  decodeQueueDepth: number = -1;
  avgDecodeRtf: number = -1;
}

class RuntimeSessionBinding {
  readonly sourceSessionId: string;
  readonly engineId: string;

  constructor(sourceSessionId: string, engineId: string) {
    this.sourceSessionId = sourceSessionId;
    this.engineId = engineId;
  }
}

class DiagnosticsRuntimeObserver implements RuntimeDiagnosticObserver {
  onRuntimeMetric(line: string): void {
    DiagnosticsModule.recordRuntimeMetric(line);
  }
}

function metricValue(value: string): Object {
  if (value === 'true') return true;
  if (value === 'false') return false;
  const numeric = Number(value);
  return value.length > 0 && Number.isFinite(numeric) ? numeric : value;
}

function parseRuntimeMetric(line: string): Record<string, Object> {
  const fields: Record<string, Object> = {};
  const parts = line.trim().split(/\s+/);
  for (let i = 0; i < parts.length; i++) {
    const equals = parts[i].indexOf('=');
    if (equals <= 0) continue;
    fields[parts[i].substring(0, equals)] = metricValue(parts[i].substring(equals + 1));
  }
  return fields;
}

function createDiagnosticsCore(): DiagnosticsCore {
  const core = new DiagnosticsCore();
  if (DEBUG) {
    core.configure({
      enabled: true,
      mode: DiagnosticMode.CUSTOMER_SUPPORT,
      captureAudio: true,
      includeRecognitionText: true,
      maxSessionAudioSec: 300,
      failureRingAudioSec: 20,
      maxSessionEvents: 512
    });
  }
  return core;
}

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
  const fp = fs.openSync(path, fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
  try {
    fs.writeSync(fp.fd, value);
  } finally {
    fs.closeSync(fp);
  }
}

function readText(path: string): string {
  const fp = fs.openSync(path, fs.OpenMode.READ_ONLY);
  try {
    const size = fs.statSync(fp.fd).size;
    const buffer = new ArrayBuffer(size);
    fs.readSync(fp.fd, buffer);
    return util.TextDecoder.create('utf-8').decodeToString(new Uint8Array(buffer));
  } finally {
    fs.closeSync(fp);
  }
}

function readProcStatus(): string {
  try {
    const fp = fs.openSync('/proc/self/status', fs.OpenMode.READ_ONLY);
    try {
      const buffer = new ArrayBuffer(16384);
      const count = fs.readSync(fp.fd, buffer);
      return util.TextDecoder.create('utf-8').decodeToString(new Uint8Array(buffer.slice(0, count)));
    } finally {
      fs.closeSync(fp);
    }
  } catch (_ignored) {
    return '';
  }
}

function procKb(status: string, key: string): number {
  const match = status.match(new RegExp(`${key}:\\s*(\\d+)\\s*kB`));
  return match === null ? -1 : Number(match[1]);
}

function procNumber(status: string, key: string): number {
  const match = status.match(new RegExp(`${key}:\\s*(\\d+)`));
  return match === null ? -1 : Number(match[1]);
}

function sampleResources(snapshot: DiagnosticsSnapshot): ResourceSample {
  const sample = new ResourceSample();
  const status = readProcStatus();
  sample.rssKb = procKb(status, 'VmRSS');
  sample.anonymousRssKb = procKb(status, 'RssAnon');
  sample.fileRssKb = procKb(status, 'RssFile');
  sample.threadCount = procNumber(status, 'Threads');
  sample.nativeHeapKb = procKb(status, 'RssAnon');
  try { sample.fdCount = fs.listFileSync('/proc/self/fd').length; } catch (_ignored) {}
  for (let i = 0; i < snapshot.sessions.length; i++) {
    if (!snapshot.sessions[i].terminal) sample.activeSessionCount += 1;
  }
  for (let i = snapshot.events.length - 1; i >= 0; i--) {
    const fields = snapshot.events[i].fields;
    if (sample.audioQueueDepth < 0 && typeof fields['audioQueueDepth'] === 'number') {
      sample.audioQueueDepth = fields['audioQueueDepth'] as number;
    }
    if (sample.maxAudioQueueDepth < 0 && typeof fields['maxAudioQueueDepth'] === 'number') {
      sample.maxAudioQueueDepth = fields['maxAudioQueueDepth'] as number;
    }
    if (sample.nativeCallsInFlight < 0 && typeof fields['nativeCallsInFlight'] === 'number') {
      sample.nativeCallsInFlight = fields['nativeCallsInFlight'] as number;
    }
    if (sample.decodeQueueDepth < 0 && typeof fields['decodeQueueDepth'] === 'number') {
      sample.decodeQueueDepth = fields['decodeQueueDepth'] as number;
    }
    if (sample.avgDecodeRtf < 0 && typeof fields['avgRtf'] === 'number') {
      sample.avgDecodeRtf = fields['avgRtf'] as number;
    }
  }
  return sample;
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

function csvOf(samples: ResourceSample[]): string {
  let output = 'wallTimeMs,rssKb,anonymousRssKb,fileRssKb,threadCount,fdCount,' +
    'activeSessionCount,audioQueueDepth,maxAudioQueueDepth,nativeCallsInFlight,' +
    'nativeHeapKb,decodeQueueDepth,avgDecodeRtf\n';
  for (let i = 0; i < samples.length; i++) {
    const s = samples[i];
    output += `${s.wallTimeMs},${s.rssKb},${s.anonymousRssKb},${s.fileRssKb},` +
      `${s.threadCount},${s.fdCount},${s.activeSessionCount},${s.audioQueueDepth},` +
      `${s.maxAudioQueueDepth},${s.nativeCallsInFlight},${s.nativeHeapKb},` +
      `${s.decodeQueueDepth},${s.avgDecodeRtf}\n`;
  }
  return output;
}

function isDirectory(path: string): boolean {
  try { return fs.statSync(path).isDirectory(); } catch (_ignored) { return false; }
}

function removeTree(path: string): void {
  if (!fs.accessSync(path)) return;
  if (!isDirectory(path)) {
    fs.unlinkSync(path);
    return;
  }
  const children = fs.listFileSync(path);
  for (let i = 0; i < children.length; i++) removeTree(`${path}/${children[i]}`);
  fs.rmdirSync(path);
}

function treeBytes(path: string): number {
  if (!fs.accessSync(path)) return 0;
  if (!isDirectory(path)) return fs.statSync(path).size;
  let size = 0;
  const children = fs.listFileSync(path);
  for (let i = 0; i < children.length; i++) size += treeBytes(`${path}/${children[i]}`);
  return size;
}

function snapshotWithSessions(snapshot: DiagnosticsSnapshot,
  sessions: DiagnosticSessionSnapshot[]): DiagnosticsSnapshot {
  const sessionIds: string[] = sessions.map((session: DiagnosticSessionSnapshot): string => session.sessionId);
  const events = snapshot.events.filter((event: DiagnosticEvent): boolean =>
    event.sessionId.length === 0 || sessionIds.indexOf(event.sessionId) >= 0);
  return { runId: snapshot.runId, config: snapshot.config, events, sessions };
}

/** File adapter. Capture is memory-only; journal/export work is scheduled outside writeAudio. */
export class DiagnosticsModule {
  private static readonly core: DiagnosticsCore = createDiagnosticsCore();
  private static readonly runtimeObserver: RuntimeDiagnosticObserver = new DiagnosticsRuntimeObserver();
  private static readonly hilogSink: HilogDiagnosticSink = new HilogDiagnosticSink();
  private static readonly ndjsonSink: NdjsonDiagnosticSink = new NdjsonDiagnosticSink();
  private static readonly runtimeSessions: Map<number, RuntimeSessionBinding> =
    new Map<number, RuntimeSessionBinding>();
  private static readonly pendingRuntimeMetrics: Map<number, string[]> = new Map<number, string[]>();
  private static rootPath: string = '';
  private static journalTimer: number = -1;
  private static maxDirectoryBytes: number = DEFAULT_MAX_DIRECTORY_BYTES;
  private static maxRetainedRuns: number = DEFAULT_MAX_RETAINED_RUNS;
  private static resourceSamples: ResourceSample[] = [];
  private static lastQueueState: Record<string, Object> = {};
  private static recoveredRoot: string = '';
  private static deliveredModelManifest: string = '';

  static isBuildEnabled(): boolean { return DEBUG; }

  static installRuntimeObserver(): void {
    if (DEBUG) AmphionRuntime.setDiagnosticObserver(DiagnosticsModule.runtimeObserver);
  }

  static setDeliveredModelManifest(value: Uint8Array): void {
    if (!DEBUG) return;
    try {
      DiagnosticsModule.deliveredModelManifest =
        util.TextDecoder.create('utf-8').decodeToString(value);
    } catch (_ignored) {
      DiagnosticsModule.deliveredModelManifest = '';
    }
  }

  static configure(options: DiagnosticOptions): void {
    DiagnosticsModule.maxDirectoryBytes = Math.max(16 * 1024 * 1024,
      Math.floor(options.maxDirectoryMb * 1024 * 1024));
    DiagnosticsModule.maxRetainedRuns = Math.max(1, options.maxRetainedRuns);
    DiagnosticsModule.core.configure({
      enabled: DEBUG && options.enabled,
      mode: options.mode,
      captureAudio: options.captureAudio,
      includeRecognitionText: options.includeRecognitionText,
      maxSessionAudioSec: options.maxSessionAudioSec,
      failureRingAudioSec: options.failureRingAudioSec,
      maxSessionEvents: options.maxSessionEvents
    });
    AmphionRuntime.setDiagnosticObserver(DEBUG && options.enabled ?
      DiagnosticsModule.runtimeObserver : undefined);
    DiagnosticsModule.scheduleJournal(0);
  }

  static setRootPath(path: string): void {
    DiagnosticsModule.rootPath = path;
    if (DEBUG && DiagnosticsModule.recoveredRoot !== path) {
      DiagnosticsModule.recoveredRoot = path;
      try { DiagnosticsModule.recoverCrashJournals(); } catch (_ignored) {}
    }
  }

  static nextEngineId(): string { return DiagnosticsModule.core.nextEngineId(); }
  static isEnabled(): boolean { return DiagnosticsModule.core.isEnabled(); }

  static beginSession(sessionId: string, engineId: string, config: Record<string, Object>): void {
    DiagnosticsModule.core.beginSession(sessionId, engineId, config);
    DiagnosticsModule.scheduleJournal(0);
  }

  static bindRuntimeSession(sessionId: string, engineId: string, runtimeSessionId: number): void {
    if (!DiagnosticsModule.core.isEnabled()) return;
    DiagnosticsModule.runtimeSessions.set(runtimeSessionId,
      new RuntimeSessionBinding(sessionId, engineId));
    const fields: Record<string, Object> = {};
    fields['runtimeSessionId'] = runtimeSessionId;
    const entry = DiagnosticsModule.core.record(sessionId, engineId, 'RUNTIME_SESSION_BOUND', fields);
    if (entry !== undefined) DiagnosticsModule.hilogSink.write(entry);
    const pending = DiagnosticsModule.pendingRuntimeMetrics.get(runtimeSessionId) ?? [];
    DiagnosticsModule.pendingRuntimeMetrics.delete(runtimeSessionId);
    for (let i = 0; i < pending.length; i++) DiagnosticsModule.recordRuntimeMetric(pending[i]);
  }

  static recordRuntimeMetric(line: string): void {
    if (!DiagnosticsModule.core.isEnabled()) return;
    const parsed = parseRuntimeMetric(line);
    const kind = `${parsed['kind'] ?? 'METRIC'}`;
    const runtimeSessionId = typeof parsed['sessionId'] === 'number' ?
      parsed['sessionId'] as number : 0;
    const knownBinding = DiagnosticsModule.runtimeSessions.get(runtimeSessionId);
    if (runtimeSessionId > 0 && knownBinding === undefined) {
      const pending = DiagnosticsModule.pendingRuntimeMetrics.get(runtimeSessionId) ?? [];
      pending.push(line);
      while (pending.length > 32) pending.shift();
      DiagnosticsModule.pendingRuntimeMetrics.set(runtimeSessionId, pending);
      return;
    }
    const fields: Record<string, Object> = {};
    const keys = Object.keys(parsed);
    for (let i = 0; i < keys.length; i++) {
      if (keys[i] !== 'kind' && keys[i] !== 'sessionId') fields[keys[i]] = parsed[keys[i]];
    }
    if (runtimeSessionId > 0) fields['runtimeSessionId'] = runtimeSessionId;
    const binding = knownBinding;
    const streamGeneration = typeof fields['streamGeneration'] === 'number' ?
      fields['streamGeneration'] as number :
      (typeof fields['toGeneration'] === 'number' ? fields['toGeneration'] as number : 0);
    const eventName = kind.indexOf('RUNTIME_') === 0 ? kind : `RUNTIME_${kind}`;
    const entry = DiagnosticsModule.core.record(
      binding?.sourceSessionId ?? '',
      binding?.engineId ?? '',
      eventName,
      fields,
      Date.now(),
      streamGeneration,
      kind.indexOf('NATIVE') >= 0 ? 'native-worker' : 'arkts-runtime'
    );
    if (entry !== undefined) DiagnosticsModule.hilogSink.write(entry);
    if (kind === 'STREAM_LIFECYCLE' && fields['action'] === 'closed' && runtimeSessionId > 0) {
      DiagnosticsModule.runtimeSessions.delete(runtimeSessionId);
    }
    DiagnosticsModule.scheduleJournal(JOURNAL_INTERVAL_MS);
  }

  static record(sessionId: string, engineId: string, event: string,
    fields: Record<string, Object> = {}): void {
    const entry = DiagnosticsModule.core.record(sessionId, engineId, event, fields);
    if (entry !== undefined) DiagnosticsModule.hilogSink.write(entry);
    const urgent = event === 'CALLBACK_ERROR' || event === 'CALLBACK_COMPLETE' ||
      event === 'CANCEL_REQUESTED' || event === 'AUTO_FINISH_REQUESTED' ||
      event === 'CALLBACK_RESULT' && (fields['isFinal'] === true || fields['isLast'] === true);
    DiagnosticsModule.scheduleJournal(urgent ? 0 : JOURNAL_INTERVAL_MS);
  }

  static captureAudio(sessionId: string, audio: ArrayBuffer): void {
    DiagnosticsModule.core.captureAudio(sessionId, audio);
    DiagnosticsModule.scheduleJournal(JOURNAL_INTERVAL_MS);
  }

  static setQueueState(state: Record<string, Object>): void {
    DiagnosticsModule.lastQueueState = state;
  }

  static export(): string {
    if (!DiagnosticsModule.core.isEnabled()) throw new Error('diagnostics are not enabled');
    if (DiagnosticsModule.rootPath.length === 0) throw new Error('diagnostics work path is not configured');
    let stage = 'snapshot';
    try {
      const snapshot = DiagnosticsModule.core.snapshot(false);
      const root = DiagnosticsModule.exportRoot();
      const runDir = `${root}/${snapshot.runId}`;
      stage = 'mkdir';
      ensureDirectory(runDir);
      DiagnosticsModule.resourceSamples.push(sampleResources(snapshot));
      stage = 'write';
      DiagnosticsModule.writeSnapshot(runDir, snapshot, false);
      stage = 'rotate';
      DiagnosticsModule.rotateRuns(snapshot.runId);
      return runDir;
    } catch (e) {
      throw new Error(`diagnostics export stage ${stage} failed: ${e}`);
    }
  }

  private static exportRoot(): string {
    const root = `${DiagnosticsModule.rootPath}/asr-diagnostics`;
    ensureDirectory(root);
    return root;
  }

  private static pendingRoot(): string {
    const root = `${DiagnosticsModule.rootPath}/asr-diagnostics-pending`;
    ensureDirectory(root);
    return root;
  }

  private static scheduleJournal(delayMs: number): void {
    if (!DEBUG || !DiagnosticsModule.core.isEnabled() || DiagnosticsModule.rootPath.length === 0) return;
    if (DiagnosticsModule.journalTimer >= 0) {
      if (delayMs > 0) return;
      clearTimeout(DiagnosticsModule.journalTimer);
      DiagnosticsModule.journalTimer = -1;
    }
    DiagnosticsModule.journalTimer = setTimeout((): void => {
      DiagnosticsModule.journalTimer = -1;
      try { DiagnosticsModule.flushBackground(); } catch (_ignored) {}
    }, delayMs);
  }

  private static flushBackground(): void {
    const journalSnapshot = DiagnosticsModule.core.snapshot(true);
    DiagnosticsModule.resourceSamples.push(sampleResources(journalSnapshot));
    if (DiagnosticsModule.resourceSamples.length > 256) DiagnosticsModule.resourceSamples.shift();

    if (journalSnapshot.config.mode === DiagnosticMode.FAILURE_ONLY) {
      const abnormal = DiagnosticsModule.core.snapshot(false);
      if (abnormal.sessions.length > 0) {
        const runDir = `${DiagnosticsModule.exportRoot()}/${abnormal.runId}`;
        ensureDirectory(runDir);
        DiagnosticsModule.writeSnapshot(runDir, abnormal, true);
        DiagnosticsModule.rotateRuns(abnormal.runId);
      }
    }

    const active = journalSnapshot.sessions.filter(
      (session: DiagnosticSessionSnapshot): boolean => !session.terminal);
    const pendingRun = `${DiagnosticsModule.pendingRoot()}/${journalSnapshot.runId}`;
    if (active.length === 0) {
      if (fs.accessSync(pendingRun)) removeTree(pendingRun);
      if (fs.accessSync(`${pendingRun}.next`)) removeTree(`${pendingRun}.next`);
      return;
    }
    const nextRun = `${pendingRun}.next`;
    if (fs.accessSync(nextRun)) removeTree(nextRun);
    ensureDirectory(nextRun);
    DiagnosticsModule.writeSnapshot(
      nextRun,
      snapshotWithSessions(journalSnapshot, active),
      true
    );
    if (fs.accessSync(pendingRun)) removeTree(pendingRun);
    fs.renameSync(nextRun, pendingRun);
  }

  private static recoverCrashJournals(): void {
    const pendingRoot = `${DiagnosticsModule.rootPath}/asr-diagnostics-pending`;
    if (!fs.accessSync(pendingRoot)) return;
    const root = DiagnosticsModule.exportRoot();
    const initialRuns = fs.listFileSync(pendingRoot);
    for (let i = 0; i < initialRuns.length; i++) {
      if (!initialRuns[i].endsWith('.next')) continue;
      const next = `${pendingRoot}/${initialRuns[i]}`;
      const stableName = initialRuns[i].substring(0, initialRuns[i].length - 5);
      const stable = `${pendingRoot}/${stableName}`;
      if (!fs.accessSync(`${next}/manifest.json`)) {
        removeTree(next);
        continue;
      }
      if (fs.accessSync(stable)) removeTree(stable);
      fs.renameSync(next, stable);
    }
    const runs = fs.listFileSync(pendingRoot);
    for (let i = 0; i < runs.length; i++) {
      const source = `${pendingRoot}/${runs[i]}`;
      if (!isDirectory(source) || !fs.accessSync(`${source}/manifest.json`)) continue;
      const destination = `${root}/${runs[i]}`;
      writeText(`${source}/crash-recovery.json`, `${JSON.stringify({
        schemaVersion: 1,
        recoveredAtMs: Date.now(),
        reason: 'previous-process-ended-with-active-session',
        possibleTailLossMs: JOURNAL_INTERVAL_MS
      })}\n`);
      DiagnosticsModule.markRecoveredCrash(source);
      if (fs.accessSync(destination)) removeTree(destination);
      fs.renameSync(source, destination);
    }
    DiagnosticsModule.rotateRuns('');
  }

  private static markRecoveredCrash(runDir: string): void {
    try {
      const summary = JSON.parse(readText(`${runDir}/summary.json`)) as Record<string, Object>;
      summary['recoveredCrash'] = true;
      const sessions = summary['sessions'] as Object[];
      summary['abnormalSessionCount'] = sessions.length;
      for (let i = 0; i < sessions.length; i++) {
        const session = sessions[i] as Record<string, Object>;
        session['abnormal'] = true;
        const reasons = session['abnormalReasons'] as string[];
        if (reasons.indexOf('process-crash-recovery') < 0) reasons.push('process-crash-recovery');
      }
      writeText(`${runDir}/summary.json`, `${JSON.stringify(summary)}\n`);
      const manifest = JSON.parse(readText(`${runDir}/manifest.json`)) as Record<string, Object>;
      manifest['recoveredCrash'] = true;
      manifest['possibleTailLossMs'] = JOURNAL_INTERVAL_MS;
      writeText(`${runDir}/manifest.json`, `${JSON.stringify(manifest)}\n`);
    } catch (_ignored) {
    }
  }

  private static writeSnapshot(runDir: string, snapshot: DiagnosticsSnapshot,
    automatic: boolean): void {
    ensureDirectory(runDir);
    writeText(`${runDir}/events.ndjson`, DiagnosticsModule.ndjsonSink.serialize(snapshot.events));
    const callbacks = snapshot.events.filter((event: DiagnosticEvent): boolean =>
      event.event.indexOf('CALLBACK_') === 0);
    writeText(`${runDir}/callbacks.ndjson`, DiagnosticsModule.ndjsonSink.serialize(callbacks));
    for (let i = 0; i < snapshot.sessions.length; i++) {
      DiagnosticsModule.writeSession(runDir, snapshot.sessions[i]);
    }
    const summary = DiagnosticsModule.summaryOf(snapshot);
    writeText(`${runDir}/summary.json`, `${JSON.stringify(summary)}\n`);
    writeText(`${runDir}/effective-config.json`, `${JSON.stringify(snapshot.config)}\n`);
    writeText(`${runDir}/resource-samples.csv`, csvOf(DiagnosticsModule.resourceSamples));

    const nativeState: Record<string, Object> = {};
    nativeState['sdkVersion'] = AmphionRuntime.version();
    nativeState['runtimeReady'] = AmphionRuntime.isRuntimeReady();
    nativeState['modelLoaded'] = AmphionRuntime.isModelLoaded();
    nativeState['systemVersion'] = deviceInfo.osFullName;
    const licenseStatus = AmphionRuntime.licenseStatus();
    nativeState['licenseState'] = licenseStatus.state;
    nativeState['licenseValid'] = licenseStatus.valid;
    nativeState['licenseErrorCode'] = licenseStatus.errorCode;
    nativeState['queue'] = DiagnosticsModule.lastQueueState;
    nativeState['capturedAtMs'] = Date.now();
    writeText(`${runDir}/native-state.json`, `${JSON.stringify(nativeState)}\n`);
    const buildIdentity: Record<string, Object> = {};
    buildIdentity['sdkVersion'] = AmphionRuntime.version();
    buildIdentity['diagnosticBuild'] = DEBUG;
    buildIdentity['diagnosticSchemaVersion'] = 2;
    buildIdentity['binaryHashStatus'] = 'not-available-at-runtime';
    writeText(`${runDir}/build-identity.json`, `${JSON.stringify(buildIdentity)}\n`);
    const modelManifest: Record<string, Object> = {};
    modelManifest['modelLoaded'] = nativeState['modelLoaded'];
    modelManifest['runtimePoolDetails'] = 'not-exposed-by-public-runtime-api';
    modelManifest['modelContentExcludedForPrivacy'] = true;
    if (DiagnosticsModule.deliveredModelManifest.length > 0) {
      try {
        modelManifest['deliveredManifest'] = JSON.parse(DiagnosticsModule.deliveredModelManifest) as Object;
      } catch (_ignored) {
        modelManifest['deliveredManifestError'] = 'invalid-json';
      }
    } else {
      modelManifest['deliveredManifestError'] = 'not-available';
    }
    writeText(`${runDir}/model-manifest.json`, `${JSON.stringify(modelManifest)}\n`);

    const manifest: Record<string, Object> = {};
    manifest['schemaVersion'] = 2;
    manifest['runId'] = snapshot.runId;
    manifest['createdAtMs'] = Date.now();
    manifest['mode'] = snapshot.config.mode;
    manifest['automaticPersistence'] = automatic;
    manifest['privacy'] = 'audio and text are independently controlled; Debug defaults on; identifiers are opaque';
    manifest['files'] = [
      'events.ndjson', 'callbacks.ndjson', 'summary.json', 'effective-config.json',
      'build-identity.json', 'model-manifest.json', 'resource-samples.csv', 'native-state.json'
    ];
    writeText(`${runDir}/manifest.json`, `${JSON.stringify(manifest)}\n`);
  }

  private static writeSession(runDir: string, session: DiagnosticSessionSnapshot): void {
    const sessionDir = `${runDir}/sessions/${session.sessionId}`;
    ensureDirectory(sessionDir);
    writeText(`${sessionDir}/timeline.json`, `${JSON.stringify(session.events)}\n`);
    const result = DiagnosticsModule.sessionSummary(session);
    writeText(`${sessionDir}/result.json`, `${JSON.stringify(result)}\n`);
    if (session.audio === undefined) return;
    writeBytes(`${sessionDir}/sdk-input.wav`, wavOf(session.audio.pcm));
    const audio = session.audio;
    const metadata: Record<string, Object> = {};
    metadata['sampleRate'] = 16000;
    metadata['channels'] = 1;
    metadata['sampleBit'] = 16;
    metadata['bytes'] = audio.bytes;
    metadata['totalInputBytes'] = audio.totalInputBytes;
    metadata['frames'] = audio.frames;
    metadata['callerFrameBytes'] = 640;
    metadata['samples'] = audio.samples;
    metadata['durationMs'] = audio.durationMs;
    metadata['actualWriteAudioDurationMs'] = audio.totalInputDurationMs;
    metadata['firstFrameTimeMs'] = audio.firstFrameTimeMs;
    metadata['lastFrameTimeMs'] = audio.lastFrameTimeMs;
    metadata['maxFrameGapMs'] = audio.maxFrameGapMs;
    metadata['rms'] = audio.rms;
    metadata['peak'] = audio.peak;
    metadata['clipRate'] = audio.clipRate;
    metadata['truncated'] = audio.truncated;
    metadata['ringBuffer'] = audio.ringBuffer;
    metadata['preTriggerDroppedBytes'] = audio.preTriggerDroppedBytes;
    metadata['rollingDroppedBytes'] = audio.rollingDroppedBytes;
    metadata['audioSource'] = 'caller-provided-external-stream';
    metadata['source'] = 'public-writeAudio-input';
    metadata['includesColdStartPreRoll'] = true;
    metadata['includesInternalSilence'] = false;
    metadata['includesInternalReplay'] = false;
    writeText(`${sessionDir}/sdk-input.json`, `${JSON.stringify(metadata)}\n`);
  }

  private static sessionSummary(session: DiagnosticSessionSnapshot): Record<string, Object> {
    let finishRequested = false;
    let autoEndReason = '';
    let lastCount = 0;
    let completeCount = 0;
    let errorCount = 0;
    let emptyFinal = false;
    let isLastBeforeFinish = false;
    let finalCount = 0;
    let streamRestartCount = 0;
    let nativeErrorCount = 0;
    let startTimeMs = -1;
    let firstCallbackMs = -1;
    for (let i = 0; i < session.events.length; i++) {
      const event = session.events[i];
      if (event.event === 'START_LISTENING') startTimeMs = event.wallTimeMs;
      if (event.event.indexOf('CALLBACK_') === 0 && firstCallbackMs < 0) firstCallbackMs = event.wallTimeMs;
      if (event.event === 'FINISH_REQUESTED') finishRequested = true;
      if (event.event === 'AUTO_FINISH_REQUESTED') {
        finishRequested = true;
        autoEndReason = `${event.fields['reason'] ?? ''}`;
      }
      if (event.event === 'CALLBACK_RESULT' && event.fields['isLast'] === true) {
        lastCount += 1;
        if (!finishRequested) isLastBeforeFinish = true;
      }
      if (event.event === 'CALLBACK_RESULT' && event.fields['isFinal'] === true) {
        finalCount += 1;
        if (event.fields['textChars'] === 0) emptyFinal = true;
      }
      if (event.event === 'CALLBACK_COMPLETE') completeCount += 1;
      if (event.event === 'CALLBACK_ERROR') errorCount += 1;
      if (event.event === 'STREAM_RESTARTED' ||
        event.event === 'RUNTIME_STREAM_TRANSITION' && event.fields['action'] === 'hard-restart') {
        streamRestartCount += 1;
      }
      if (event.event === 'RUNTIME_NATIVE_ERROR' || event.event === 'RUNTIME_DECODE_ERROR' ||
        event.event === 'CALLBACK_ERROR' && Number(event.fields['errorCode'] ?? 0) >= 9000) {
        nativeErrorCount += 1;
      }
    }
    const result: Record<string, Object> = {};
    result['sessionId'] = session.sessionId;
    result['abnormal'] = session.abnormal;
    result['abnormalReasons'] = session.abnormalReasons;
    result['terminal'] = session.terminal;
    result['finishRequested'] = finishRequested;
    result['isLastBeforeFinish'] = isLastBeforeFinish;
    result['lastCount'] = lastCount;
    result['finalCount'] = finalCount;
    result['completeCount'] = completeCount;
    result['errorCount'] = errorCount;
    result['nativeErrorCount'] = nativeErrorCount;
    result['autoEndReason'] = autoEndReason;
    result['emptyFinal'] = emptyFinal;
    result['streamRestartCount'] = streamRestartCount;
    result['actualPcmDurationMs'] = session.audio?.durationMs ?? 0;
    result['actualWriteAudioDurationMs'] = session.audio?.totalInputDurationMs ?? 0;
    result['pcmTruncated'] = session.audio?.truncated ?? false;
    result['callbackLatencyMs'] = startTimeMs >= 0 && firstCallbackMs >= 0 ? firstCallbackMs - startTimeMs : -1;
    result['nextSessionReady'] = session.terminal && errorCount === 0;
    return result;
  }

  private static summaryOf(snapshot: DiagnosticsSnapshot): Record<string, Object> {
    const sessions: Object[] = [];
    let abnormalSessionCount = 0;
    let errorCount = 0;
    let emptyFinalCount = 0;
    for (let i = 0; i < snapshot.sessions.length; i++) {
      const result = DiagnosticsModule.sessionSummary(snapshot.sessions[i]);
      sessions.push(result);
      if (snapshot.sessions[i].abnormal) abnormalSessionCount += 1;
      errorCount += result['errorCount'] as number;
      if (result['emptyFinal'] === true) emptyFinalCount += 1;
    }
    const summary: Record<string, Object> = {};
    summary['schemaVersion'] = 2;
    summary['runId'] = snapshot.runId;
    summary['mode'] = snapshot.config.mode;
    summary['sessionCount'] = snapshot.sessions.length;
    summary['abnormalSessionCount'] = abnormalSessionCount;
    summary['errorCount'] = errorCount;
    summary['emptyFinalCount'] = emptyFinalCount;
    const problemSessions = sessions.filter((value: Object): boolean =>
      (value as Record<string, Object>)['abnormal'] === true);
    summary['problemSessionId'] = problemSessions.length > 0 ?
      (problemSessions[problemSessions.length - 1] as Record<string, Object>)['sessionId'] :
      (sessions.length > 0 ? (sessions[sessions.length - 1] as Record<string, Object>)['sessionId'] : '');
    summary['sessions'] = sessions;
    return summary;
  }

  private static rotateRuns(currentRunId: string): void {
    const root = DiagnosticsModule.exportRoot();
    const runs = fs.listFileSync(root)
      .filter((name: string): boolean => isDirectory(`${root}/${name}`))
      .sort((left: string, right: string): number => right.localeCompare(left));
    let totalBytes = 0;
    for (let i = 0; i < runs.length; i++) {
      const path = `${root}/${runs[i]}`;
      const bytes = treeBytes(path);
      const mustKeepCurrent = runs[i] === currentRunId;
      if (!mustKeepCurrent && (i >= DiagnosticsModule.maxRetainedRuns ||
        totalBytes + bytes > DiagnosticsModule.maxDirectoryBytes)) {
        removeTree(path);
      } else {
        totalBytes += bytes;
      }
    }
  }
}
