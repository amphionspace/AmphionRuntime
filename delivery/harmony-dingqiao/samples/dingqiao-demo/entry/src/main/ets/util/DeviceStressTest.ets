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
const FRAME_DURATION_MS: number = 20;
const IDLE_FRAME_PACE_MS: number = FRAME_DURATION_MS + 10;
const START_TIMEOUT_MS: number = 10000;
const COMPLETE_TIMEOUT_MS: number = 30000;
const CANCEL_DRAIN_TIMEOUT_MS: number = 2000;
const CANCEL_CALLBACK_STABILITY_MS: number = 100;
const MAX_DURATION_TEST_MS: number = 8000;
const MAX_DURATION_TEST_FRAMES: number = MAX_DURATION_TEST_MS / FRAME_DURATION_MS;
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
  enrollmentCount: number = 1;
  enforceTargetSpeakerBusinessText: boolean = true;
  speakerVadThreshold: number = -2;
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
  audioFeedStartedAtMs: number = -1;
  speechBeginAtMs: number = -1;
  firstNonEmptyResultAtMs: number = -1;
  lastIsLast: boolean = false;
  lastFinals: number = 0;
  speakerScores: number = 0;
  nonEmptySpeakerScores: number = 0;
  missingSpeakerScores: number = 0;
  firstNonEmptyFinalHasScore?: boolean;
  targetSpeakerEnhancementResults: number = 0;
  errorCodes: number[] = [];
  errorMessages: string[] = [];
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

