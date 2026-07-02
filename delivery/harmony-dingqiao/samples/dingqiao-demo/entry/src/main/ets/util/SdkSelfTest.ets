import hilog from '@ohos.hilog';
import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import {
  SpeechRecognizeSdk,
  CreateEngineParams,
  StartParams,
  AudioInfo,
  VoiceprintRegisterParams,
  VoiceprintRegisterResult,
  LicenseActivationCallback,
  LicenseActivationResult,
  CreateEngineCallback,
  RecognitionListener,
  SpeechRecognitionResult,
  SpeechRecognitionEngine,
  LicenseInfo,
  DingqiaoErrorCode
} from 'amphion_dingqiao';

const TAG: string = 'SdkSelfTest';
const DOMAIN: number = 0x0000;

// Collects PASS/FAIL for every public API + callback and logs each line so a host-side hilog grep can
// build the coverage matrix. This exercises the CONTRACT (callables, callbacks, error codes, lifecycle)
// with synthetic PCM; recognition accuracy is verified separately with real mic audio.
class Report {
  private passCount: number = 0;
  private failCount: number = 0;

  check(name: string, ok: boolean, detail: string): void {
    if (ok) {
      this.passCount += 1;
      hilog.info(DOMAIN, TAG, 'PASS | %{public}s | %{public}s', name, detail);
    } else {
      this.failCount += 1;
      hilog.error(DOMAIN, TAG, 'FAIL | %{public}s | %{public}s', name, detail);
    }
  }

  summary(): void {
    hilog.info(DOMAIN, TAG, 'SUMMARY pass=%{public}d fail=%{public}d', this.passCount, this.failCount);
  }
}

class EventLog {
  starts: number = 0;
  events: number = 0;
  results: number = 0;
  finals: number = 0;
  completes: number = 0;
  errors: number = 0;
  lastErrorCode: number = 0;
  lastText: string = '';
}

class TestListener implements RecognitionListener {
  private log: EventLog;
  constructor(log: EventLog) { this.log = log; }
  onStart(sessionId: string, eventMessage?: string): void { this.log.starts += 1; }
  onEvent(sessionId: string, eventCode: number, message: string): void { this.log.events += 1; }
  onResult(sessionId: string, result: SpeechRecognitionResult): void {
    this.log.results += 1;
    if (result.isFinal) this.log.finals += 1;
    if (result.result.length > 0) this.log.lastText = result.result;
  }
  onComplete(sessionId: string, eventMessage?: string): void { this.log.completes += 1; }
  onError(sessionId: string, errorCode: number, message: string): void {
    this.log.errors += 1;
    this.log.lastErrorCode = errorCode;
  }
}

class LicenseCb implements LicenseActivationCallback {
  private resolve: (r: LicenseActivationResult) => void;
  constructor(resolve: (r: LicenseActivationResult) => void) { this.resolve = resolve; }
  onResult(result: LicenseActivationResult): void { this.resolve(result); }
  onError(errorCode: number, message: string): void {
    const r = new LicenseActivationResult();
    r.errorCode = errorCode;
    r.errorMessage = message;
    this.resolve(r);
  }
}

class CreateCb implements CreateEngineCallback {
  private resolve: (e: SpeechRecognitionEngine | undefined) => void;
  constructor(resolve: (e: SpeechRecognitionEngine | undefined) => void) { this.resolve = resolve; }
  onSuccess(engine: SpeechRecognitionEngine): void { this.resolve(engine); }
  onError(errorCode: number, message: string): void { this.resolve(undefined); }
}

function sleep(ms: number): Promise<void> {
  return new Promise<void>((resolve: () => void): void => { setTimeout(resolve, ms); });
}

async function waitFor(pred: () => boolean, timeoutMs: number): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (pred()) return true;
    await sleep(50);
  }
  return pred();
}

function setLicenseAsync(licPath: string): Promise<LicenseActivationResult> {
  return new Promise<LicenseActivationResult>((resolve: (r: LicenseActivationResult) => void): void => {
    SpeechRecognizeSdk.setLicense(licPath, new LicenseCb(resolve));
  });
}

function createEngineAsyncP(params: CreateEngineParams): Promise<SpeechRecognitionEngine | undefined> {
  return new Promise<SpeechRecognitionEngine | undefined>((resolve: (e: SpeechRecognitionEngine | undefined) => void): void => {
    SpeechRecognizeSdk.createEngineAsync(params, new CreateCb(resolve));
  });
}

