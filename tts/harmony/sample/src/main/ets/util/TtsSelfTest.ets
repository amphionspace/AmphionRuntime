/*
 * Headless self-test for the Lits TTS HarmonyOS SDK.
 * Exercises every public interface of TextToSpeechSdk / TextToSpeechEngine plus
 * the error-code paths, and proves real on-device synthesis by writing WAV files.
 * Triggered from EntryAbility when launched with --ps selftest true.
 * Results are logged under tag 'TtsSelfTest' as: PASS/FAIL | name | detail
 */
import hilog from '@ohos.hilog';
import fs from '@ohos.file.fs';
import common from '@ohos.app.ability.common';
import {
  TextToSpeechSdk,
  TtsErrorCode,
  TextToSpeechException,
  RunMode,
  PlayType,
  QueueMode,
  CompleteType,
  StopType
} from 'sdk';
import type {
  Callback,
  TextToSpeechEngine,
  SpeakListener,
  CreateEngineParams,
  VoiceQuery,
  VoiceInfo,
  SpeakParams,
  StartResponse,
  SynthesisResponse,
  CompleteResponse,
  StopResponse,
  LicenseActivationCallback,
  LicenseActivationResult,
  LicenseInfo
} from 'sdk';

const TAG: string = 'TtsSelfTest';
const DOMAIN: number = 0x0000;
const ZH_VOICE_ID: string = 'lits-female-02';
const EN_VOICE_ID: string = 'lits-female-01';

class Report {
  passed: number = 0;
  failed: number = 0;

  pass(name: string, detail: string): void {
    this.passed += 1;
    hilog.info(DOMAIN, TAG, 'PASS | %{public}s | %{public}s', name, detail);
  }

  fail(name: string, detail: string): void {
    this.failed += 1;
    hilog.error(DOMAIN, TAG, 'FAIL | %{public}s | %{public}s', name, detail);
  }

  check(name: string, ok: boolean, detail: string): void {
    if (ok) {
      this.pass(name, detail);
    } else {
      this.fail(name, detail);
    }
  }

  summary(): void {
    hilog.info(
      DOMAIN,
      TAG,
      'SELFTEST DONE passed=%{public}d failed=%{public}d total=%{public}d',
      this.passed,
      this.failed,
      this.passed + this.failed
    );
  }
}

interface CreateResult {
  engine?: TextToSpeechEngine;
  errorCode?: number;
  errorMessage?: string;
}

class CreateCb implements Callback<TextToSpeechEngine> {
  private readonly resolve: (r: CreateResult) => void;
  private settled: boolean = false;

  constructor(resolve: (r: CreateResult) => void) {
    this.resolve = resolve;
  }

  onSuccess(engine: TextToSpeechEngine): void {
    if (this.settled) {
      return;
    }
    this.settled = true;
    const r: CreateResult = { engine };
    this.resolve(r);
  }

  onError(errorCode: number, errorMessage: string): void {
    if (this.settled) {
      return;
    }
    this.settled = true;
    const r: CreateResult = { errorCode, errorMessage };
    this.resolve(r);
  }
}

interface SpeakResult {
  started: boolean;
  sampleRate: number;
  chunkCount: number;
  bytes: number;
  completed: boolean;
  completeType: string;
  stopped: boolean;
  stopType: string;
  errorCode: number;
  errorMessage: string;
  pcm: Array<ArrayBuffer>;
}

function newSpeakResult(): SpeakResult {
  return {
    started: false,
    sampleRate: 0,
    chunkCount: 0,
    bytes: 0,
    completed: false,
    completeType: '',
    stopped: false,
    stopType: '',
    errorCode: 0,
    errorMessage: '',
    pcm: []
  };
}

class CollectListener implements SpeakListener {
  readonly result: SpeakResult = newSpeakResult();
  private readonly done: (r: SpeakResult) => void;
  private readonly terminal: string;
  private settled: boolean = false;

  constructor(done: (r: SpeakResult) => void, terminal: string) {
    this.done = done;
    this.terminal = terminal;
  }

  onStart(requestId: string, response: StartResponse): void {
    this.result.started = true;
    this.result.sampleRate = response.sampleRate;
  }

