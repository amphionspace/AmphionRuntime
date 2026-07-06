import application from '@ohos.app.ability.application';
import common from '@ohos.app.ability.common';
import fs from '@ohos.file.fs';
import picker from '@ohos.file.picker';
import textToSpeech from '@hms.ai.textToSpeech';

const TAG: string = 'HmsSeedTTS';
const DEFAULT_SAMPLE_RATE: number = 16000;
const DEFAULT_SAMPLE_BIT: number = 16;
const DEFAULT_AUDIO_CHANNEL: number = 1;
const TIMEOUT_MS: number = 90000;
const TAR_BLOCK_SIZE: number = 512;
const COPY_BUFFER_SIZE: number = 1024 * 1024;
const EVAL_CASES_RAWFILE: string = 'hms_native_eval_cases.jsonl';

interface SeedTtsCase {
  case_id: string;
  text: string;
}

interface HmsSeedMetric {
  model_id: string;
  case_id: string;
  status: string;
  error: string;
  wav_path: string;
  sample_rate: number;
  sample_bit: number;
  audio_channel: number;
  first_audio_ms: number;
  synthesis_ms: number;
  audio_duration_ms: number;
  rtf: number;
  chunk_count: number;
  audio_bytes: number;
}

interface PendingRun {
  resolve: (value: HmsSeedMetric) => void;
  testCase: SeedTtsCase;
  requestId: string;
  startedAtMs: number;
  firstDataAtMs: number;
  sampleRate: number;
  sampleBit: number;
  audioChannel: number;
  chunks: Map<number, ArrayBuffer>;
  bytes: number;
  chunkCount: number;
  timer: number;
  done: boolean;
}