function terminalCallbackOrderOk(events: SessionEvents, sessionId: string): boolean {
  const last = `${sessionId}:final-last`;
  const complete = `${sessionId}:complete`;
  let lastIndex = -1;
  let completeIndex = -1;
  for (let i = 0; i < events.callbackTrace.length; i++) {
    const item = events.callbackTrace[i];
    if (item === last) {
      if (lastIndex >= 0) return false;
      lastIndex = i;
    }
    if (item === complete) {
      if (completeIndex >= 0) return false;
      completeIndex = i;
    }
  }
  if (lastIndex < 0 || completeIndex < 0 || lastIndex > completeIndex) return false;
  for (let i = completeIndex + 1; i < events.callbackTrace.length; i++) {
    if (events.callbackTrace[i].startsWith(`${sessionId}:`)) return false;
  }
  return true;
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
    if (eventCode === DingqiaoEventCode.SPEECH_BEGIN) {
      this.events.speechBegins += 1;
      const expectedSession = this.expectedSessionId.length === 0 || sessionId === this.expectedSessionId;
      if (expectedSession && this.events.speechBeginAtMs < 0) this.events.speechBeginAtMs = Date.now();
    }
    if (eventCode === DingqiaoEventCode.SPEECH_END) this.events.speechEnds += 1;
    this.record(sessionId, 'event', `-${eventCode}`);
  }

  onResult(sessionId: string, result: SpeechRecognitionResult): void {
    const expectedSession = this.expectedSessionId.length === 0 || sessionId === this.expectedSessionId;
    if (expectedSession && result.result.length > 0 && this.events.firstNonEmptyResultAtMs < 0) {
      this.events.firstNonEmptyResultAtMs = Date.now();
    }
    if (!result.isFinal) {
      this.events.partials += 1;
      this.record(sessionId, 'partial');
      return;
    }
    if (result.targetSpeakerEnhancementApplied === true) {
      this.events.targetSpeakerEnhancementResults += 1;
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
      if (result.result.length > 0) this.events.nonEmptySpeakerScores += 1;
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

  onError(sessionId: string, errorCode: number, message: string): void {
    this.events.errors += 1;
    this.events.errorCodes.push(errorCode);
    this.events.errorMessages.push(safeDetail(message));
    this.record(sessionId, 'error', `-${errorCode}`);
  }
}

class OnStartSpeakerVadListener extends StressListener {
  private engine: SpeechRecognitionEngine;
  enableAttempted: boolean = false;
  enableReturned: boolean = false;
  speakerVadChangedEvents: number = 0;
  enableThrowMessage: string = '';

  constructor(events: SessionEvents, expectedSessionId: string, engine: SpeechRecognitionEngine) {
    super(events, expectedSessionId);
    this.engine = engine;
  }

  onStart(sessionId: string, eventMessage?: string): void {
    super.onStart(sessionId, eventMessage);
    this.enableAttempted = true;
    try {
      this.engine.setSpeakerVadEnabled(true);
      this.enableReturned = true;
    } catch (e) {
      this.enableThrowMessage = safeDetail(`${e}`);
    }
  }

  onEvent(sessionId: string, eventCode: number, message: string): void {
    if (eventCode === DingqiaoEventCode.SPEAKER_VAD_CHANGED) this.speakerVadChangedEvents += 1;
    super.onEvent(sessionId, eventCode, message);
  }
}

class CallbackRecord {
  sessionId: string;
  kind: string;
  isLast: boolean;
  errorCode: number;
  eventCode: number;

  constructor(sessionId: string, kind: string, isLast: boolean = false, errorCode: number = 0,
    eventCode: number = -1) {
    this.sessionId = sessionId;
    this.kind = kind;
    this.isLast = isLast;
    this.errorCode = errorCode;
    this.eventCode = eventCode;
  }
}

class SequenceListener implements RecognitionListener {
  events: SessionEvents = new SessionEvents();
  records: CallbackRecord[] = [];

  protected record(callback: CallbackRecord): void {
    this.records.push(callback);
    let detail = callback.isLast ? '-last' : '';
    if (callback.kind === 'error') detail = `-${callback.errorCode}`;
    if (callback.kind === 'event') detail = `-${callback.eventCode}`;
    this.events.callbackTrace.push(`${callback.sessionId}:${callback.kind}${detail}`);
  }

  onStart(sessionId: string, _eventMessage?: string): void {
    this.events.starts += 1;
    this.record(new CallbackRecord(sessionId, 'start'));
  }

  onEvent(_sessionId: string, eventCode: number, _message: string): void {
    if (eventCode === DingqiaoEventCode.SPEECH_BEGIN) this.events.speechBegins += 1;
    if (eventCode === DingqiaoEventCode.SPEECH_END) this.events.speechEnds += 1;
    this.record(new CallbackRecord(_sessionId, 'event', false, 0, eventCode));
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

  sessionTrace(sessionId: string): string {
    const trace: string[] = [];
    for (let i = 0; i < this.records.length; i++) {
      const record = this.records[i];
      if (record.sessionId !== sessionId) continue;
      let detail = record.kind;
      if (record.kind === 'event') detail += `-${record.eventCode}`;
      if (record.kind === 'final' && record.isLast) detail += '-last';
      if (record.kind === 'error') detail += `-${record.errorCode}`;
      trace.push(detail);
    }
    return trace.join(',');
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

class CallbackApiReentrantListener extends SequenceListener {
  private engine: SpeechRecognitionEngine;
  private expectedSessionId: string;
  private trigger: string;
  reentryAttempted: boolean = false;
  writeCalls: number = 0;
  finishCalls: number = 0;
  reentryThrowMessage: string = '';

  constructor(engine: SpeechRecognitionEngine, expectedSessionId: string, trigger: string) {
    super();
    this.engine = engine;
    this.expectedSessionId = expectedSessionId;
    this.trigger = trigger;
  }

  private checkOwnership(sessionId: string): void {
    if (sessionId !== this.expectedSessionId) this.events.unexpectedSessionCallbacks += 1;
  }

  private reenter(sessionId: string): void {
    if (this.reentryAttempted) return;
    this.reentryAttempted = true;
    try {
      this.writeCalls += 1;
      this.engine.writeAudio(sessionId, new ArrayBuffer(FRAME_BYTES));
      this.finishCalls += 1;
      this.engine.finish(sessionId);
    } catch (e) {
      this.reentryThrowMessage = safeDetail(`${e}`);
    }
  }

  private finishOnly(sessionId: string): void {
    if (this.reentryAttempted) return;
    this.reentryAttempted = true;
    try {
      this.finishCalls += 1;
      this.engine.finish(sessionId);
    } catch (e) {
      this.reentryThrowMessage = safeDetail(`${e}`);
    }
  }

  onStart(sessionId: string, eventMessage?: string): void {
    this.checkOwnership(sessionId);
    super.onStart(sessionId, eventMessage);
  }

  onEvent(sessionId: string, eventCode: number, message: string): void {
    this.checkOwnership(sessionId);
    super.onEvent(sessionId, eventCode, message);
    if (this.trigger === 'speech-begin' && eventCode === DingqiaoEventCode.SPEECH_BEGIN) {
      this.reenter(sessionId);
    } else if (this.trigger === 'speech-end' && eventCode === DingqiaoEventCode.SPEECH_END) {
      // Customer integration calls finish() synchronously from SPEECH_END without writing another frame.
      // Keep this path exact so an empty trailing isLast result cannot hide behind synthetic audio.
      this.finishOnly(sessionId);
    }
  }

  onResult(sessionId: string, result: SpeechRecognitionResult): void {
    this.checkOwnership(sessionId);
    super.onResult(sessionId, result);
    if (this.trigger === 'result' && result.isFinal && !result.isLast) this.reenter(sessionId);
  }

  onComplete(sessionId: string, eventMessage?: string): void {
    this.checkOwnership(sessionId);
    super.onComplete(sessionId, eventMessage);
  }

  onError(sessionId: string, errorCode: number, message: string): void {
    this.checkOwnership(sessionId);
    super.onError(sessionId, errorCode, message);
  }
}

class EndpointReentrantListener extends SequenceListener {
  private engine: SpeechRecognitionEngine;
  private oldSessionId: string;
  private newSessionId: string;
  private switchOnLast: boolean;
  switchAttempted: boolean = false;
  idleAfterCancel: boolean = false;
  startThrowMessage: string = '';
  oldFinalsAtSwitch: number = 0;
  oldLastAtSwitch: number = 0;
  oldCompletesAtSwitch: number = 0;
  oldTraceAtSwitch: string = '';
  newAudioStarted: boolean = false;
  newCallbackBeforeAudio: boolean = false;

  constructor(engine: SpeechRecognitionEngine, oldSessionId: string, newSessionId: string,
    switchOnLast: boolean) {
    super();
    this.engine = engine;
    this.oldSessionId = oldSessionId;
    this.newSessionId = newSessionId;
    this.switchOnLast = switchOnLast;
  }

  protected record(callback: CallbackRecord): void {
    if (callback.sessionId === this.newSessionId && !this.newAudioStarted && callback.kind !== 'start') {
      this.newCallbackBeforeAudio = true;
    }
    super.record(callback);
  }

  onEvent(sessionId: string, eventCode: number, message: string): void {
    super.onEvent(sessionId, eventCode, message);
    if (this.switchOnLast || sessionId !== this.oldSessionId || eventCode !== DingqiaoEventCode.SPEECH_END ||
      this.switchAttempted) return;

    this.switchSession();
  }

  private switchSession(): void {
    this.switchAttempted = true;
    this.oldFinalsAtSwitch = this.count(this.oldSessionId, 'final');
    this.oldLastAtSwitch = this.lastCount(this.oldSessionId);
    this.oldCompletesAtSwitch = this.count(this.oldSessionId, 'complete');
    this.oldTraceAtSwitch = this.sessionTrace(this.oldSessionId);
    try {
      this.engine.cancel(this.oldSessionId);
      this.idleAfterCancel = !this.engine.isBusy();
      this.engine.startListening(startParams(this.newSessionId, 'endpoint-reentrant', 0));
    } catch (e) {
      this.startThrowMessage = safeDetail(`${e}`);
    }
  }

  onResult(sessionId: string, result: SpeechRecognitionResult): void {
    super.onResult(sessionId, result);
    if (this.switchOnLast && sessionId === this.oldSessionId && result.isFinal && result.isLast &&
      !this.switchAttempted) {
      this.switchSession();
    }
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

class StartWriteListener implements RecognitionListener {
  private events: SessionEvents;
  private engine: SpeechRecognitionEngine;
  private bufferedFrames: ArrayBuffer[];
  private finishInStart: boolean;
  framesWrittenInStart: number = 0;
  finishCalledInStart: boolean = false;
  writeBatchElapsedMs: number = 0;
  maxWriteCallMs: number = 0;

  constructor(events: SessionEvents, engine: SpeechRecognitionEngine, bufferedFrames: ArrayBuffer[],
    finishInStart: boolean) {
    this.events = events;
    this.engine = engine;
    this.bufferedFrames = bufferedFrames;
    this.finishInStart = finishInStart;
  }

  onStart(sessionId: string, _eventMessage?: string): void {
    this.events.starts += 1;
    this.events.callbackTrace.push(`${sessionId}:start`);
    const batchStartedAt = Date.now();
    for (let i = 0; i < this.bufferedFrames.length; i++) {
      const writeStartedAt = Date.now();
      this.engine.writeAudio(sessionId, this.bufferedFrames[i]);
      this.maxWriteCallMs = Math.max(this.maxWriteCallMs, Date.now() - writeStartedAt);
      this.framesWrittenInStart += 1;
    }
    this.writeBatchElapsedMs = Date.now() - batchStartedAt;
    if (this.finishInStart) {
      this.finishCalledInStart = true;
      this.engine.finish(sessionId);
    }
  }

  onEvent(sessionId: string, eventCode: number, _message: string): void {
    if (eventCode === DingqiaoEventCode.SPEECH_BEGIN) this.events.speechBegins += 1;
    if (eventCode === DingqiaoEventCode.SPEECH_END) this.events.speechEnds += 1;
    this.events.callbackTrace.push(`${sessionId}:event-${eventCode}`);
  }

  onResult(sessionId: string, result: SpeechRecognitionResult): void {
    if (!result.isFinal) {
      this.events.partials += 1;
      this.events.callbackTrace.push(`${sessionId}:partial`);
      return;
    }
    this.events.finals += 1;
    this.events.finalChars += result.result.length;
    this.events.finalTexts.push(result.result);
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

class TargetSpeakerEnhancementOnStartListener extends StressListener {
  private targetEvents: SessionEvents;
  private engine: SpeechRecognitionEngine;
  private bufferedFrames: ArrayBuffer[];
  private action: string;
  framesWrittenInStart: number = 0;
  actionCalledInStart: boolean = false;
  lastFinalsBeforeAction: number = -1;

  constructor(events: SessionEvents, expectedSessionId: string, engine: SpeechRecognitionEngine,
    bufferedFrames: ArrayBuffer[], action: string) {
    super(events, expectedSessionId);
    this.targetEvents = events;
    this.engine = engine;
    this.bufferedFrames = bufferedFrames;
    this.action = action;
  }

  onStart(sessionId: string, eventMessage?: string): void {
    super.onStart(sessionId, eventMessage);
    for (let i = 0; i < this.bufferedFrames.length; i++) {
      this.engine.writeAudio(sessionId, this.bufferedFrames[i]);
      this.framesWrittenInStart += 1;
    }
    this.lastFinalsBeforeAction = this.targetEvents.lastFinals;
    if (this.action === 'finish') {
      this.actionCalledInStart = true;
      this.engine.finish(sessionId);
    } else if (this.action === 'cancel') {
      this.actionCalledInStart = true;
      this.engine.cancel(sessionId);
    }
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
  nonEmptyFinals: number = 0;
  completes: number = 0;
  errors: number = 0;
  finalChars: number = 0;
  speakerScores: number = 0;
  nonEmptySpeakerScores: number = 0;
  missingSpeakerScores: number = 0;
  firstNonEmptyFinalHasScore: number = -1;
  requestedVadBeginMs: number = -1;
  confirmationGraceMs: number = -1;
  requestedMaxAudioDurationMs: number = -1;
  effectiveMaxAudioDurationMs: number = -1;
  voiceprintIdCount: number = 0;
  fedFrames: number = 0;
  lastFinalsBeforeFinish: number = -1;
  speechEndsBeforeFinish: number = -1;
  recoveryStarts: number = -1;
  recoveryLastFinals: number = -1;
  recoveryCompletes: number = -1;
  recoveryErrors: number = -1;
  recoveryTerminalOrder: number = -1;
  recoveryUnexpectedCallbacks: number = -1;
  liveStreams: number = 0;
  elapsedMs: number = 0;
  firstNonEmptyResultMs: number = -1;
  audioStartToFirstNonEmptyResultMs: number = -1;
  audioStartToSpeechBeginMs: number = -1;
  speechBeginToFirstNonEmptyResultMs: number = -1;
  resultHex: string = '';
  callbackTrace: string = '';
  unexpectedSessionCallbacks: number = 0;
  detail: string = '';

  toLine(): string {
    return `CYCLE|index=${this.index}|id=${this.corpusId}|status=${this.ok ? 'PASS' : 'FAIL'}` +
      `|starts=${this.starts}|partials=${this.partials}|finals=${this.finals}` +
      `|nonEmptyFinals=${this.nonEmptyFinals}|completes=${this.completes}` +
      `|errors=${this.errors}|finalChars=${this.finalChars}|speakerScores=${this.speakerScores}` +
      `|nonEmptySpeakerScores=${this.nonEmptySpeakerScores}` +
      `|missingSpeakerScores=${this.missingSpeakerScores}` +
      `|firstNonEmptyFinalHasScore=${this.firstNonEmptyFinalHasScore}` +
      `|requestedVadBeginMs=${this.requestedVadBeginMs}|confirmationGraceMs=${this.confirmationGraceMs}` +
      `|requestedMaxAudioDurationMs=${this.requestedMaxAudioDurationMs}` +
      `|effectiveMaxAudioDurationMs=${this.effectiveMaxAudioDurationMs}` +
      `|voiceprintIdCount=${this.voiceprintIdCount}|fedFrames=${this.fedFrames}` +
      `|lastFinalsBeforeFinish=${this.lastFinalsBeforeFinish}` +
      `|speechEndsBeforeFinish=${this.speechEndsBeforeFinish}|liveStreams=${this.liveStreams}` +
      `|recoveryStarts=${this.recoveryStarts}|recoveryLastFinals=${this.recoveryLastFinals}` +
      `|recoveryCompletes=${this.recoveryCompletes}|recoveryErrors=${this.recoveryErrors}` +
      `|recoveryTerminalOrder=${this.recoveryTerminalOrder}` +
      `|recoveryUnexpectedCallbacks=${this.recoveryUnexpectedCallbacks}` +
      `|unexpectedCallbacks=${this.unexpectedSessionCallbacks}|elapsedMs=${this.elapsedMs}` +
      `|firstNonEmptyResultMs=${this.firstNonEmptyResultMs}` +
      `|audioStartToFirstNonEmptyResultMs=${this.audioStartToFirstNonEmptyResultMs}` +
      `|audioStartToSpeechBeginMs=${this.audioStartToSpeechBeginMs}` +
      `|speechBeginToFirstNonEmptyResultMs=${this.speechBeginToFirstNonEmptyResultMs}` +
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

function prepareStressVoiceprint(workPath: string, entries: CorpusEntry[]): string {
  const samplePaths: string[] = [];
  for (let i = 0; i < entries.length; i++) {
    const fp = fs.openSync(entries[i].path);
    let pcm: ArrayBuffer;
    let bytesRead = 0;
    try {
      const sourceBytes = fs.statSync(fp.fd).size;
      const readBytes = entries.length > 1 ? sourceBytes : Math.min(sourceBytes, 5 * 16000 * 2);
      pcm = new ArrayBuffer(readBytes);
      bytesRead = fs.readSync(fp.fd, pcm);
    } finally {
      fs.closeSync(fp.fd);
    }
    if (bytesRead < 3 * 16000 * 2) throw new Error('voiceprint-enrollment-source-too-short');
    const samplePath = `${workPath}/stress-voiceprint-enroll-${i}.wav`;
    WavIo.writePcmBytes(samplePath, pcm.slice(0, bytesRead));
    samplePaths.push(samplePath);
  }
  const params = new VoiceprintRegisterParams();
  params.samplePaths = samplePaths;
  const registered = SpeechRecognizeSdk.registerVoiceprint(params);
  const ids = Object.keys(registered.voiceprintId);
  if (registered.status !== 0 || ids.length !== 1) {
    throw new Error(`voiceprint-register-${registered.status}-${safeDetail(registered.message)}`);
  }
  return ids[0];
}

async function feedPcmFile(engine: SpeechRecognitionEngine, sessionId: string, path: string,
  maxFrames: number, paceMs: number, stopWhen?: () => boolean, gain: number = 1,
  onFirstFrame?: () => void): Promise<number> {
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
      if (fed === 0) onFirstFrame?.();
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

function readPcmFrames(path: string, count: number): ArrayBuffer[] {
  const frames: ArrayBuffer[] = [];
  const fp = fs.openSync(path);
  try {
    for (let i = 0; i < count; i++) {
      const frame = new ArrayBuffer(FRAME_BYTES);
      const bytesRead = fs.readSync(fp.fd, frame);
      if (bytesRead <= 0) break;
      frames.push(frame);
    }
  } finally {
    fs.closeSync(fp);
  }
  return frames;
}

function feedSilence(engine: SpeechRecognitionEngine, sessionId: string, frames: number): void {
  for (let i = 0; i < frames; i++) engine.writeAudio(sessionId, new ArrayBuffer(FRAME_BYTES));
}

function mergeSessionEvents(target: SessionEvents, source: SessionEvents): void {
  target.starts += source.starts;
  target.partials += source.partials;
  target.speechBegins += source.speechBegins;
  target.speechEnds += source.speechEnds;
  target.finals += source.finals;
  target.completes += source.completes;
  target.errors += source.errors;
  target.finalChars += source.finalChars;
  target.lastFinals += source.lastFinals;
  target.speakerScores += source.speakerScores;
  target.nonEmptySpeakerScores += source.nonEmptySpeakerScores;
  target.missingSpeakerScores += source.missingSpeakerScores;
  target.unexpectedSessionCallbacks += source.unexpectedSessionCallbacks;
  for (let i = 0; i < source.finalTexts.length; i++) target.finalTexts.push(source.finalTexts[i]);
  for (let i = 0; i < source.errorCodes.length; i++) target.errorCodes.push(source.errorCodes[i]);
  for (let i = 0; i < source.callbackTrace.length; i++) target.callbackTrace.push(source.callbackTrace[i]);
  if (source.finals > 0) target.lastIsLast = source.lastIsLast;
  if (target.firstNonEmptyFinalHasScore === undefined &&
    source.firstNonEmptyFinalHasScore !== undefined) {
    target.firstNonEmptyFinalHasScore = source.firstNonEmptyFinalHasScore;
  }
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
  result.nonEmptyFinals = events.finalTexts.filter((text: string): boolean => text.length > 0).length;
  result.completes = events.completes;
  result.errors = events.errors;
  result.finalChars = events.finalChars;
  result.speakerScores = events.speakerScores;
  result.nonEmptySpeakerScores = events.nonEmptySpeakerScores;
  result.missingSpeakerScores = events.missingSpeakerScores;
  result.firstNonEmptyFinalHasScore = events.firstNonEmptyFinalHasScore === undefined ? -1 :
    (events.firstNonEmptyFinalHasScore ? 1 : 0);
  result.liveStreams = AmphionRuntime.activeOnlineStreamCount();
  result.elapsedMs = Date.now() - startedAt;
  if (events.firstNonEmptyResultAtMs >= 0) {
    result.firstNonEmptyResultMs = events.firstNonEmptyResultAtMs - startedAt;
    if (events.audioFeedStartedAtMs >= 0) {
      result.audioStartToFirstNonEmptyResultMs =
        events.firstNonEmptyResultAtMs - events.audioFeedStartedAtMs;
    }
    if (events.speechBeginAtMs >= 0 && events.speechBeginAtMs <= events.firstNonEmptyResultAtMs) {
      result.speechBeginToFirstNonEmptyResultMs =
        events.firstNonEmptyResultAtMs - events.speechBeginAtMs;
    }
  }
  if (events.audioFeedStartedAtMs >= 0 && events.speechBeginAtMs >= events.audioFeedStartedAtMs) {
    result.audioStartToSpeechBeginMs = events.speechBeginAtMs - events.audioFeedStartedAtMs;
  }
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
  const params = startParams(sessionId, options.mode, index);
  if (options.mode === 'paced') params.extraParams['enablePartialResult'] = true;
  engine.startListening(params);
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    const startDetail = events.errorMessages.length > 0 ?
      `start-${events.errorMessages[0]}` : 'start-timeout';
    return finishCycle(index, entry.id, events, startedAt, false, startDetail);
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
    const drained = await waitFor((): boolean =>
      AmphionRuntime.activeOnlineStreamCount() === 0, CANCEL_DRAIN_TIMEOUT_MS);
    // Native teardown may complete before an already-posted ArkTS callback is delivered. Keep the
    // callback snapshots open for a bounded stability window before asserting cancel quiescence.
    await sleep(CANCEL_CALLBACK_STABILITY_MS);
    const ok = drained && !engine.isBusy() && events.errors === 0 && lastFinalsBefore === 0 &&
      completesBefore === 0 && events.finals === finalsBefore && events.lastFinals === lastFinalsBefore &&
      events.completes === completesBefore;
    const detail = options.mode === 'cancel-full' ? 'cancelled-full' : 'cancelled';
    return finishCycle(index, entry.id, events, startedAt, ok,
      ok ? detail : (drained ? 'cancel-contract' : 'cancel-drain-timeout'));
  }

  const paceMs = options.mode === 'paced' ? options.paceMs : 0;
  const fed = await feedPcmFile(engine, sessionId, entry.path, 0, paceMs, undefined, 1,
    (): void => { events.audioFeedStartedAtMs = Date.now(); });
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
    const startDetail = events.errorMessages.length > 0 ?
      `start-${events.errorMessages[0]}` : 'start-timeout';
    return finishCycle(index, entry.id, events, startedAt, false, startDetail);
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
  let nonEmptyFinals = 0;
  for (let i = 0; i < events.finalTexts.length; i++) {
    if (events.finalTexts[i].length > 0) nonEmptyFinals += 1;
  }
  const scoreContract = scenario === 'short' ? events.speakerScores === 0 :
    events.speakerScores > 0 && events.nonEmptySpeakerScores === nonEmptyFinals;
  const utteranceContract = scenario !== 'multi-utterance' || nonEmptyFinals >= 2;
  const ok = completed && events.starts === 1 && events.finals > 0 && events.lastFinals === 1 &&
    lastFinalsBeforeFinish === 0 && events.completes === 1 && events.errors === 0 && scoreContract &&
    utteranceContract && !engine.isBusy();
  let detail = `voiceprint-${scenario}-${scenario === 'short' ? 'no-score' : 'scored'}`;
  if (!scoreContract) {
    detail = `voiceprint-score-contract-${scenario}-nonempty-${nonEmptyFinals}-scored-${events.nonEmptySpeakerScores}`;
  } else if (!utteranceContract) {
    detail = `voiceprint-multi-utterance-finals-${events.finals}`;
  } else if (lastFinalsBeforeFinish > 0) {
    detail = 'is-last-before-finish';
  }
  return finishCycle(index, entry.id, events, startedAt, ok, detail);
}

async function runTargetSpeakerEnhancementCycle(engine: SpeechRecognitionEngine,
  entry: CorpusEntry, index: number, voiceprintId: string,
  options: DeviceStressOptions): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  const sessionId = `target-speaker-enhancement-${index}`;
  engine.setListener(new StressListener(events, sessionId));
  const params = startParams(sessionId, 'target-speaker-enhancement', index);
  params.extraParams['enableSpeakerVad'] = true;
  params.extraParams['enableTargetSpeakerEnhancement'] = true;
  params.extraParams['voiceprintIds'] = [voiceprintId];
  engine.startListening(params);
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    const startDetail = events.errorMessages.length > 0 ?
      `start-${events.errorMessages[0]}` : 'start-timeout';
    return finishCycle(index, entry.id, events, startedAt, false, startDetail);
  }
  const fed = await feedPcmFile(engine, sessionId, entry.path, 0, options.paceMs);
  if (fed === 0) {
    engine.cancel(sessionId);
    return finishCycle(index, entry.id, events, startedAt, false, 'empty-pcm');
  }
  const lastFinalsBeforeFinish = events.lastFinals;
  engine.finish(sessionId);
  const completed = await waitFor((): boolean => events.completes === 1, COMPLETE_TIMEOUT_MS);
  const text = events.finalTexts.join('');
  const businessTextPassed = text.includes('上海') && !text.includes('你好');
  const ok = completed && events.starts === 1 && events.finals > 0 &&
    events.lastFinals === 1 && lastFinalsBeforeFinish === 0 && events.completes === 1 &&
    events.errors === 0 && events.targetSpeakerEnhancementResults === events.finals && businessTextPassed &&
    !engine.isBusy();
  let detail = ok ?
    `target-speaker-enhancement-applied-${events.targetSpeakerEnhancementResults}` :
    'target-speaker-enhancement-contract';
  if (lastFinalsBeforeFinish > 0) detail = 'is-last-before-finish';
  else if (events.targetSpeakerEnhancementResults !== events.finals) detail = 'enhancement-marker-missing';
  else if (!businessTextPassed) detail = 'target-text-contract';
  const result = finishCycle(index, entry.id, events, startedAt, ok, detail);
  result.voiceprintIdCount = 1;
  result.fedFrames = fed;
  result.lastFinalsBeforeFinish = lastFinalsBeforeFinish;
  return result;
}

async function runSpeakerVadTurnCycle(engine: SpeechRecognitionEngine,
  entry: CorpusEntry, index: number, voiceprintId: string,
  options: DeviceStressOptions): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  const sessionId = `speaker-vad-turn-${index}`;
  engine.setListener(new StressListener(events, sessionId));
  const params = startParams(sessionId, 'speaker-vad-turn', index);
  params.extraParams['enableSpeakerVad'] = true;
  params.extraParams['enablePartialResult'] = true;
  params.extraParams['voiceprintIds'] = [voiceprintId];
  if (options.speakerVadThreshold >= -1 && options.speakerVadThreshold <= 1) {
    params.extraParams['speakerVadThreshold'] = options.speakerVadThreshold;
  }
  engine.startListening(params);
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    const startDetail = events.errorMessages.length > 0 ?
      `start-${events.errorMessages[0]}` : 'start-timeout';
    return finishCycle(index, entry.id, events, startedAt, false, startDetail);
  }
  const fed = await feedPcmFile(engine, sessionId, entry.path, 0, options.paceMs, undefined, 1,
    (): void => { events.audioFeedStartedAtMs = Date.now(); });
  if (fed === 0) {
    engine.cancel(sessionId);
    return finishCycle(index, entry.id, events, startedAt, false, 'empty-pcm');
  }
  const lastFinalsBeforeFinish = events.lastFinals;
  const speechEndsBeforeFinish = events.speechEnds;
  engine.finish(sessionId);
  const completed = await waitFor((): boolean => events.completes === 1, COMPLETE_TIMEOUT_MS);
  const text = events.finalTexts.join('');
  const businessTextPassed = !options.enforceTargetSpeakerBusinessText ||
    (text.includes('上海') && !text.includes('你好'));
  const ok = completed && events.starts === 1 && events.finals > 0 && events.lastFinals === 1 &&
    lastFinalsBeforeFinish === 0 && events.completes === 1 && events.errors === 0 &&
    businessTextPassed && events.partials > 0 && speechEndsBeforeFinish > 0 && !engine.isBusy();
  let detail = ok ? 'speaker-vad-turn-clean' : 'speaker-vad-turn-contract';
  if (lastFinalsBeforeFinish > 0) detail = 'is-last-before-finish';
  else if (speechEndsBeforeFinish === 0) detail = 'speaker-vad-turn-missing-endpoint';
  else if (!businessTextPassed) detail = 'speaker-vad-turn-text-contract';
  if (events.errorMessages.length > 0) {
    detail = `speaker-vad-turn-error-${events.errorMessages[0]}`;
  }
  const result = finishCycle(index, entry.id, events, startedAt, ok, detail);
  result.voiceprintIdCount = 1;
  result.fedFrames = fed;
  result.lastFinalsBeforeFinish = lastFinalsBeforeFinish;
  result.speechEndsBeforeFinish = speechEndsBeforeFinish;
  return result;
}

function enableTargetSpeakerEnhancement(params: StartParams, voiceprintId: string): void {
  params.extraParams['enableSpeakerVad'] = true;
  params.extraParams['enableTargetSpeakerEnhancement'] = true;
  params.extraParams['voiceprintIds'] = [voiceprintId];
}

async function runTargetSpeakerEnhancementOnStartCycle(engine: SpeechRecognitionEngine,
  entry: CorpusEntry, index: number, voiceprintId: string): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  const actions: string[] = ['continue', 'finish', 'cancel'];
  const action = actions[index % actions.length];
  const bufferedFrameCount = 100;
  const bufferedFrames = readPcmFrames(entry.path, bufferedFrameCount);
  if (bufferedFrames.length !== bufferedFrameCount) {
    return finishCycle(index, entry.id, events, startedAt, false,
      `buffer-source-too-short-${bufferedFrames.length}-${bufferedFrameCount}`);
  }
  const sessionId = `target-speaker-enhancement-onstart-${action}-${index}`;
  const listener = new TargetSpeakerEnhancementOnStartListener(
    events, sessionId, engine, bufferedFrames, action
  );
  engine.setListener(listener);
  const params = startParams(sessionId, 'target-speaker-enhancement-onstart', index);
  enableTargetSpeakerEnhancement(params, voiceprintId);
  engine.startListening(params);
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, events, startedAt, false, 'start-timeout');
  }
  let fedFrames = listener.framesWrittenInStart;
  let lastFinalsBeforeFinish = listener.lastFinalsBeforeAction;
  if (action === 'continue') {
    const fed = await feedPcmFile(engine, sessionId, entry.path, 80, 0);
    if (fed === 0) {
      engine.cancel(sessionId);
      return finishCycle(index, entry.id, events, startedAt, false, 'empty-pcm');
    }
    fedFrames += fed;
    lastFinalsBeforeFinish = events.lastFinals;
    engine.finish(sessionId);
  }
  if (action === 'cancel') await sleep(500);
  else await waitFor((): boolean => events.completes === 1, COMPLETE_TIMEOUT_MS);

  const actionContract = action === 'continue' ? !listener.actionCalledInStart :
    listener.actionCalledInStart;
  const lifecycleContract = action === 'cancel' ?
    events.finals === 0 && events.completes === 0 :
    events.lastFinals === 1 && events.completes === 1 &&
      events.targetSpeakerEnhancementResults === events.finals;
  const ok = listener.framesWrittenInStart === bufferedFrameCount && actionContract &&
    events.starts === 1 && events.errors === 0 && lifecycleContract && !engine.isBusy();
  const result = finishCycle(index, entry.id, events, startedAt, ok,
    ok ? `target-speaker-enhancement-onstart-${action}` :
      `target-speaker-enhancement-onstart-${action}-contract`);
  result.voiceprintIdCount = 1;
  result.fedFrames = fedFrames;
  result.lastFinalsBeforeFinish = lastFinalsBeforeFinish;
  return result;
}

async function runTargetSpeakerEnhancementCancelCycle(engine: SpeechRecognitionEngine,
  entry: CorpusEntry, index: number, voiceprintId: string): Promise<CycleResult> {
  const startedAt = Date.now();
  const canceledEvents = new SessionEvents();
  const canceledSessionId = `target-speaker-enhancement-cancel-${index}`;
  engine.setListener(new StressListener(canceledEvents, canceledSessionId));
  const canceledParams = startParams(canceledSessionId, 'target-speaker-enhancement-cancel', index);
  enableTargetSpeakerEnhancement(canceledParams, voiceprintId);
  engine.startListening(canceledParams);
  if (!await waitFor((): boolean => canceledEvents.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, canceledEvents, startedAt, false, 'cancel-start-timeout');
  }
  const canceledFed = await feedPcmFile(engine, canceledSessionId, entry.path, 100, 0);
  engine.cancel(canceledSessionId);
  const canceledStableAtReturn = canceledEvents.finals === 0 && canceledEvents.completes === 0 &&
    canceledEvents.errors === 0 && !engine.isBusy();

  const recoveryEvents = new SessionEvents();
  const recoverySessionId = `target-speaker-enhancement-recovery-${index}`;
  engine.setListener(new StressListener(recoveryEvents, recoverySessionId));
  const recoveryParams = startParams(recoverySessionId, 'target-speaker-enhancement-cancel', index);
  enableTargetSpeakerEnhancement(recoveryParams, voiceprintId);
  engine.startListening(recoveryParams);
  if (!await waitFor((): boolean => recoveryEvents.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, recoveryEvents, startedAt, false, 'recovery-start-timeout');
  }
  const recoveryFed = await feedPcmFile(engine, recoverySessionId, entry.path, 0, 0);
  const lastFinalsBeforeFinish = recoveryEvents.lastFinals;
  engine.finish(recoverySessionId);
  const recovered = await waitFor((): boolean => recoveryEvents.completes === 1, COMPLETE_TIMEOUT_MS);
  await sleep(500);
  const recoveryText = recoveryEvents.finalTexts.join('');
  const ok = canceledFed === 100 && canceledStableAtReturn && recoveryFed > 0 && recovered &&
    recoveryEvents.starts === 1 && recoveryEvents.lastFinals === 1 && lastFinalsBeforeFinish === 0 &&
    recoveryEvents.completes === 1 && recoveryEvents.errors === 0 &&
    recoveryEvents.unexpectedSessionCallbacks === 0 &&
    recoveryEvents.targetSpeakerEnhancementResults === recoveryEvents.finals &&
    recoveryText.includes('上海') &&
    !recoveryText.includes('你好') && !engine.isBusy();
  let detail = ok ? 'target-speaker-enhancement-cancel-recovered' :
    'target-speaker-enhancement-cancel-contract';
  if (!canceledStableAtReturn) detail = 'callback-before-cancel-return';
  else if (recoveryEvents.unexpectedSessionCallbacks > 0) detail = 'late-canceled-session-callback';
  const result = finishCycle(index, entry.id, recoveryEvents, startedAt, ok, detail);
  result.voiceprintIdCount = 1;
  result.fedFrames = canceledFed + recoveryFed;
  result.lastFinalsBeforeFinish = lastFinalsBeforeFinish;
  return result;
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
  const nonEmptyFinalScoreContract = events.finalChars === 0 ||
    events.firstNonEmptyFinalHasScore === true;
  const ok = completed && events.starts === 1 && events.finals > 0 && events.speakerScores > 0 &&
    nonEmptyFinalScoreContract &&
    events.lastFinals === 1 && lastFinalsBeforeFinish === 0 && events.completes === 1 &&
    events.errors === 0 && !engine.isBusy();
  let detail = `voiceprint-vad-begin-${paced ? 'paced' : 'burst'}-${leadingSilence ? 'leading' : 'direct'}`;
  if (lastFinalsBeforeFinish > 0) detail = 'is-last-before-finish';
  else if (events.speakerScores === 0) detail = 'missing-speaker-score';
  else if (events.finalChars > 0 && events.firstNonEmptyFinalHasScore !== true) {
    detail = 'first-final-missing-speaker-score';
  }
  const result = finishCycle(index, entry.id, events, startedAt, ok, detail);
  result.requestedVadBeginMs = 1000;
  result.confirmationGraceMs = 1500;
  result.voiceprintIdCount = 1;
  result.fedFrames = fed;
  result.lastFinalsBeforeFinish = lastFinalsBeforeFinish;
  return result;
}

async function runVoiceprintFallbackCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry, index: number,
  voiceprintId: string): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  const sessionId = `voiceprint-fallback-${index}`;
  engine.setListener(new StressListener(events, sessionId));
  const params = startParams(sessionId, 'voiceprint-fallback', index);
  // Isolate sample selection from automatic-last behavior; max duration has its own dedicated mode.
  params.extraParams['maxAudioDuration'] = 28800000;
  params.extraParams['vadBegin'] = 5000;
  params.extraParams['vadEnd'] = 1600;
  params.extraParams['enablePartialResult'] = true;
  params.extraParams['enableVoiceprintVerification'] = true;
  params.extraParams['enableSpeakerVad'] = false;
  params.extraParams['voiceprintIds'] = [voiceprintId];
  engine.startListening(params);
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, events, startedAt, false, 'start-timeout');
  }
  const fed = await feedPcmFile(engine, sessionId, entry.path, 300, FRAME_DURATION_MS);
  if (fed === 0) {
    engine.cancel(sessionId);
    return finishCycle(index, entry.id, events, startedAt, false, 'empty-pcm');
  }
  let silenceFed = 0;
  while (events.finals === 0 && silenceFed < 320) {
    engine.writeAudio(sessionId, new ArrayBuffer(FRAME_BYTES));
    silenceFed += 1;
    await sleep(FRAME_DURATION_MS);
  }
  await waitFor((): boolean => events.finals > 0, 5000);
  const endpointFinals = events.finals;
  let endpointNonEmptyFinals = 0;
  for (let i = 0; i < events.finalTexts.length; i++) {
    if (events.finalTexts[i].length > 0) endpointNonEmptyFinals += 1;
  }
  const endpointNonEmptySpeakerScores = events.nonEmptySpeakerScores;
  const lastFinalsBeforeFinish = events.lastFinals;
  engine.finish(sessionId);
  const completed = await waitFor((): boolean => events.completes === 1, COMPLETE_TIMEOUT_MS);
  const endpointScoreContract = endpointNonEmptyFinals > 0 &&
    endpointNonEmptySpeakerScores === endpointNonEmptyFinals;
  const ok = completed && events.starts === 1 && endpointScoreContract && events.speakerScores > 0 &&
    events.lastFinals === 1 && lastFinalsBeforeFinish === 0 &&
    events.completes === 1 && events.errors === 0 && !engine.isBusy();
  let detail = index === 0 ? 'voiceprint-fallback-cold-scored' : 'voiceprint-fallback-warm-scored';
  if (endpointFinals === 0) detail = 'missing-endpoint-final';
  else if (!endpointScoreContract) detail = 'endpoint-final-missing-speaker-score';
  else if (lastFinalsBeforeFinish > 0) detail = 'is-last-before-finish';
  const result = finishCycle(index, entry.id, events, startedAt, ok, detail);
  result.requestedVadBeginMs = 5000;
  result.confirmationGraceMs = 1500;
  result.requestedMaxAudioDurationMs = 28800000;
  result.effectiveMaxAudioDurationMs = 28800000;
  result.voiceprintIdCount = 1;
  result.fedFrames = fed + silenceFed;
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
    // writeAudio snapshots and dispatches asynchronously. Pace this deadline probe so fedFrames
    // continues to represent processed PCM time instead of the caller-side queue depth.
    await sleep(IDLE_FRAME_PACE_MS);
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

async function runSpeakerVadOnStartCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry, index: number,
  voiceprintId: string): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  const paced = index % 2 === 1;
  const leadingSilence = index % 4 >= 2;
  const sessionId = `speaker-vad-onstart-${index}`;
  const listener = new OnStartSpeakerVadListener(events, sessionId, engine);
  engine.setListener(listener);
  const params = startParams(sessionId, 'speaker-vad-onstart', index);
  params.extraParams['vadBegin'] = 1000;
  params.extraParams['enableVoiceprintVerification'] = false;
  params.extraParams['enableSpeakerVad'] = false;
  params.extraParams['voiceprintIds'] = [voiceprintId];
  engine.startListening(params);
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, events, startedAt, false, 'start-timeout');
  }

  const lastFinalsAfterStart = events.lastFinals;
  if (leadingSilence && engine.isBusy()) feedSilence(engine, sessionId, 40);
  const fed = engine.isBusy() ? await feedPcmFile(
    engine, sessionId, entry.path, VOICEPRINT_LONG_FRAMES, paced ? 20 : 0
  ) : 0;
  const lastFinalsBeforeFinish = events.lastFinals;
  if (engine.isBusy()) engine.finish(sessionId);
  const completed = await waitFor((): boolean => events.completes === 1, COMPLETE_TIMEOUT_MS);

  const primaryContract = completed && events.starts === 1 && events.finals > 0 &&
    events.nonEmptySpeakerScores > 0 &&
    events.lastFinals === 1 && lastFinalsAfterStart === 0 && lastFinalsBeforeFinish === 0 &&
    events.completes === 1 && events.errors === 0 && listener.enableAttempted &&
    listener.enableReturned && listener.enableThrowMessage.length === 0 &&
    listener.speakerVadChangedEvents === 1 && !engine.isBusy();

  const recoveryEvents = new SessionEvents();
  const recoveryId = `speaker-vad-recovery-${index}`;
  let recovered = false;
  if (primaryContract) {
    engine.setListener(new StressListener(recoveryEvents, recoveryId));
    engine.startListening(startParams(recoveryId, 'speaker-vad-onstart', index));
    const recoveryStarted = await waitFor((): boolean => recoveryEvents.starts === 1, START_TIMEOUT_MS);
    if (recoveryStarted && engine.isBusy()) engine.cancel(recoveryId);
    await sleep(100);
    recovered = recoveryStarted && recoveryEvents.starts === 1 && recoveryEvents.finals === 0 &&
      recoveryEvents.completes === 0 && recoveryEvents.errors === 0 && !engine.isBusy();
  }
  mergeSessionEvents(events, recoveryEvents);

  const ok = primaryContract && recovered;
  let detail = `speaker-vad-onstart-${paced ? 'paced' : 'burst'}-${leadingSilence ? 'leading' : 'direct'}`;
  if (listener.enableThrowMessage.length > 0) detail = `speaker-vad-enable-throw-${listener.enableThrowMessage}`;
  else if (!listener.enableReturned || listener.speakerVadChangedEvents !== 1) {
    detail = `speaker-vad-enable-contract-${listener.speakerVadChangedEvents}`;
  } else if (lastFinalsAfterStart > 0 || lastFinalsBeforeFinish > 0) detail = 'is-last-before-finish';
  else if (events.nonEmptySpeakerScores === 0) detail = 'speaker-vad-missing-nonempty-speaker-score';
  else if (!primaryContract) detail = 'speaker-vad-onstart-session-contract';
  else if (!recovered) detail = 'speaker-vad-onstart-recovery-contract';
  const result = finishCycle(index, entry.id, events, startedAt, ok, detail);
  result.requestedVadBeginMs = 1000;
  result.confirmationGraceMs = 1500;
  result.voiceprintIdCount = 1;
  result.fedFrames = fed;
  result.lastFinalsBeforeFinish = lastFinalsBeforeFinish;
  return result;
}

