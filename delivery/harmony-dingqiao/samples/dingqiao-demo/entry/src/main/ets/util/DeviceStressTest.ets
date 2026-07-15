import hilog from '@ohos.hilog';
import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import {
  AudioInfo,
  CreateEngineParams,
  DingqiaoErrorCode,
  DingqiaoEventCode,
  LicenseActivationCallback,
  LicenseActivationResult,
  PrepareRuntimeCallback,
  RecognitionListener,
  SpeechRecognitionEngine,
  SpeechRecognitionResult,
  SpeechRecognizeSdk,
  StartParams,
  VoiceprintRegisterParams
} from 'amphion_dingqiao';
import { AmphionRuntime } from 'amphion_asr';
import { WavIo } from './WavIo';

const TAG: string = 'DeviceStressTest';
const DOMAIN: number = 0x0000;
const FRAME_BYTES: number = 640;
const START_TIMEOUT_MS: number = 10000;
const COMPLETE_TIMEOUT_MS: number = 30000;
const VOICEPRINT_SHORT_FRAMES: number = 25;
const VOICEPRINT_THRESHOLD_FRAMES: number = 75;
const VOICEPRINT_LONG_FRAMES: number = 150;
const VOICEPRINT_LEADING_SILENCE_FRAMES: number = 50;
const VOICEPRINT_LOW_GAIN: number = 0.15;
const VOICEPRINT_SCENARIOS: string[] = [
  'short', 'threshold', 'long', 'leading-silence', 'low-volume', 'multi-utterance', 'alternate-source'
];

export class DeviceStressOptions {
  runId: string = 'manual';
  manifestPath: string = '';
  resultPath: string = '';
  mode: string = 'burst';
  cycles: number = 1;
  settleMs: number = 0;
  paceMs: number = 20;
}

class CorpusEntry {
  id: string;
  path: string;

  constructor(id: string, path: string) {
    this.id = id;
    this.path = path;
  }
}

class SessionEvents {
  starts: number = 0;
  partials: number = 0;
  speechBegins: number = 0;
  speechEnds: number = 0;
  finals: number = 0;
  completes: number = 0;
  errors: number = 0;
  finalChars: number = 0;
  finalTexts: string[] = [];
  lastIsLast: boolean = false;
  lastFinals: number = 0;
  speakerScores: number = 0;
  missingSpeakerScores: number = 0;
  firstNonEmptyFinalHasScore?: boolean;
  errorCodes: number[] = [];
  callbackTrace: string[] = [];
  unexpectedSessionCallbacks: number = 0;
}

function errorCount(events: SessionEvents, code: number): number {
  let count = 0;
  for (let i = 0; i < events.errorCodes.length; i++) {
    if (events.errorCodes[i] === code) count += 1;
  }
  return count;
}

class StressListener implements RecognitionListener {
  private events: SessionEvents;
  private expectedSessionId: string;

  constructor(events: SessionEvents, expectedSessionId: string = '') {
    this.events = events;
    this.expectedSessionId = expectedSessionId;
  }

  private record(sessionId: string, kind: string, detail: string = ''): void {
    this.events.callbackTrace.push(`${sessionId}:${kind}${detail}`);
    if (this.expectedSessionId.length > 0 && sessionId !== this.expectedSessionId) {
      this.events.unexpectedSessionCallbacks += 1;
    }
  }

  onStart(sessionId: string, _eventMessage?: string): void {
    this.events.starts += 1;
    this.record(sessionId, 'start');
  }

  onEvent(sessionId: string, eventCode: number, _message: string): void {
    if (eventCode === DingqiaoEventCode.SPEECH_BEGIN) this.events.speechBegins += 1;
    if (eventCode === DingqiaoEventCode.SPEECH_END) this.events.speechEnds += 1;
    this.record(sessionId, 'event', `-${eventCode}`);
  }

  onResult(sessionId: string, result: SpeechRecognitionResult): void {
    if (!result.isFinal) {
      this.events.partials += 1;
      this.record(sessionId, 'partial');
      return;
    }
    this.events.finals += 1;
    this.events.finalChars += result.result.length;
    this.events.finalTexts.push(result.result);
    this.events.lastIsLast = result.isLast;
    if (result.isLast) this.events.lastFinals += 1;
    if (result.speakerSimilarity === undefined) {
      this.events.missingSpeakerScores += 1;
    } else {
      this.events.speakerScores += 1;
    }
    if (result.result.length > 0 && this.events.firstNonEmptyFinalHasScore === undefined) {
      this.events.firstNonEmptyFinalHasScore = result.speakerSimilarity !== undefined;
    }
    this.record(sessionId, 'final', result.isLast ? '-last' : '');
  }

  onComplete(sessionId: string, _eventMessage?: string): void {
    this.events.completes += 1;
    this.record(sessionId, 'complete');
  }

  onError(sessionId: string, errorCode: number, _message: string): void {
    this.events.errors += 1;
    this.events.errorCodes.push(errorCode);
    this.record(sessionId, 'error', `-${errorCode}`);
  }
}

class CallbackRecord {
  sessionId: string;
  kind: string;
  isLast: boolean;
  errorCode: number;

  constructor(sessionId: string, kind: string, isLast: boolean = false, errorCode: number = 0) {
    this.sessionId = sessionId;
    this.kind = kind;
    this.isLast = isLast;
    this.errorCode = errorCode;
  }
}

class SequenceListener implements RecognitionListener {
  events: SessionEvents = new SessionEvents();
  records: CallbackRecord[] = [];

  private record(callback: CallbackRecord): void {
    this.records.push(callback);
    let detail = callback.isLast ? '-last' : '';
    if (callback.kind === 'error') detail = `-${callback.errorCode}`;
    this.events.callbackTrace.push(`${callback.sessionId}:${callback.kind}${detail}`);
  }

  onStart(sessionId: string, _eventMessage?: string): void {
    this.events.starts += 1;
    this.record(new CallbackRecord(sessionId, 'start'));
  }

  onEvent(_sessionId: string, eventCode: number, _message: string): void {
    if (eventCode === DingqiaoEventCode.SPEECH_BEGIN) this.events.speechBegins += 1;
    if (eventCode === DingqiaoEventCode.SPEECH_END) this.events.speechEnds += 1;
  }

  onResult(sessionId: string, result: SpeechRecognitionResult): void {
    if (!result.isFinal) {
      this.events.partials += 1;
      this.record(new CallbackRecord(sessionId, 'partial'));
      return;
    }
    this.events.finals += 1;
    this.events.finalChars += result.result.length;
    this.events.finalTexts.push(result.result);
    this.events.lastIsLast = result.isLast;
    if (result.isLast) this.events.lastFinals += 1;
    this.record(new CallbackRecord(sessionId, 'final', result.isLast));
  }

  onComplete(sessionId: string, _eventMessage?: string): void {
    this.events.completes += 1;
    this.record(new CallbackRecord(sessionId, 'complete'));
  }

  onError(sessionId: string, errorCode: number, _message: string): void {
    this.events.errors += 1;
    this.events.errorCodes.push(errorCode);
    this.record(new CallbackRecord(sessionId, 'error', false, errorCode));
  }

