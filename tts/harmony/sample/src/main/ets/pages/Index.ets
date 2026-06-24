import application from '@ohos.app.ability.application';
import fs from '@ohos.file.fs';
import { audio } from '@kit.AudioKit';
import { PlayType, QueueMode, RunMode, TextToSpeechSdk } from 'sdk';
import type {
  Callback,
  CompleteResponse,
  CreateEngineParams,
  SpeakListener,
  SpeakParams,
  StartResponse,
  StopResponse,
  SynthesisResponse,
  TextToSpeechEngine
} from 'sdk';

const DEFAULT_VOICE_ID: string = 'lits-female-01';
const LOG_LIMIT: number = 60;
const PROGRESS_INTERVAL_MS: number = 140;
const PROGRESS_STEP: number = 7;
const PROGRESS_MAX: number = 92;
const PROGRESS_MIN_VISIBLE_MS: number = 600;
const METRICS_PLACEHOLDER: string = '采样率 -- Hz | 总耗时 -- ms | 音频时长 -- ms | RTF -- | 播放方式 --';
const PCM_BYTES_PER_SAMPLE: number = 2;

@Entry
@Component
struct Index {
  @State private inputText: string = '欢迎使用 Lits delivery 纯 TTS 示例。房间 204 已准备就绪。';
  @State private language: string = 'zh-en';
  @State private speed: string = '1.0';
  @State private pitch: string = '1.0';
  @State private volume: string = '1.0';
  @State private status: string = '等待操作';
  @State private metricsText: string = METRICS_PLACEHOLDER;
  @State private logText: string = '等待运行日志…';
  @State private loadingEngine: boolean = false;
  @State private busy: boolean = false;
  @State private localPlaying: boolean = false;
  @State private savingFile: boolean = false;
  @State private loadedLanguageText: string = '未加载';
  @State private progressVisible: boolean = false;
  @State private progressLabel: string = '';
  @State private progressValue: number = 0;

  private engine: TextToSpeechEngine | undefined = undefined;
  private engineLanguage: string = '';
  private currentPlayType: PlayType = PlayType.SYNTHESIZE_ONLY;
  private requestCounter: number = 0;
  private requestChunkCount: number = 0;
  private requestAudioBytes: number = 0;
  private requestStartedAtMs: number = 0;
  private requestSampleRate: number = 16000;
  private requestPcmChunks: Map<number, ArrayBuffer> = new Map<number, ArrayBuffer>();
  private lastAudio: ArrayBuffer | undefined = undefined;
  private lastSampleRate: number = 16000;
  private logLines: Array<string> = [];
  private progressTimer: number | undefined = undefined;
  private progressStartedAtMs: number = 0;
  private readonly listener: SpeakListener = new PageSpeakListener(this);
  private readonly player: SamplePcmPlayer = new SamplePcmPlayer();

  aboutToAppear(): void {
    this.inputText = this.presetTextFor(this.language);
    this.metricsText = METRICS_PLACEHOLDER;
    this.appendLog('sample 已启动，仅保留纯 TTS 流程。');
    this.appendLog('createEngine 负责模型加载；纯英文品牌词或缩写发音异常，通常属于模型前端或词典问题。');
    void this.preloadEngine(this.language, false);
  }

  aboutToDisappear(): void {
    this.clearProgressBar();
    void this.player.stop();
    this.releaseEngine();
  }

