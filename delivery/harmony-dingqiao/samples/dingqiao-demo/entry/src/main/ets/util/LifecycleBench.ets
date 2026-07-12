import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import hilog from '@ohos.hilog';
import { util } from '@kit.ArkTS';
import {
  AudioInfo,
  CreateEngineParams,
  CreateEngineCallback,
  LicenseActivationCallback,
  LicenseActivationResult,
  PrepareRuntimeCallback,
  RecognitionListener,
  SpeechRecognitionEngine,
  SpeechRecognitionResult,
  SpeechRecognizeSdk,
  StartParams
} from 'amphion_dingqiao';

// 两级加载生命周期 + 全工况延迟/内存 bench(demo 侧,非 SDK)。驱动 prepareRuntime → createEngine →
// (推理) → unloadModel → unloadRuntime,把每个工况的延迟、SDK 净内存(= 当前 PSS − 载体基线)、
// 推理侧首块/RTF/尾包、峰值内存都采出来,供 prepack on/off A/B。载体基线由 EntryAbility 在任何 SDK
// 调用之前采样并传入,减法得纯 SDK 净值。

const TAG: string = 'LifecycleBench';
const DOMAIN: number = 0x0000;
const SR: number = 16000;
const FRAME_BYTES: number = 640;   // 20ms @ 16kHz 16bit mono
const INFER_UTTERANCES: number = 12;

export class LifecycleBenchOptions {
  resultPath: string = '';
  disablePrepack: boolean = false;
  carrierBaselinePss: number = 0;   // EntryAbility 在 SDK init 前采的载体基线(PSS)
  carrierBaselineAnon: number = 0;  // 同上,私有 anon
  iters: number = 20;               // 压测轮数(默认 20,可传 100)
}

class ManifestEntry {
  offset: number = 0;
  nbytes: number = 0;
  durMs: number = 0;
}

// 从 /proc/self/status 读内核账(权威)。hidebug.getPss() 实测低估(私有 anon 曾 > 其报的 PSS,不可能),
// 故一律以 /proc 为准。返回 [VmRSS 总, RssAnon 私有独占(OOM相关), RssFile mmap文件页(可换出)] MB。
function procMem(): number[] {
  try {
    const fp = fs.openSync('/proc/self/status', fs.OpenMode.READ_ONLY);
    try {
      const buf = new ArrayBuffer(8192);
      const n = fs.readSync(fp.fd, buf);
      const text = util.TextDecoder.create('utf-8').decodeToString(new Uint8Array(buf.slice(0, n)));
      const g = (key: string): number => {
        const m = text.match(new RegExp(key + ':\\s*(\\d+)\\s*kB'));
        return m !== null ? Math.round(Number(m[1]) / 1024) : -1;
      };
      return [g('VmRSS'), g('RssAnon'), g('RssFile')];
    } finally { fs.closeSync(fp); }
  } catch (e) { return [-1, -1, -1]; }
}

function delay(ms: number): Promise<void> {
  return new Promise<void>((resolve: () => void): void => { setTimeout(resolve, ms); });
}

class LicCb implements LicenseActivationCallback {
  private resolve: (r: LicenseActivationResult) => void;
  constructor(resolve: (r: LicenseActivationResult) => void) { this.resolve = resolve; }
  onResult(r: LicenseActivationResult): void { this.resolve(r); }
  onError(code: number, message: string): void {
    const r = new LicenseActivationResult(); r.errorCode = code; r.errorMessage = message; this.resolve(r);
  }
}

class PrepCb implements PrepareRuntimeCallback {
  private resolve: (ok: boolean) => void;
  constructor(resolve: (ok: boolean) => void) { this.resolve = resolve; }
  onReady(): void { this.resolve(true); }
  onError(_code: number, _message: string): void { this.resolve(false); }
}

class EngineResult {
  engine?: SpeechRecognitionEngine;
  errorCode: number = 0;
  errorMessage: string = '';
}

class CreateCb implements CreateEngineCallback {
  private resolve: (r: EngineResult) => void;
  constructor(resolve: (r: EngineResult) => void) { this.resolve = resolve; }
  onSuccess(engine: SpeechRecognitionEngine): void {
    const r = new EngineResult(); r.engine = engine; this.resolve(r);
  }
  onError(errorCode: number, message: string): void {
    const r = new EngineResult(); r.errorCode = errorCode; r.errorMessage = message; this.resolve(r);
  }
}