  count(sessionId: string, kind: string): number {
    let count = 0;
    for (let i = 0; i < this.records.length; i++) {
      if (this.records[i].sessionId === sessionId && this.records[i].kind === kind) count += 1;
    }
    return count;
  }

  lastCount(sessionId: string): number {
    let count = 0;
    for (let i = 0; i < this.records.length; i++) {
      const record = this.records[i];
      if (record.sessionId === sessionId && record.kind === 'final' && record.isLast) count += 1;
    }
    return count;
  }

  errorCount(sessionId: string, errorCode: number): number {
    let count = 0;
    for (let i = 0; i < this.records.length; i++) {
      const record = this.records[i];
      if (record.sessionId === sessionId && record.kind === 'error' && record.errorCode === errorCode) count += 1;
    }
    return count;
  }

  terminalOrderOk(sessionId: string): boolean {
    let lastIndex = -1;
    let completeIndex = -1;
    for (let i = 0; i < this.records.length; i++) {
      const record = this.records[i];
      if (record.sessionId !== sessionId) continue;
      if (record.kind === 'final' && record.isLast) {
        if (lastIndex >= 0) return false;
        lastIndex = i;
      }
      if (record.kind === 'complete') {
        if (completeIndex >= 0) return false;
        completeIndex = i;
      }
    }
    if (lastIndex < 0 || completeIndex < 0 || lastIndex > completeIndex) return false;
    for (let i = completeIndex + 1; i < this.records.length; i++) {
      const record = this.records[i];
      if (record.sessionId === sessionId &&
        (record.kind === 'partial' || record.kind === 'final' || record.kind === 'complete')) return false;
    }
    return true;
  }

  errorsAreExpected(finishedSessionId: string, nextSessionId: string): boolean {
    let nextBusyErrors = 0;
    for (let i = 0; i < this.records.length; i++) {
      const record = this.records[i];
      if (record.kind !== 'error') continue;
      if (record.sessionId === nextSessionId && record.errorCode === DingqiaoErrorCode.ENGINE_BUSY) {
        nextBusyErrors += 1;
        continue;
      }
      if (record.sessionId === finishedSessionId &&
        (record.errorCode === DingqiaoErrorCode.NOT_LISTENING ||
          record.errorCode === DingqiaoErrorCode.RECOGNITION_ERROR ||
          record.errorCode === DingqiaoErrorCode.FINISH_FAILED ||
          record.errorCode === DingqiaoErrorCode.CANCEL_FAILED)) continue;
      return false;
    }
    return nextBusyErrors <= 1;
  }
}

class ReentrantCompleteListener implements RecognitionListener {
  private events: SessionEvents;
  private engine: SpeechRecognitionEngine;
  private firstSessionId: string;
  secondSessionId: string;
  secondStartAttempted: boolean = false;
  firstCompleteBusy: boolean = false;
  startThrowMessage: string = '';

  constructor(events: SessionEvents, engine: SpeechRecognitionEngine, firstSessionId: string,
    secondSessionId: string) {
    this.events = events;
    this.engine = engine;
    this.firstSessionId = firstSessionId;
    this.secondSessionId = secondSessionId;
  }

  onStart(sessionId: string, _eventMessage?: string): void {
    this.events.starts += 1;
    this.events.callbackTrace.push(`${sessionId}:start`);
  }

  onResult(sessionId: string, result: SpeechRecognitionResult): void {
    if (!result.isFinal) return;
    this.events.finals += 1;
    this.events.finalChars += result.result.length;
    this.events.lastIsLast = result.isLast;
    if (result.isLast) this.events.lastFinals += 1;
    this.events.callbackTrace.push(`${sessionId}:final${result.isLast ? '-last' : ''}`);
  }

  onComplete(sessionId: string, _eventMessage?: string): void {
    this.events.completes += 1;
    this.events.callbackTrace.push(`${sessionId}:complete`);
    if (sessionId !== this.firstSessionId || this.secondStartAttempted) return;
    this.firstCompleteBusy = this.engine.isBusy();
    this.secondStartAttempted = true;
    try {
      this.engine.startListening(startParams(this.secondSessionId, 'reentrant', 0));
    } catch (e) {
      this.startThrowMessage = safeDetail(`${e}`);
    }
  }

  onError(sessionId: string, errorCode: number, _message: string): void {
    this.events.errors += 1;
    this.events.errorCodes.push(errorCode);
    this.events.callbackTrace.push(`${sessionId}:error-${errorCode}`);
  }
}

class StartCancelListener implements RecognitionListener {
  private events: SessionEvents;
  private engine: SpeechRecognitionEngine;
  cancelledInStart: boolean = false;
  eventAfterCancel: boolean = false;
  eventAfterCancelSessionId: string = '';

  constructor(events: SessionEvents, engine: SpeechRecognitionEngine) {
    this.events = events;
    this.engine = engine;
  }

  onStart(sessionId: string, _eventMessage?: string): void {
    this.events.starts += 1;
    this.events.callbackTrace.push(`${sessionId}:start`);
    this.cancelledInStart = true;
    this.engine.cancel(sessionId);
  }

  onEvent(sessionId: string, _eventCode: number, _message: string): void {
    if (!this.cancelledInStart) return;
    this.eventAfterCancel = true;
    this.eventAfterCancelSessionId = sessionId;
  }

  onResult(sessionId: string, result: SpeechRecognitionResult): void {
    if (!result.isFinal) return;
    this.events.finals += 1;
    this.events.finalChars += result.result.length;
    this.events.lastIsLast = result.isLast;
    if (result.isLast) this.events.lastFinals += 1;
    this.events.callbackTrace.push(`${sessionId}:final${result.isLast ? '-last' : ''}`);
  }

  onComplete(sessionId: string, _eventMessage?: string): void {
    this.events.completes += 1;
    this.events.callbackTrace.push(`${sessionId}:complete`);
  }

  onError(sessionId: string, errorCode: number, _message: string): void {
    this.events.errors += 1;
    this.events.errorCodes.push(errorCode);
    this.events.callbackTrace.push(`${sessionId}:error-${errorCode}`);
  }
}

class LicenseCb implements LicenseActivationCallback {
  private resolve: (result: LicenseActivationResult) => void;

  constructor(resolve: (result: LicenseActivationResult) => void) {
    this.resolve = resolve;
  }

  onResult(result: LicenseActivationResult): void {
    this.resolve(result);
  }

  onError(errorCode: number, message: string): void {
    const result = new LicenseActivationResult();
    result.errorCode = errorCode;
    result.errorMessage = message;
    this.resolve(result);
  }
}

class PrepareRuntimeCb implements PrepareRuntimeCallback {
  private resolve: (errorCode: number) => void;

  constructor(resolve: (errorCode: number) => void) {
    this.resolve = resolve;
  }

  onReady(): void {
    this.resolve(0);
  }

  onError(errorCode: number, _message: string): void {
    this.resolve(errorCode);
  }
}