  build() {
    Scroll() {
      Column({ space: 16 }) {
        Text('Lits_delivery 纯 TTS Sample')
          .fontSize(24)
          .fontWeight(FontWeight.Bold)
          .width('100%')
          .textAlign(TextAlign.Start);

        Text('页面只展示纯 TTS 业务流程：输入文本、选择语言、开始合成、SDK 直接播报、播放结果、保存 WAV。createEngine 阶段负责模型加载。')
          .fontSize(14)
          .fontColor('#666666')
          .lineHeight(22)
          .width('100%');

        Column({ space: 12 }) {
          Text('合成文本')
            .fontWeight(FontWeight.Medium)
            .width('100%');

          TextArea({ text: this.inputText, placeholder: '请输入要合成的文本' })
            .width('100%')
            .height(180)
            .backgroundColor('#FFF9F1')
            .borderRadius(16)
            .padding(12)
            .onChange((value: string) => {
              this.inputText = value;
            });

          Text('语言模式')
            .fontWeight(FontWeight.Medium)
            .width('100%');

          Row({ space: 10 }) {
            this.languageButton('zh-en', this.language === 'zh-en', (): void => {
              this.switchLanguage('zh-en');
            });
            this.languageButton('en-US', this.language === 'en-US', (): void => {
              this.switchLanguage('en-US');
            });
          }.width('100%');

          Text('数字读法由 languageContext 决定：zh-en 按中文逐位读，en-US 按英文逐位读。')
            .fontSize(12)
            .fontColor('#8A6F54')
            .lineHeight(18)
            .width('100%');

          Text('说明：像 HarmonyOS 这类英文品牌词或缩写如果念得不自然，问题通常在模型前端与词典，不在 Harmony 播放链路。')
            .fontSize(12)
            .fontColor('#8A6F54')
            .lineHeight(18)
            .width('100%');

          Text('声学参数')
            .fontWeight(FontWeight.Medium)
            .width('100%');

          Text('这些参数都在 SDK 内部生效：speed 控制语速，pitch 控制音高，volume 控制音量。')
            .fontSize(12)
            .fontColor('#8A6F54')
            .lineHeight(18)
            .width('100%');

          Column({ space: 8 }) {
            this.paramField(
              '语速 speed',
              '1.0 为默认语速，范围 0.5 ~ 2.0，越大越快。',
              this.speed,
              '1.0',
              (value: string): void => {
                this.speed = value;
              }
            );
            this.paramField(
              '音高 pitch',
              '1.0 为默认音高，范围 0.5 ~ 2.0，越大越高。',
              this.pitch,
              '1.0',
              (value: string): void => {
                this.pitch = value;
              }
            );
            this.paramField(
              '音量 volume',
              '1.0 为默认音量，范围 0.0 ~ 2.0，越大越响。',
              this.volume,
              '1.0',
              (value: string): void => {
                this.volume = value;
              }
            );
          }
          .width('100%')
          .backgroundColor('#F7F2EA')
          .borderRadius(14)
          .padding(12);

          Row({ space: 12 }) {
            Button('开始合成')
              .layoutWeight(1)
              .height(44)
              .backgroundColor('#C46A2B')
              .fontColor('#FFFFFF')
              .fontWeight(FontWeight.Bold)
              .enabled(!this.isUiBusy())
              .onClick((): void => {
                void this.submitSynthesis(PlayType.SYNTHESIZE_ONLY);
              });

            Button('SDK 直接播报')
              .layoutWeight(1)
              .height(44)
              .enabled(!this.isUiBusy())
              .onClick((): void => {
                void this.submitSynthesis(PlayType.SYNTHESIZE_AND_PLAY);
              });
          }.width('100%');

          Row({ space: 12 }) {
            Button('播放结果')
              .layoutWeight(1)
              .height(40)
              .enabled(!this.isUiBusy() && this.hasLastAudio())
              .onClick((): void => {
                void this.playLastAudio();
              });

            Button('保存 WAV')
              .layoutWeight(1)
              .height(40)
              .enabled(!this.isUiBusy() && this.hasLastAudio())
              .onClick((): void => {
                void this.saveLastAudio();
              });
          }.width('100%');

          Row({ space: 12 }) {
            Button('停止')
              .layoutWeight(1)
              .height(40)
              .enabled(this.busy || this.localPlaying)
              .onClick((): void => {
                void this.stopCurrentWork();
              });

            Button('重新加载模型')
              .layoutWeight(1)
              .height(40)
              .enabled(!this.isUiBusy())
              .onClick((): void => {
                void this.preloadEngine(this.language, true);
              });
          }.width('100%');
        }
        .width('100%')
        .backgroundColor('#FFFFFF')
        .borderRadius(20)
        .padding(16);

        Column({ space: 10 }) {
          Text('运行结果')
            .fontWeight(FontWeight.Medium)
            .width('100%');

          Text(`当前选择：${this.language} | 当前已加载：${this.loadedLanguageText}`)
            .width('100%')
            .fontSize(12)
            .lineHeight(18)
            .padding(12)
            .backgroundColor('#F7F2EA')
            .borderRadius(14)
            .fontColor('#6F5A46');

          Text(this.status)
            .width('100%')
            .fontSize(14)
            .lineHeight(22)
            .padding(12)
            .backgroundColor('#F7F2EA')
            .borderRadius(14);

          Text(this.metricsText)
            .width('100%')
            .fontSize(12)
            .lineHeight(18)
            .padding(12)
            .backgroundColor('#F7F2EA')
            .borderRadius(14)
            .fontColor('#6F5A46');

          if (this.progressVisible) {
            Column({ space: 8 }) {
              Text(this.progressLabel)
                .width('100%')
                .fontSize(12)
                .fontColor('#8A6F54');

              Progress({
                value: this.progressValue,
                total: 100,
                type: ProgressType.Linear
              })
                .width('100%')
                .height(6)
                .color('#1D5DF1')
                .backgroundColor('#E7DCCF')
                .borderRadius(6);
            }
            .width('100%')
            .padding(12)
            .backgroundColor('#F7F2EA')
            .borderRadius(14);
          }
        }
        .width('100%')
        .backgroundColor('#FFFFFF')
        .borderRadius(20)
        .padding(16);

        Column({ space: 10 }) {
          Text('运行日志（自测）')
            .fontWeight(FontWeight.Medium)
            .width('100%');

          TextArea({ text: this.logText })
            .width('100%')
            .height(220)
            .focusable(false)
            .fontFamily('monospace')
            .fontSize(12)
            .backgroundColor('#F7F2EA')
            .borderRadius(14)
            .padding(12);
        }
        .width('100%')
        .backgroundColor('#FFFFFF')
        .borderRadius(20)
        .padding(16);
      }
      .width('100%')
      .padding(16)
      .backgroundColor('#F3E8DA');
    }
    .width('100%')
    .height('100%');
  }