async function runCallbackApiReentrantCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry,
  index: number): Promise<CycleResult> {
  const startedAt = Date.now();
  const triggers: string[] = ['speech-begin', 'speech-end', 'result'];
  const trigger = triggers[index % triggers.length];
  const sessionId = `callback-api-${trigger}-${index}`;
  const listener = new CallbackApiReentrantListener(engine, sessionId, trigger);
  const events = listener.events;
  engine.setListener(listener);
  const params = startParams(sessionId, 'callback-api-reentrant', index);
  params.extraParams['vadEnd'] = 500;
  engine.startListening(params);
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, events, startedAt, false, 'start-timeout');
  }

  const fed = await feedPcmFile(engine, sessionId, entry.path, 150, 0,
    (): boolean => listener.reentryAttempted || events.completes > 0);
  let silenceFed = 0;
  while (!listener.reentryAttempted && events.completes === 0 && silenceFed < 100) {
    engine.writeAudio(sessionId, new ArrayBuffer(FRAME_BYTES));
    silenceFed += 1;
    if (silenceFed % 10 === 0) await sleep(1);
  }
  if (!listener.reentryAttempted) {
    await waitFor((): boolean => listener.reentryAttempted, COMPLETE_TIMEOUT_MS);
  }
  const completed = listener.reentryAttempted &&
    await waitFor((): boolean => events.completes === 1, COMPLETE_TIMEOUT_MS);
  if (!completed && engine.isBusy()) engine.cancel(sessionId);

  const finalsAtTerminal = events.finals;
  const beginsAtTerminal = events.speechBegins;
  const endsAtTerminal = events.speechEnds;
  const completesAtTerminal = events.completes;
  await sleep(100);
  const callbacksStable = events.finals === finalsAtTerminal &&
    events.speechBegins === beginsAtTerminal && events.speechEnds === endsAtTerminal &&
    events.completes === completesAtTerminal;
  let eventContract = events.speechBegins <= 1 && events.speechEnds <= 1;
  if (trigger === 'speech-begin') eventContract = events.speechBegins === 1 && events.speechEnds <= 1;
  else if (trigger === 'speech-end') eventContract = events.speechBegins === 1 && events.speechEnds === 1;
  let finalContract = events.lastFinals === 1 && events.finals >= 1;
  if (trigger === 'speech-end') {
    const terminalText = events.finalTexts.length > 0 ? events.finalTexts[events.finalTexts.length - 1] : '';
    finalContract = finalContract && terminalText.length > 0;
  }
  const expectedWriteCalls = trigger === 'speech-end' ? 0 : 1;
  const ok = completed && listener.reentryAttempted && listener.writeCalls === expectedWriteCalls &&
    listener.finishCalls === 1 && listener.reentryThrowMessage.length === 0 && events.starts === 1 &&
    eventContract && finalContract && events.completes === 1 && events.errors === 0 &&
    events.unexpectedSessionCallbacks === 0 && listener.terminalOrderOk(sessionId) &&
    callbacksStable && !engine.isBusy();
  let detail = `callback-api-reentrant-${trigger}`;
  if (!listener.reentryAttempted) detail = `${trigger}-callback-not-observed-${fed}-${silenceFed}`;
  else if (listener.reentryThrowMessage.length > 0) detail = `callback-api-throw-${listener.reentryThrowMessage}`;
  else if (listener.writeCalls !== expectedWriteCalls || listener.finishCalls !== 1) detail = 'callback-api-call-count';
  else if (!eventContract) detail = `callback-event-count-${events.speechBegins}-${events.speechEnds}`;
  else if (!finalContract) detail = `callback-final-count-${events.finals}-${events.lastFinals}`;
  else if (!callbacksStable) detail = 'callback-count-changed-after-terminal';
  else if (!listener.terminalOrderOk(sessionId)) detail = 'callback-terminal-order';
  const result = finishCycle(index, entry.id, events, startedAt, ok, detail);
  result.fedFrames = fed + silenceFed;
  return result;
}

