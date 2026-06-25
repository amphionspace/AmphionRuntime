import { fileIo as fs } from '@kit.CoreFileKit';
import { buffer } from '@kit.ArkTS';
import { audio } from '@kit.AudioKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { CircularBuffer, OfflineTts, OfflineTtsConfig, TtsInput, listRawfileDir } from 'sherpa_onnx';
import { TtsAssetRegistry, TtsModelLayout } from './TtsAssetRegistry';
import {
  PlayType,
  RunMode,
  SpeakParams,
  TextToSpeechEngine,
  TextToSpeechListener,
  TtsCreateEngineParams,
  TtsErrorCode,
  TtsVoiceInfo
} from './TtsTypes';

interface TtsChunk {
  samples: Float32Array;
  progress: number;
}

function log(message: string): void {
  console.info(`[AmphionTts] ${message}`);
}

function mkdirRecursive(filesDir: string, relParts: string[]): void {
  let dir = filesDir;
  for (const part of relParts) {
    dir = `${dir}/${part}`;
    if (!fs.accessSync(dir)) {
      fs.mkdirSync(dir);
    }
  }
}

function copyRawfileToSandbox(context: Context, rawPath: string): void {
  const data: Uint8Array = context.resourceManager.getRawFileContentSync(rawPath);
  const filesDir: string = context.getApplicationContext().filesDir;
  const dst = `${filesDir}/${rawPath}`;
  if (fs.accessSync(dst)) {
    const stat = fs.statSync(dst);
    if (stat.size === data.length) {
      return;
    }
  }
  const fp = fs.openSync(dst, fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
  fs.writeSync(fp.fd, buffer.from(data).buffer);
  fs.close(fp.fd);
}

/**
 * 把 rawfile 子目录解包到应用沙箱，返回沙箱绝对路径。
 * `listRawfileDir` 返回的条目已包含 rawfile 根下的完整相对路径。
 */
function copyRawfileDirToSandbox(context: Context, rawDir: string): string {
  const filesDir: string = context.getApplicationContext().filesDir;
  const files: string[] = listRawfileDir(context.resourceManager, rawDir);
  for (const rel of files) {
    const parts: string[] = rel.split('/');
    if (parts.length > 1) {
      mkdirRecursive(filesDir, parts.slice(0, parts.length - 1));
    }
    copyRawfileToSandbox(context, rel);
  }
  return `${filesDir}/${rawDir}`;
}

class OfflineTtsEngineImpl implements TextToSpeechEngine {
  private context: Context;
  private params: TtsCreateEngineParams;
  private tts: OfflineTts;
  private listener?: TextToSpeechListener;
  private busy: boolean = false;
  private cancelled: boolean = false;
  private destroyed: boolean = false;
  // 内置播放（SYNTHESIZE_AND_PLAY）：合成线程 push、AudioRenderer 的 writeData 回调 pull。
  private renderer: audio.AudioRenderer | null = null;
  private playBuffer: CircularBuffer = new CircularBuffer(16000 * 5);
  private generating: boolean = false;
  private playEnabled: boolean = false;

  constructor(context: Context, params: TtsCreateEngineParams) {
    this.context = context;
    this.params = params;
    if (params.mode === RunMode.ONLINE) {
      log('ONLINE mode is unsupported on the HarmonyOS offline SDK; fallback to OFFLINE');
    }
    const layout = TtsAssetRegistry.layoutFor(params.voiceId);
    this.tts = new OfflineTts(this.buildConfig(layout), context.resourceManager);
  }

  setListener(listener: TextToSpeechListener): void {
    this.listener = listener;
  }

  speak(text: string, params: SpeakParams): void {
    if (this.destroyed) {
      this.listener?.onError?.(params.requestId, TtsErrorCode.ENGINE_DESTROYED, 'engine destroyed');
      return;
    }
    if (text.length === 0) {
      this.listener?.onError?.(params.requestId, TtsErrorCode.TEXT_LENGTH_INVALID, 'text is empty');
      return;
    }
    this.cancelled = false;
    this.busy = true;
    this.generating = true;
    this.playEnabled = params.playType === PlayType.SYNTHESIZE_AND_PLAY;
    if (this.playEnabled) {
      this.playBuffer = new CircularBuffer(16000 * 5);
      this.ensureRenderer();
    }
    this.listener?.onStart?.(params.requestId);
    this.synthesize(text, params);
  }

  stop(): void {
    this.cancelled = true;
    this.generating = false;
    if (this.renderer !== null && this.renderer.state === audio.AudioState.STATE_RUNNING) {
      this.renderer.stop();
    }
  }

  isBusy(): boolean {
    return this.busy;
  }

  shutdown(): void {
    this.destroyed = true;
    this.cancelled = true;
    this.busy = false;
    this.generating = false;
    if (this.renderer !== null) {
      this.renderer.release();
      this.renderer = null;
    }
  }

  private async synthesize(text: string, params: SpeakParams): Promise<void> {
    const input = new TtsInput();
    input.text = text;
    input.sid = params.sid;
    input.speed = params.speed;
    input.callback = (chunk: TtsChunk): number => {
      if (this.cancelled) {
        return 0;
      }
      this.listener?.onData?.(params.requestId, OfflineTtsEngineImpl.toPcm16(chunk.samples));
      if (this.playEnabled) {
        this.playBuffer.push(chunk.samples);
        if (this.renderer !== null && this.renderer.state !== audio.AudioState.STATE_RUNNING) {
          this.renderer.start();
        }
      }
      return 1;
    };

    try {
      await this.tts.generateAsync(input);
      this.busy = false;
      this.generating = false;
      if (this.cancelled) {
        this.listener?.onStop?.(params.requestId);
      } else {
        this.listener?.onComplete?.(params.requestId);
      }
    } catch (e) {
      this.busy = false;
      this.generating = false;
      this.listener?.onError?.(params.requestId, TtsErrorCode.RUNTIME_EXCEPTION, `${e}`);
    }
  }

  private ensureRenderer(): void {
    if (this.renderer !== null) {
      return;
    }
    const streamInfo: audio.AudioStreamInfo = {
      samplingRate: this.tts.sampleRate,
      channels: audio.AudioChannel.CHANNEL_1,
      sampleFormat: audio.AudioSampleFormat.SAMPLE_FORMAT_S16LE,
      encodingType: audio.AudioEncodingType.ENCODING_TYPE_RAW
    };
    const rendererInfo: audio.AudioRendererInfo = {
      usage: audio.StreamUsage.STREAM_USAGE_MUSIC,
      rendererFlags: 0
    };
    const options: audio.AudioRendererOptions = { streamInfo, rendererInfo };
    audio.createAudioRenderer(options, (err: BusinessError, renderer: audio.AudioRenderer): void => {
      if (err) {
        log(`create audio renderer failed: ${err.message}`);
        return;
      }
      this.renderer = renderer;
      this.renderer.on('writeData', this.audioPlayCallback);
      if (this.playBuffer.size() > 0) {
        this.renderer.start();
      }
    });
  }

  private audioPlayCallback = (buf: ArrayBuffer): void => {
    const numSamples = buf.byteLength / 2;
    if (this.playBuffer.size() >= numSamples) {
      const samples: Float32Array = this.playBuffer.get(this.playBuffer.head(), numSamples);
      const int16 = new Int16Array(buf);
      for (let i = 0; i < numSamples; i++) {
        let s = samples[i] * 32767;
        if (s > 32767) {
          s = 32767;
        }
        if (s < -32768) {
          s = -32768;
        }
        int16[i] = s;
      }
      this.playBuffer.pop(numSamples);
    } else {
      (new Int16Array(buf)).fill(0);
      if (!this.generating && this.renderer !== null && this.renderer.state === audio.AudioState.STATE_RUNNING) {
        this.renderer.stop();
      }
    }
  };

  private buildConfig(layout: TtsModelLayout): OfflineTtsConfig {
    const config = new OfflineTtsConfig();
    config.model.kokoro.model = layout.model;
    config.model.kokoro.voices = layout.voices;
    config.model.kokoro.tokens = layout.tokens;
    config.model.kokoro.lexicon = layout.lexicon;
    config.model.kokoro.dataDir = this.prepareDataDir(layout.dataDirRawfile);
    config.model.numThreads = this.params.numThreads;
    config.model.debug = false;
    config.model.provider = 'cpu';
    config.ruleFsts = layout.ruleFsts;
    config.maxNumSentences = 1;
    return config;
  }

  private prepareDataDir(rawDir: string): string {
    try {
      return copyRawfileDirToSandbox(this.context, rawDir);
    } catch (e) {
      log(`prepare dataDir failed for ${rawDir}: ${e}`);
      return '';
    }
  }

  private static toPcm16(samples: Float32Array): ArrayBuffer {
    const out = new ArrayBuffer(samples.length * 2);
    const view = new DataView(out);
    for (let i = 0; i < samples.length; i++) {
      let s = samples[i];
      if (s > 1) {
        s = 1;
      }
      if (s < -1) {
        s = -1;
      }
      view.setInt16(i * 2, s < 0 ? s * 32768 : s * 32767, true);
    }
    return out;
  }
}

export class TextToSpeechSdk {
  private static context?: Context;
  private static workPath: string = '';

  static init(context: Context): void {
    TextToSpeechSdk.context = context;
  }

  static setWorkPath(path: string): void {
    TextToSpeechSdk.workPath = path;
  }

  static getWorkPath(): string {
    return TextToSpeechSdk.workPath;
  }

  static createEngine(params: TtsCreateEngineParams): TextToSpeechEngine {
    if (TextToSpeechSdk.context === undefined) {
      throw new Error('TextToSpeechSdk.init must be called first');
    }
    return new OfflineTtsEngineImpl(TextToSpeechSdk.context, params);
  }

  static listVoices(language?: string): TtsVoiceInfo[] {
    const all = TtsAssetRegistry.voices();
    if (language === undefined || language.length === 0) {
      return all;
    }
    return all.filter((v: TtsVoiceInfo): boolean => v.language === language);
  }
}