  @Builder
  private languageButton(label: string, selected: boolean, onClick: () => void) {
    Button(label)
      .type(ButtonType.Capsule)
      .layoutWeight(1)
      .height(40)
      .backgroundColor(selected ? '#5F3B23' : '#F2E5D6')
      .fontColor(selected ? '#FFFFFF' : '#5F3B23')
      .fontWeight(FontWeight.Medium)
      .enabled(!this.isUiBusy())
      .onClick(onClick);
  }

  @Builder
  private paramField(
    title: string,
    description: string,
    value: string,
    placeholder: string,
    onChange: (value: string) => void
  ) {
    Column({ space: 4 }) {
      Text(title)
        .fontSize(13)
        .fontWeight(FontWeight.Medium)
        .width('100%');
      Text(description)
        .fontSize(11)
        .fontColor('#8A6F54')
        .lineHeight(16)
        .width('100%');
      TextInput({ text: value, placeholder })
        .width('100%')
        .backgroundColor('#FFFFFF')
        .borderRadius(10)
        .padding({ left: 12, right: 12 })
        .enabled(!this.isUiBusy())
        .onChange(onChange);
    }
    .width('100%');
  }

  private isUiBusy(): boolean {
    return this.loadingEngine || this.busy || this.localPlaying || this.savingFile;
  }

  private hasLastAudio(): boolean {
    return this.lastAudio !== undefined && this.lastAudio.byteLength > 0;
  }

  private switchLanguage(language: string): void {
    if (this.language === language) {
      return;
    }
    this.language = language;
    this.inputText = this.presetTextFor(language);
    this.setStatus(`正在切换语言并加载模型：${language}`);
    this.setMetrics(METRICS_PLACEHOLDER);
    this.appendLog(`切换语言：${language}`);
    void this.preloadEngine(language, false);
  }