// 推理监听:记首个结果时刻、finish→complete、final 文本,供延迟工况计算。
class InferListener implements RecognitionListener {
  startAt: number = 0;
  firstResultAt: number = -1;
  completeAt: number = -1;
  finals: number = 0;
  lastText: string = '';
  private done: (() => void) | undefined;

  setStart(t: number): void { this.startAt = t; }
  onComplete(_sessionId: string, _eventMessage?: string): void {
    this.completeAt = Date.now();
    if (this.done !== undefined) this.done();
  }
  waitComplete(timeoutMs: number): Promise<void> {
    return new Promise<void>((resolve: () => void): void => {
      this.done = resolve;
      setTimeout(resolve, timeoutMs);   // 兜底:onComplete 万一不触发也不死等
    });
  }
  onStart(_sessionId: string, _eventMessage?: string): void {}
  onEvent(_sessionId: string, _eventCode: number, _message: string): void {}
  onResult(_sessionId: string, result: SpeechRecognitionResult): void {
    if (this.firstResultAt < 0) this.firstResultAt = Date.now();
    if (result.isFinal) { this.finals += 1; this.lastText = result.result; }
  }
  onError(_sessionId: string, _errorCode: number, _message: string): void {}
}

function prepareLicense(context: common.UIAbilityContext, workPath: string): string {
  const data = context.resourceManager.getRawFileContentSync('amphion-license.lic');
  if (!fs.accessSync(workPath)) fs.mkdirSync(workPath);
  const dst = `${workPath}/lifecycle-amphion-license.lic`;
  const fp = fs.openSync(dst, fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
  try { fs.writeSync(fp.fd, data.buffer); } finally { fs.closeSync(fp); }
  return dst;
}

function activateLicense(path: string): Promise<LicenseActivationResult> {
  return new Promise<LicenseActivationResult>((resolve: (r: LicenseActivationResult) => void): void => {
    SpeechRecognizeSdk.setLicense(path, new LicCb(resolve));
  });
}

function prepareRuntime(): Promise<boolean> {
  return new Promise<boolean>((resolve: (v: boolean) => void): void => {
    SpeechRecognizeSdk.prepareRuntime(new PrepCb(resolve));
  });
}

function createEngineAsync(params: CreateEngineParams): Promise<EngineResult> {
  return new Promise<EngineResult>((resolve: (r: EngineResult) => void): void => {
    SpeechRecognizeSdk.createEngineAsync(params, new CreateCb(resolve));
  });
}

function makeParams(disablePrepack: boolean): CreateEngineParams {
  const p = new CreateEngineParams();
  p.language = 'zh-CN';
  p.online = 1;
  p.extraParams = { 'disablePrepack': disablePrepack } as Record<string, Object>;
  return p;
}

function readManifest(ctx: common.UIAbilityContext): ManifestEntry[] {
  const data: Uint8Array = ctx.resourceManager.getRawFileContentSync('asr_eval/manifest.jsonl');
  const text: string = util.TextDecoder.create('utf-8').decodeToString(data);
  const out: ManifestEntry[] = [];
  const lines: string[] = text.split('\n');
  for (let i = 0; i < lines.length && out.length < INFER_UTTERANCES; i++) {
    const line = lines[i].trim();
    if (line.length === 0) continue;
    try {
      const obj = JSON.parse(line) as Record<string, Object>;
      const e = new ManifestEntry();
      e.offset = Number(obj.offset);
      e.nbytes = Number(obj.nbytes);
      e.durMs = Number(obj.dur) * 1000;
      out.push(e);
    } catch (err) { /* skip */ }
  }
  return out;
}

// 单条推理:走甲方接口 startListening→writeAudio(640B/帧)→finish→onComplete,不限速(最大吞吐,量 RTF)。
// 返回 [firstPartialMs, finishToCompleteMs, rtf, ok]。
async function feedOne(engine: SpeechRecognitionEngine, sid: string, blobFd: number,
  rawBase: number, e: ManifestEntry): Promise<number[]> {
  const buf: ArrayBuffer = new ArrayBuffer(e.nbytes);
  fs.readSync(blobFd, buf, { offset: rawBase + e.offset, length: e.nbytes });
  const bytes = new Uint8Array(buf);

  const listener = new InferListener();
  engine.setListener(listener);
  const sp = new StartParams();
  sp.sessionId = sid;
  sp.audioInfo = new AudioInfo();
  const startAt = Date.now();
  listener.setStart(startAt);
  engine.startListening(sp);
  // 契约要求每帧正好 640 字节:尾帧不满则补零到 640(否则 writeAudio 报错、会话卡死)。
  for (let off = 0; off < e.nbytes; off += FRAME_BYTES) {
    const end = Math.min(off + FRAME_BYTES, e.nbytes);
    const frame = new Uint8Array(FRAME_BYTES);   // 默认全 0
    frame.set(bytes.subarray(off, end));
    engine.writeAudio(sid, frame.buffer as ArrayBuffer);
  }
  engine.finish(sid);
  const finishAt = Date.now();
  await listener.waitComplete(8000);
  const firstPartialMs = listener.firstResultAt > 0 ? listener.firstResultAt - startAt : -1;
  const finishToCompleteMs = listener.completeAt > 0 ? listener.completeAt - finishAt : -1;
  const wallMs = listener.completeAt - startAt;
  const rtf = e.durMs > 0 ? Math.round(wallMs / e.durMs * 1000) / 1000 : -1;
  return [firstPartialMs, finishToCompleteMs, rtf, listener.finals > 0 ? 1 : 0];
}

function writeText(path: string, text: string): void {
  const b = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i++) b[i] = text.charCodeAt(i) & 0x7F;
  const fp = fs.openSync(path, fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
  try { fs.writeSync(fp.fd, b.buffer); } finally { fs.closeSync(fp); }
}

// 逐轮追加到文件(hilog buffer 会滚动丢早期轮次,文件不会)。
function appendLine(path: string, text: string): void {
  const b = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i++) b[i] = text.charCodeAt(i) & 0x7F;
  const fp = fs.openSync(path, fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.APPEND);
  try { fs.writeSync(fp.fd, b.buffer); } finally { fs.closeSync(fp); }
}