// Reproduces the legacy PTT host sequence exactly: finish, observe the still-draining busy state,
// then immediately release the engine. An accepted finish must retain ownership until its unique
// last/complete callbacks have been delivered.
async function runFinishShutdownCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry,
  index: number): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  const sessionId = `finish-shutdown-${index}`;
  engine.setListener(new StressListener(events, sessionId));
  engine.startListening(startParams(sessionId, 'finish-shutdown', index));
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, events, startedAt, false, 'start-timeout');
  }

  const fed = await feedPcmFile(engine, sessionId, entry.path, 150, 0);
  if (fed === 0) {
    engine.cancel(sessionId);
    return finishCycle(index, entry.id, events, startedAt, false, 'empty-pcm');
  }
  const lastFinalsBeforeFinish = events.lastFinals;
  engine.finish(sessionId);
  const busyAfterFinish = engine.isBusy();
  engine.shutdown();
  const completed = await waitFor((): boolean => events.completes === 1, COMPLETE_TIMEOUT_MS);
  const ok = busyAfterFinish && completed && lastFinalsBeforeFinish === 0 && events.starts === 1 &&
    events.lastFinals === 1 && events.completes === 1 && events.errors === 0 &&
    events.finals > 0 && terminalCallbackOrderOk(events, sessionId) && !engine.isBusy();
  let detail = 'finish-shutdown-drained';
  if (!busyAfterFinish) detail = 'finish-returned-idle-before-complete';
  else if (!completed) detail = 'shutdown-dropped-complete';
  else if (events.lastFinals !== 1) detail = `shutdown-last-count-${events.lastFinals}`;
  else if (!terminalCallbackOrderOk(events, sessionId)) detail = 'shutdown-terminal-order';
  else if (events.errors !== 0) detail = `shutdown-error-count-${events.errors}`;
  const result = finishCycle(index, entry.id, events, startedAt, ok, detail);
  result.fedFrames = fed;
  result.lastFinalsBeforeFinish = lastFinalsBeforeFinish;
  return result;
}