  private async submitSynthesis(playType: PlayType): Promise<void> {
    const text = this.inputText.trim();
    if (text.length === 0) {
      this.setStatus('请输入要合成的文本');
      return;
    }
    if (this.loadingEngine) {
      this.setStatus(`模型加载中：${this.language}`);
      return;
    }
    if (this.localPlaying || this.savingFile) {
      return;
    }

    let readyEngine = this.engine;
    if (readyEngine === undefined || this.engineLanguage !== this.language) {
      this.setStatus(`正在加载模型：${this.language}`);
      await this.preloadEngine(this.language, false);
      readyEngine = this.engine;
      if (readyEngine === undefined || this.engineLanguage !== this.language) {
        return;
      }
    }

    const numericSpeed = parseFloat(this.speed);
    const numericPitch = parseFloat(this.pitch);
    const numericVolume = parseFloat(this.volume);
    if (Number.isNaN(numericSpeed) || Number.isNaN(numericPitch) || Number.isNaN(numericVolume)) {
      this.setStatus('声学参数必须是数字：speed / pitch / volume');
      return;
    }

    const requestId = this.nextRequestId(playType === PlayType.SYNTHESIZE_ONLY ? 'synth' : 'speak');
    this.currentPlayType = playType;
    this.requestChunkCount = 0;
    this.requestAudioBytes = 0;
    this.requestStartedAtMs = Date.now();
    this.requestSampleRate = 16000;
    this.requestPcmChunks.clear();
    if (playType === PlayType.SYNTHESIZE_ONLY) {
      this.lastAudio = undefined;
    }

    this.busy = true;
    this.updateProgressBar(playType === PlayType.SYNTHESIZE_ONLY ? '正在合成 PCM…' : '正在合成并准备 SDK 播报…');

    const actionText = playType === PlayType.SYNTHESIZE_ONLY ? '开始合成' : 'SDK 直接播报';
    this.setStatus(`${actionText}：${requestId}`);
    this.setMetrics(METRICS_PLACEHOLDER);
    this.appendLog(`提交请求 requestId=${requestId} language=${this.language} playType=${playType}`);

    const speakParams: SpeakParams = {
      requestId,
      playType,
      queueMode: QueueMode.PREEMPT,
      languageContext: this.language === 'en-US' ? 'en-US' : 'zh-CN',
      audioType: 'pcm',
      speed: numericSpeed,
      pitch: numericPitch,
      volume: numericVolume
    };

    try {
      readyEngine.speak(text, speakParams);
    } catch (error) {
      this.busy = false;
      this.clearProgressBar();
      this.setStatus(`提交请求失败：${formatError(error)}`);
      this.appendLog(`speak failed requestId=${requestId} message=${formatError(error)}`);
    }
  }

  private preloadEngine(language: string, forceReload: boolean): Promise<void> {
    if (!forceReload && this.engine !== undefined && this.engineLanguage === language) {
      this.setStatus(`模型已加载：${language}`);
      this.loadedLanguageText = language;
      return Promise.resolve();
    }
    if (this.loadingEngine) {
      return Promise.resolve();
    }

    this.loadingEngine = true;
    this.busy = false;
    this.localPlaying = false;
    this.savingFile = false;
    this.updateProgressBar(`正在加载模型：${language}`);
    this.setStatus(`正在加载模型：${language}`);
    this.setMetrics(METRICS_PLACEHOLDER);
    this.appendLog(`createEngine language=${language} voiceId=${DEFAULT_VOICE_ID}`);

    void this.player.stop();
    this.releaseEngine();
    this.loadedLanguageText = '切换中';

    const params: CreateEngineParams = {
      language,
      mode: RunMode.OFFLINE,
      voiceId: DEFAULT_VOICE_ID
    };

    return new Promise<void>((resolve: () => void): void => {
      const callback = new EngineCreateCallback(this, language, resolve);
      TextToSpeechSdk.createEngine(params, callback);
    });
  }

  handleEngineCreateSuccess(language: string, engine: TextToSpeechEngine): void {
    engine.setListener(this.listener);
    if (this.language !== language) {
      try {
        engine.shutdown();
      } catch (_error) {
      }
      this.loadingEngine = false;
      this.clearProgressBar();
      void this.preloadEngine(this.language, false);
      return;
    }
    this.engine = engine;
    this.engineLanguage = language;
    this.loadedLanguageText = language;
    this.loadingEngine = false;
    this.clearProgressBar();
    this.setStatus(`模型加载完成：${language}`);
    this.appendLog(`createEngine success language=${language} voiceId=${DEFAULT_VOICE_ID}`);
  }

  handleEngineCreateError(language: string, errorCode: number, errorMessage: string): void {
    this.loadingEngine = false;
    this.engine = undefined;
    this.engineLanguage = '';
    this.loadedLanguageText = '未加载';
    this.clearProgressBar();
    this.setStatus(`模型加载失败：${language} / ${errorCode} / ${errorMessage}`);
    this.appendLog(`createEngine failed language=${language} code=${errorCode} message=${errorMessage}`);
  }