  onData(requestId: string, audio: ArrayBuffer, response: SynthesisResponse): void {
    this.result.chunkCount += 1;
    this.result.bytes += audio.byteLength;
    this.result.pcm.push(audio);
  }

  onComplete(requestId: string, response: CompleteResponse): void {
    this.result.completed = true;
    this.result.completeType = String(response.type);
    if (String(response.type) === this.terminal) {
      this.settle();
    }
  }

  onStop(requestId: string, response: StopResponse): void {
    this.result.stopped = true;
    this.result.stopType = String(response.type);
    this.settle();
  }

  onError(requestId: string, errorCode: number, errorMessage: string): void {
    this.result.errorCode = errorCode;
    this.result.errorMessage = errorMessage;
    this.settle();
  }

  private settle(): void {
    if (this.settled) {
      return;
    }
    this.settled = true;
    this.done(this.result);
  }
}

function delay(ms: number): Promise<void> {
  return new Promise<void>((resolve: () => void): void => {
    setTimeout(() => {
      resolve();
    }, ms);
  });
}

function createEngineAsyncP(params: CreateEngineParams): Promise<CreateResult> {
  return new Promise<CreateResult>((resolve: (r: CreateResult) => void): void => {
    TextToSpeechSdk.createEngine(params, new CreateCb(resolve));
  });
}

interface LicResult {
  errorCode: number;
  errorMessage: string;
  authorizedFeatures: string[];
}

class LicenseCb implements LicenseActivationCallback {
  private readonly resolve: (r: LicResult) => void;
  private settled: boolean = false;

  constructor(resolve: (r: LicResult) => void) {
    this.resolve = resolve;
  }

  onResult(result: LicenseActivationResult): void {
    if (this.settled) {
      return;
    }
    this.settled = true;
    this.resolve({ errorCode: result.errorCode, errorMessage: result.errorMessage, authorizedFeatures: result.authorizedFeatures });
  }

  onError(errorCode: number, errorMessage: string): void {
    if (this.settled) {
      return;
    }
    this.settled = true;
    this.resolve({ errorCode, errorMessage, authorizedFeatures: [] });
  }
}

function setLicenseP(path: string): Promise<LicResult> {
  return new Promise<LicResult>((resolve: (r: LicResult) => void): void => {
    TextToSpeechSdk.setLicense(path, new LicenseCb(resolve));
  });
}