class CycleResult {
  index: number = 0;
  corpusId: string = '';
  ok: boolean = false;
  starts: number = 0;
  partials: number = 0;
  finals: number = 0;
  completes: number = 0;
  errors: number = 0;
  finalChars: number = 0;
  speakerScores: number = 0;
  missingSpeakerScores: number = 0;
  firstNonEmptyFinalHasScore: number = -1;
  requestedVadBeginMs: number = -1;
  confirmationGraceMs: number = -1;
  voiceprintIdCount: number = 0;
  fedFrames: number = 0;
  lastFinalsBeforeFinish: number = -1;
  liveStreams: number = 0;
  elapsedMs: number = 0;
  resultHex: string = '';
  callbackTrace: string = '';
  unexpectedSessionCallbacks: number = 0;
  detail: string = '';

  toLine(): string {
    return `CYCLE|index=${this.index}|id=${this.corpusId}|status=${this.ok ? 'PASS' : 'FAIL'}` +
      `|starts=${this.starts}|partials=${this.partials}|finals=${this.finals}|completes=${this.completes}` +
      `|errors=${this.errors}|finalChars=${this.finalChars}|speakerScores=${this.speakerScores}` +
      `|missingSpeakerScores=${this.missingSpeakerScores}` +
      `|firstNonEmptyFinalHasScore=${this.firstNonEmptyFinalHasScore}` +
      `|requestedVadBeginMs=${this.requestedVadBeginMs}|confirmationGraceMs=${this.confirmationGraceMs}` +
      `|voiceprintIdCount=${this.voiceprintIdCount}|fedFrames=${this.fedFrames}` +
      `|lastFinalsBeforeFinish=${this.lastFinalsBeforeFinish}|liveStreams=${this.liveStreams}` +
      `|unexpectedCallbacks=${this.unexpectedSessionCallbacks}|elapsedMs=${this.elapsedMs}` +
      `|resultHex=${this.resultHex}|trace=${this.callbackTrace}|detail=${this.detail}`;
  }
}

class StressTotals {
  completed: number = 0;
  failed: number = 0;
  emptyFinals: number = 0;
  starts: number = 0;
  partials: number = 0;
  finals: number = 0;
  completes: number = 0;
  errors: number = 0;

  add(result: CycleResult): void {
    this.completed += 1;
    if (!result.ok) this.failed += 1;
    if (result.finals > 0 && result.finalChars === 0) this.emptyFinals += 1;
    this.starts += result.starts;
    this.partials += result.partials;
    this.finals += result.finals;
    this.completes += result.completes;
    this.errors += result.errors;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise<void>((resolve: () => void): void => {
    setTimeout(resolve, ms);
  });
}

async function waitFor(predicate: () => boolean, timeoutMs: number): Promise<boolean> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (predicate()) return true;
    await sleep(25);
  }
  return predicate();
}

function asciiBytesToString(bytes: Uint8Array): string {
  let result = '';
  for (let i = 0; i < bytes.length; i++) result += String.fromCharCode(bytes[i]);
  return result;
}

function stringToAsciiBytes(value: string): ArrayBuffer {
  const bytes = new Uint8Array(value.length);
  for (let i = 0; i < value.length; i++) bytes[i] = value.charCodeAt(i) & 0x7F;
  return bytes.buffer;
}

function stringToUtf16Hex(value: string): string {
  let result = '';
  for (let i = 0; i < value.length; i++) {
    result += value.charCodeAt(i).toString(16).padStart(4, '0');
  }
  return result;
}

function readBytes(path: string): ArrayBuffer {
  const fp = fs.openSync(path);
  try {
    const size = fs.statSync(fp.fd).size;
    const data = new ArrayBuffer(size);
    fs.readSync(fp.fd, data);
    return data;
  } finally {
    fs.closeSync(fp);
  }
}

function readManifest(path: string): CorpusEntry[] {
  const text = asciiBytesToString(new Uint8Array(readBytes(path)));
  const entries: CorpusEntry[] = [];
  const lines = text.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (line.length === 0 || line.startsWith('#')) continue;
    const tab = line.indexOf('\t');
    if (tab <= 0 || tab === line.length - 1) throw new Error(`invalid manifest line ${i + 1}`);
    entries.push(new CorpusEntry(line.substring(0, tab), line.substring(tab + 1)));
  }
  if (entries.length === 0) throw new Error('stress manifest is empty');
  return entries;
}