  private async stopCurrentWork(): Promise<void> {
    if (this.localPlaying) {
      await this.player.stop();
      this.localPlaying = false;
    }
    if (this.busy) {
      try {
        this.engine?.stop();
      } catch (_error) {
      }
    }
    this.busy = false;
    this.clearProgressBar();
    this.setStatus('当前任务已停止');
    this.appendLog('stop current work');
  }

  private async playLastAudio(): Promise<void> {
    const audioData = this.lastAudio;
    if (audioData === undefined || audioData.byteLength === 0) {
      this.setStatus('最近一次合成结果为空，无法播放');
      return;
    }

    this.localPlaying = true;
    this.updateProgressBar('正在播放最近一次合成结果…');
    this.setStatus('正在播放最近一次合成结果');
    this.appendLog(`play pcm bytes=${audioData.byteLength} sampleRate=${this.lastSampleRate}`);

    try {
      await this.player.play(audioData, this.lastSampleRate);
      this.setStatus('最近一次合成结果播放完成');
      this.appendLog('playback complete');
    } catch (error) {
      this.setStatus(`播放结果失败：${formatError(error)}`);
      this.appendLog(`playback failed message=${formatError(error)}`);
    } finally {
      this.localPlaying = false;
      this.clearProgressBar();
    }
  }

  private async saveLastAudio(): Promise<void> {
    const audioData = this.lastAudio;
    if (audioData === undefined || audioData.byteLength === 0) {
      this.setStatus('最近一次合成结果为空，无法保存');
      return;
    }

    this.savingFile = true;
    this.updateProgressBar('正在保存 WAV…');
    this.appendLog(`save wav bytes=${audioData.byteLength} sampleRate=${this.lastSampleRate}`);

    try {
      const outputDir = joinPath(application.getApplicationContext().filesDir, 'tts-sample', 'output');
      ensureDirectory(outputDir);
      const filePath = joinPath(outputDir, `tts-${this.timestamp()}.wav`);
      const wavBytes = buildWavFile(audioData, this.lastSampleRate);
      writeBinaryFile(filePath, new Uint8Array(wavBytes));
      this.setStatus(`已保存到：${filePath}`);
      this.appendLog(`save wav success path=${filePath}`);
    } catch (error) {
      this.setStatus(`保存 WAV 失败：${formatError(error)}`);
      this.appendLog(`save wav failed message=${formatError(error)}`);
    } finally {
      this.savingFile = false;
      this.clearProgressBar();
    }
  }

  private releaseEngine(): void {
    const current = this.engine;
    this.engine = undefined;
    this.engineLanguage = '';
    this.loadedLanguageText = '未加载';
    if (current === undefined) {
      return;
    }
    try {
      current.shutdown();
    } catch (_error) {
    }
  }

  private presetTextFor(language: string): string {
    if (language === 'en-US') {
      return 'Welcome to the Lits delivery TTS sample. Room 204 is ready.';
    }
    return '欢迎使用 Lits delivery 纯 TTS 示例。房间 204 已准备就绪。';
  }

  private nextRequestId(prefix: string): string {
    this.requestCounter += 1;
    return `${prefix}-${Date.now()}-${this.requestCounter}`;
  }

  private timestamp(): string {
    const now = new Date();
    return `${now.getFullYear()}${pad2(now.getMonth() + 1)}${pad2(now.getDate())}-${pad2(now.getHours())}${pad2(now.getMinutes())}${pad2(now.getSeconds())}`;
  }

  private setStatus(status: string): void {
    this.status = status;
  }

  private setMetrics(metrics: string): void {
    this.metricsText = metrics;
  }

  private appendLog(line: string): void {
    this.logLines.push(line);
    if (this.logLines.length > LOG_LIMIT) {
      this.logLines.shift();
    }
    this.logText = this.logLines.join('\n');
  }

  private updateProgressBar(label: string): void {
    this.progressLabel = label;
    this.progressVisible = true;
    if (this.progressStartedAtMs <= 0) {
      this.progressStartedAtMs = Date.now();
    }
    if (this.progressValue <= 0 || this.progressValue >= 100) {
      this.progressValue = 8;
    }
    if (this.progressTimer !== undefined) {
      return;
    }
    this.progressTimer = setInterval((): void => {
      const next = this.progressValue + PROGRESS_STEP;
      this.progressValue = next >= PROGRESS_MAX ? 8 : next;
    }, PROGRESS_INTERVAL_MS) as number;
  }