const SEEDTTS_ZH_CASES: Array<SeedTtsCase> = [
  {case_id: "zh_en_bench_001", text: "周末我们去周边的 city walk 吧，找个小众的巷子逛一逛拍拍照。"},
  {case_id: "zh_en_bench_002", text: "这个 offer 的薪资和福利都超预期，我纠结了好久还是决定接了。"},
  {case_id: "zh_en_bench_003", text: "这个月的 KPI 还差一大截，我最近天天加班到深夜，人都快熬废了。"},
  {case_id: "zh_en_bench_004", text: "这个新版本 bug 也太多了，动不动就闪退，体验感真的太差了。"},
  {case_id: "zh_en_bench_005", text: "你帮我看看这个 email 的措辞有没有问题？我要发给国外的客户，怕不礼貌。"},
  {case_id: "zh_en_bench_006", text: "我们这个 team 的氛围真的超好，大家都很 nice，完全没有职场内耗。"},
  {case_id: "zh_en_bench_007", text: "我们这周要团建，leader 说让大家投票选想去的地方。"},
  {case_id: "zh_en_bench_008", text: "我最近在剪 vlog ，记录一下日常的生活，还挺有意思的。"},
  {case_id: "zh_en_bench_009", text: "这家店的 wifi 信号也太差了，刷个视频都半天加载不出来。"},
  {case_id: "zh_en_bench_010", text: "我上学期也系统学习了 Python，"},
  {case_id: "zh_en_bench_011", text: "平时会做不少和 AI 相关的项目与实践。"},
  {case_id: "zh_en_bench_012", text: "我们统计专业本来就要求掌握 R 语言，是专业必备的工具之一。"},
  {case_id: "zh_en_bench_013", text: "身边不少同学也都在用 Mac 设备，用来编程学习特别方便。"},
  {case_id: "zh_en_bench_014", text: "我最近看了一篇相关的 paper，里面提到的理论刚好可以套用在我们的项目里。"},
  {case_id: "zh_en_bench_015", text: "数据分析熟练掌握 Excel，效率能翻倍。"},
  {case_id: "zh_en_bench_016", text: "这个事情就交给你了！no problem!"},
  {case_id: "zh_en_bench_017", text: "这次的项目 deadline 快到了，我们得加快进度赶一赶。"},
  {case_id: "zh_en_bench_018", text: "把整理好的资料今晚发给我就行，ok。"},
  {case_id: "zh_en_bench_019", text: "我这会儿正在跟我的 crush 聊天"},
  {case_id: "zh_en_bench_020", text: "我刚才突然 get 到了你那句话的笑点，真的太搞笑了。"},
  {case_id: "zh_en_bench_021", text: "你这身穿搭今天看起来真的很 low，赶紧回去换一套吧。"},
  {case_id: "zh_en_bench_022", text: "我现在主要是做 Web 前端开发，每天都在跟代码打交道。"},
  {case_id: "zh_en_bench_023", text: "刚才老板开会让大家头脑风暴，你有什么好的 idea 吗？"},
  {case_id: "zh_en_bench_024", text: "这个方案被老板 pass 了，让我们明天重新想一个方向。"},
  {case_id: "zh_en_bench_025", text: "昨天晚上的 party 你怎么没来？大家都问你呢。"},
  {case_id: "zh_en_bench_026", text: "这个文件你直接 copy 到U盘里带过去就行了，不用打印。"},
  {case_id: "zh_en_bench_027", text: "这个歌手的 live 现场太震撼了，比听录音室版本燃多了。"},
  {case_id: "zh_en_bench_028", text: "你下午有空帮我 cover 一下工作吗？我有点私事要出去一趟。"},
  {case_id: "zh_en_bench_029", text: "你这个 PPT 的排版太拥挤了，得改改。"},
  {case_id: "zh_en_bench_030", text: "go go go出发了"},
  {case_id: "zh_en_bench_031", text: "我是你们play的一环吗"},
  {case_id: "zh_en_bench_032", text: "接下来专属他的 solo 高光时刻开启！"},
  {case_id: "zh_en_bench_033", text: "我正在学习 SQL 数据库查询，做数据分析必备技能。"},
  {case_id: "zh_en_bench_034", text: "我超级喜欢这种 ins 风的装修，温柔又有氛围感。"},
  {case_id: "zh_en_bench_035", text: "这款 app 的 UI 设计太好看了，简约又高级。"},
  {case_id: "zh_en_bench_036", text: "这个项目进度落后了，我们得赶紧 push 一下。"},
  {case_id: "zh_en_bench_037", text: "真心受不了那种待人很 mean 的女生"},
  {case_id: "zh_en_bench_038", text: "oh my god，好好一件事全被你搞砸了。"},
  {case_id: "zh_en_bench_039", text: "这个视频的 BGM 是什么啊？听起来好有感觉，求分享！"},
  {case_id: "zh_en_bench_040", text: "这个展的 VIP 票太值了，不用排队还能拿到限定周边。"},
  {case_id: "zh_en_bench_041", text: "这个理发的 Tony 老师完全不听我说话，剪得太短了。"},
  {case_id: "zh_en_bench_042", text: "你的声音好好听，要不要一起去唱 K？我请你。"},
  {case_id: "zh_en_bench_043", text: "我最近在学插花，发现这也是一门技术活，没那么 easy。"},
  {case_id: "zh_en_bench_044", text: "你的英语平时是怎么练习的？有没有什么 tips？"},
  {case_id: "zh_en_bench_045", text: "你能不能别总是那么 push 我？我自己有分寸的。"},
  {case_id: "zh_en_bench_046", text: "这个品牌的 marketing 策略真的很成功，全网都在刷。"},
  {case_id: "zh_en_bench_047", text: "今天碰到了一个超级 nice 的出租车司机，聊了一路。"},
  {case_id: "zh_en_bench_048", text: "秋招果断 all in 大模型，专注赛道，全力冲刺。"},
  {case_id: "zh_en_bench_049", text: "我已经把详情发到你邮箱了，记得 check 一下。"},
  {case_id: "zh_en_bench_050", text: "拜托别总是 emo 了，生活总得往前看呀。"},
];

class TarWriter {
  private file: fs.File | undefined = undefined;
  private readonly tarPath: string;