function writeText(path: string, text: string): void {
  const fp = fs.openSync(path, fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
  try {
    fs.writeSync(fp.fd, stringToAsciiBytes(text));
  } finally {
    fs.closeSync(fp);
  }
}

function cleanupStressInputs(context: common.UIAbilityContext, manifestPath: string,
  entries: CorpusEntry[]): void {
  const sandboxStressRoot = `${context.filesDir}/asr-stress/`;
  const transferStressRoot = '/data/storage/el2/base/files/asr-stress/';
  if (!manifestPath.startsWith(sandboxStressRoot) && !manifestPath.startsWith(transferStressRoot)) return;

  const separator = manifestPath.lastIndexOf('/');
  const runDir = separator > 0 ? manifestPath.substring(0, separator) : '';
  if (runDir.length === 0 || manifestPath !== `${runDir}/manifest.txt`) return;
  const audioRoot = `${runDir}/audio/`;

  for (let i = 0; i < entries.length; i++) {
    const path = entries[i].path;
    if (!path.startsWith(audioRoot)) continue;
    try {
      if (fs.accessSync(path)) fs.unlinkSync(path);
    } catch (_e) {
    }
  }

  const cleanupPaths: string[] = [manifestPath, `${runDir}/corpus.json`];
  for (let i = 0; i < cleanupPaths.length; i++) {
    try {
      if (fs.accessSync(cleanupPaths[i])) fs.unlinkSync(cleanupPaths[i]);
    } catch (_e) {
    }
  }
  try {
    if (runDir.length > 0 && fs.accessSync(`${runDir}/audio`)) fs.rmdirSync(`${runDir}/audio`);
  } catch (_e) {
  }
}

function prepareLicense(context: common.UIAbilityContext, workPath: string): string {
  const data = context.resourceManager.getRawFileContentSync('amphion-license.lic');
  if (!fs.accessSync(workPath)) fs.mkdirSync(workPath);
  const destination = `${workPath}/stress-amphion-license.lic`;
  const fp = fs.openSync(destination, fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
  try {
    fs.writeSync(fp.fd, data.buffer);
  } finally {
    fs.closeSync(fp);
  }
  return destination;
}

function activateLicense(path: string): Promise<LicenseActivationResult> {
  return new Promise<LicenseActivationResult>((resolve: (result: LicenseActivationResult) => void): void => {
    SpeechRecognizeSdk.setLicense(path, new LicenseCb(resolve));
  });
}

function prepareRuntime(): Promise<number> {
  return new Promise<number>((resolve: (errorCode: number) => void): void => {
    SpeechRecognizeSdk.prepareRuntime(new PrepareRuntimeCb(resolve));
  });
}

function createEngine(): SpeechRecognitionEngine {
  const params = new CreateEngineParams();
  params.language = 'zh-CN';
  params.online = 1;
  return SpeechRecognizeSdk.createEngine(params);
}

function startParams(sessionId: string, mode: string, cycle: number): StartParams {
  const params = new StartParams();
  params.sessionId = sessionId;
  params.audioInfo = new AudioInfo();
  params.extraParams['enablePartialResult'] = false;
  // Standard lifecycle tests must end only at their explicit finish. The max-duration mode overrides this.
  params.extraParams['maxAudioDuration'] = 28800000;
  if (mode === 'vad-begin') params.extraParams['vadBegin'] = 10000;
  if (mode === 'vad-begin-silence') params.extraParams['vadBegin'] = 500;
  if (mode === 'reconfigure') {
    const values: number[] = [500, 800, 1200];
    params.extraParams['vadEnd'] = values[cycle % values.length];
  }
  return params;
}

function prepareStressVoiceprint(workPath: string, entry: CorpusEntry): string {
  const pcm = new ArrayBuffer(5 * 16000 * 2);
  const fp = fs.openSync(entry.path);
  let bytesRead = 0;
  try {
    bytesRead = fs.readSync(fp.fd, pcm);
  } finally {
    fs.closeSync(fp.fd);
  }
  if (bytesRead < 3 * 16000 * 2) throw new Error('voiceprint-enrollment-source-too-short');
  const samplePath = `${workPath}/stress-voiceprint-enroll.wav`;
  WavIo.writePcmBytes(samplePath, pcm.slice(0, bytesRead));
  const params = new VoiceprintRegisterParams();
  params.samplePaths = [samplePath];
  const registered = SpeechRecognizeSdk.registerVoiceprint(params);
  const ids = Object.keys(registered.voiceprintId);
  if (registered.status !== 0 || ids.length !== 1) {
    throw new Error(`voiceprint-register-${registered.status}-${safeDetail(registered.message)}`);
  }
  return ids[0];
}

async function feedPcmFile(engine: SpeechRecognitionEngine, sessionId: string, path: string,
  maxFrames: number, paceMs: number, stopWhen?: () => boolean, gain: number = 1): Promise<number> {
  const frame = new ArrayBuffer(FRAME_BYTES);
  const frameBytes = new Uint8Array(frame);
  let fed = 0;
  const fp = fs.openSync(path);
  try {
    while (maxFrames <= 0 || fed < maxFrames) {
      if (stopWhen?.()) break;
      frameBytes.fill(0);
      const bytesRead = fs.readSync(fp.fd, frame);
      if (bytesRead <= 0) break;
      if (gain !== 1) {
        for (let i = 0; i + 1 < bytesRead; i += 2) {
          let sample = frameBytes[i] | (frameBytes[i + 1] << 8);
          if ((sample & 0x8000) !== 0) sample -= 0x10000;
          const scaled = Math.max(-32768, Math.min(32767, Math.round(sample * gain)));
          frameBytes[i] = scaled & 0xFF;
          frameBytes[i + 1] = (scaled >> 8) & 0xFF;
        }
      }
      engine.writeAudio(sessionId, frame);
      fed += 1;
      if (paceMs > 0) {
        await sleep(paceMs);
      } else if (fed % 50 === 0) {
        // Burst remains much faster than realtime, but must not monopolize the UIAbility event runner
        // long enough for Harmony's foreground-app watchdog to terminate a long-file stress cycle.
        await sleep(1);
      }
    }
  } finally {
    fs.closeSync(fp);
  }
  return fed;
}

function feedSilence(engine: SpeechRecognitionEngine, sessionId: string, frames: number): void {
  for (let i = 0; i < frames; i++) engine.writeAudio(sessionId, new ArrayBuffer(FRAME_BYTES));
}

function finishCycle(index: number, corpusId: string, events: SessionEvents, startedAt: number,
  ok: boolean, detail: string): CycleResult {
  const result = new CycleResult();
  result.index = index;
  result.corpusId = corpusId;
  result.ok = ok;
  result.starts = events.starts;
  result.partials = events.partials;
  result.finals = events.finals;
  result.completes = events.completes;
  result.errors = events.errors;
  result.finalChars = events.finalChars;
  result.speakerScores = events.speakerScores;
  result.missingSpeakerScores = events.missingSpeakerScores;
  result.firstNonEmptyFinalHasScore = events.firstNonEmptyFinalHasScore === undefined ? -1 :
    (events.firstNonEmptyFinalHasScore ? 1 : 0);
  result.liveStreams = AmphionRuntime.activeOnlineStreamCount();
  result.elapsedMs = Date.now() - startedAt;
  result.resultHex = stringToUtf16Hex(events.finalTexts.join(''));
  result.callbackTrace = events.callbackTrace.join('>');
  result.unexpectedSessionCallbacks = events.unexpectedSessionCallbacks;
  result.ok = ok && result.liveStreams === 0 && result.unexpectedSessionCallbacks === 0;
  if (result.liveStreams !== 0) {
    result.detail = `live-streams-${result.liveStreams}`;
  } else if (result.unexpectedSessionCallbacks !== 0) {
    result.detail = `unexpected-session-callbacks-${result.unexpectedSessionCallbacks}`;
  } else {
    result.detail = detail;
  }
  return result;
}

async function runRecognitionCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry, index: number,
  options: DeviceStressOptions): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  const sessionId = `stress-${index}`;
  engine.setListener(new StressListener(events, sessionId));
  engine.startListening(startParams(sessionId, options.mode, index));
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, events, startedAt, false, 'start-timeout');
  }

  if (options.mode === 'cancel' || options.mode === 'cancel-full') {
    const maxFrames = options.mode === 'cancel' ? 25 : 0;
    const fed = await feedPcmFile(engine, sessionId, entry.path, maxFrames, 0);
    if (fed === 0) {
      engine.cancel(sessionId);
      return finishCycle(index, entry.id, events, startedAt, false, 'empty-pcm');
    }
    const finalsBefore = events.finals;
    const lastFinalsBefore = events.lastFinals;
    const completesBefore = events.completes;
    engine.cancel(sessionId);
    await sleep(100);
    const ok = !engine.isBusy() && events.errors === 0 && lastFinalsBefore === 0 &&
      completesBefore === 0 && events.finals === finalsBefore && events.lastFinals === lastFinalsBefore &&
      events.completes === completesBefore;
    const detail = options.mode === 'cancel-full' ? 'cancelled-full' : 'cancelled';
    return finishCycle(index, entry.id, events, startedAt, ok, ok ? detail : 'cancel-contract');
  }

  const paceMs = options.mode === 'paced' ? options.paceMs : 0;
  const fed = await feedPcmFile(engine, sessionId, entry.path, 0, paceMs);
  if (fed === 0) {
    engine.cancel(sessionId);
    return finishCycle(index, entry.id, events, startedAt, false, 'empty-pcm');
  }
  if (options.settleMs > 0) await sleep(options.settleMs);
  const lastFinalsBeforeFinish = events.lastFinals;
  engine.finish(sessionId);
  const completed = await waitFor((): boolean => events.completes === 1, COMPLETE_TIMEOUT_MS);
  const ok = completed && events.starts === 1 && events.completes === 1 && events.errors === 0 &&
    events.finals > 0 && events.lastIsLast && events.lastFinals === 1 && lastFinalsBeforeFinish === 0 &&
    !engine.isBusy();
  const passDetail = options.mode === 'vad-begin' ?
    `vad-begin-no-early-last-speech-events-${events.speechBegins}` : 'finished';
  let failDetail = 'finish-contract';
  if (lastFinalsBeforeFinish > 0) failDetail = 'is-last-before-finish';
  return finishCycle(index, entry.id, events, startedAt, ok, ok ? passDetail : failDetail);
}

