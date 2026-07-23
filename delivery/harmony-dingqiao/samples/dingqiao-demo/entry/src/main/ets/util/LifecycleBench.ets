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

// 两级加载生命周期 + 全链路延迟/内存 bench(demo 侧,非 SDK)。驱动 setLicense(只验权) →
// prepareRuntime → createEngine → 推理 → engine.shutdown → unloadModel → unloadRuntime。
// 输出均为 /proc 的进程绝对值;载体基线由 EntryAbility 在任何 SDK 调用前采样并传入,
// 主机后处理使用「阶段绝对值 − 载体基线」计算 SDK 净增量,避免把 Demo/ArkUI 共享内存算入 SDK。

const TAG: string = 'LifecycleBench';
const DOMAIN: number = 0x0000;
const SR: number = 16000;
const FRAME_BYTES: number = 640;   // 20ms @ 16kHz 16bit mono
const INFER_UTTERANCES: number = 12;

export class LifecycleBenchOptions {
  resultPath: string = '';
  disablePrepack: boolean = false;
  carrierBaselinePss: number = 0;   // 历史字段名;实际传入 SDK init 前的 VmRSS
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

// 一条会话的全链路指标。内存均是调用返回后立即采样的进程绝对值(MB)。
class InferMetrics {
  firstPartialMs: number = -1;
  finishToCompleteMs: number = -1;
  inferWallMs: number = -1;
  rtf: number = -1;
  ok: number = 0;

  startListeningMs: number = 0;
  startListeningVmRssMb: number = -1;
  startListeningRssAnonMb: number = -1;
  startListeningRssFileMb: number = -1;

  finishMs: number = 0;
  finishVmRssMb: number = -1;
  finishRssAnonMb: number = -1;
  finishRssFileMb: number = -1;