function prepareLicense(context: common.UIAbilityContext, workPath: string): string {
  const data = context.resourceManager.getRawFileContentSync('amphion-license.lic');
  if (!fs.accessSync(workPath)) fs.mkdirSync(workPath);
  const dest = `${workPath}/selftest-amphion-license.lic`;
  const dst = fs.openSync(dest, fs.OpenMode.READ_WRITE | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
  try {
    fs.writeSync(dst.fd, data.buffer);
  } finally {
    fs.closeSync(dst);
  }
  return dest;
}

function frame640(): ArrayBuffer {
  // 320 int16 samples of near-silence = one 20ms frame @ 16 kHz mono.
  return new ArrayBuffer(640);
}

function buildCreateParams(): CreateEngineParams {
  const p = new CreateEngineParams();
  p.language = 'zh-CN';
  p.online = 1;
  return p;
}

export async function runSdkSelfTest(context: common.UIAbilityContext): Promise<void> {
  const r = new Report();
  hilog.info(DOMAIN, TAG, 'BEGIN self-test');

  // --- setWorkPath / getWorkPath ---
  const workPath = `${context.filesDir}/dingqiao_work`;
  SpeechRecognizeSdk.setWorkPath(workPath);
  r.check('setWorkPath/getWorkPath', SpeechRecognizeSdk.getWorkPath() === workPath, workPath);

  // --- getLicenseInfo before setLicense -> throws LICENSE_NOT_SET ---
  let threw = false;
  let thrownMsg = '';
  try {
    SpeechRecognizeSdk.getLicenseInfo();
  } catch (e) {
    threw = true;
    thrownMsg = `${e}`;
  }
  r.check('getLicenseInfo before setLicense throws LICENSE_NOT_SET', threw && thrownMsg.includes('not set'), thrownMsg);

  // --- setLicense (valid bundled license) -> onResult errorCode=0 + ASR feature ---
  const licPath = prepareLicense(context, workPath);
  const lic = await setLicenseAsync(licPath);
  r.check('setLicense onResult errorCode=0', lic.errorCode === 0, `code=${lic.errorCode} msg=${lic.errorMessage}`);
  const feats = lic.authorizedFeatures ?? [];
  r.check('setLicense authorizedFeatures has ASR', feats.includes('ASR'), feats.join(','));

  // --- getLicenseInfo after setLicense ---
  const info: LicenseInfo = SpeechRecognizeSdk.getLicenseInfo();
  r.check('getLicenseInfo returns ASR feature', info.authorizedFeatures.includes('ASR'), `status=${info.status} features=${info.authorizedFeatures.join(',')}`);

  // --- setLicense error path: unreadable path -> onError LICENSE_FILE_UNREADABLE ---
  const badLic = await setLicenseAsync(`${workPath}/does-not-exist.lic`);
  r.check('setLicense bad path -> LICENSE_FILE_UNREADABLE', badLic.errorCode === DingqiaoErrorCode.LICENSE_FILE_UNREADABLE, `code=${badLic.errorCode}`);
  // re-activate the real license so the engine can be created
  await setLicenseAsync(licPath);

  // --- createEngine (sync) ---
  let engine: SpeechRecognitionEngine | undefined;
  try {
    engine = SpeechRecognizeSdk.createEngine(buildCreateParams());
  } catch (e) {
    engine = undefined;
  }
  r.check('createEngine (sync) returns engine', engine !== undefined, '');
  if (engine === undefined) { r.summary(); return; }

  // --- createEngineAsync ---
  const engine2 = await createEngineAsyncP(buildCreateParams());
  r.check('createEngineAsync -> onSuccess', engine2 !== undefined, '');
  if (engine2 !== undefined) engine2.shutdown();

  // --- setListener + full recognition lifecycle (synthetic silence PCM) ---
  const evt = new EventLog();
  engine.setListener(new TestListener(evt));

  const sid = 'selftest-1';
  const sp = new StartParams();
  sp.sessionId = sid;
  sp.audioInfo = new AudioInfo();
  engine.startListening(sp);
  const started = await waitFor((): boolean => evt.starts > 0, 8000);
  r.check('startListening -> onStart', started, `starts=${evt.starts}`);
  r.check('onEvent SPEECH_BEGIN fired', evt.events > 0, `events=${evt.events}`);
  r.check('isBusy() true during session', engine.isBusy(), '');

  // --- startListening while busy -> ENGINE_BUSY ---
  const busyBefore = evt.errors;
  const sp2 = new StartParams();
  sp2.sessionId = 'selftest-busy';
  sp2.audioInfo = new AudioInfo();
  engine.startListening(sp2);
  await sleep(200);
  r.check('startListening while busy -> ENGINE_BUSY', evt.errors > busyBefore && evt.lastErrorCode === DingqiaoErrorCode.ENGINE_BUSY, `code=${evt.lastErrorCode}`);

  // --- writeAudio: feed ~1.2s of frames ---
  for (let i = 0; i < 60; i++) engine.writeAudio(sid, frame640());
  await sleep(100);
  r.check('writeAudio accepted (no error)', evt.lastErrorCode !== DingqiaoErrorCode.RECOGNITION_ERROR, `errors=${evt.errors}`);

  // --- writeAudio wrong frame size -> RECOGNITION_ERROR ---
  const wrongBefore = evt.errors;
  engine.writeAudio(sid, new ArrayBuffer(320));
  await sleep(100);
  r.check('writeAudio wrong size -> RECOGNITION_ERROR', evt.errors > wrongBefore && evt.lastErrorCode === DingqiaoErrorCode.RECOGNITION_ERROR, `code=${evt.lastErrorCode}`);

  // --- setSpeakerVadEnabled (not configured -> graceful, no crash) ---
  let svOk = true;
  try { engine.setSpeakerVadEnabled(true); engine.setSpeakerVadEnabled(false); } catch (e) { svOk = false; }
  r.check('setSpeakerVadEnabled graceful', svOk, '');

  // --- finish -> onComplete + isBusy false ---
  engine.finish(sid);
  const completed = await waitFor((): boolean => evt.completes > 0, 8000);
  r.check('finish -> onComplete', completed, `completes=${evt.completes}`);
  r.check('isBusy() false after complete', !engine.isBusy(), '');
  hilog.info(DOMAIN, TAG, 'INFO results=%{public}d finals=%{public}d lastText="%{public}s"', evt.results, evt.finals, evt.lastText);

  // --- re-startListening (reuse; should be fast, not a 3s reload) ---
  const t0 = Date.now();
  const sid3 = 'selftest-3';
  const sp3 = new StartParams();
  sp3.sessionId = sid3;
  sp3.audioInfo = new AudioInfo();
  engine.startListening(sp3);
  const restarted = await waitFor((): boolean => evt.starts >= 2, 8000);
  const restartMs = Date.now() - t0;
  r.check('re-startListening works', restarted, `starts=${evt.starts}`);
  r.check('re-start fast (engine reused, <1500ms)', restartMs < 1500, `restartMs=${restartMs}`);

  // --- cancel -> isBusy false ---
  engine.cancel(sid3);
  await sleep(300);
  r.check('cancel -> isBusy false', !engine.isBusy(), '');

  // --- writeAudio without an active session -> NOT_LISTENING ---
  const notListenBefore = evt.errors;
  engine.writeAudio('no-session', frame640());
  await sleep(100);
  r.check('writeAudio no session -> NOT_LISTENING', evt.errors > notListenBefore && evt.lastErrorCode === DingqiaoErrorCode.NOT_LISTENING, `code=${evt.lastErrorCode}`);

  // --- startListening invalid audioInfo -> START_LISTENING_FAILED ---
  const badAudioBefore = evt.errors;
  const spBad = new StartParams();
  spBad.sessionId = 'selftest-bad';
  spBad.audioInfo = new AudioInfo();
  spBad.audioInfo.sampleRate = 8000;
  engine.startListening(spBad);
  await sleep(200);
  r.check('startListening bad audioInfo -> START_LISTENING_FAILED', evt.errors > badAudioBefore && evt.lastErrorCode === DingqiaoErrorCode.START_LISTENING_FAILED, `code=${evt.lastErrorCode}`);

  // --- registerVoiceprint without model/samples -> graceful error (no crash) ---
  let vpHandled = true;
  let vpDetail = '';
  try {
    const vp = new VoiceprintRegisterParams();
    vp.voiceprintId = 'selftest-vp';
    vp.samplePaths = [];
    const vr: VoiceprintRegisterResult = SpeechRecognizeSdk.registerVoiceprint(vp);
    vpDetail = `status=${vr.status} msg=${vr.message}`;
    vpHandled = vr.status !== 0;
  } catch (e) {
    vpDetail = `threw ${e}`;
    vpHandled = true;
  }
  r.check('registerVoiceprint (no samples) handled gracefully', vpHandled, vpDetail);

  // --- deleteVoiceprint (nonexistent) -> throws VOICEPRINT_NOT_FOUND (Android parity) ---
  let delThrew = false;
  let delMsg = '';
  try { SpeechRecognizeSdk.deleteVoiceprint('nonexistent-id'); } catch (e) { delThrew = true; delMsg = `${e}`; }
  r.check('deleteVoiceprint nonexistent -> throws VOICEPRINT_NOT_FOUND', delThrew && delMsg.includes('not found'), delMsg);

  // --- shutdown -> subsequent startListening errors (ENGINE_DESTROYED) ---
  engine.shutdown();
  const destroyedBefore = evt.errors;
  const spAfter = new StartParams();
  spAfter.sessionId = 'selftest-after-shutdown';
  spAfter.audioInfo = new AudioInfo();
  let shutdownThrew = false;
  try {
    engine.startListening(spAfter);
  } catch (e) {
    shutdownThrew = true;
  }
  await sleep(150);
  const gotDestroyed = shutdownThrew || (evt.errors > destroyedBefore);
  r.check('shutdown -> subsequent call rejected', gotDestroyed, `code=${evt.lastErrorCode} threw=${shutdownThrew}`);

  r.summary();
  hilog.info(DOMAIN, TAG, 'END self-test');
}