  private clearProgressBar(force?: boolean): void {
    if (!force && this.progressVisible) {
      const elapsed = Date.now() - this.progressStartedAtMs;
      if (elapsed < PROGRESS_MIN_VISIBLE_MS) {
        setTimeout((): void => {
          this.clearProgressBar(true);
        }, PROGRESS_MIN_VISIBLE_MS - elapsed);
        return;
      }
    }
    if (this.progressTimer !== undefined) {
      clearInterval(this.progressTimer);
      this.progressTimer = undefined;
    }
    this.progressVisible = false;
    this.progressLabel = '';
    this.progressValue = 0;
    this.progressStartedAtMs = 0;
  }

  handleSpeakStart(requestId: string, response: StartResponse): void {
    this.busy = true;
    this.requestStartedAtMs = Date.now();
    this.requestSampleRate = response.sampleRate;
    if (this.currentPlayType === PlayType.SYNTHESIZE_AND_PLAY) {
      this.setStatus(`正在合成并准备 SDK 播报：${requestId}`);
      this.updateProgressBar('正在合成并准备 SDK 播报…');
    } else {
      this.setStatus(`正在合成：${requestId}`);
      this.updateProgressBar('正在合成 PCM…');
    }
    this.appendLog(`onStart requestId=${requestId} sampleRate=${response.sampleRate} sampleBit=${response.sampleBit} channel=${response.audioChannel}`);
  }

  handleSpeakData(requestId: string, audio: ArrayBuffer, response: SynthesisResponse): void {
    this.requestChunkCount += 1;
    this.requestAudioBytes += audio.byteLength;
    this.requestPcmChunks.set(response.sequence, audio);
  }

  handleSpeakComplete(requestId: string, response: CompleteResponse): void {
    if (response.type === 'SYNTHESIS_COMPLETE') {
      const orderedAudio = concatOrderedAudioChunks(this.requestPcmChunks);
      this.requestPcmChunks.clear();
      const synthesisMs = Math.max(0, Date.now() - this.requestStartedAtMs);
      const audioDuration = audioDurationMs(orderedAudio.byteLength, this.requestSampleRate);
      this.appendLog(`onData summary requestId=${requestId} chunks=${this.requestChunkCount} bytes=${this.requestAudioBytes}`);
      if (this.currentPlayType === PlayType.SYNTHESIZE_ONLY) {
        this.lastAudio = orderedAudio;
        this.lastSampleRate = this.requestSampleRate;
        this.busy = false;
        this.clearProgressBar();
        this.setStatus(`合成完成：${requestId}`);
        this.setMetrics(
          `采样率 ${this.requestSampleRate} Hz | 总耗时 ${synthesisMs} ms | 音频时长 ${audioDuration} ms | RTF ${formatRtf(synthesisMs, audioDuration)} | 播放方式 PCM`
        );
      } else {
        this.setStatus(`合成完成，SDK 正在播报：${requestId}`);
        this.setMetrics(
          `采样率 ${this.requestSampleRate} Hz | 总耗时 ${synthesisMs} ms | 音频时长 ${audioDuration} ms | RTF ${formatRtf(synthesisMs, audioDuration)} | 播放方式 SDK`
        );
        this.updateProgressBar('SDK 正在播报…');
      }
    }
    if (response.type === 'PLAYBACK_COMPLETE') {
      this.busy = false;
      this.clearProgressBar();
      this.setStatus(`SDK 播报完成：${requestId}`);
    }
    this.appendLog(`onComplete requestId=${requestId} type=${response.type} message=${response.message}`);
  }

  handleSpeakStop(requestId: string, response: StopResponse): void {
    this.busy = false;
    this.requestPcmChunks.clear();
    this.clearProgressBar();
    this.setStatus(`请求已停止：${requestId}`);
    this.appendLog(`onStop requestId=${requestId} type=${response.type} message=${response.message}`);
  }

  handleSpeakError(requestId: string, errorCode: number, errorMessage: string): void {
    this.busy = false;
    this.requestPcmChunks.clear();
    this.clearProgressBar();
    this.setStatus(`请求失败：${requestId} / ${errorCode} / ${errorMessage}`);
    this.appendLog(`onError requestId=${requestId} code=${errorCode} message=${errorMessage}`);
  }
}

class PageSpeakListener implements SpeakListener {
  private readonly owner: Index;

  constructor(owner: Index) {
    this.owner = owner;
  }