  constructor(tarPath: string) {
    this.tarPath = tarPath;
    ensureDirectory(parentDir(tarPath));
    this.file = fs.openSync(tarPath, fs.OpenMode.CREATE | fs.OpenMode.WRITE_ONLY | fs.OpenMode.TRUNC);
  }

  append(fileName: string, content: Uint8Array): void {
    const file = this.file;
    if (file === undefined) {
      throw new Error('tar writer closed');
    }
    writeBytes(file.fd, buildTarHeader(fileName, content.byteLength));
    writeBytes(file.fd, content);
    const padding = (TAR_BLOCK_SIZE - (content.byteLength % TAR_BLOCK_SIZE)) % TAR_BLOCK_SIZE;
    if (padding > 0) {
      writeBytes(file.fd, new Uint8Array(padding));
    }
  }

  finish(): void {
    const file = this.file;
    if (file === undefined) {
      return;
    }
    try {
      writeBytes(file.fd, new Uint8Array(TAR_BLOCK_SIZE * 2));
    } finally {
      fs.closeSync(file);
      this.file = undefined;
    }
  }
}

class HmsSeedTtsListener implements textToSpeech.SpeakListener {
  private pending: PendingRun | undefined = undefined;
  private readonly tarWriter: TarWriter;
  private readonly tarPath: string;

  constructor(tarWriter: TarWriter, tarPath: string) {
    this.tarWriter = tarWriter;
    this.tarPath = tarPath;
  }

  run(engine: textToSpeech.TextToSpeechEngine, testCase: SeedTtsCase): Promise<HmsSeedMetric> {
    const requestId = `hms-seedtts-${Date.now()}-${testCase.case_id}`;
    return new Promise<HmsSeedMetric>((resolve) => {
      const startedAtMs = Date.now();
      const pending: PendingRun = {
        resolve,
        testCase,
        requestId,
        startedAtMs,
        firstDataAtMs: 0,
        sampleRate: DEFAULT_SAMPLE_RATE,
        sampleBit: DEFAULT_SAMPLE_BIT,
        audioChannel: DEFAULT_AUDIO_CHANNEL,
        chunks: new Map<number, ArrayBuffer>(),
        bytes: 0,
        chunkCount: 0,
        timer: 0,
        done: false
      };
      pending.timer = setTimeout((): void => {
        if (!pending.done) {
          pending.done = true;
          resolve(metricFrom(pending, 'timeout', 'timeout', `${this.tarPath}:${pending.testCase.case_id}.wav`));
          this.pending = undefined;
        }
      }, TIMEOUT_MS);
      this.pending = pending;
      try {
        engine.speak(testCase.text, {
          requestId,
          extraParams: {
            queueMode: 0,
            speed: 1,
            volume: 1,
            pitch: 1,
            languageContext: 'zh-CN',
            playType: 0
          }
        } as textToSpeech.SpeakParams);
      } catch (error) {
        pending.done = true;
        clearTimeout(pending.timer);
        const message = error instanceof Error ? error.message : String(error);
        resolve(metricFrom(pending, 'error', `speak failed: ${message}`, ''));
        this.pending = undefined;
      }
    });
  }

  onStart(requestId: string, response: textToSpeech.StartResponse): void {
    const pending = this.pending;
    if (pending === undefined || requestId !== pending.requestId) {
      return;
    }
    pending.sampleRate = response.sampleRate > 0 ? response.sampleRate : DEFAULT_SAMPLE_RATE;
    pending.sampleBit = response.sampleBit > 0 ? response.sampleBit : DEFAULT_SAMPLE_BIT;
    pending.audioChannel = resolvePcmChannelCount(response.audioChannel);
  }

  onData(requestId: string, audio: ArrayBuffer, response: textToSpeech.SynthesisResponse): void {
    const pending = this.pending;
    if (pending === undefined || pending.done || requestId !== pending.requestId) {
      return;
    }
    if (pending.firstDataAtMs === 0) {
      pending.firstDataAtMs = Date.now();
    }
    pending.chunks.set(response.sequence, cloneArrayBuffer(audio));
    pending.bytes += audio.byteLength;
    pending.chunkCount += 1;
  }

