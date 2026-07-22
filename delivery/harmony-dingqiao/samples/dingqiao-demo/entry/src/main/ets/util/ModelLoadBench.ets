import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import hilog from '@ohos.hilog';
import {
  CreateEngineCallback,
  CreateEngineParams,
  LicenseActivationCallback,
  LicenseActivationResult,
  PrepareRuntimeCallback,
  SpeechRecognitionEngine,
  SpeechRecognizeSdk
} from 'amphion_dingqiao';
import { AmphionRuntime } from 'amphion_asr';

const TAG: string = 'ModelLoadBench';
const DOMAIN: number = 0x0000;
const POOL_HIT_CREATES: number = 3;
const ASR_NUM_THREADS: number = 4;

export class ModelLoadBenchOptions {
  runId: string = 'manual';
  resultPath: string = '';
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

class EngineCreateResult {
  engine?: SpeechRecognitionEngine;
  errorCode: number = 0;
  errorMessage: string = '';
  callbackAtMs: number = 0;
}

interface PunctuationInspectableEngine extends SpeechRecognitionEngine {
  isPunctuationLoaded(): boolean;
}

class CreateCb implements CreateEngineCallback {
  private resolve: (result: EngineCreateResult) => void;

  constructor(resolve: (result: EngineCreateResult) => void) {
    this.resolve = resolve;
  }

  onSuccess(engine: SpeechRecognitionEngine): void {
    const result = new EngineCreateResult();
    result.callbackAtMs = Date.now();
    result.engine = engine;
    this.resolve(result);
  }

  onError(errorCode: number, message: string): void {
    const result = new EngineCreateResult();
    result.callbackAtMs = Date.now();
    result.errorCode = errorCode;
    result.errorMessage = message;
    this.resolve(result);
  }
}

function stringToAsciiBytes(value: string): ArrayBuffer {
  const bytes = new Uint8Array(value.length);
  for (let i = 0; i < value.length; i++) bytes[i] = value.charCodeAt(i) & 0x7F;
  return bytes.buffer;
}

function writeText(path: string, text: string): void {
  const fp = fs.openSync(path, fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
  try {
    fs.writeSync(fp.fd, stringToAsciiBytes(text));
  } finally {
    fs.closeSync(fp);
  }
}

function prepareLicense(context: common.UIAbilityContext, workPath: string): string {
  const data = context.resourceManager.getRawFileContentSync('amphion-license.lic');
  if (!fs.accessSync(workPath)) fs.mkdirSync(workPath);
  const destination = `${workPath}/loadbench-amphion-license.lic`;
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

function createParams(): CreateEngineParams {
  const params = new CreateEngineParams();
  params.language = 'zh-CN';
  params.online = 1;
  return params;
}

function createEngineAsync(params: CreateEngineParams): Promise<EngineCreateResult> {
  return new Promise<EngineCreateResult>((resolve: (result: EngineCreateResult) => void): void => {
    SpeechRecognizeSdk.createEngineAsync(params, new CreateCb(resolve));
  });
}

function safeDetail(value: string): string {
  return value.replace(/[^A-Za-z0-9_.:-]/g, '_').substring(0, 160);
}

export async function runModelLoadBench(context: common.UIAbilityContext,
  options: ModelLoadBenchOptions): Promise<void> {
  const engines: SpeechRecognitionEngine[] = [];
  const poolHitMs: number[] = [];
  let coldMs = -1;
  let punctuationLoaded = false;
  let fatal = '';

  try {
    if (options.resultPath.length === 0) throw new Error('resultPath is required');
    const workPath = `${context.filesDir}/dingqiao_work`;
    SpeechRecognizeSdk.setWorkPath(workPath);
    const license = await activateLicense(prepareLicense(context, workPath));
    if (license.errorCode !== 0) throw new Error(`license-${license.errorCode}`);
    const runtimeError = await prepareRuntime();
    if (runtimeError !== 0) throw new Error(`runtime-${runtimeError}`);

    // The compatibility adapter always enables punctuation. Keep parameter construction and license work out
    // of the interval so this measures the public async path from invocation through its callback,
    // including concurrent ASR construction/warm-up and punctuation construction.
    const params = createParams();
    let startedAt = Date.now();
    const coldResult = await createEngineAsync(params);
    coldMs = coldResult.callbackAtMs - startedAt;
    const coldEngine = coldResult.engine;
    if (coldEngine === undefined) {
      throw new Error(`create-${coldResult.errorCode}-${safeDetail(coldResult.errorMessage)}`);
    }
    engines.push(coldEngine);
    if (!(coldEngine as PunctuationInspectableEngine).isPunctuationLoaded()) {
      throw new Error('punctuation-not-loaded');
    }
    punctuationLoaded = true;

    // Keep all engines alive until every sample is collected. This makes the next three creates hit
    // the same-process recognizer and punctuation pools instead of relying on finalizer timing.
    for (let i = 0; i < POOL_HIT_CREATES; i++) {
      startedAt = Date.now();
      const poolResult = await createEngineAsync(params);
      poolHitMs.push(poolResult.callbackAtMs - startedAt);
      const poolEngine = poolResult.engine;
      if (poolEngine === undefined) {
        throw new Error(`pool-create-${poolResult.errorCode}-${safeDetail(poolResult.errorMessage)}`);
      }
      engines.push(poolEngine);
      if (!(poolEngine as PunctuationInspectableEngine).isPunctuationLoaded()) {
        punctuationLoaded = false;
        throw new Error('pool-punctuation-not-loaded');
      }
    }
  } catch (e) {
    fatal = safeDetail(`${e}`);
  } finally {
    for (let i = engines.length - 1; i >= 0; i--) engines[i].shutdown();
  }

  const status = fatal.length === 0 && punctuationLoaded && coldMs >= 0 &&
    poolHitMs.length === POOL_HIT_CREATES ?
    'PASS' : 'FAIL';
  const result = `LOADBENCH|version=2|api=createEngineAsync|runId=${safeDetail(options.runId)}|status=${status}` +
    `|punctuationRequested=true|punctuationLoaded=${punctuationLoaded}` +
    `|numThreads=${ASR_NUM_THREADS}|warmupSamples=${AmphionRuntime.eagerWarmupSamples()}` +
    `|coldMs=${coldMs}|poolHitMs=${poolHitMs.join(',')}|fatal=${fatal}`;
  try {
    writeText(options.resultPath, `${result}\n`);
  } catch (e) {
    hilog.error(DOMAIN, TAG, 'result write failed: %{public}s', safeDetail(`${e}`));
  }
  hilog.info(DOMAIN, TAG, '%{public}s', result);
}