// Regression reproduction of the customer sequence: finish a session with queued async
// decode work, release the engine, then accept a refreshed license before the terminal callback.
// A safe SDK must not let Runtime invalidation free handles still owned by the decode worker.
async function runFinishShutdownRelicenseCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry,
  index: number, licensePath: string): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  const sessionId = `finish-shutdown-relicense-${index}`;
  engine.setListener(new StressListener(events, sessionId));
  engine.startListening(startParams(sessionId, 'finish-shutdown-relicense', index));
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, events, startedAt, false, 'start-timeout');
  }

  // Burst the complete customer clip so finish is accepted while decode work is still queued.
  const fed = await feedPcmFile(engine, sessionId, entry.path, 1000000, 0);
  if (fed === 0) {
    engine.cancel(sessionId);
    return finishCycle(index, entry.id, events, startedAt, false, 'empty-pcm');
  }
  const lastFinalsBeforeFinish = events.lastFinals;
  engine.finish(sessionId);
  const busyAfterFinish = engine.isBusy();
  engine.shutdown();

  const license = await activateLicense(licensePath);
  const runtimeError = license.errorCode === 0 ? await prepareRuntime() : license.errorCode;
  const completed = await waitFor((): boolean => events.completes === 1, COMPLETE_TIMEOUT_MS);
  const recoveryEvents = new SessionEvents();
  const recoverySessionId = `finish-shutdown-relicense-recovery-${index}`;
  let recoveryStarted = false;
  let recoveryFed = 0;
  let recoveryLastBeforeFinish = -1;
  let recoveryCompleted = false;
  let recoveryEngine: SpeechRecognitionEngine | undefined;
  if (runtimeError === 0) {
    try {
      recoveryEngine = createEngine();
      recoveryEngine.setListener(new StressListener(recoveryEvents, recoverySessionId));
      recoveryEngine.startListening(startParams(recoverySessionId, 'finish-shutdown-relicense', index));
      recoveryStarted = await waitFor((): boolean => recoveryEvents.starts === 1, START_TIMEOUT_MS);
      if (recoveryStarted) {
        recoveryFed = await feedPcmFile(recoveryEngine, recoverySessionId, entry.path, 150, 0);
        recoveryLastBeforeFinish = recoveryEvents.lastFinals;
        recoveryEngine.finish(recoverySessionId);
        recoveryCompleted = await waitFor(
          (): boolean => recoveryEvents.completes === 1, COMPLETE_TIMEOUT_MS);
      }
    } catch (_) {
      recoveryEvents.errors += 1;
    } finally {
      recoveryEngine?.shutdown();
    }
  }
  const recoveryOk = recoveryStarted && recoveryFed > 0 && recoveryLastBeforeFinish === 0 &&
    recoveryCompleted && recoveryEvents.starts === 1 && recoveryEvents.lastFinals === 1 &&
    recoveryEvents.completes === 1 && recoveryEvents.errors === 0 &&
    recoveryEvents.unexpectedSessionCallbacks === 0 &&
    terminalCallbackOrderOk(recoveryEvents, recoverySessionId);
  const ok = busyAfterFinish && license.errorCode === 0 && runtimeError === 0 && completed &&
    lastFinalsBeforeFinish === 0 && events.starts === 1 && events.lastFinals === 1 &&
    events.completes === 1 && events.errors === 0 && events.finals > 0 &&
    terminalCallbackOrderOk(events, sessionId) && recoveryOk;
  let detail = 'finish-shutdown-relicense-drained';
  if (!busyAfterFinish) detail = 'finish-returned-idle-before-complete';
  else if (license.errorCode !== 0) detail = `relicense-${license.errorCode}`;
  else if (runtimeError !== 0) detail = `runtime-${runtimeError}`;
  else if (!completed) detail = 'relicense-dropped-complete';
  else if (events.lastFinals !== 1) detail = `relicense-last-count-${events.lastFinals}`;
  else if (!terminalCallbackOrderOk(events, sessionId)) detail = 'relicense-terminal-order';
  else if (events.errors !== 0) detail = `relicense-error-count-${events.errors}`;
  else if (!recoveryOk) detail = 'relicense-recovery-session';
  const result = finishCycle(index, entry.id, events, startedAt, ok, detail);
  result.fedFrames = fed;
  result.lastFinalsBeforeFinish = lastFinalsBeforeFinish;
  result.recoveryStarts = recoveryEvents.starts;
  result.recoveryLastFinals = recoveryEvents.lastFinals;
  result.recoveryCompletes = recoveryEvents.completes;
  result.recoveryErrors = recoveryEvents.errors;
  result.recoveryTerminalOrder = terminalCallbackOrderOk(recoveryEvents, recoverySessionId) ? 1 : 0;
  result.recoveryUnexpectedCallbacks = recoveryEvents.unexpectedSessionCallbacks;
  return result;
}

