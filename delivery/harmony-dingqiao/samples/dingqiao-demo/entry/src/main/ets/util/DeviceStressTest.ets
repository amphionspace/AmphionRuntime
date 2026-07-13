import hilog from '@ohos.hilog';
import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import {
  AudioInfo,
  CreateEngineParams,
  DingqiaoErrorCode,
  LicenseActivationCallback,
  LicenseActivationResult,
  PrepareRuntimeCallback,
  RecognitionListener,
  SpeechRecognitionEngine,
  SpeechRecognitionResult,
  SpeechRecognizeSdk,
  StartParams
} from 'amphion_dingqiao';
import { AmphionRuntime } from 'amphion_asr';

const TAG: string = 'DeviceStressTest';
const DOMAIN: number = 0x0000;
const FRAME_BYTES: number = 640;
const START_TIMEOUT_MS: number = 10000;
const COMPLETE_TIMEOUT_MS: number = 30000;

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
  finals: number = 0;
  completes: number = 0;
  errors: number = 0;
  finalChars: number = 0;
  finalTexts: string[] = [];
  lastIsLast: boolean = false;
  errorCodes: number[] = [];
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

  constructor(events: SessionEvents) {
    this.events = events;
  }

  onStart(_sessionId: string, _eventMessage?: string): void {
    this.events.starts += 1;
  }

  onResult(_sessionId: string, result: SpeechRecognitionResult): void {
    if (!result.isFinal) return;
    this.events.finals += 1;
    this.events.finalChars += result.result.length;
    this.events.finalTexts.push(result.result);
    this.events.lastIsLast = result.isLast;
  }

  onComplete(_sessionId: string, _eventMessage?: string): void {
    this.events.completes += 1;
  }

  onError(_sessionId: string, errorCode: number, _message: string): void {
    this.events.errors += 1;
    this.events.errorCodes.push(errorCode);
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

  onStart(_sessionId: string, _eventMessage?: string): void {
    this.events.starts += 1;
  }

  onResult(_sessionId: string, result: SpeechRecognitionResult): void {
    if (!result.isFinal) return;
    this.events.finals += 1;
    this.events.finalChars += result.result.length;
    this.events.lastIsLast = result.isLast;
  }

  onComplete(sessionId: string, _eventMessage?: string): void {
    this.events.completes += 1;
    if (sessionId !== this.firstSessionId || this.secondStartAttempted) return;
    this.firstCompleteBusy = this.engine.isBusy();
    this.secondStartAttempted = true;
    try {
      this.engine.startListening(startParams(this.secondSessionId, 'reentrant', 0));
    } catch (e) {
      this.startThrowMessage = safeDetail(`${e}`);
    }
  }

  onError(_sessionId: string, errorCode: number, _message: string): void {
    this.events.errors += 1;
    this.events.errorCodes.push(errorCode);
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
    this.cancelledInStart = true;
    this.engine.cancel(sessionId);
  }

  onEvent(sessionId: string, _eventCode: number, _message: string): void {
    if (!this.cancelledInStart) return;
    this.eventAfterCancel = true;
    this.eventAfterCancelSessionId = sessionId;
  }

  onResult(_sessionId: string, result: SpeechRecognitionResult): void {
    if (!result.isFinal) return;
    this.events.finals += 1;
    this.events.finalChars += result.result.length;
    this.events.lastIsLast = result.isLast;
  }

  onComplete(_sessionId: string, _eventMessage?: string): void {
    this.events.completes += 1;
  }

  onError(_sessionId: string, errorCode: number, _message: string): void {
    this.events.errors += 1;
    this.events.errorCodes.push(errorCode);
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
  finals: number = 0;
  completes: number = 0;
  errors: number = 0;
  finalChars: number = 0;
  liveStreams: number = 0;
  elapsedMs: number = 0;
  resultHex: string = '';
  detail: string = '';

  toLine(): string {
    return `CYCLE|index=${this.index}|id=${this.corpusId}|status=${this.ok ? 'PASS' : 'FAIL'}` +
      `|starts=${this.starts}|finals=${this.finals}|completes=${this.completes}` +
      `|errors=${this.errors}|finalChars=${this.finalChars}|liveStreams=${this.liveStreams}` +
      `|elapsedMs=${this.elapsedMs}|resultHex=${this.resultHex}|detail=${this.detail}`;
  }
}

class StressTotals {
  completed: number = 0;
  failed: number = 0;
  emptyFinals: number = 0;
  starts: number = 0;
  finals: number = 0;
  completes: number = 0;
  errors: number = 0;

  add(result: CycleResult): void {
    this.completed += 1;
    if (!result.ok) this.failed += 1;
    if (result.finals > 0 && result.finalChars === 0) this.emptyFinals += 1;
    this.starts += result.starts;
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
  params.extraParams['maxAudioDuration'] = 60000;
  if (mode === 'reconfigure') {
    const values: number[] = [500, 800, 1200];
    params.extraParams['vadEnd'] = values[cycle % values.length];
  }
  return params;
}

async function feedPcmFile(engine: SpeechRecognitionEngine, sessionId: string, path: string,
  maxFrames: number, paceMs: number, stopWhen?: () => boolean): Promise<number> {
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

function finishCycle(index: number, corpusId: string, events: SessionEvents, startedAt: number,
  ok: boolean, detail: string): CycleResult {
  const result = new CycleResult();
  result.index = index;
  result.corpusId = corpusId;
  result.ok = ok;
  result.starts = events.starts;
  result.finals = events.finals;
  result.completes = events.completes;
  result.errors = events.errors;
  result.finalChars = events.finalChars;
  result.liveStreams = AmphionRuntime.activeOnlineStreamCount();
  result.elapsedMs = Date.now() - startedAt;
  result.resultHex = stringToUtf16Hex(events.finalTexts.join(''));
  result.ok = ok && result.liveStreams === 0;
  result.detail = result.liveStreams === 0 ? detail : `live-streams-${result.liveStreams}`;
  return result;
}

async function runRecognitionCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry, index: number,
  options: DeviceStressOptions): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  engine.setListener(new StressListener(events));
  const sessionId = `stress-${index}`;
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
    const completesBefore = events.completes;
    engine.cancel(sessionId);
    await sleep(100);
    const ok = !engine.isBusy() && events.errors === 0 && events.finals === finalsBefore &&
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
  engine.finish(sessionId);
  const completed = await waitFor((): boolean => events.completes === 1, COMPLETE_TIMEOUT_MS);
  const ok = completed && events.starts === 1 && events.completes === 1 && events.errors === 0 &&
    events.finals > 0 && events.lastIsLast && !engine.isBusy();
  return finishCycle(index, entry.id, events, startedAt, ok, ok ? 'finished' : 'finish-contract');
}

async function runMaxDurationCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry,
  index: number): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  engine.setListener(new StressListener(events));
  const sessionId = `max-${index}`;
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
  for (let i = 0; i < 80; i++) {
    engine.writeAudio(sessionId, new ArrayBuffer(FRAME_BYTES));
  }
  const ok = completed && events.completes === 1 && events.errors === 0 && events.lastIsLast &&
    !engine.isBusy() && fedFrames >= 1000;
  return finishCycle(index, entry.id, events, startedAt, ok, ok ? 'auto-finished' : 'max-duration-contract');
}

async function runNumericEdgeCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry,
  index: number): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  engine.setListener(new StressListener(events));
  const sessionId = `numeric-${index}`;
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

    if (options.mode !== 'recreate') engine = createEngine();
    for (let i = 0; i < options.cycles; i++) {
      const entry = entries[i % entries.length];
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
  }

  const status = fatal.length === 0 && totals.failed === 0 && totals.completed === options.cycles ? 'PASS' : 'FAIL';
  const summary = `SUMMARY|runId=${options.runId}|status=${status}|mode=${options.mode}` +
    `|requested=${options.cycles}|completed=${totals.completed}|failed=${totals.failed}` +
    `|emptyFinals=${totals.emptyFinals}|starts=${totals.starts}|finals=${totals.finals}` +
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