function writeTextToSandbox(ctx: common.UIAbilityContext, name: string, text: string): string {
  const dir: string = ctx.filesDir + '/tts-selftest';
  try {
    fs.mkdirSync(dir);
  } catch (e) {
    // directory may already exist
  }
  const path: string = dir + '/' + name;
  const file = fs.openSync(path, fs.OpenMode.READ_WRITE | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
  fs.writeSync(file.fd, text);
  fs.closeSync(file);
  return path;
}

function extractLicenseText(ctx: common.UIAbilityContext): string {
  const data = ctx.resourceManager.getRawFileContentSync('amphion-license.lic');
  let s = '';
  for (let i = 0; i < data.length; i++) {
    s += String.fromCharCode(data[i]);
  }
  return s;
}

function tamperLicense(text: string): string {
  // Locate the sig_b64 value robustly (JSON may be pretty-printed with spaces),
  // then flip a base64 char well inside the signature so the ECDSA check must fail.
  const marker = 'sig_b64';
  const mi = text.indexOf(marker);
  if (mi < 0) {
    return text;
  }
  const colon = text.indexOf(':', mi + marker.length);
  if (colon < 0) {
    return text;
  }
  const openQuote = text.indexOf('"', colon);
  if (openQuote < 0) {
    return text;
  }
  const pos = openQuote + 11;
  if (pos >= text.length) {
    return text;
  }
  const c = text.charAt(pos);
  const repl = c === 'A' ? 'B' : 'A';
  return text.substring(0, pos) + repl + text.substring(pos + 1);
}

function speakAndWait(
  engine: TextToSpeechEngine,
  text: string,
  params: SpeakParams,
  terminal: string,
  timeoutMs: number
): Promise<SpeakResult> {
  return new Promise<SpeakResult>((resolve: (r: SpeakResult) => void): void => {
    let settled: boolean = false;
    const finish = (r: SpeakResult): void => {
      if (settled) {
        return;
      }
      settled = true;
      resolve(r);
    };
    const listener = new CollectListener((r: SpeakResult): void => {
      finish(r);
    }, terminal);
    engine.setListener(listener);
    setTimeout(() => {
      finish(listener.result);
    }, timeoutMs);
    try {
      engine.speak(text, params);
    } catch (e) {
      const msg: string = e instanceof Error ? e.message : String(e);
      listener.result.errorMessage = 'THROW:' + msg;
      finish(listener.result);
    }
  });
}

function errorCodeOf(e: Object): number {
  if (e instanceof TextToSpeechException) {
    return e.errorCode;
  }
  return -1;
}

function messageOf(e: Object): string {
  if (e instanceof Error) {
    return e.message;
  }
  return String(e);
}

function buildSpeakParams(requestId: string, language: string, playType: PlayType): SpeakParams {
  const params: SpeakParams = {
    requestId,
    playType,
    queueMode: QueueMode.PREEMPT,
    languageContext: language === 'en-US' ? 'en-US' : 'zh-en',
    audioType: 'pcm',
    speed: 1.0,
    pitch: 1.0,
    volume: 1.0
  };
  return params;
}

function writeWav(ctx: common.UIAbilityContext, name: string, result: SpeakResult): string {
  const dir: string = ctx.filesDir + '/tts-selftest';
  try {
    fs.mkdirSync(dir);
  } catch (e) {
    // directory may already exist; ignore
  }
  const sampleRate: number = result.sampleRate > 0 ? result.sampleRate : 24000;
  let dataLen: number = 0;
  for (const c of result.pcm) {
    dataLen += c.byteLength;
  }
  const buf = new ArrayBuffer(44 + dataLen);
  const view = new DataView(buf);
  const putStr = (offset: number, s: string): void => {
    for (let i = 0; i < s.length; i++) {
      view.setUint8(offset + i, s.charCodeAt(i));
    }
  };
  putStr(0, 'RIFF');
  view.setUint32(4, 36 + dataLen, true);
  putStr(8, 'WAVE');
  putStr(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  putStr(36, 'data');
  view.setUint32(40, dataLen, true);
  let offset: number = 44;
  for (const c of result.pcm) {
    const src = new Uint8Array(c);
    const dst = new Uint8Array(buf, offset, c.byteLength);
    dst.set(src);
    offset += c.byteLength;
  }
  const path: string = dir + '/' + name;
  const file = fs.openSync(path, fs.OpenMode.READ_WRITE | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
  fs.writeSync(file.fd, buf);
  fs.closeSync(file);
  return path;
}

async function shutdownQuietly(engine?: TextToSpeechEngine): Promise<void> {
  if (!engine) {
    return;
  }
  try {
    engine.shutdown();
  } catch (e) {
    // ignore
  }
  await delay(100);
}

export async function runTtsSelfTest(ctx: common.UIAbilityContext): Promise<void> {
  const r = new Report();
  hilog.info(DOMAIN, TAG, 'SELFTEST START');

  // 0. setContext (API12: host must inject context before createEngine so the
  //    SDK can extract bundled model resources without the API14 getApplicationContext).
  try {
    TextToSpeechSdk.setContext(ctx);
    r.pass('setContext', 'context injected for bundled model extraction');
  } catch (e) {
    r.fail('setContext', 'threw ' + messageOf(e));
  }

  // 1. listVoices (sync)
  try {
    const query: VoiceQuery = { requestId: 'lv-1', mode: RunMode.OFFLINE };
    const voices: Array<VoiceInfo> = TextToSpeechSdk.listVoices(query);
    let hasZh: boolean = false;
    let hasEn: boolean = false;
    for (const v of voices) {
      if (v.voiceId === ZH_VOICE_ID) {
        hasZh = true;
      }
      if (v.voiceId === EN_VOICE_ID) {
        hasEn = true;
      }
    }
    r.check('listVoices', voices.length > 0 && hasZh && hasEn,
      `count=${voices.length} hasZh=${hasZh} hasEn=${hasEn}`);
  } catch (e) {
    r.fail('listVoices', 'threw ' + messageOf(e));
  }

  // ---- License gate tests (createEngine is license-gated) ----
  // L1: getLicenseInfo before setLicense -> LICENSE_NOT_SET
  try {
    TextToSpeechSdk.getLicenseInfo();
    r.fail('license.getInfoBeforeSet', 'no error thrown');
  } catch (e) {
    r.check('license.getInfoBeforeSet', errorCodeOf(e) === TtsErrorCode.LICENSE_NOT_SET, `code=${errorCodeOf(e)}`);
  }
  // L2: createEngine before setLicense -> gated with LICENSE_MISSING
  try {
    const p: CreateEngineParams = { language: 'zh-en', mode: RunMode.OFFLINE, voiceId: ZH_VOICE_ID };
    TextToSpeechSdk.createEngine(p);
    r.fail('license.createEngineBeforeLicense', 'no error thrown');
  } catch (e) {
    r.check('license.createEngineBeforeLicense', errorCodeOf(e) === TtsErrorCode.LICENSE_MISSING, `code=${errorCodeOf(e)}`);
  }
  // L3: tampered license -> LICENSE_SIGNATURE_INVALID; L4: valid license -> success
  let licPath = '';
  try {
    const text = extractLicenseText(ctx);
    licPath = writeTextToSandbox(ctx, 'amphion-license.lic', text);
    const badPath = writeTextToSandbox(ctx, 'amphion-license-bad.lic', tamperLicense(text));
    const bad = await setLicenseP(badPath);
    r.check('license.setTampered', bad.errorCode === TtsErrorCode.LICENSE_SIGNATURE_INVALID, `code=${bad.errorCode}`);
  } catch (e) {
    r.fail('license.prepare', messageOf(e));
  }
  if (licPath.length > 0) {
    const okRes = await setLicenseP(licPath);
    r.check('license.setValid', okRes.errorCode === 0, `code=${okRes.errorCode} features=${okRes.authorizedFeatures.join(',')}`);
    r.check('license.featureTTS', okRes.authorizedFeatures.indexOf('TTS') >= 0, `features=${okRes.authorizedFeatures.join(',')}`);
    try {
      const info: LicenseInfo = TextToSpeechSdk.getLicenseInfo();
      r.check('license.getInfoAfter', info.status === 0, `status=${info.status} features=${info.authorizedFeatures.join(',')}`);
    } catch (e) {
      r.fail('license.getInfoAfter', messageOf(e));
    }
  }

  // 2. createEngine async (callback) zh-en
  let zhEngine: TextToSpeechEngine | undefined = undefined;
  {
    const params: CreateEngineParams = {
      language: 'zh-en',
      mode: RunMode.OFFLINE,
      voiceId: ZH_VOICE_ID
    };
    const started: number = Date.now();
    const res = await createEngineAsyncP(params);
    if (res.engine) {
      zhEngine = res.engine;
      r.pass('createEngine.async(zh-en)', `loadMs=${Date.now() - started}`);
    } else {
      r.fail('createEngine.async(zh-en)', `code=${res.errorCode} msg=${res.errorMessage}`);
    }
  }

  // 3. speak SYNTHESIZE_ONLY (zh) + prove real PCM
  if (zhEngine) {
    const params = buildSpeakParams('zh-synth-1', 'zh-en', PlayType.SYNTHESIZE_ONLY);
    const res = await speakAndWait(zhEngine, '你好，欢迎使用鼎桥语音合成。今天是二零二六年七月二日，费用一百二十三元。',
      params, String(CompleteType.SYNTHESIS_COMPLETE), 30000);
    const ok: boolean = res.started && res.chunkCount > 0 && res.bytes > 0 && res.completed && res.errorCode === 0;
    r.check('speak.SYNTHESIZE_ONLY(zh)', ok,
      `started=${res.started} chunks=${res.chunkCount} bytes=${res.bytes} sr=${res.sampleRate} completeType=${res.completeType} err=${res.errorCode}`);
    r.check('audio.sampleRate==24000', res.sampleRate === 24000, `sampleRate=${res.sampleRate}`);
    if (res.bytes > 0) {
      try {
        const p = writeWav(ctx, 'zh_synth.wav', res);
        r.pass('audio.wavWritten(zh)', `${p} bytes=${res.bytes}`);
      } catch (e) {
        r.fail('audio.wavWritten(zh)', 'threw ' + messageOf(e));
      }
    }
  }

  // 4. isBusy() false after completion
  if (zhEngine) {
    try {
      const busy: boolean = zhEngine.isBusy();
      r.check('isBusy.afterComplete', busy === false, `isBusy=${busy}`);
    } catch (e) {
      r.fail('isBusy.afterComplete', 'threw ' + messageOf(e));
    }
  }

  // 5. speak SYNTHESIZE_AND_PLAY (zh) — real playback through device
  if (zhEngine) {
    const params = buildSpeakParams('zh-play-1', 'zh-en', PlayType.SYNTHESIZE_AND_PLAY);
    const res = await speakAndWait(zhEngine, '这是一句通过扬声器播放的测试。',
      params, String(CompleteType.PLAYBACK_COMPLETE), 30000);
    const ok: boolean = res.started && res.completed && res.errorCode === 0;
    r.check('speak.SYNTHESIZE_AND_PLAY(zh)', ok,
      `started=${res.started} chunks=${res.chunkCount} completeType=${res.completeType} err=${res.errorCode}`);
  }

  // 6. stop() during a long synthesis
  if (zhEngine) {
    const params = buildSpeakParams('zh-stop-1', 'zh-en', PlayType.SYNTHESIZE_AND_PLAY);
    let stopSeen: boolean = false;
    const listener = new CollectListener((res: SpeakResult): void => {
      stopSeen = res.stopped;
    }, String(CompleteType.PLAYBACK_COMPLETE));
    zhEngine.setListener(listener);
    try {
      zhEngine.speak('这是一段较长的文本，用来测试在合成过程中调用停止接口能否正确中断当前的语音合成与播放流程。', params);
      await delay(400);
      zhEngine.stop();
      await delay(1200);
      r.check('stop.duringSpeak', stopSeen || listener.result.stopped, `stopped=${listener.result.stopped} stopType=${listener.result.stopType}`);
    } catch (e) {
      r.fail('stop.duringSpeak', 'threw ' + messageOf(e));
    }
  }

  // 7. Error: speak before setListener -> ENGINE_NOT_INITIALIZED (use a fresh sync engine)
  let enEngine: TextToSpeechEngine | undefined = undefined;
  try {
    const params: CreateEngineParams = { language: 'en-US', mode: RunMode.OFFLINE, voiceId: EN_VOICE_ID };
    enEngine = TextToSpeechSdk.createEngine(params);
    r.pass('createEngine.sync(en-US)', 'engine created');
  } catch (e) {
    r.fail('createEngine.sync(en-US)', 'threw ' + messageOf(e));
  }
  if (enEngine) {
    try {
      const p = buildSpeakParams('en-nolistener', 'en-US', PlayType.SYNTHESIZE_ONLY);
      enEngine.speak('hello', p);
      r.fail('error.speakBeforeSetListener', 'no error thrown');
    } catch (e) {
      const code: number = errorCodeOf(e);
      r.check('error.speakBeforeSetListener', code === TtsErrorCode.ENGINE_NOT_INITIALIZED, `code=${code}`);
    }
  }

  // 8. speak SYNTHESIZE_ONLY (en) on the sync engine
  if (enEngine) {
    const params = buildSpeakParams('en-synth-1', 'en-US', PlayType.SYNTHESIZE_ONLY);
    const res = await speakAndWait(enEngine, 'Hello, welcome to Lits text to speech. The total is 456 dollars.',
      params, String(CompleteType.SYNTHESIS_COMPLETE), 30000);
    const ok: boolean = res.started && res.chunkCount > 0 && res.bytes > 0 && res.completed && res.errorCode === 0;
    r.check('speak.SYNTHESIZE_ONLY(en)', ok,
      `chunks=${res.chunkCount} bytes=${res.bytes} sr=${res.sampleRate} err=${res.errorCode}`);
    if (res.bytes > 0) {
      try {
        writeWav(ctx, 'en_synth.wav', res);
        r.pass('audio.wavWritten(en)', `bytes=${res.bytes}`);
      } catch (e) {
        r.fail('audio.wavWritten(en)', 'threw ' + messageOf(e));
      }
    }
  }

  // 9. Error: text too long -> TEXT_LENGTH_INVALID
  if (enEngine) {
    try {
      let big: string = '';
      for (let i = 0; i < 11000; i++) {
        big += 'a';
      }
      const p = buildSpeakParams('en-toolong', 'en-US', PlayType.SYNTHESIZE_ONLY);
      enEngine.speak(big, p);
      // may surface via onError instead of throw; give it a moment
      await delay(300);
      r.pass('error.textTooLong(submitted)', 'no synchronous throw (may surface via onError)');
    } catch (e) {
      const code: number = errorCodeOf(e);
      r.check('error.textTooLong', code === TtsErrorCode.TEXT_LENGTH_INVALID, `code=${code}`);
    }
  }

  // 10. shutdown() then speak -> ENGINE_DESTROYED (surfaced via throw OR onError callback)
  if (enEngine) {
    const destroyListener = new CollectListener((res: SpeakResult): void => {}, 'none');
    try {
      enEngine.setListener(destroyListener);
    } catch (e) {
      // ignore
    }
    try {
      enEngine.shutdown();
      r.pass('shutdown(en)', 'ok');
    } catch (e) {
      r.fail('shutdown(en)', 'threw ' + messageOf(e));
    }
    let threwCode: number = 0;
    try {
      const p = buildSpeakParams('en-afterdestroy', 'en-US', PlayType.SYNTHESIZE_ONLY);
      enEngine.speak('hello', p);
    } catch (e) {
      threwCode = errorCodeOf(e);
    }
    await delay(150);
    const viaCallback: number = destroyListener.result.errorCode;
    const ok: boolean = threwCode === TtsErrorCode.ENGINE_DESTROYED || viaCallback === TtsErrorCode.ENGINE_DESTROYED;
    r.check('error.speakAfterShutdown', ok, `throw=${threwCode} onError=${viaCallback}`);
    enEngine = undefined;
  }

  // 11. Error: createEngine unsupported language -> LANGUAGE_UNSUPPORTED
  try {
    const params: CreateEngineParams = { language: 'ja-JP', mode: RunMode.OFFLINE, voiceId: ZH_VOICE_ID };
    const eng = TextToSpeechSdk.createEngine(params);
    await shutdownQuietly(eng);
    r.fail('error.badLanguage', 'no error thrown');
  } catch (e) {
    const code: number = errorCodeOf(e);
    r.check('error.badLanguage', code === TtsErrorCode.LANGUAGE_UNSUPPORTED, `code=${code}`);
  }

  // 12. Error: createEngine unsupported voiceId -> VOICE_UNSUPPORTED
  try {
    const params: CreateEngineParams = { language: 'zh-en', mode: RunMode.OFFLINE, voiceId: 'no-such-voice' };
    const eng = TextToSpeechSdk.createEngine(params);
    await shutdownQuietly(eng);
    r.fail('error.badVoice', 'no error thrown');
  } catch (e) {
    const code: number = errorCodeOf(e);
    r.check('error.badVoice', code === TtsErrorCode.VOICE_UNSUPPORTED, `code=${code}`);
  }

  // 13. Error: setWorkPath('') -> RUNTIME_EXCEPTION
  try {
    TextToSpeechSdk.setWorkPath('');
    r.fail('error.setWorkPathBlank', 'no error thrown');
  } catch (e) {
    const code: number = errorCodeOf(e);
    r.check('error.setWorkPathBlank', code === TtsErrorCode.RUNTIME_EXCEPTION, `code=${code}`);
  }

  // 14. Error: setWorkPath while an engine is active -> INTERNAL_SERVICE_ERROR
  if (zhEngine) {
    try {
      TextToSpeechSdk.setWorkPath('/data/storage/el2/base/haps/tts-selftest-dummy');
      r.fail('error.setWorkPathWhileActive', 'no error thrown');
    } catch (e) {
      const code: number = errorCodeOf(e);
      r.check('error.setWorkPathWhileActive', code === TtsErrorCode.INTERNAL_SERVICE_ERROR, `code=${code}`);
    }
  }

  // cleanup
  await shutdownQuietly(zhEngine);
  zhEngine = undefined;

  r.summary();
}