  onComplete(requestId: string, _response: textToSpeech.CompleteResponse): void {
    const pending = this.pending;
    if (pending === undefined || pending.done || requestId !== pending.requestId) {
      return;
    }
    pending.done = true;
    clearTimeout(pending.timer);
    this.pending = undefined;
    this.completePending(pending);
  }

  private completePending(pending: PendingRun): void {
    const wavMemberName = `${pending.testCase.case_id}.wav`;
    try {
      const pcm = concatenateChunks(pending.chunks);
      const wav = buildWavFile(pcm, pending.sampleRate, pending.sampleBit, pending.audioChannel);
      this.tarWriter.append(wavMemberName, new Uint8Array(wav));
      pending.resolve(metricFrom(pending, 'ok', '', `${this.tarPath}:${wavMemberName}`));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      pending.resolve(metricFrom(pending, 'error', `tar append failed: ${message}`, `${this.tarPath}:${wavMemberName}`));
    }
  }

  onStop(requestId: string, response: textToSpeech.StopResponse): void {
    console.error(`[${TAG}] STOP ${JSON.stringify({ requestId, response })}`);
  }

  onError(requestId: string, errorCode: number, errorMessage: string): void {
    const pending = this.pending;
    if (pending === undefined || pending.done || requestId !== pending.requestId) {
      return;
    }
    pending.done = true;
    clearTimeout(pending.timer);
    pending.resolve(metricFrom(pending, 'error', `${errorCode}:${errorMessage}`, ''));
    this.pending = undefined;
  }
}

let hasRun: boolean = false;

export async function runHmsSeedTtsEvalOnce(context?: common.UIAbilityContext): Promise<void> {
  if (hasRun) {
    return;
  }
  hasRun = true;
  const cases = loadSeedTtsCases(EVAL_CASES_RAWFILE);
  const runId = `hms-native-local-python-asr-zh-en-mixed-dedup-474-person13-${Date.now()}`;
  const rootDir = joinPath(application.getApplicationContext().filesDir, 'hms-native-seedtts-eval', runId);
  ensureDirectory(rootDir);
  const tarPath = joinPath(rootDir, `${runId}.tar`);
  const metricsPath = joinPath(rootDir, 'metrics.jsonl');
  console.error(`[${TAG}] RUN_START ${JSON.stringify({ runId, total: cases.length, rootDir, tarPath, metricsPath })}`);

  const tarWriter = new TarWriter(tarPath);
  const engine = await createAvailableEngine();
  const listener = new HmsSeedTtsListener(tarWriter, tarPath);
  engine.setListener(listener);
  const metrics: Array<HmsSeedMetric> = [];
  try {
    for (let index = 0; index < cases.length; index += 1) {
      const item = cases[index];
      if (index % 20 === 0) {
        console.error(`[${TAG}] PROGRESS ${JSON.stringify({ runId, index, total: cases.length })}`);
      }
      const metric = await listener.run(engine, item);
      metrics.push(metric);
      console.error(`[${TAG}] RESULT ${JSON.stringify(metric)}`);
    }
  } finally {
    try {
      engine.shutdown();
    } catch (_error) {}
  }
  const metricsJsonl = metrics.map((item: HmsSeedMetric): string => JSON.stringify(item)).join('\n') + '\n';
  const summaryJson = JSON.stringify({
    runId,
    total: metrics.length,
    ok: metrics.filter((item: HmsSeedMetric): boolean => item.status === 'ok').length,
    error: metrics.filter((item: HmsSeedMetric): boolean => item.status !== 'ok').length,
    rootDir,
    tarPath,
    metricsPath
  });
  writeAsciiTextFile(metricsPath, metricsJsonl);
  tarWriter.append('metrics.jsonl', stringToUtf8(metricsJsonl));
  tarWriter.append('summary.json', stringToUtf8(`${summaryJson}\n`));
  tarWriter.finish();
  await saveTarWithPicker(context, runId, tarPath);
  console.error(`[${TAG}] SUMMARY ${summaryJson}`);
}