async function runVadBeginSilenceCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry,
  index: number): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  const sessionId = `vad-begin-silence-${index}`;
  engine.setListener(new StressListener(events, sessionId));
  engine.startListening(startParams(sessionId, 'vad-begin-silence', index));
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, events, startedAt, false, 'start-timeout');
  }
  for (let i = 0; i < 30 && events.completes === 0; i++) {
    engine.writeAudio(sessionId, new ArrayBuffer(FRAME_BYTES));
  }
  const completed = await waitFor((): boolean => events.completes === 1, COMPLETE_TIMEOUT_MS);
  const ok = completed && events.starts === 1 && events.speechBegins === 0 && events.finals === 1 &&
    events.lastFinals === 1 && events.completes === 1 && events.errors === 0 && !engine.isBusy();
  return finishCycle(index, entry.id, events, startedAt, ok,
    ok ? 'vad-begin-silence-auto-finished' : 'vad-begin-silence-contract');
}

async function runVoiceprintCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry, index: number,
  voiceprintId: string): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  const scenario = VOICEPRINT_SCENARIOS[index % VOICEPRINT_SCENARIOS.length];
  const sessionId = `voiceprint-${scenario}-${index}`;
  engine.setListener(new StressListener(events, sessionId));
  const params = startParams(sessionId, 'voiceprint', index);
  params.extraParams['enableVoiceprintVerification'] = true;
  params.extraParams['voiceprintIds'] = [voiceprintId];
  engine.startListening(params);
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, events, startedAt, false, 'start-timeout');
  }
  let fed = 0;
  if (scenario === 'short') {
    fed = await feedPcmFile(engine, sessionId, entry.path, VOICEPRINT_SHORT_FRAMES, 0);
  } else if (scenario === 'threshold') {
    fed = await feedPcmFile(engine, sessionId, entry.path, VOICEPRINT_THRESHOLD_FRAMES, 0);
  } else if (scenario === 'leading-silence') {
    feedSilence(engine, sessionId, VOICEPRINT_LEADING_SILENCE_FRAMES);
    fed = await feedPcmFile(engine, sessionId, entry.path, VOICEPRINT_LONG_FRAMES, 0);
  } else if (scenario === 'low-volume') {
    fed = await feedPcmFile(engine, sessionId, entry.path, VOICEPRINT_LONG_FRAMES, 0,
      undefined, VOICEPRINT_LOW_GAIN);
  } else if (scenario === 'multi-utterance') {
    fed = await feedPcmFile(engine, sessionId, entry.path, VOICEPRINT_LONG_FRAMES, 0);
    feedSilence(engine, sessionId, VOICEPRINT_LEADING_SILENCE_FRAMES);
    await sleep(100);
    fed += await feedPcmFile(engine, sessionId, entry.path, VOICEPRINT_LONG_FRAMES, 0);
  } else {
    fed = await feedPcmFile(engine, sessionId, entry.path, VOICEPRINT_LONG_FRAMES, 0);
  }
  if (fed === 0) {
    engine.cancel(sessionId);
    return finishCycle(index, entry.id, events, startedAt, false, 'empty-pcm');
  }
  const lastFinalsBeforeFinish = events.lastFinals;
  engine.finish(sessionId);
  const completed = await waitFor((): boolean => events.completes === 1, COMPLETE_TIMEOUT_MS);
  const scoreContract = scenario === 'short' ? events.speakerScores === 0 : events.speakerScores > 0;
  const utteranceContract = scenario !== 'multi-utterance' || events.finals >= 2;
  const ok = completed && events.starts === 1 && events.finals > 0 && events.lastFinals === 1 &&
    lastFinalsBeforeFinish === 0 && events.completes === 1 && events.errors === 0 && scoreContract &&
    utteranceContract && !engine.isBusy();
  let detail = `voiceprint-${scenario}-${scenario === 'short' ? 'no-score' : 'scored'}`;
  if (!scoreContract) {
    detail = `voiceprint-score-contract-${scenario}-scores-${events.speakerScores}`;
  } else if (!utteranceContract) {
    detail = `voiceprint-multi-utterance-finals-${events.finals}`;
  } else if (lastFinalsBeforeFinish > 0) {
    detail = 'is-last-before-finish';
  }
  return finishCycle(index, entry.id, events, startedAt, ok, detail);
}

async function runVoiceprintVadBeginCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry, index: number,
  voiceprintId: string): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  const paced = index % 2 === 1;
  const leadingSilence = index % 4 >= 2;
  const sessionId = `voiceprint-vad-begin-${index}`;
  engine.setListener(new StressListener(events, sessionId));
  const params = startParams(sessionId, 'voiceprint-vad-begin', index);
  params.extraParams['vadBegin'] = 1000;
  params.extraParams['enableVoiceprintVerification'] = true;
  params.extraParams['voiceprintIds'] = [voiceprintId];
  engine.startListening(params);
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, events, startedAt, false, 'start-timeout');
  }
  if (leadingSilence) feedSilence(engine, sessionId, 40);
  const fed = await feedPcmFile(engine, sessionId, entry.path, VOICEPRINT_LONG_FRAMES, paced ? 20 : 0);
  if (fed === 0) {
    engine.cancel(sessionId);
    return finishCycle(index, entry.id, events, startedAt, false, 'empty-pcm');
  }
  const lastFinalsBeforeFinish = events.lastFinals;
  engine.finish(sessionId);
  const completed = await waitFor((): boolean => events.completes === 1, COMPLETE_TIMEOUT_MS);
  const ok = completed && events.starts === 1 && events.finals > 0 && events.speakerScores > 0 &&
    events.firstNonEmptyFinalHasScore === true &&
    events.lastFinals === 1 && lastFinalsBeforeFinish === 0 && events.completes === 1 &&
    events.errors === 0 && !engine.isBusy();
  let detail = `voiceprint-vad-begin-${paced ? 'paced' : 'burst'}-${leadingSilence ? 'leading' : 'direct'}`;
  if (lastFinalsBeforeFinish > 0) detail = 'is-last-before-finish';
  else if (events.firstNonEmptyFinalHasScore !== true) detail = 'first-final-missing-speaker-score';
  const result = finishCycle(index, entry.id, events, startedAt, ok, detail);
  result.requestedVadBeginMs = 1000;
  result.confirmationGraceMs = 1500;
  result.voiceprintIdCount = 1;
  result.fedFrames = fed;
  result.lastFinalsBeforeFinish = lastFinalsBeforeFinish;
  return result;
}

async function runVoiceprintVadBeginIdleCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry, index: number,
  voiceprintId: string): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  const noisy = index % 2 === 1;
  const sessionId = `voiceprint-vad-begin-idle-${index}`;
  engine.setListener(new StressListener(events, sessionId));
  const params = startParams(sessionId, 'voiceprint-vad-begin-idle', index);
  params.extraParams['vadBegin'] = 1000;
  params.extraParams['enableVoiceprintVerification'] = true;
  params.extraParams['voiceprintIds'] = [voiceprintId];
  engine.startListening(params);
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, events, startedAt, false, 'start-timeout');
  }

  const frame = new ArrayBuffer(FRAME_BYTES);
  if (noisy) {
    const samples = new Int16Array(frame);
    for (let i = 0; i < samples.length; i++) samples[i] = i % 2 === 0 ? 700 : -700;
  }
  let fed = 0;
  while (events.completes === 0 && fed < 160) {
    engine.writeAudio(sessionId, frame);
    fed += 1;
    if (fed % 10 === 0) await sleep(1);
  }
  const completed = await waitFor((): boolean => events.completes === 1, COMPLETE_TIMEOUT_MS);
  const timingOk = noisy ? fed >= 110 && fed <= 150 : fed >= 45 && fed <= 70;
  const ok = completed && timingOk && events.starts === 1 && events.finals === 1 &&
    events.lastFinals === 1 && events.finalChars === 0 && events.speechBegins === 0 &&
    events.completes === 1 && events.errors === 0 && !engine.isBusy();
  let detail = `voiceprint-vad-begin-${noisy ? 'bounded-noise' : 'pure-silence'}`;
  if (!completed) detail = 'auto-complete-timeout';
  else if (!timingOk) detail = `unexpected-auto-finish-frame-${fed}`;
  else if (events.finals !== 1) detail = `unexpected-final-count-${events.finals}`;
  else if (events.speechBegins !== 0) detail = `unexpected-speech-begin-${events.speechBegins}`;
  else if (events.finalChars !== 0) detail = `unexpected-final-chars-${events.finalChars}`;
  const result = finishCycle(index, entry.id, events, startedAt, ok, detail);
  result.requestedVadBeginMs = 1000;
  result.confirmationGraceMs = 1500;
  result.voiceprintIdCount = 1;
  result.fedFrames = fed;
  return result;
}

async function runMaxDurationCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry,
  index: number): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  const sessionId = `max-${index}`;
  engine.setListener(new StressListener(events, sessionId));
  const params = startParams(sessionId, 'max-duration', index);
  params.extraParams['maxAudioDuration'] = 20000;
  engine.startListening(params);
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, events, startedAt, false, 'start-timeout');
  }

  let fedFrames = 0;
  while (events.completes === 0 && fedFrames < 1100) {
    const fed = await feedPcmFile(engine, sessionId, entry.path, 0, 0,
      (): boolean => events.completes > 0);
    if (fed === 0) break;
    fedFrames += fed;
  }
  const completed = await waitFor((): boolean => events.completes === 1, COMPLETE_TIMEOUT_MS);
  const finalsBeforeLateFrames = events.finals;
  const lastFinalsBeforeLateFrames = events.lastFinals;
  const completesBeforeLateFrames = events.completes;
  const errorsBeforeLateFrames = events.errors;
  for (let i = 0; i < 80; i++) {
    engine.writeAudio(sessionId, new ArrayBuffer(FRAME_BYTES));
  }
  await sleep(150);
  const lateFramesStable = events.finals === finalsBeforeLateFrames &&
    events.lastFinals === lastFinalsBeforeLateFrames && events.completes === completesBeforeLateFrames &&
    events.errors === errorsBeforeLateFrames;
  const ok = completed && finalsBeforeLateFrames > 0 && lastFinalsBeforeLateFrames === 1 &&
    completesBeforeLateFrames === 1 && errorsBeforeLateFrames === 0 && lateFramesStable &&
    events.lastIsLast && !engine.isBusy() && fedFrames >= 1000;
  return finishCycle(index, entry.id, events, startedAt, ok, ok ? 'auto-finished' : 'max-duration-contract');
}

async function runNumericEdgeCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry,
  index: number): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  const sessionId = `numeric-${index}`;
  engine.setListener(new StressListener(events, sessionId));
  const params = startParams(sessionId, 'numeric-edge', index);
  params.extraParams['maxAudioDuration'] = Number.NaN;
  engine.startListening(params);
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, events, startedAt, false, 'start-timeout');
  }

  let fedFrames = 0;
  while (events.completes === 0 && fedFrames < 1100) {
    const fed = await feedPcmFile(engine, sessionId, entry.path, 0, 0,
      (): boolean => events.completes > 0);
    if (fed === 0) break;
    fedFrames += fed;
  }
  const completed = await waitFor((): boolean => events.completes === 1, 1000);
  if (!completed && engine.isBusy()) {
    engine.cancel(sessionId);
    await sleep(100);
  }

  const ok = completed && events.completes === 1 && events.errors === 0 && events.lastIsLast &&
    !engine.isBusy() && fedFrames >= 1000;
  const detail = ok ? 'nan-max-duration-defaulted' : `nan-max-duration-bypass-fed-${fedFrames}`;
  return finishCycle(index, entry.id, events, startedAt, ok, detail);
}

async function runReentrantCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry,
  index: number): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  const firstSessionId = `reentrant-a-${index}`;
  const secondSessionId = `reentrant-b-${index}`;
  const listener = new ReentrantCompleteListener(events, engine, firstSessionId, secondSessionId);
  engine.setListener(listener);
  engine.startListening(startParams(firstSessionId, 'reentrant', index));
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, events, startedAt, false, 'start-timeout');
  }

  const firstFed = await feedPcmFile(engine, firstSessionId, entry.path, 80, 0);
  if (firstFed === 0) {
    engine.cancel(firstSessionId);
    return finishCycle(index, entry.id, events, startedAt, false, 'empty-pcm');
  }
  engine.finish(firstSessionId);
  const firstCompleted = await waitFor((): boolean => events.completes >= 1 &&
    listener.secondStartAttempted, COMPLETE_TIMEOUT_MS);
  if (!firstCompleted) {
    return finishCycle(index, entry.id, events, startedAt, false, 'first-complete-timeout');
  }

  let secondCompleted = false;
  if (events.starts >= 2) {
    const secondFed = await feedPcmFile(engine, secondSessionId, entry.path, 80, 0);
    if (secondFed > 0) {
      engine.finish(secondSessionId);
      secondCompleted = await waitFor((): boolean => events.completes === 2, COMPLETE_TIMEOUT_MS);
    }
  }
  if (engine.isBusy()) {
    engine.cancel(secondSessionId);
    await sleep(100);
  }

  const ok = !listener.firstCompleteBusy && listener.secondStartAttempted && events.starts === 2 &&
    secondCompleted && events.completes === 2 && events.errors === 0 && !engine.isBusy();
  let detail = 'reentrant-complete-contract';
  if (ok) {
    detail = 'reentrant-complete';
  } else if (listener.startThrowMessage.length > 0) {
    detail = `reentrant-start-throw-${listener.startThrowMessage}`;
  } else if (listener.firstCompleteBusy) {
    detail = 'oncomplete-observed-busy';
  } else if (errorCount(events, DingqiaoErrorCode.ENGINE_BUSY) > 0) {
    detail = 'reentrant-start-engine-busy';
  }
  return finishCycle(index, entry.id, events, startedAt, ok, detail);
}