  inferCompleteVmRssMb: number = -1;
  inferCompleteRssAnonMb: number = -1;
  inferCompleteRssFileMb: number = -1;
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
    if (this.completeAt >= 0) return Promise.resolve();
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
async function feedOne(engine: SpeechRecognitionEngine, sid: string, blobFd: number,
  rawBase: number, e: ManifestEntry): Promise<InferMetrics> {
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
  const startCallAt = Date.now();
  engine.startListening(sp);
  const startListeningMs = Date.now() - startCallAt;
  const startListeningMem = procMem();
  // 契约要求每帧正好 640 字节:尾帧不满则补零到 640(否则 writeAudio 报错、会话卡死)。
  for (let off = 0; off < e.nbytes; off += FRAME_BYTES) {
    const end = Math.min(off + FRAME_BYTES, e.nbytes);
    const frame = new Uint8Array(FRAME_BYTES);   // 默认全 0
    frame.set(bytes.subarray(off, end));
    engine.writeAudio(sid, frame.buffer as ArrayBuffer);
  }
  const finishCallAt = Date.now();
  engine.finish(sid);
  const finishAt = Date.now();
  const finishMs = finishAt - finishCallAt;
  const finishMem = procMem();
  await listener.waitComplete(8000);
  const inferCompleteMem = procMem();
  const firstPartialMs = listener.firstResultAt > 0 ? listener.firstResultAt - startAt : -1;
  const finishToCompleteMs = listener.completeAt > 0 ? listener.completeAt - finishAt : -1;
  const wallMs = listener.completeAt > 0 ? listener.completeAt - startAt : -1;
  const rtf = e.durMs > 0 ? Math.round(wallMs / e.durMs * 1000) / 1000 : -1;
  const out = new InferMetrics();
  out.firstPartialMs = firstPartialMs;
  out.finishToCompleteMs = finishToCompleteMs;
  out.inferWallMs = wallMs;
  out.rtf = rtf;
  out.ok = listener.finals > 0 ? 1 : 0;
  out.startListeningMs = startListeningMs;
  out.startListeningVmRssMb = startListeningMem[0];
  out.startListeningRssAnonMb = startListeningMem[1];
  out.startListeningRssFileMb = startListeningMem[2];
  out.finishMs = finishMs;
  out.finishVmRssMb = finishMem[0];
  out.finishRssAnonMb = finishMem[1];
  out.finishRssFileMb = finishMem[2];
  out.inferCompleteVmRssMb = inferCompleteMem[0];
  out.inferCompleteRssAnonMb = inferCompleteMem[1];
  out.inferCompleteRssFileMb = inferCompleteMem[2];
  return out;
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

const STRESS_UTT_PER_ITER: number = 1;   // 交付口径:每轮只起一个实际会话

export async function runLifecycleBench(context: common.UIAbilityContext,
  options: LifecycleBenchOptions): Promise<void> {
  let status = 'PASS';
  let fatal = '';
  const pk = options.disablePrepack ? 'off' : 'on';
  const summary: string[] = [];
  let iterOk = 0;
  try {
    if (options.resultPath.length === 0) throw new Error('resultPath required');
    const workPath = `${context.filesDir}/amphion_asr_work`;
    SpeechRecognizeSdk.setWorkPath(workPath);
    try { writeText(`${options.resultPath}.iters`, ''); } catch (e) { /* ignore */ }

    summary.push(`carrierBaselineVmRssMb=${options.carrierBaselinePss}`);
    summary.push(`carrierBaselineRssAnonMb=${options.carrierBaselineAnon}`);

    // EntryAbility 已调 SDK init;在 Demo license 文件 IO 前先采 SDK init 后的边界值。
    const afterSdkInitMem = procMem();
    summary.push(`afterSdkInitVmRssMb=${afterSdkInitMem[0]}|` +
      `afterSdkInitRssAnonMb=${afterSdkInitMem[1]}|` +
      `afterSdkInitRssFileMb=${afterSdkInitMem[2]}`);

    // 再准备 license 文件并采 beforeSetLicense,避免把 Demo 文件 IO 计入 setLicense 耗时/净增量。
    const licensePath = prepareLicense(context, workPath);
    const beforeSetLicenseMem = procMem();
    summary.push(`beforeSetLicenseVmRssMb=${beforeSetLicenseMem[0]}|` +
      `beforeSetLicenseRssAnonMb=${beforeSetLicenseMem[1]}|` +
      `beforeSetLicenseRssFileMb=${beforeSetLicenseMem[2]}`);

    // setLicense 只验权/缓存授权,不启动 Runtime。
    let s = Date.now();
    const lic = await activateLicense(licensePath);
    const setLicenseMs = Date.now() - s;
    const setLicenseMem = procMem();
    if (lic.errorCode !== 0) throw new Error(`license-${lic.errorCode}`);
    summary.push(`setLicenseMs=${setLicenseMs}|` +
      `setLicenseImmediateVmRssMb=${setLicenseMem[0]}|` +
      `setLicenseImmediateRssAnonMb=${setLicenseMem[1]}|` +
      `setLicenseImmediateRssFileMb=${setLicenseMem[2]}`);

    // 第一次 prepareRuntime 是冷加载;第二次单独量幂等命中。两次均在返回后立即采内存。
    s = Date.now();
    const prepareColdOk = await prepareRuntime();
    const prepareRuntimeColdMs = Date.now() - s;
    const prepareColdMem = procMem();
    if (!prepareColdOk) throw new Error('prepare-runtime-cold');
    s = Date.now();
    const prepareIdempotentOk = await prepareRuntime();
    const prepareRuntimeIdempotentMs = Date.now() - s;
    const prepareIdempotentMem = procMem();
    if (!prepareIdempotentOk) throw new Error('prepare-runtime-idempotent');
    summary.push(`prepareRuntimeColdMs=${prepareRuntimeColdMs}|prepareRuntimeColdOk=${prepareColdOk}|` +
      `prepareRuntimeColdImmediateVmRssMb=${prepareColdMem[0]}|` +
      `prepareRuntimeColdImmediateRssAnonMb=${prepareColdMem[1]}|` +
      `prepareRuntimeColdImmediateRssFileMb=${prepareColdMem[2]}`);
    summary.push(`prepareRuntimeIdempotentMs=${prepareRuntimeIdempotentMs}|` +
      `prepareRuntimeIdempotentOk=${prepareIdempotentOk}|` +
      `prepareRuntimeIdempotentImmediateVmRssMb=${prepareIdempotentMem[0]}|` +
      `prepareRuntimeIdempotentImmediateRssAnonMb=${prepareIdempotentMem[1]}|` +
      `prepareRuntimeIdempotentImmediateRssFileMb=${prepareIdempotentMem[2]}`);

    const man = readManifest(context);
    const rfd = await context.resourceManager.getRawFileDescriptor('asr_eval/pcm.bin');
    const iters = options.iters;
    try {
      // 代码仍支持多轮,交付单次链路由主机传 iters=1。所有内存都是进程绝对值。
      for (let it = 0; it < iters; it++) {
        s = Date.now();
        const e1 = await createEngineAsync(makeParams(options.disablePrepack));
        const modelCreateColdMs = Date.now() - s;
        if (e1.engine === undefined) throw new Error(`iter${it}-create-${e1.errorCode}`);
        const engine = e1.engine;
        const modelColdMem = procMem();

        let firstSum = 0;
        let rtfSum = 0;
        let ok = 0;
        let peakVmRss = modelColdMem[0];
        let peakAnon = modelColdMem[1];
        let peakFile = modelColdMem[2];
        let firstSession = new InferMetrics();
        for (let u = 0; u < STRESS_UTT_PER_ITER && u < man.length; u++) {
          const r = await feedOne(engine, `it${it}_${u}`, rfd.fd, rfd.offset, man[u]);
          if (u === 0) firstSession = r;
          if (r.ok === 1) {
            firstSum += r.firstPartialMs;
            rtfSum += r.rtf;
            ok += 1;
          }
          const m = procMem();
          if (m[0] > peakVmRss) peakVmRss = m[0];
          if (m[1] > peakAnon) peakAnon = m[1];
          if (m[2] > peakFile) peakFile = m[2];
        }
        const firstAvg = ok > 0 ? Math.round(firstSum / ok * 10) / 10 : -1;
        const rtfAvg = ok > 0 ? Math.round(rtfSum / ok * 1000) / 1000 : -1;

        // 推理完成后先销毁实例;模型仍常驻,然后单独测同配置模型复用。
        s = Date.now();
        engine.shutdown();
        const engineShutdownMs = Date.now() - s;
        const engineShutdownMem = procMem();

        s = Date.now();
        const e2 = await createEngineAsync(makeParams(options.disablePrepack));
        const modelCreateReuseMs = Date.now() - s;
        const reuseEngine = e2.engine;
        if (reuseEngine === undefined) throw new Error(`iter${it}-reuse-${e2.errorCode}`);
        const modelReuseMem = procMem();

        s = Date.now();
        reuseEngine.shutdown();
        const reuseEngineShutdownMs = Date.now() - s;
        const reuseEngineShutdownMem = procMem();

        // unloadModel: API 返回后立即采样;另保留 400ms settled 值,不与调用耗时混在一起。
        s = Date.now();
        SpeechRecognizeSdk.unloadModel();
        const unloadModelMs = Date.now() - s;
        const unloadModelImmediateMem = procMem();
        await delay(400);
        const unloadModelSettledMem = procMem();

        if (ok === STRESS_UTT_PER_ITER) iterOk += 1;
        // 每轮一条 LCITER。VmRSS/RssAnon/RssFile 均为 MB 绝对值;主机侧再扣载体基线。
        const iterLine =
          `LCITER|prepack=${pk}|iter=${it}|modelCreateColdMs=${modelCreateColdMs}|` +
          `modelColdImmediateVmRssMb=${modelColdMem[0]}|modelColdImmediateRssAnonMb=${modelColdMem[1]}|` +
          `modelColdImmediateRssFileMb=${modelColdMem[2]}|` +
          `startListeningMs=${firstSession.startListeningMs}|` +
          `startListeningImmediateVmRssMb=${firstSession.startListeningVmRssMb}|` +
          `startListeningImmediateRssAnonMb=${firstSession.startListeningRssAnonMb}|` +
          `startListeningImmediateRssFileMb=${firstSession.startListeningRssFileMb}|` +
          `finishMs=${firstSession.finishMs}|finishImmediateVmRssMb=${firstSession.finishVmRssMb}|` +
          `finishImmediateRssAnonMb=${firstSession.finishRssAnonMb}|` +
          `finishImmediateRssFileMb=${firstSession.finishRssFileMb}|` +
          `inferWallMs=${firstSession.inferWallMs}|firstPartialMs=${firstSession.firstPartialMs}|` +
          `finishToCompleteMs=${firstSession.finishToCompleteMs}|rtf=${rtfAvg}|` +
          `inferCompleteImmediateVmRssMb=${firstSession.inferCompleteVmRssMb}|` +
          `inferCompleteImmediateRssAnonMb=${firstSession.inferCompleteRssAnonMb}|` +
          `inferCompleteImmediateRssFileMb=${firstSession.inferCompleteRssFileMb}|` +
          `inferOk=${ok}/${STRESS_UTT_PER_ITER}|firstMs=${firstAvg}|` +
          `peakVmRssMb=${peakVmRss}|peakRssAnonMb=${peakAnon}|peakRssFileMb=${peakFile}|` +
          `engineShutdownMs=${engineShutdownMs}|engineShutdownImmediateVmRssMb=${engineShutdownMem[0]}|` +
          `engineShutdownImmediateRssAnonMb=${engineShutdownMem[1]}|` +
          `engineShutdownImmediateRssFileMb=${engineShutdownMem[2]}|` +
          `modelCreateReuseMs=${modelCreateReuseMs}|modelReuseImmediateVmRssMb=${modelReuseMem[0]}|` +
          `modelReuseImmediateRssAnonMb=${modelReuseMem[1]}|modelReuseImmediateRssFileMb=${modelReuseMem[2]}|` +
          `reuseEngineShutdownMs=${reuseEngineShutdownMs}|` +
          `reuseEngineShutdownImmediateVmRssMb=${reuseEngineShutdownMem[0]}|` +
          `reuseEngineShutdownImmediateRssAnonMb=${reuseEngineShutdownMem[1]}|` +
          `reuseEngineShutdownImmediateRssFileMb=${reuseEngineShutdownMem[2]}|` +
          `unloadModelMs=${unloadModelMs}|unloadModelImmediateVmRssMb=${unloadModelImmediateMem[0]}|` +
          `unloadModelImmediateRssAnonMb=${unloadModelImmediateMem[1]}|` +
          `unloadModelImmediateRssFileMb=${unloadModelImmediateMem[2]}|` +
          `unloadModelSettledVmRssMb=${unloadModelSettledMem[0]}|` +
          `unloadModelSettledRssAnonMb=${unloadModelSettledMem[1]}|` +
          `unloadModelSettledRssFileMb=${unloadModelSettledMem[2]}`;
        hilog.info(DOMAIN, TAG, '%{public}s', iterLine);
        try { appendLine(`${options.resultPath}.iters`, iterLine + '\n'); } catch (e) { /* ignore */ }
      }
    } finally {
      context.resourceManager.closeRawFileDescriptor('asr_eval/pcm.bin');
    }

    // unloadRuntime 同样分开 API 调用耗时、immediate 和 settled 内存。
    s = Date.now();
    SpeechRecognizeSdk.unloadRuntime();
    const unloadRuntimeMs = Date.now() - s;
    const unloadRuntimeImmediateMem = procMem();
    await delay(800);
    const unloadRuntimeSettledMem = procMem();
    summary.push(`unloadRuntimeMs=${unloadRuntimeMs}|` +
      `unloadRuntimeImmediateVmRssMb=${unloadRuntimeImmediateMem[0]}|` +
      `unloadRuntimeImmediateRssAnonMb=${unloadRuntimeImmediateMem[1]}|` +
      `unloadRuntimeImmediateRssFileMb=${unloadRuntimeImmediateMem[2]}|` +
      `unloadRuntimeSettledVmRssMb=${unloadRuntimeSettledMem[0]}|` +
      `unloadRuntimeSettledRssAnonMb=${unloadRuntimeSettledMem[1]}|` +
      `unloadRuntimeSettledRssFileMb=${unloadRuntimeSettledMem[2]}`);
    summary.push(`iters=${iters}|iterOk=${iterOk}`);
  } catch (e) {
    fatal = `${e}`.replace(/[^A-Za-z0-9_.:-]/g, '_').substring(0, 160);
    status = 'FAIL';
  }
  const line = `LIFECYCLE|version=4|status=${status}|prepack=${pk}|` +
    summary.join('|') + `|fatal=${fatal}\n`;
  try { writeText(options.resultPath, line); } catch (e) {
    hilog.error(DOMAIN, TAG, 'result write failed: %{public}s', `${e}`);
  }
  hilog.info(DOMAIN, TAG, '%{public}s', line);
}