function loadSeedTtsCases(rawfileName: string): Array<SeedTtsCase> {
  try {
    const bytes = application.getApplicationContext().resourceManager.getRawFileContentSync(rawfileName);
    const text = utf8Decode(bytes);
    const cases: Array<SeedTtsCase> = [];
    text.split('\n').forEach((line: string): void => {
      const trimmed = line.trim();
      if (trimmed.length === 0) {
        return;
      }
      const value = JSON.parse(trimmed) as SeedTtsCase;
      if (value.case_id.length > 0 && value.text.length > 0) {
        cases.push(value);
      }
    });
    if (cases.length > 0) {
      return cases;
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`[${TAG}] LOAD_RAWFILE_FAILED ${JSON.stringify({ rawfileName, error: message })}`);
  }
  return SEEDTTS_ZH_CASES;
}

async function createAvailableEngine(): Promise<textToSpeech.TextToSpeechEngine> {
  for (const online of [1, 0]) {
    try {
      const voices = await textToSpeech.listVoices({ requestId: `hms-list-${Date.now()}-${online}`, online });
      console.error(`[${TAG}] VOICES ${JSON.stringify({ online, voices })}`);
      return await textToSpeech.createEngine({ language: 'zh-CN', person: 13, online });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error(`[${TAG}] CREATE_ENGINE_FAILED ${JSON.stringify({ online, error: message })}`);
    }
  }
  throw new Error('no available HMS TextToSpeech engine for zh-CN');
}

async function saveTarWithPicker(context: common.UIAbilityContext | undefined, runId: string, tarPath: string): Promise<void> {
  const directUri = `file://docs/storage/Users/currentUser/Download/${runId}.tar`;
  try {
    copyFile(tarPath, directUri);
    console.error(`[${TAG}] DIRECT_WRITE_DONE ${JSON.stringify({ uri: directUri })}`);
    return;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`[${TAG}] DIRECT_WRITE_FAILED ${JSON.stringify({ uri: directUri, error: message })}`);
  }
  if (context === undefined) {
    return;
  }
  try {
    const viewPicker = new picker.DocumentViewPicker(context);
    const options = new picker.DocumentSaveOptions();
    options.newFileNames = [`${runId}.tar`];
    options.fileSuffixChoices = ['TAR|.tar'];
    const uris = await viewPicker.save(options);
    console.error(`[${TAG}] PICKER_SAVE ${JSON.stringify({ requested: 1, uris })}`);
    if (uris.length > 0) {
      copyFile(tarPath, uris[0]);
      console.error(`[${TAG}] PICKER_WRITE_DONE ${JSON.stringify({ count: 1, uri: uris[0] })}`);
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`[${TAG}] PICKER_SAVE_FAILED ${JSON.stringify({ error: message })}`);
  }
}

function metricFrom(pending: PendingRun, status: string, error: string, wavPath: string): HmsSeedMetric {
  const completedAtMs = Date.now();
  const synthesisMs = completedAtMs - pending.startedAtMs;
  const bytesPerFrame = Math.max(1, pending.audioChannel) * Math.max(1, pending.sampleBit / 8);
  const audioDurationMs = pending.sampleRate > 0 ? pending.bytes * 1000 / (pending.sampleRate * bytesPerFrame) : 0;
  return {
    model_id: 'hms_native_texttospeech',
    case_id: pending.testCase.case_id,
    status,
    error,
    wav_path: wavPath,
    sample_rate: pending.sampleRate,
    sample_bit: pending.sampleBit,
    audio_channel: pending.audioChannel,
    first_audio_ms: pending.firstDataAtMs > 0 ? pending.firstDataAtMs - pending.startedAtMs : -1,
    synthesis_ms: synthesisMs,
    audio_duration_ms: audioDurationMs,
    rtf: audioDurationMs > 0 ? synthesisMs / audioDurationMs : -1,
    chunk_count: pending.chunkCount,
    audio_bytes: pending.bytes
  };
}

function resolvePcmChannelCount(audioChannel: number): number {
  if (audioChannel === 1 || audioChannel === 2) {
    return audioChannel;
  }
  return DEFAULT_AUDIO_CHANNEL;
}