async function runMaxDurationCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry,
  index: number): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  const sessionId = `max-${index}`;
  engine.setListener(new StressListener(events, sessionId));
  const params = startParams(sessionId, 'max-duration', index);
  const paced = index % 2 === 1;
  params.extraParams['maxAudioDuration'] = MAX_DURATION_TEST_MS;
  engine.startListening(params);
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, events, startedAt, false, 'start-timeout');
  }

  let fedFrames = 0;
  while (events.completes === 0 && fedFrames < MAX_DURATION_TEST_FRAMES) {
    const fed = await feedPcmFile(engine, sessionId, entry.path,
      MAX_DURATION_TEST_FRAMES - fedFrames, paced ? FRAME_DURATION_MS : 0,
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
    events.lastIsLast && !engine.isBusy() && fedFrames === MAX_DURATION_TEST_FRAMES &&
    (!paced || Date.now() - startedAt >= MAX_DURATION_TEST_MS - 1000);
  const result = finishCycle(index, entry.id, events, startedAt, ok,
    ok ? `auto-finished-${paced ? 'paced' : 'burst'}` : 'max-duration-contract');
  result.requestedMaxAudioDurationMs = MAX_DURATION_TEST_MS;
  result.effectiveMaxAudioDurationMs = MAX_DURATION_TEST_MS;
  result.fedFrames = fedFrames;
  return result;
}

async function runNumericEdgeCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry,
  index: number): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  const sessionId = `numeric-${index}`;
  engine.setListener(new StressListener(events, sessionId));
  const params = startParams(sessionId, 'numeric-edge', index);
  if (index % 2 === 0) {
    params.extraParams = {};
    params.extraParams['enablePartialResult'] = false;
  } else {
    params.extraParams['maxAudioDuration'] = Number.NaN;
  }
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
  const autoCompleted = await waitFor((): boolean => events.completes > 0, 1000);
  const activeBeforeFinish = !autoCompleted && events.lastFinals === 0 && events.completes === 0 &&
    events.errors === 0 && engine.isBusy();
  if (activeBeforeFinish) engine.finish(sessionId);
  const completed = await waitFor((): boolean => events.completes === 1, COMPLETE_TIMEOUT_MS);
  if (!completed && engine.isBusy()) engine.cancel(sessionId);

  const ok = activeBeforeFinish && completed && events.completes === 1 && events.lastFinals === 1 &&
    events.errors === 0 && events.lastIsLast && !engine.isBusy() && fedFrames >= 1000;
  const variant = index % 2 === 0 ? 'omitted' : 'nan';
  const detail = ok ? `${variant}-max-duration-disabled` : `${variant}-max-duration-contract-fed-${fedFrames}`;
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