async function runStartCancelCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry,
  index: number): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  const listener = new StartCancelListener(events, engine);
  engine.setListener(listener);
  const sessionId = `start-cancel-${index}`;
  engine.startListening(startParams(sessionId, 'start-cancel', index));
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, events, startedAt, false, 'start-timeout');
  }
  await sleep(100);
  if (engine.isBusy()) {
    engine.cancel(sessionId);
    await sleep(100);
  }

  const ok = events.starts === 1 && events.finals === 0 && events.completes === 0 &&
    events.errors === 0 && !listener.eventAfterCancel && !engine.isBusy();
  const detail = listener.eventAfterCancel
    ? `event-after-cancel-session-${safeDetail(listener.eventAfterCancelSessionId)}`
    : (ok ? 'start-cancel' : 'start-cancel-contract');
  return finishCycle(index, entry.id, events, startedAt, ok, detail);
}

// Mirrors a real caller under impatient user input: cancel and immediately reuse the engine, try to
// restart while finish is still settling, then deliver stale calls from the old session while the new
// one is active. Text accuracy is deliberately irrelevant; only session isolation and callback order
// are accepted as success criteria.
async function runUserSequenceCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry,
  index: number): Promise<CycleResult> {
  const startedAt = Date.now();
  const listener = new SequenceListener();
  engine.setListener(listener);
  const cancelSession = `user-cancel-${index}`;
  const finishSession = `user-finish-${index}`;
  const nextSession = `user-next-${index}`;

  const cancelParams = startParams(cancelSession, 'user-sequence', index);
  cancelParams.extraParams['enablePartialResult'] = true;
  engine.startListening(cancelParams);
  if (!await waitFor((): boolean => listener.count(cancelSession, 'start') === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, listener.events, startedAt, false, 'cancel-start-timeout');
  }
  const cancelFrames: number[] = [0, 25, 150];
  const cancelFrameCount = cancelFrames[index % cancelFrames.length];
  if (cancelFrameCount > 0) {
    await feedPcmFile(engine, cancelSession, entry.path, cancelFrameCount, 0);
  }
  const cancelPartialsBeforeCancel = listener.count(cancelSession, 'partial');
  const cancelFinalsBeforeCancel = listener.count(cancelSession, 'final');
  const cancelLastBeforeCancel = listener.lastCount(cancelSession);
  const cancelCompletesBeforeCancel = listener.count(cancelSession, 'complete');
  engine.cancel(cancelSession);
  const idleAfterCancel = !engine.isBusy();

  // No settling delay: this is the common stop/start gesture that exposes stale callback ownership.
  const finishParams = startParams(finishSession, 'user-sequence', index);
  finishParams.extraParams['enablePartialResult'] = true;
  engine.startListening(finishParams);
  if (!await waitFor((): boolean => listener.count(finishSession, 'start') === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, listener.events, startedAt, false, 'restart-after-cancel-timeout');
  }
  const firstFed = await feedPcmFile(engine, finishSession, entry.path, 150, 0);
  if (firstFed === 0) {
    engine.cancel(finishSession);
    return finishCycle(index, entry.id, listener.events, startedAt, false, 'empty-pcm');
  }
  const finishLastBefore = listener.lastCount(finishSession);
  engine.finish(finishSession);

  // Depending on whether native stop completed synchronously, immediate restart may either start or
  // return ENGINE_BUSY. Both are valid, but a silent lost request is not.
  const nextParams = startParams(nextSession, 'user-sequence', index);
  nextParams.extraParams['enablePartialResult'] = true;
  engine.startListening(nextParams);
  await waitFor((): boolean => listener.count(finishSession, 'complete') === 1, COMPLETE_TIMEOUT_MS);
  let nextStarts = listener.count(nextSession, 'start');
  const immediateBusy = listener.errorCount(nextSession, DingqiaoErrorCode.ENGINE_BUSY) > 0;
  const immediateOutcome = nextStarts === 1 || immediateBusy;
  if (nextStarts === 0) {
    engine.startListening(nextParams);
    await waitFor((): boolean => listener.count(nextSession, 'start') === 1, START_TIMEOUT_MS);
    nextStarts = listener.count(nextSession, 'start');
  }

  if (nextStarts === 1) {
    // Calls from the completed session must be rejected or ignored without touching the active one.
    engine.writeAudio(finishSession, new ArrayBuffer(FRAME_BYTES));
    engine.finish(finishSession);
    engine.cancel(finishSession);
  }
  const busyAfterStaleCalls = nextStarts === 1 && engine.isBusy();
  const secondFed = nextStarts === 1 ? await feedPcmFile(engine, nextSession, entry.path, 150, 0) : 0;
  const nextLastBefore = listener.lastCount(nextSession);
  if (nextStarts === 1 && secondFed > 0 && engine.isBusy()) engine.finish(nextSession);
  await waitFor((): boolean => listener.count(nextSession, 'complete') === 1, COMPLETE_TIMEOUT_MS);
  await sleep(150);

  const cancelledCleanly = idleAfterCancel && cancelLastBeforeCancel === 0 && cancelCompletesBeforeCancel === 0 &&
    listener.count(cancelSession, 'start') === 1 &&
    listener.count(cancelSession, 'partial') === cancelPartialsBeforeCancel &&
    listener.count(cancelSession, 'final') === cancelFinalsBeforeCancel &&
    listener.count(cancelSession, 'complete') === cancelCompletesBeforeCancel;
  const finishContract = finishLastBefore === 0 && listener.count(finishSession, 'start') === 1 &&
    listener.lastCount(finishSession) === 1 && listener.count(finishSession, 'complete') === 1 &&
    listener.terminalOrderOk(finishSession);
  const nextContract = nextLastBefore === 0 && nextStarts === 1 && secondFed > 0 &&
    listener.lastCount(nextSession) === 1 && listener.count(nextSession, 'complete') === 1 &&
    listener.terminalOrderOk(nextSession);
  const errorContract = listener.errorsAreExpected(finishSession, nextSession) &&
    listener.errorCount(nextSession, DingqiaoErrorCode.ENGINE_BUSY) === (immediateBusy ? 1 : 0);
  const ok = cancelledCleanly && immediateOutcome && finishContract && busyAfterStaleCalls &&
    nextContract && errorContract && !engine.isBusy();
  let detail = 'user-sequence';
  if (!cancelledCleanly) detail = 'cancel-leaked-callback';
  else if (!immediateOutcome) detail = 'immediate-restart-silently-lost';
  else if (!finishContract) detail = 'finish-session-contract';
  else if (!busyAfterStaleCalls) detail = 'stale-call-corrupted-active-session';
  else if (!nextContract) detail = 'next-session-contract';
  else if (!errorContract) detail = 'unexpected-sequence-error';
  return finishCycle(index, entry.id, listener.events, startedAt, ok, detail);
}