  onStart(requestId: string, response: StartResponse): void {
    this.owner.handleSpeakStart(requestId, response);
  }

  onData(requestId: string, audio: ArrayBuffer, response: SynthesisResponse): void {
    this.owner.handleSpeakData(requestId, audio, response);
  }

  onComplete(requestId: string, response: CompleteResponse): void {
    this.owner.handleSpeakComplete(requestId, response);
  }

  onStop(requestId: string, response: StopResponse): void {
    this.owner.handleSpeakStop(requestId, response);
  }

  onError(requestId: string, errorCode: number, errorMessage: string): void {
    this.owner.handleSpeakError(requestId, errorCode, errorMessage);
  }
}

class EngineCreateCallback implements Callback<TextToSpeechEngine> {
  private readonly owner: Index;
  private readonly language: string;
  private readonly resolve: () => void;

  constructor(owner: Index, language: string, resolve: () => void) {
    this.owner = owner;
    this.language = language;
    this.resolve = resolve;
  }

  onSuccess(engine: TextToSpeechEngine): void {
    this.owner.handleEngineCreateSuccess(this.language, engine);
    this.resolve();
  }

  onError(errorCode: number, errorMessage: string): void {
    this.owner.handleEngineCreateError(this.language, errorCode, errorMessage);
    this.resolve();
  }
}

class SamplePcmPlayer {
  private renderer: audio.AudioRenderer | undefined = undefined;
  private stopped: boolean = false;

  async play(pcm: ArrayBuffer, sampleRate: number): Promise<void> {
    this.stopped = false;
    if (pcm.byteLength === 0) {
      return;
    }
    const renderer = await this.createRenderer(sampleRate);
    this.renderer = renderer;
    try {
      await renderer.start();
      let offset = 0;
      while (offset < pcm.byteLength && !this.stopped) {
        const chunkBytes = Math.min(4096, pcm.byteLength - offset);
        const chunk = cloneArrayBuffer(pcm, offset, chunkBytes);
        await renderer.write(chunk);
        offset += chunkBytes;
      }
      if (!this.stopped) {
        await renderer.drain();
      }
    } finally {
      await this.releaseRenderer();
    }
  }

  async stop(): Promise<void> {
    this.stopped = true;
    await this.releaseRenderer();
  }

  private async createRenderer(sampleRate: number): Promise<audio.AudioRenderer> {
    const options: audio.AudioRendererOptions = {
      streamInfo: {
        samplingRate: sampleRate,
        channels: audio.AudioChannel.CHANNEL_1,
        sampleFormat: audio.AudioSampleFormat.SAMPLE_FORMAT_S16LE,
        encodingType: audio.AudioEncodingType.ENCODING_TYPE_RAW
      },
      rendererInfo: {
        usage: audio.StreamUsage.STREAM_USAGE_MEDIA,
        rendererFlags: 0
      }
    };
    return audio.createAudioRenderer(options);
  }

  private async releaseRenderer(): Promise<void> {
    const renderer = this.renderer;
    this.renderer = undefined;
    if (renderer === undefined) {
      return;
    }
    try {
      if (renderer.state === audio.AudioState.STATE_RUNNING) {
        await renderer.stop();
      }
    } catch (_error) {
    }
    try {
      await renderer.release();
    } catch (_error) {
    }
  }
}

function formatError(error: Object): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function formatRtf(synthesisMs: number, audioDurationMsValue: number): string {
  if (audioDurationMsValue <= 0) {
    return '--';
  }
  return (synthesisMs / audioDurationMsValue).toFixed(2);
}

function audioDurationMs(totalBytes: number, sampleRate: number): number {
  if (sampleRate <= 0) {
    return 0;
  }
  return Math.floor((totalBytes * 1000) / (sampleRate * PCM_BYTES_PER_SAMPLE));
}