async function runStartWriteCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry,
  index: number): Promise<CycleResult> {
  const startedAt = Date.now();
  const events = new SessionEvents();
  const bufferedFrameCount = index % 2 === 0 ? 32 : 88;
  const finishInStart = index % 4 >= 2;
  const bufferedFrames = readPcmFrames(entry.path, bufferedFrameCount);
  if (bufferedFrames.length !== bufferedFrameCount) {
    return finishCycle(index, entry.id, events, startedAt, false,
      `buffer-source-too-short-${bufferedFrames.length}-${bufferedFrameCount}`);
  }
  const listener = new StartWriteListener(events, engine, bufferedFrames, finishInStart);
  engine.setListener(listener);
  const sessionId = `start-write-${index}`;
  engine.startListening(startParams(sessionId, 'start-write', index));
  if (!await waitFor((): boolean => events.starts === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, events, startedAt, false, 'start-timeout');
  }

  if (!finishInStart) {
    const fed = await feedPcmFile(engine, sessionId, entry.path, 80, 0);
    if (fed === 0) {
      engine.cancel(sessionId);
      return finishCycle(index, entry.id, events, startedAt, false, 'empty-pcm');
    }
    engine.finish(sessionId);
  }
  const completed = await waitFor((): boolean => events.completes === 1, COMPLETE_TIMEOUT_MS);
  const notListening = errorCount(events, DingqiaoErrorCode.NOT_LISTENING);
  const finishFailed = errorCount(events, DingqiaoErrorCode.FINISH_FAILED);
  const writeLatencyOk = listener.maxWriteCallMs <= 100 && listener.writeBatchElapsedMs <= 200;
  const ok = listener.framesWrittenInStart === bufferedFrameCount && completed && events.starts === 1 &&
    listener.finishCalledInStart === finishInStart && events.completes === 1 && events.lastFinals === 1 &&
    events.errors === 0 && !engine.isBusy() && writeLatencyOk;
  let detail = ok ?
    `onstart-write-${bufferedFrameCount}-frames-${finishInStart ? 'finish' : 'continue'}` +
      `-batch-${listener.writeBatchElapsedMs}ms-max-${listener.maxWriteCallMs}ms` :
    'onstart-write-contract';
  if (notListening > 0) detail = 'onstart-write-not-listening';
  if (finishFailed > 0) detail = 'onstart-finish-failed';
  if (!writeLatencyOk) {
    detail = `onstart-write-blocked-batch-${listener.writeBatchElapsedMs}ms-max-${listener.maxWriteCallMs}ms`;
  }
  return finishCycle(index, entry.id, events, startedAt, ok, detail);
}