const STRESS_UTT_PER_ITER: number = 3;   // 每轮喂几条音频量 RTF(重复冷加载才是主发热源)

export async function runLifecycleBench(context: common.UIAbilityContext,
  options: LifecycleBenchOptions): Promise<void> {
  let status = 'PASS';
  let fatal = '';
  const pk = options.disablePrepack ? 'off' : 'on';
  const summary: string[] = [];
  let iterOk = 0;
  try {
    if (options.resultPath.length === 0) throw new Error('resultPath required');
    const workPath = `${context.filesDir}/dingqiao_work`;
    SpeechRecognizeSdk.setWorkPath(workPath);
    try { writeText(`${options.resultPath}.iters`, ''); } catch (e) { /* ignore */ }

    // 运行时侧:setLicense 内部完成 runtime init(甲方冷启动首帧的运行时代价)
    let s = Date.now();
    const lic = await activateLicense(prepareLicense(context, workPath));
    const setLicenseMs = Date.now() - s;
    if (lic.errorCode !== 0) throw new Error(`license-${lic.errorCode}`);

    // prepareRuntime 幂等 + 运行时净内存(全新运行时,未加载模型)
    s = Date.now(); const ok1 = await prepareRuntime();
    const prepMs = Date.now() - s;
    const pm = procMem();        // 运行时常驻态(全新运行时,未加载模型)/proc 权威
    await prepareRuntime();      // 再调一次验幂等

    summary.push(`carrierBaselineVmRss=${options.carrierBaselinePss}`);
    summary.push(`carrierBaselineAnon=${options.carrierBaselineAnon}`);
    summary.push(`setLicenseRuntimeInitMs=${setLicenseMs}`);
    summary.push(`prepareRuntimeMs=${prepMs}|prepareRuntimeIdempotent=${ok1}`);
    summary.push(`runtimeResidentVmRss=${pm[0]}|runtimeResidentAnon=${pm[1]}|runtimeResidentFile=${pm[2]}`);

    const man = readManifest(context);
    const rfd = await context.resourceManager.getRawFileDescriptor('asr_eval/pcm.bin');
    const iters = options.iters;
    try {
      // 压测循环:重复「createEngine 冷加载 → 推理 → unloadModel」N 轮,heat SoC(USB 充电已关=电池)。
      // 每轮所有 PSS 为总进程占用(绝对 PSS);主机侧 = demo基线 / 总 / SDK净(相减)三视图 + p50/p95 + 首末轮热漂移。
      for (let it = 0; it < iters; it++) {
        s = Date.now();
        const e1 = await createEngineAsync(makeParams(options.disablePrepack));
        const coldMs = Date.now() - s;
        if (e1.engine === undefined) throw new Error(`iter${it}-create-${e1.errorCode}`);
        const engine = e1.engine;
        const cm = procMem();
        const coldVmRss = cm[0], coldAnon = cm[1], coldFile = cm[2];

        let firstSum = 0, rtfSum = 0, ok = 0, peakVmRss = coldVmRss, peakAnon = coldAnon;
        for (let u = 0; u < STRESS_UTT_PER_ITER && u < man.length; u++) {
          const r = await feedOne(engine, `it${it}_${u}`, rfd.fd, rfd.offset, man[u]);
          if (r[3] === 1) { firstSum += r[0]; rtfSum += r[2]; ok += 1; }
          const m = procMem();
          if (m[0] > peakVmRss) peakVmRss = m[0];
          if (m[1] > peakAnon) peakAnon = m[1];
        }
        const firstAvg = ok > 0 ? Math.round(firstSum / ok * 10) / 10 : -1;
        const rtfAvg = ok > 0 ? Math.round(rtfSum / ok * 1000) / 1000 : -1;

        // ② 复用命中(同配置再 createEngine,量复用延迟)
        s = Date.now();
        const e2 = await createEngineAsync(makeParams(options.disablePrepack));
        const reuseMs = Date.now() - s;
        if (e2.engine !== undefined) e2.engine.shutdown();

        engine.shutdown();

        // ③ unloadModel 释放模型 → 采卸载后内存(短延迟给 finalizer/GC)
        SpeechRecognizeSdk.unloadModel();
        await delay(400);
        const um = procMem();
        const unloadVmRss = um[0], unloadAnon = um[1];

        if (ok === STRESS_UTT_PER_ITER) iterOk += 1;
        // 每轮一条 LCITER。内存全部 /proc 权威:VmRss=总RSS;Anon=私有独占(OOM相关);File=mmap文件页(可换出)
        const iterLine =
          `LCITER|prepack=${pk}|iter=${it}|coldMs=${coldMs}|reuseMs=${reuseMs}|` +
          `firstMs=${firstAvg}|rtf=${rtfAvg}|inferOk=${ok}/${STRESS_UTT_PER_ITER}|` +
          `coldVmRss=${coldVmRss}|coldAnon=${coldAnon}|coldFile=${coldFile}|` +
          `peakVmRss=${peakVmRss}|peakAnon=${peakAnon}|` +
          `unloadVmRss=${unloadVmRss}|unloadAnon=${unloadAnon}`;
        hilog.info(DOMAIN, TAG, '%{public}s', iterLine);
        try { appendLine(`${options.resultPath}.iters`, iterLine + '\n'); } catch (e) { /* ignore */ }
      }
    } finally {
      context.resourceManager.closeRawFileDescriptor('asr_eval/pcm.bin');
    }

    // unloadRuntime(模型跟随)→ 终态内存
    SpeechRecognizeSdk.unloadRuntime();
    await delay(800);
    const fm = procMem();
    summary.push(`afterUnloadRuntimeVmRss=${fm[0]}|afterUnloadRuntimeAnon=${fm[1]}`);
    summary.push(`iters=${iters}|iterOk=${iterOk}`);
  } catch (e) {
    fatal = `${e}`.replace(/[^A-Za-z0-9_.:-]/g, '_').substring(0, 160);
    status = 'FAIL';
  }
  const line = `LIFECYCLE|version=3|status=${status}|prepack=${pk}|` +
    summary.join('|') + `|fatal=${fatal}\n`;
  try { writeText(options.resultPath, line); } catch (e) {
    hilog.error(DOMAIN, TAG, 'result write failed: %{public}s', `${e}`);
  }
  hilog.info(DOMAIN, TAG, '%{public}s', line);
}