async function runEdgeCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry,
  index: number): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  engine.setListener(new StressListener(events));

  const idleSessionId = `edge-idle-${index}`;
  engine.writeAudio(idleSessionId, new ArrayBuffer(FRAME_BYTES));
  engine.finish(idleSessionId);
  engine.cancel(idleSessionId);
  engine.startListening(startParams('', 'edge', index));

  const sessionId = `edge-${index}`;
  engine.startListening(startParams(sessionId, 'edge', index));
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, events, startedAt, false, 'start-timeout');
  }

  engine.writeAudio(sessionId, new ArrayBuffer(0));
  engine.writeAudio(sessionId, new ArrayBuffer(320));
  engine.writeAudio('wrong-session', new ArrayBuffer(FRAME_BYTES));
  engine.startListening(startParams(`edge-busy-${index}`, 'edge', index));
  await feedPcmFile(engine, sessionId, entry.path, 50, 0);
  const errorsBeforeFinish = events.errors;
  engine.finish(sessionId);
  engine.finish(sessionId);
  await waitFor((): boolean => events.completes === 1, COMPLETE_TIMEOUT_MS);
  const duplicateFinishError = events.errors !== errorsBeforeFinish;
  engine.writeAudio(sessionId, new ArrayBuffer(FRAME_BYTES));

  const expectedErrorCount = 8;
  const expectedErrors = errorCount(events, DingqiaoErrorCode.NOT_LISTENING) === 2 &&
    errorCount(events, DingqiaoErrorCode.FINISH_FAILED) === 1 &&
    errorCount(events, DingqiaoErrorCode.CANCEL_FAILED) === 1 &&
    errorCount(events, DingqiaoErrorCode.START_LISTENING_FAILED) === 1 &&
    errorCount(events, DingqiaoErrorCode.RECOGNITION_ERROR) === 2 &&
    errorCount(events, DingqiaoErrorCode.ENGINE_BUSY) === 1;
  const ok = expectedErrors && !duplicateFinishError && events.errors === expectedErrorCount &&
    events.completes === 1 && events.finals > 0 && !engine.isBusy();
  return finishCycle(index, entry.id, events, startedAt, ok,
    duplicateFinishError ? 'duplicate-finish-not-idempotent' : (ok ? 'edge-contracts' : 'edge-contract'));
}

function logLine(line: string): void {
  hilog.info(DOMAIN, TAG, 'ASR_STRESS|%{public}s', line);
}

function safeDetail(value: string): string {
  return value.replace(/[^A-Za-z0-9_.:-]/g, '_').substring(0, 160);
}

export async function runDeviceStress(context: common.UIAbilityContext,
  options: DeviceStressOptions): Promise<void> {
  const startedAt = Date.now();
  const lines: string[] = [];
  const totals = new StressTotals();
  let entries: CorpusEntry[] = [];
  let engine: SpeechRecognitionEngine | undefined;
  let stressVoiceprintId: string = '';
  let stressVoiceprintSamplePath: string = '';
  let fatal = '';
  logLine(`BEGIN|runId=${options.runId}|mode=${options.mode}|cycles=${options.cycles}`);

  try {
    if (options.manifestPath.length === 0 || options.resultPath.length === 0) {
      throw new Error('manifestPath and resultPath are required');
    }
    entries = readManifest(options.manifestPath);
    const workPath = `${context.filesDir}/dingqiao_work`;
    SpeechRecognizeSdk.setWorkPath(workPath);
    const license = await activateLicense(prepareLicense(context, workPath));
    if (license.errorCode !== 0) throw new Error(`license-${license.errorCode}`);
    const runtimeError = await prepareRuntime();
    if (runtimeError !== 0) throw new Error(`runtime-${runtimeError}`);

    if (options.mode === 'voiceprint' || options.mode === 'voiceprint-vad-begin' ||
      options.mode === 'voiceprint-vad-begin-idle') {
      if (options.mode === 'voiceprint' && entries.length < 2) {
        throw new Error('voiceprint-stress-requires-two-corpus-sources');
      }
      stressVoiceprintSamplePath = `${workPath}/stress-voiceprint-enroll.wav`;
      stressVoiceprintId = prepareStressVoiceprint(workPath, entries[0]);
    }

    if (options.mode !== 'recreate') engine = createEngine();
    for (let i = 0; i < options.cycles; i++) {
      let entry = entries[i % entries.length];
      if (options.mode === 'voiceprint' &&
        VOICEPRINT_SCENARIOS[i % VOICEPRINT_SCENARIOS.length] === 'alternate-source') {
        entry = entries[1];
      }
      if (options.mode === 'recreate') engine = createEngine();
      if (engine === undefined) throw new Error('engine-create-failed');

      let result: CycleResult;
      if (options.mode === 'edge') {
        result = await runEdgeCycle(engine, entry, i);
      } else if (options.mode === 'max-duration') {
        result = await runMaxDurationCycle(engine, entry, i);
      } else if (options.mode === 'numeric-edge') {
        result = await runNumericEdgeCycle(engine, entry, i);
      } else if (options.mode === 'reentrant') {
        result = await runReentrantCycle(engine, entry, i);
      } else if (options.mode === 'start-cancel') {
        result = await runStartCancelCycle(engine, entry, i);
      } else if (options.mode === 'user-sequence') {
        result = await runUserSequenceCycle(engine, entry, i);
      } else if (options.mode === 'vad-begin-silence') {
        result = await runVadBeginSilenceCycle(engine, entry, i);
      } else if (options.mode === 'voiceprint') {
        result = await runVoiceprintCycle(engine, entry, i, stressVoiceprintId);
      } else if (options.mode === 'voiceprint-vad-begin') {
        result = await runVoiceprintVadBeginCycle(engine, entry, i, stressVoiceprintId);
      } else if (options.mode === 'voiceprint-vad-begin-idle') {
        result = await runVoiceprintVadBeginIdleCycle(engine, entry, i, stressVoiceprintId);
      } else {
        result = await runRecognitionCycle(engine, entry, i, options);
      }
      totals.add(result);
      lines.push(result.toLine());
      logLine(result.toLine());

      if (options.mode === 'recreate') {
        engine.shutdown();
        engine.shutdown();
        engine = undefined;
      }
      await sleep(10);
    }
  } catch (e) {
    fatal = safeDetail(`${e}`);
    logLine(`FATAL|runId=${options.runId}|detail=${fatal}`);
  } finally {
    if (engine !== undefined) engine.shutdown();
    if (stressVoiceprintId.length > 0) {
      try { SpeechRecognizeSdk.deleteVoiceprint(stressVoiceprintId); } catch (_e) {}
    }
    if (stressVoiceprintSamplePath.length > 0) {
      try { if (fs.accessSync(stressVoiceprintSamplePath)) fs.unlinkSync(stressVoiceprintSamplePath); } catch (_e) {}
    }
  }

  const status = fatal.length === 0 && totals.failed === 0 && totals.completed === options.cycles ? 'PASS' : 'FAIL';
  const summary = `SUMMARY|runId=${options.runId}|status=${status}|mode=${options.mode}` +
    `|requested=${options.cycles}|completed=${totals.completed}|failed=${totals.failed}` +
    `|emptyFinals=${totals.emptyFinals}|starts=${totals.starts}|partials=${totals.partials}|finals=${totals.finals}` +
    `|completes=${totals.completes}|errors=${totals.errors}|elapsedMs=${Date.now() - startedAt}` +
    `|fatal=${fatal}`;
  lines.push(summary);
  let resultWritten = false;
  try {
    writeText(options.resultPath, `${lines.join('\n')}\n`);
    resultWritten = true;
  } catch (e) {
    logLine(`RESULT_WRITE_FAILED|runId=${options.runId}|detail=${safeDetail(`${e}`)}`);
  }
  if (resultWritten) cleanupStressInputs(context, options.manifestPath, entries);
  logLine(summary);
  logLine(`END|runId=${options.runId}`);
}