function concatenateChunks(chunks: Map<number, ArrayBuffer>): ArrayBuffer {
  const keys = Array.from(chunks.keys()).sort((a: number, b: number): number => a - b);
  let total = 0;
  keys.forEach((key: number): void => { total += chunks.get(key)?.byteLength ?? 0; });
  const output = new Uint8Array(total);
  let offset = 0;
  keys.forEach((key: number): void => {
    const chunk = chunks.get(key);
    if (chunk !== undefined) {
      output.set(new Uint8Array(chunk), offset);
      offset += chunk.byteLength;
    }
  });
  return output.buffer;
}

function cloneArrayBuffer(source: ArrayBuffer): ArrayBuffer {
  const output = new Uint8Array(source.byteLength);
  output.set(new Uint8Array(source));
  return output.buffer;
}

function buildWavFile(pcm: ArrayBuffer, sampleRate: number, sampleBit: number, channels: number): ArrayBuffer {
  const bytesPerSample = Math.max(1, sampleBit / 8);
  const blockAlign = Math.max(1, channels) * bytesPerSample;
  const totalBytes = 44 + pcm.byteLength;
  const wav = new ArrayBuffer(totalBytes);
  const view = new DataView(wav);
  writeAscii(view, 0, 'RIFF');
  view.setUint32(4, 36 + pcm.byteLength, true);
  writeAscii(view, 8, 'WAVE');
  writeAscii(view, 12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * blockAlign, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, sampleBit, true);
  writeAscii(view, 36, 'data');
  view.setUint32(40, pcm.byteLength, true);
  new Uint8Array(wav, 44).set(new Uint8Array(pcm));
  return wav;
}

function buildTarHeader(fileName: string, size: number): Uint8Array {
  const header = new Uint8Array(TAR_BLOCK_SIZE);
  writeAsciiBytes(header, 0, fileName, 100);
  writeOctalBytes(header, 100, 8, 0o644);
  writeOctalBytes(header, 108, 8, 0);
  writeOctalBytes(header, 116, 8, 0);
  writeOctalBytes(header, 124, 12, size);
  writeOctalBytes(header, 136, 12, Math.floor(Date.now() / 1000));
  for (let index = 148; index < 156; index += 1) {
    header[index] = 0x20;
  }
  header[156] = 0x30;
  writeAsciiBytes(header, 257, 'ustar', 6);
  writeAsciiBytes(header, 263, '00', 2);
  let checksum = 0;
  for (let index = 0; index < TAR_BLOCK_SIZE; index += 1) {
    checksum += header[index];
  }
  writeChecksumBytes(header, checksum);
  return header;
}

function writeAsciiBytes(target: Uint8Array, offset: number, text: string, maxLength: number): void {
  const length = Math.min(text.length, maxLength);
  for (let index = 0; index < length; index += 1) {
    target[offset + index] = text.charCodeAt(index) & 0x7f;
  }
}

function writeOctalBytes(target: Uint8Array, offset: number, length: number, value: number): void {
  const text = Math.floor(value).toString(8).padStart(length - 1, '0');
  for (let index = 0; index < length - 1; index += 1) {
    target[offset + index] = text.charCodeAt(index);
  }
  target[offset + length - 1] = 0;
}

function writeChecksumBytes(target: Uint8Array, checksum: number): void {
  const text = checksum.toString(8).padStart(6, '0');
  for (let index = 0; index < 6; index += 1) {
    target[148 + index] = text.charCodeAt(index);
  }
  target[154] = 0;
  target[155] = 0x20;
}

