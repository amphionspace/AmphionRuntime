import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import hilog from '@ohos.hilog';
import {
  AudioInfo,
  CreateEngineCallback,
  CreateEngineParams,
  LicenseActivationCallback,
  LicenseActivationResult,
  PrepareRuntimeCallback,
  RecognitionListener,
  SpeechRecognitionEngine,
  SpeechRecognitionResult,
  SpeechRecognizeSdk,
  StartParams
} from 'amphion_dingqiao';

const TAG: string = 'HotwordDeviceEval';
const DOMAIN: number = 0x0000;
const FRAME_BYTES: number = 640;
const COMPLETE_TIMEOUT_MS: number = 45000;

export class HotwordDeviceEvalOptions {
  manifestPath: string = '';
  resultPath: string = '';
  paceMs: number = 0;
  maxCases: number = 0;
}

class EvalEntry {
  id: string = '';
  language: string = 'zh-CN';
  path: string = '';
  hotwords: string[] = [];
}

class EngineCreateResult {
  engine?: SpeechRecognitionEngine;
  errorCode: number = 0;
  errorMessage: string = '';
}

class CreateCb implements CreateEngineCallback {
  private resolve: (result: EngineCreateResult) => void;

  constructor(resolve: (result: EngineCreateResult) => void) {
    this.resolve = resolve;
  }

  onSuccess(engine: SpeechRecognitionEngine): void {
    const result = new EngineCreateResult();
    result.engine = engine;
    this.resolve(result);
  }