function concatOrderedAudioChunks(chunks: Map<number, ArrayBuffer>): ArrayBuffer {
  if (chunks.size === 0) {
    return new ArrayBuffer(0);
  }
  if (chunks.size === 1) {
    let singleChunk: ArrayBuffer | undefined = undefined;
    chunks.forEach((audio: ArrayBuffer): void => {
      singleChunk = audio;
    });
    return singleChunk ?? new ArrayBuffer(0);
  }
  const sequences: Array<number> = [];
  let totalBytes = 0;
  chunks.forEach((audio: ArrayBuffer, sequence: number): void => {
    sequences.push(sequence);
    totalBytes += audio.byteLength;
  });
  sequences.sort((left: number, right: number): number => left - right);

  const output = new Uint8Array(totalBytes);
  let cursor = 0;
  sequences.forEach((sequence: number): void => {
    const audio = chunks.get(sequence);
    if (audio === undefined) {
      return;
    }
    const bytes = new Uint8Array(audio);
    output.set(bytes, cursor);
    cursor += bytes.length;
  });
  return output.buffer;
}

function cloneArrayBuffer(source: ArrayBuffer, offset?: number, length?: number): ArrayBuffer {
  const start = offset ?? 0;
  const chunkLength = length ?? (source.byteLength - start);
  const output = new Uint8Array(chunkLength);
  output.set(new Uint8Array(source, start, chunkLength));
  return output.buffer;
}

function buildWavFile(pcm: ArrayBuffer, sampleRate: number): ArrayBuffer {
  const totalBytes = 44 + pcm.byteLength;
  const wav = new ArrayBuffer(totalBytes);
  const view = new DataView(wav);
  writeAscii(view, 0, 'RIFF');
  view.setUint32(4, 36 + pcm.byteLength, true);
  writeAscii(view, 8, 'WAVE');
  writeAscii(view, 12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * PCM_BYTES_PER_SAMPLE, true);
  view.setUint16(32, PCM_BYTES_PER_SAMPLE, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, 'data');
  view.setUint32(40, pcm.byteLength, true);
  new Uint8Array(wav, 44).set(new Uint8Array(pcm));
  return wav;
}

function writeAscii(view: DataView, offset: number, text: string): void {
  for (let index = 0; index < text.length; index += 1) {
    view.setUint8(offset + index, text.charCodeAt(index));
  }
}

function writeBinaryFile(filePath: string, content: Uint8Array): void {
  ensureDirectory(parentDir(filePath));
  let file: fs.File | undefined = undefined;
  try {
    file = fs.openSync(filePath, fs.OpenMode.CREATE | fs.OpenMode.WRITE_ONLY | fs.OpenMode.TRUNC);
    const payload = content.byteOffset === 0 && content.byteLength === content.buffer.byteLength
      ? content.buffer
      : content.slice().buffer;
    fs.writeSync(file.fd, payload);
  } finally {
    if (file !== undefined) {
      try {
        fs.closeSync(file);
      } catch (_error) {
      }
    }
  }
}

function ensureDirectory(path: string): void {
  const normalized = normalizeDir(path);
  if (normalized.length === 0) {
    return;
  }
  if (isDirectory(normalized)) {
    return;
  }
  fs.mkdirSync(normalized, true);
}

function isDirectory(path: string): boolean {
  try {
    return fs.statSync(path).isDirectory();
  } catch (_error) {
    return false;
  }
}

function parentDir(path: string): string {
  const normalized = normalizeDir(path);
  const lastSlash = normalized.lastIndexOf('/');
  if (lastSlash <= 0) {
    return normalized;
  }
  return normalized.substring(0, lastSlash);
}

function joinPath(basePath: string, ...parts: Array<string>): string {
  let output = normalizeDir(basePath);
  parts.forEach((part: string): void => {
    const cleaned = trimSlashes(part);
    if (cleaned.length === 0) {
      return;
    }
    if (output.length === 0 || output.endsWith('/')) {
      output += cleaned;
      return;
    }
    output += `/${cleaned}`;
  });
  return output;
}

function trimSlashes(path: string): string {
  let start = 0;
  let end = path.length;
  while (start < end && (path[start] === '/' || path[start] === '\\')) {
    start += 1;
  }
  while (end > start && (path[end - 1] === '/' || path[end - 1] === '\\')) {
    end -= 1;
  }
  return path.substring(start, end);
}

function normalizeDir(path: string): string {
  const withForwardSlash = path.replace(/\\/g, '/');
  if (withForwardSlash.length <= 1) {
    return withForwardSlash;
  }
  let end = withForwardSlash.length;
  while (end > 1 && withForwardSlash[end - 1] === '/') {
    end -= 1;
  }
  return withForwardSlash.substring(0, end);
}

function pad2(value: number): string {
  return value < 10 ? `0${value}` : String(value);
}