async function runEndpointReentrantCycle(engine: SpeechRecognitionEngine, entry: CorpusEntry,
  index: number): Promise<CycleResult> {
  const startedAt = Date.now();
  const oldSessionId = `endpoint-old-${index}`;
  const newSessionId = `endpoint-new-${index}`;
  const switchOnLast = index % 2 === 1;
  const listener = new EndpointReentrantListener(engine, oldSessionId, newSessionId, switchOnLast);
  engine.setListener(listener);
  engine.startListening(startParams(oldSessionId, 'endpoint-reentrant', index));
  if (!await waitFor((): boolean => listener.count(oldSessionId, 'start') === 1, START_TIMEOUT_MS)) {
    return finishCycle(index, entry.id, listener.events, startedAt, false, 'old-start-timeout');
  }

  let oldFed = 0;
  let silenceFed = 0;
  if (switchOnLast) {
    oldFed = await feedPcmFile(engine, oldSessionId, entry.path, 150, 0);
    if (oldFed > 0 && engine.isBusy()) engine.finish(oldSessionId);
  } else {
    oldFed = await feedPcmFile(engine, oldSessionId, entry.path, 300, 0,
      (): boolean => listener.switchAttempted);
    while (!listener.switchAttempted && silenceFed < 100) {
      engine.writeAudio(oldSessionId, new ArrayBuffer(FRAME_BYTES));
      silenceFed += 1;
      if (silenceFed % 10 === 0) await sleep(1);
    }
  }
  const newStarted = await waitFor((): boolean => listener.count(newSessionId, 'start') === 1,
    START_TIMEOUT_MS);
  // Old Core processing resumes only after onEvent returns. Give deferred native callbacks a chance
  // to prove they cannot be attributed to the newly published session.
  await sleep(100);
  const oldStableBeforeNewAudio = listener.sessionTrace(oldSessionId) === listener.oldTraceAtSwitch;
  const oldSwitchContract = listener.oldCompletesAtSwitch === 0 &&
    (!switchOnLast || listener.oldLastAtSwitch === 1);
  const cleanBeforeNewAudio = !listener.newCallbackBeforeAudio &&
    listener.sessionTrace(newSessionId) === 'start';

  let newFed = 0;
  if (newStarted && engine.isBusy()) {
    listener.newAudioStarted = true;
    newFed = await feedPcmFile(engine, newSessionId, entry.path, 150, 0);
    if (newFed > 0 && engine.isBusy()) engine.finish(newSessionId);
  }
  const newCompleted = await waitFor((): boolean => listener.count(newSessionId, 'complete') === 1,
    COMPLETE_TIMEOUT_MS);
  if (engine.isBusy()) engine.cancel(newSessionId);
  await sleep(100);

  const oldStableAfterNewSession = listener.sessionTrace(oldSessionId) === listener.oldTraceAtSwitch;
  const oldCallbacksStable = oldStableBeforeNewAudio && oldStableAfterNewSession;
  const newContract = newStarted && newFed > 0 && newCompleted &&
    listener.lastCount(newSessionId) === 1 && listener.count(newSessionId, 'complete') === 1 &&
    listener.terminalOrderOk(newSessionId);
  const ok = oldFed > 0 && listener.switchAttempted && listener.idleAfterCancel &&
    listener.startThrowMessage.length === 0 && oldCallbacksStable && oldSwitchContract && cleanBeforeNewAudio &&
    newContract && listener.events.errors === 0 && !engine.isBusy();
  const variant = switchOnLast ? 'last-result' : 'speech-end';
  let detail = `endpoint-reentrant-${variant}`;
  if (!listener.switchAttempted) detail = `${variant}-not-observed-${oldFed}-${silenceFed}`;
  else if (!listener.idleAfterCancel) detail = 'cancel-did-not-publish-idle';
  else if (listener.startThrowMessage.length > 0) detail = `new-start-throw-${listener.startThrowMessage}`;
  else if (!oldStableBeforeNewAudio) detail = 'old-callback-before-new-audio';
  else if (!oldStableAfterNewSession) detail = 'old-callback-during-new-session';
  else if (!oldSwitchContract) detail = `old-${variant}-contract`;
  else if (!cleanBeforeNewAudio) detail = 'callback-attributed-to-new-session-before-audio';
  else if (!newContract) detail = 'new-session-contract';
  const result = finishCycle(index, entry.id, listener.events, startedAt, ok, detail);
  result.fedFrames = oldFed + silenceFed + newFed;
  return result;
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
  const stressVoiceprintSamplePaths: string[] = [];
  let fatal = '';
  logLine(`BEGIN|runId=${options.runId}|mode=${options.mode}|cycles=${options.cycles}`);

  try {
    if (options.manifestPath.length === 0 || options.resultPath.length === 0) {
      throw new Error('manifestPath and resultPath are required');
    }
    entries = readManifest(options.manifestPath);
    const workPath = `${context.filesDir}/amphion_asr_work`;
    SpeechRecognizeSdk.setWorkPath(workPath);
    const license = await activateLicense(prepareLicense(context, workPath));
    if (license.errorCode !== 0) throw new Error(`license-${license.errorCode}`);
    const runtimeError = await prepareRuntime();
    if (runtimeError !== 0) throw new Error(`runtime-${runtimeError}`);

    if (options.mode === 'voiceprint' || options.mode === 'voiceprint-fallback' ||
      options.mode === 'voiceprint-vad-begin' ||
      options.mode === 'voiceprint-vad-begin-idle' || options.mode === 'speaker-vad-onstart' ||
      options.mode === 'speaker-vad-turn' ||
      options.mode === 'target-speaker-enhancement' ||
      options.mode === 'target-speaker-enhancement-onstart' ||
      options.mode === 'target-speaker-enhancement-cancel') {
      if ((options.mode === 'voiceprint' || options.mode === 'voiceprint-fallback') &&
        entries.length < 2) {
        throw new Error('voiceprint-stress-requires-two-corpus-sources');
      }
      const requiresSeparateCase = options.mode === 'speaker-vad-turn' ||
        options.mode === 'target-speaker-enhancement' ||
        options.mode === 'target-speaker-enhancement-onstart' ||
        options.mode === 'target-speaker-enhancement-cancel';
      if (options.enrollmentCount < 1 || options.enrollmentCount > entries.length ||
        (requiresSeparateCase && options.enrollmentCount === entries.length)) {
        throw new Error('invalid-stress-enrollment-count');
      }
      stressVoiceprintId = prepareStressVoiceprint(
        workPath, entries.slice(0, options.enrollmentCount));
      for (let i = 0; i < options.enrollmentCount; i++) {
        stressVoiceprintSamplePaths.push(`${workPath}/stress-voiceprint-enroll-${i}.wav`);
      }
      if (options.mode === 'voiceprint-fallback') SpeechRecognizeSdk.unloadModel();
    }

    const recreateEachCycle = options.mode === 'recreate' || options.mode === 'start-write-reload' ||
      options.mode === 'finish-shutdown' || options.mode === 'finish-shutdown-relicense';
    if (!recreateEachCycle) engine = createEngine();
    for (let i = 0; i < options.cycles; i++) {
      let entry = entries[i % entries.length];
      if (options.mode === 'voiceprint' &&
        VOICEPRINT_SCENARIOS[i % VOICEPRINT_SCENARIOS.length] === 'alternate-source') {
        entry = entries[1];
      } else if (options.mode === 'voiceprint-fallback') {
        entry = entries[1];
      } else if (options.mode === 'speaker-vad-turn' ||
        options.mode === 'target-speaker-enhancement' ||
        options.mode === 'target-speaker-enhancement-onstart' ||
        options.mode === 'target-speaker-enhancement-cancel') {
        entry = entries[options.enrollmentCount +
          (i % (entries.length - options.enrollmentCount))];
      }
      if (recreateEachCycle) engine = createEngine();
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
      } else if (options.mode === 'start-write' || options.mode === 'start-write-reload') {
        result = await runStartWriteCycle(engine, entry, i);
      } else if (options.mode === 'speaker-vad-onstart') {
        result = await runSpeakerVadOnStartCycle(engine, entry, i, stressVoiceprintId);
      } else if (options.mode === 'speaker-vad-turn') {
        result = await runSpeakerVadTurnCycle(engine, entry, i, stressVoiceprintId, options);
      } else if (options.mode === 'callback-api-reentrant') {
        result = await runCallbackApiReentrantCycle(engine, entry, i);
      } else if (options.mode === 'endpoint-reentrant') {
        result = await runEndpointReentrantCycle(engine, entry, i);
      } else if (options.mode === 'finish-shutdown') {
        result = await runFinishShutdownCycle(engine, entry, i);
      } else if (options.mode === 'finish-shutdown-relicense') {
        result = await runFinishShutdownRelicenseCycle(
          engine, entry, i, `${workPath}/stress-amphion-license.lic`);
      } else if (options.mode === 'user-sequence') {
        result = await runUserSequenceCycle(engine, entry, i);
      } else if (options.mode === 'vad-begin-silence') {
        result = await runVadBeginSilenceCycle(engine, entry, i);
      } else if (options.mode === 'voiceprint') {
        result = await runVoiceprintCycle(engine, entry, i, stressVoiceprintId);
      } else if (options.mode === 'voiceprint-fallback') {
        result = await runVoiceprintFallbackCycle(engine, entry, i, stressVoiceprintId);
      } else if (options.mode === 'voiceprint-vad-begin') {
        result = await runVoiceprintVadBeginCycle(engine, entry, i, stressVoiceprintId);
      } else if (options.mode === 'voiceprint-vad-begin-idle') {
        result = await runVoiceprintVadBeginIdleCycle(engine, entry, i, stressVoiceprintId);
      } else if (options.mode === 'target-speaker-enhancement') {
        result = await runTargetSpeakerEnhancementCycle(engine, entry, i, stressVoiceprintId, options);
      } else if (options.mode === 'target-speaker-enhancement-onstart') {
        result = await runTargetSpeakerEnhancementOnStartCycle(engine, entry, i, stressVoiceprintId);
      } else if (options.mode === 'target-speaker-enhancement-cancel') {
        result = await runTargetSpeakerEnhancementCancelCycle(engine, entry, i, stressVoiceprintId);
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
      } else if (options.mode === 'start-write-reload') {
        engine.shutdown();
        engine = undefined;
        SpeechRecognizeSdk.unloadModel();
      } else if (options.mode === 'finish-shutdown' || options.mode === 'finish-shutdown-relicense') {
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
    for (let i = 0; i < stressVoiceprintSamplePaths.length; i++) {
      try {
        if (fs.accessSync(stressVoiceprintSamplePaths[i])) fs.unlinkSync(stressVoiceprintSamplePaths[i]);
      } catch (_e) {}
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