  onError(errorCode: number, message: string): void {
    const result = new EngineCreateResult();
    result.errorCode = errorCode;
    result.errorMessage = message;
    this.resolve(result);
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

class PrepareCb implements PrepareRuntimeCallback {
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

class SessionOutcome {
  text: string = '';
  errorCode: number = 0;
  errorMessage: string = '';
  elapsedMs: number = 0;
}

class EvalListener implements RecognitionListener {
  private expectedSessionId: string;
  private resolve: (result: SessionOutcome) => void;
  private startedAt: number;
  private finalText: string = '';
  private settled: boolean = false;

  constructor(expectedSessionId: string, startedAt: number,
    resolve: (result: SessionOutcome) => void) {
    this.expectedSessionId = expectedSessionId;
    this.startedAt = startedAt;
    this.resolve = resolve;
  }

  onResult(sessionId: string, result: SpeechRecognitionResult): void {
    if (sessionId === this.expectedSessionId && result.isFinal && result.result.length > 0) {
      this.finalText += result.result;
    }
  }

  onComplete(sessionId: string, _eventMessage?: string): void {
    if (sessionId !== this.expectedSessionId || this.settled) return;
    const outcome = new SessionOutcome();
    outcome.text = this.finalText;
    outcome.elapsedMs = Date.now() - this.startedAt;
    this.settled = true;
    this.resolve(outcome);
  }

  onError(sessionId: string, errorCode: number, message: string): void {
    if (sessionId !== this.expectedSessionId || this.settled) return;
    const outcome = new SessionOutcome();
    outcome.text = this.finalText;
    outcome.errorCode = errorCode;
    outcome.errorMessage = message;
    outcome.elapsedMs = Date.now() - this.startedAt;
    this.settled = true;
    this.resolve(outcome);
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise<void>((resolve: () => void): void => {
    setTimeout((): void => resolve(), ms);
  });
}

function safeMessage(value: string): string {
  return value.replace(/[\r\n\t]/g, ' ').substring(0, 300);
}

function readBytes(path: string): Uint8Array {
  const fp = fs.openSync(path);
  try {
    const size = fs.statSync(fp.fd).size;
    const data = new ArrayBuffer(size);
    const count = fs.readSync(fp.fd, data);
    return new Uint8Array(data.slice(0, count));
  } finally {
    fs.closeSync(fp);
  }
}

function readManifest(path: string, maxCases: number): EvalEntry[] {
  const text = util.TextDecoder.create('utf-8').decodeToString(readBytes(path));
  const entries: EvalEntry[] = [];
  const lines = text.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (line.length === 0) continue;
    const obj = JSON.parse(line) as Record<string, Object>;
    const entry = new EvalEntry();
    entry.id = String(obj['id']);
    entry.language = String(obj['language']);
    entry.path = String(obj['path']);
    entry.hotwords = obj['hotwords'] as string[];
    if (entry.id.length === 0 || entry.path.length === 0 || entry.hotwords.length === 0) {
      throw new Error(`invalid manifest line ${i + 1}`);
    }
    entries.push(entry);
    if (maxCases > 0 && entries.length >= maxCases) break;
  }
  if (entries.length === 0) throw new Error('hotword eval manifest is empty');
  return entries;
}

function utf8Bytes(value: string): ArrayBuffer {
  const output: number[] = [];
  for (let i = 0; i < value.length; i++) {
    let codePoint = value.charCodeAt(i);
    if (codePoint >= 0xD800 && codePoint <= 0xDBFF && i + 1 < value.length) {
      const low = value.charCodeAt(i + 1);
      if (low >= 0xDC00 && low <= 0xDFFF) {
        codePoint = 0x10000 + ((codePoint - 0xD800) << 10) + (low - 0xDC00);
        i += 1;
      }
    }
    if (codePoint <= 0x7F) {
      output.push(codePoint);
    } else if (codePoint <= 0x7FF) {
      output.push(0xC0 | (codePoint >> 6));
      output.push(0x80 | (codePoint & 0x3F));
    } else if (codePoint <= 0xFFFF) {
      output.push(0xE0 | (codePoint >> 12));
      output.push(0x80 | ((codePoint >> 6) & 0x3F));
      output.push(0x80 | (codePoint & 0x3F));
    } else {
      output.push(0xF0 | (codePoint >> 18));
      output.push(0x80 | ((codePoint >> 12) & 0x3F));
      output.push(0x80 | ((codePoint >> 6) & 0x3F));
      output.push(0x80 | (codePoint & 0x3F));
    }
  }
  const data = new ArrayBuffer(output.length);
  new Uint8Array(data).set(output);
  return data;
}

function writeUtf8(path: string, text: string): void {
  const data = utf8Bytes(text);
  const fp = fs.openSync(path, fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
  try {
    fs.writeSync(fp.fd, data);
  } finally {
    fs.closeSync(fp);
  }
}

function appendUtf8(path: string, text: string): void {
  const data = utf8Bytes(text);
  const fp = fs.openSync(path, fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.APPEND);
  try {
    fs.writeSync(fp.fd, data);
  } finally {
    fs.closeSync(fp);
  }
}

function prepareLicense(context: common.UIAbilityContext, workPath: string): string {
  const data = context.resourceManager.getRawFileContentSync('amphion-license.lic');
  if (!fs.accessSync(workPath)) fs.mkdirSync(workPath);
  const destination = `${workPath}/hotword-eval-amphion-license.lic`;
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
    SpeechRecognizeSdk.prepareRuntime(new PrepareCb(resolve));
  });
}

function createEngine(language: string, hotwords: string[]): Promise<EngineCreateResult> {
  const params = new CreateEngineParams();
  params.language = language;
  params.online = 1;
  params.extraParams['disablePrepack'] = true;
  if (hotwords.length > 0) params.extraParams['sysGeneralLexicon'] = hotwords;
  return new Promise<EngineCreateResult>((resolve: (result: EngineCreateResult) => void): void => {
    SpeechRecognizeSdk.createEngineAsync(params, new CreateCb(resolve));
  });
}

async function feedPcm(engine: SpeechRecognitionEngine, sessionId: string, path: string,
  paceMs: number): Promise<number> {
  const fp = fs.openSync(path);
  const frame = new ArrayBuffer(FRAME_BYTES);
  const bytes = new Uint8Array(frame);
  let frames = 0;
  try {
    while (true) {
      bytes.fill(0);
      const count = fs.readSync(fp.fd, frame);
      if (count <= 0) break;
      engine.writeAudio(sessionId, frame);
      frames += 1;
      if (paceMs > 0) await sleep(paceMs);
      else if (frames % 50 === 0) await sleep(1);
    }
  } finally {
    fs.closeSync(fp);
  }
  return frames;
}

async function recognize(engine: SpeechRecognitionEngine, entry: EvalEntry, variant: string,
  paceMs: number, index: number): Promise<SessionOutcome> {
  const sessionId = `hwe-${variant}-${index}`;
  const startedAt = Date.now();
  let timeoutId: number = -1;
  const resultPromise = new Promise<SessionOutcome>((resolve: (result: SessionOutcome) => void): void => {
    engine.setListener(new EvalListener(sessionId, startedAt, resolve));
    timeoutId = setTimeout((): void => {
      const outcome = new SessionOutcome();
      outcome.errorCode = -1;
      outcome.errorMessage = 'complete-timeout';
      outcome.elapsedMs = Date.now() - startedAt;
      resolve(outcome);
    }, COMPLETE_TIMEOUT_MS);
  });
  const params = new StartParams();
  params.sessionId = sessionId;
  params.audioInfo = new AudioInfo();
  params.extraParams['enablePartialResult'] = false;
  params.extraParams['enablePoliceEnhancement'] = false;
  params.extraParams['maxAudioDuration'] = 28800000;
  engine.startListening(params);
  await feedPcm(engine, sessionId, entry.path, paceMs);
  engine.finish(sessionId);
  const outcome = await resultPromise;
  if (timeoutId >= 0) clearTimeout(timeoutId);
  if (engine.isBusy()) engine.cancel(sessionId);
  return outcome;
}

function outputLine(entry: EvalEntry, variant: string, outcome: SessionOutcome): string {
  const value: Record<string, Object> = {};
  value['id'] = entry.id;
  value['variant'] = variant;
  value['text'] = outcome.text;
  value['elapsed_ms'] = outcome.elapsedMs;
  value['error_code'] = outcome.errorCode;
  value['error_message'] = safeMessage(outcome.errorMessage);
  return `${JSON.stringify(value)}\n`;
}

export async function runHotwordDeviceEval(context: common.UIAbilityContext,
  options: HotwordDeviceEvalOptions): Promise<void> {
  if (options.manifestPath.length === 0 || options.resultPath.length === 0) {
    throw new Error('manifestPath and resultPath are required');
  }
  writeUtf8(options.resultPath, '');
  const entries = readManifest(options.manifestPath, options.maxCases);
  const workPath = `${context.filesDir}/amphion_asr_work`;
  SpeechRecognizeSdk.setWorkPath(workPath);
  const license = await activateLicense(prepareLicense(context, workPath));
  if (license.errorCode !== 0) throw new Error(`license-${license.errorCode}`);
  const runtimeError = await prepareRuntime();
  if (runtimeError !== 0) throw new Error(`runtime-${runtimeError}`);

  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i];
    for (let pass = 0; pass < 2; pass++) {
      const variant = pass === 0 ? 'baseline' : 'hotword';
      const hotwords: string[] = pass === 0 ? [] : entry.hotwords;
      let engine: SpeechRecognitionEngine | undefined;
      let outcome = new SessionOutcome();
      try {
        const created = await createEngine(entry.language, hotwords);
        engine = created.engine;
        if (engine === undefined) {
          outcome.errorCode = created.errorCode;
          outcome.errorMessage = `create: ${created.errorMessage}`;
        } else {
          outcome = await recognize(engine, entry, variant, options.paceMs, i);
        }
      } catch (e) {
        outcome.errorCode = -2;
        outcome.errorMessage = `${e}`;
      } finally {
        engine?.shutdown();
      }
      appendUtf8(options.resultPath, outputLine(entry, variant, outcome));
      hilog.info(DOMAIN, TAG, 'progress %{public}d/%{public}d %{public}s error=%{public}d',
        i + 1, entries.length, variant, outcome.errorCode);
    }
  }
  hilog.info(DOMAIN, TAG, 'HOTWORD_EVAL_COMPLETE cases=%{public}d', entries.length);
}