function copyFile(sourcePath: string, targetPath: string): void {
  let source: fs.File | undefined = undefined;
  let target: fs.File | undefined = undefined;
  try {
    source = fs.openSync(sourcePath, fs.OpenMode.READ_ONLY);
    target = fs.openSync(targetPath, fs.OpenMode.CREATE | fs.OpenMode.WRITE_ONLY | fs.OpenMode.TRUNC);
    const buffer = new ArrayBuffer(COPY_BUFFER_SIZE);
    while (true) {
      const bytesRead = fs.readSync(source.fd, buffer);
      if (bytesRead <= 0) {
        break;
      }
      if (bytesRead === COPY_BUFFER_SIZE) {
        fs.writeSync(target.fd, buffer);
      } else {
        const chunk = new Uint8Array(bytesRead);
        chunk.set(new Uint8Array(buffer, 0, bytesRead));
        fs.writeSync(target.fd, chunk.buffer);
      }
    }
  } finally {
    if (source !== undefined) {
      fs.closeSync(source);
    }
    if (target !== undefined) {
      fs.closeSync(target);
    }
  }
}

function writeAscii(view: DataView, offset: number, text: string): void {
  for (let index = 0; index < text.length; index += 1) {
    view.setUint8(offset + index, text.charCodeAt(index));
  }
}

function writeBytes(fd: number, content: Uint8Array): void {
  if (content.byteOffset === 0 && content.byteLength === content.buffer.byteLength) {
    fs.writeSync(fd, content.buffer);
    return;
  }
  const copy = new Uint8Array(content.byteLength);
  copy.set(content);
  fs.writeSync(fd, copy.buffer);
}

function stringToUtf8(content: string): Uint8Array {
  const bytes = new Uint8Array(content.length);
  for (let index = 0; index < content.length; index += 1) {
    bytes[index] = content.charCodeAt(index) & 0xff;
  }
  return bytes;
}

function utf8Decode(bytes: Uint8Array): string {
  let output = '';
  let index = 0;
  while (index < bytes.length) {
    const first = bytes[index];
    if (first < 0x80) {
      output += String.fromCharCode(first);
      index += 1;
    } else if (first < 0xE0 && index + 1 < bytes.length) {
      const code = ((first & 0x1F) << 6) | (bytes[index + 1] & 0x3F);
      output += String.fromCharCode(code);
      index += 2;
    } else if (first < 0xF0 && index + 2 < bytes.length) {
      const code = ((first & 0x0F) << 12) | ((bytes[index + 1] & 0x3F) << 6) | (bytes[index + 2] & 0x3F);
      output += String.fromCharCode(code);
      index += 3;
    } else if (index + 3 < bytes.length) {
      const codePoint = ((first & 0x07) << 18) | ((bytes[index + 1] & 0x3F) << 12) | ((bytes[index + 2] & 0x3F) << 6) | (bytes[index + 3] & 0x3F);
      const adjusted = codePoint - 0x10000;
      output += String.fromCharCode(0xD800 + (adjusted >> 10), 0xDC00 + (adjusted & 0x3FF));
      index += 4;
    } else {
      index += 1;
    }
  }
  return output;
}

function writeAsciiTextFile(filePath: string, content: string): void {
  const bytes = stringToUtf8(content);
  ensureDirectory(parentDir(filePath));
  let file: fs.File | undefined = undefined;
  try {
    file = fs.openSync(filePath, fs.OpenMode.CREATE | fs.OpenMode.WRITE_ONLY | fs.OpenMode.TRUNC);
    writeBytes(file.fd, bytes);
  } finally {
    if (file !== undefined) {
      fs.closeSync(file);
    }
  }
}

function ensureDirectory(dirPath: string): void {
  if (dirPath.length === 0 || directoryExists(dirPath)) {
    return;
  }
  ensureDirectory(parentDir(dirPath));
  try {
    fs.mkdirSync(dirPath);
  } catch (_error) {}
}

function directoryExists(dirPath: string): boolean {
  try {
    return fs.accessSync(dirPath);
  } catch (_error) {
    return false;
  }
}

function parentDir(filePath: string): string {
  const index = filePath.lastIndexOf('/');
  return index <= 0 ? '' : filePath.substring(0, index);
}

function joinPath(...parts: Array<string>): string {
  return parts.map((part: string, index: number): string => index === 0 ? part.replace(/\/+$/g, '') : part.replace(/^\/+|\/+$/g, '')).filter((part: string): boolean => part.length > 0).join('/');
}
