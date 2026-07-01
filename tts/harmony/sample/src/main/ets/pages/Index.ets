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

const ZH_VOICE_ID: string = 'lits-female-02';
const EN_VOICE_ID: string = 'lits-female-01';
const LOG_LIMIT: number = 60;
const PROGRESS_INTERVAL_MS: number = 140;
const PROGRESS_STEP: number = 7;
const PROGRESS_MAX: number = 92;
const PROGRESS_MIN_VISIBLE_MS: number = 600;
const METRICS_PLACEHOLDER: string = '模式: --\n引擎加载: -- ms\n采样率: -- Hz\n首包时延: -- ms\n合成耗时: -- ms\n音频时长: -- ms\nRTF: --\nChunk数: --';
const PCM_BYTES_PER_SAMPLE: number = 2;
const DEFAULT_SAMPLE_RATE: number = 24000;
const DEFAULT_STREAMING_CHUNK_SIZE: string = '50';
const DEFAULT_PCM_QUEUE_CAPACITY: string = '32';
const DEFAULT_SPEED: string = '1.0';
const AUTO_BATCH_RAWFILE: string = 'dual_tts_eval_cases.jsonl';
const AUTO_BATCH_LOG_TAG: string = '[DualTtsEval]';
const AUTO_BATCH_OUTPUT_FILE: string = 'dual_tts_eval_metrics.jsonl';
const AUTO_WARMUP_ENABLED: boolean = true;
const AUTO_BATCH_ENABLED: boolean = false;

interface AutoBatchCase {
  case_id: string;
  dataset: string;
  lang: string;
  tn_mode: string;
  spk_id: number;
  text: string;
  reference_text: string;
}

interface AutoBatchMetric {
  model_id: string;
  case_id: string;
  dataset: string;
  lang: string;
  tn_mode: string;
  text: string;
  reference_text: string;
  status: string;
  error: string;
  sample_rate: number;
  first_audio_ms: number;
  synthesis_ms: number;
  audio_duration_ms: number;
  rtf: number;
  chunk_count: number;
  audio_bytes: number;
  engine_load_ms: number;
}

@Entry
@Component
struct Index {
  @State private inputText: string = '欢迎使用 Lits delivery 纯 TTS 示例。房间 204 已准备就绪。';
  @State private language: string = 'zh-en';
  @State private chunkSize: string = DEFAULT_STREAMING_CHUNK_SIZE;
  @State private pcmQueueCapacity: string = DEFAULT_PCM_QUEUE_CAPACITY;
  @State private speed: string = DEFAULT_SPEED;
  @State private status: string = '等待操作';
  @State private metricsText: string = METRICS_PLACEHOLDER;
  @State private logText: string = '等待运行日志…';
  @State private loadingEngine: boolean = false;
  @State private busy: boolean = false;
  @State private localPlaying: boolean = false;
  @State private savingFile: boolean = false;
  @State private warmupDone: boolean = false;
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
  private requestFirstChunkAtMs: number = 0;
  private requestSampleRate: number = 16000;
  private engineLoadStartedAtMs: number = 0;
  private engineLoadMs: number = -1;
  private engineLoadGeneration: number = 0;
  private loadingLanguage: string = '';
  private requestPcmChunks: Map<number, ArrayBuffer> = new Map<number, ArrayBuffer>();
  private lastAudio: ArrayBuffer | undefined = undefined;
  private lastSampleRate: number = 16000;
  private logLines: Array<string> = [];
  private progressTimer: number | undefined = undefined;
  private progressStartedAtMs: number = 0;
  private autoBatchCases: Array<AutoBatchCase> = [];
  private autoBatchMetrics: Array<AutoBatchMetric> = [];
  private autoBatchIndex: number = 0;
  private autoBatchRunning: boolean = false;
  private autoBatchStarted: boolean = false;
  private currentBatchCase: AutoBatchCase | undefined = undefined;
  private readonly listener: SpeakListener = new PageSpeakListener(this);
  private readonly player: SamplePcmPlayer = new SamplePcmPlayer();

  aboutToAppear(): void {
    this.inputText = this.presetTextFor(this.language);
    this.metricsText = METRICS_PLACEHOLDER;
    this.appendLog('sample 已启动，当前页面参考 clean sample 的 TTS 卡片布局，只保留纯 TTS 流程。');
    this.appendLog('启动后自动加载模型并 Warmup；批测需要手动触发。');
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

        Text('页面只展示纯 TTS 业务流程：输入文本、选择语言、开始合成、SDK 直接播报、播放结果、保存 WAV。SDK 接口生命周期和回调处理都在后台完成。')
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
            .height(150)
            .backgroundColor('#FAF7F2')
            .borderRadius(8)
            .padding(12)
            .onChange((value: string) => {
              this.inputText = value;
            });

          Text('语言模式')
            .fontWeight(FontWeight.Medium)
            .width('100%');

          Row({ space: 10 }) {
            this.languageButton('zh-en');
            this.languageButton('en-US');
          }.width('100%');

          Text('数字读法由 languageContext 决定：zh-en 按中文逐位读，en-US 按英文逐位读。')
            .fontSize(12)
            .fontColor('#9A9387')
            .lineHeight(18)
            .width('100%');

          Text(`当前选择：${this.language}`)
            .fontSize(12)
            .fontWeight(FontWeight.Medium)
            .fontColor('#1D5DF1')
            .width('100%');

          Text('Chunk size')
            .fontWeight(FontWeight.Medium)
            .width('100%');

          TextInput({ text: this.chunkSize, placeholder: '默认 100' })
            .width('100%')
            .backgroundColor('#FAF7F2')
            .borderRadius(8)
            .padding({ left: 12, right: 12 })
            .enabled(!this.isUiBusy())
            .onChange((value: string): void => {
              this.chunkSize = value;
            });

          Text('PCM queue capacity')
            .fontWeight(FontWeight.Medium)
            .width('100%');

          TextInput({ text: this.pcmQueueCapacity, placeholder: '默认 128' })
            .width('100%')
            .backgroundColor('#FAF7F2')
            .borderRadius(8)
            .padding({ left: 12, right: 12 })
            .enabled(!this.isUiBusy())
            .onChange((value: string): void => {
              this.pcmQueueCapacity = value;
            });

          Text('Speed')
            .fontWeight(FontWeight.Medium)
            .width('100%');

          TextInput({ text: this.speed, placeholder: '默认 1.0，范围 0.5~2.0' })
            .width('100%')
            .backgroundColor('#FAF7F2')
            .borderRadius(8)
            .padding({ left: 12, right: 12 })
            .enabled(!this.isUiBusy())
            .onChange((value: string): void => {
              this.speed = value;
            });

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
            Button('Warmup')
              .layoutWeight(1)
              .height(40)
              .enabled(!this.isUiBusy())
              .onClick((): void => {
                void this.submitWarmup(false);
              });

            Button('停止')
              .layoutWeight(1)
              .height(40)
              .enabled(this.busy || this.localPlaying)
              .onClick((): void => {
                void this.stopCurrentWork();
              });
          }.width('100%');

          Text('“开始合成”用于测流式回调；“SDK 直接播报”用于测边推边播；“Warmup”会先跑一条短句，把模型首次执行开销排除掉。Chunk size 会覆盖流式切块大小，PCM queue capacity 会覆盖 SDK 直接播报的播放缓冲队列容量，Speed 会调整语速。')
            .fontSize(12)
            .fontColor('#9A9387')
            .lineHeight(18)
            .width('100%');
        }
        .width('100%')
        .backgroundColor('#FAF7F2')
        .borderRadius(20)
        .padding(16);

        Column({ space: 10 }) {
          Text('运行结果')
            .fontWeight(FontWeight.Medium)
            .width('100%');

          Text(this.status)
            .width('100%')
            .fontSize(14)
            .lineHeight(22)
            .fontColor('#6F6A60');

          Text(this.metricsText)
            .width('100%')
            .fontSize(12)
            .lineHeight(18)
            .padding(12)
            .fontFamily('monospace')
            .backgroundColor('#EEE7DA')
            .borderRadius(8)
            .fontColor('#6F6A60');

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
        .backgroundColor('#FAF7F2')
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
        .backgroundColor('#FAF7F2')
        .borderRadius(20)
        .padding(16);
      }
      .width('100%')
      .padding(20)
      .backgroundColor('#F3EEE5');
    }
    .width('100%')
    .height('100%');
  }

  @Builder
  private languageButton(language: string) {
    Button(this.language === language ? `✓ ${language}` : language)
      .type(ButtonType.Capsule)
      .layoutWeight(1)
      .height(44)
      .backgroundColor(this.language === language ? '#1D5DF1' : '#FFFFFF')
      .fontColor(this.language === language ? '#FFFFFF' : '#2C2A26')
      .fontWeight(this.language === language ? FontWeight.Bold : FontWeight.Medium)
      .border({
        width: this.language === language ? 2 : 1,
        color: this.language === language ? '#0D3DB8' : '#D8CEC0'
      })
      .enabled(!this.isUiBusy())
      .onClick((): void => {
        this.switchLanguage(language);
      });
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
    if (this.isUiBusy()) {
      this.setStatus(`请等待当前任务完成后再切换语言：${this.language}`);
      return;
    }
    if (this.language === language && this.engineLanguage === language && !this.loadingEngine) {
      return;
    }
    this.language = language;
    this.inputText = this.presetTextFor(language);
    this.warmupDone = false;
    this.busy = false;
    this.localPlaying = false;
    this.savingFile = false;
    this.setStatus(`正在切换语言并加载模型：${language}`);
    this.setMetrics(METRICS_PLACEHOLDER);
    this.appendLog(`切换语言：${language}`);
    void this.player.stop();
    try {
      this.engine?.stop();
    } catch (_error) {
    }
    this.releaseEngine();
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

    const requestId = this.nextRequestId(playType === PlayType.SYNTHESIZE_ONLY ? 'synth' : 'speak');
    this.currentPlayType = playType;
    this.requestChunkCount = 0;
    this.requestAudioBytes = 0;
    this.requestStartedAtMs = Date.now();
    this.requestFirstChunkAtMs = 0;
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
    const selectedSpeed = this.selectedSpeed();
    this.appendLog(`提交请求 requestId=${requestId} language=${this.language} playType=${playType} speed=${selectedSpeed} chunkSize=${this.selectedChunkSize()} pcmQueueCapacity=${this.selectedPcmQueueCapacity()}`);

    const speakParams: SpeakParams = {
      requestId,
      playType,
      queueMode: QueueMode.PREEMPT,
      languageContext: this.language === 'en-US' ? 'en-US' : 'zh-en',
      audioType: 'pcm',
      speed: selectedSpeed,
      pitch: 1.0,
      volume: 1.0,
      extraParams: {
        streamingChunkSize: this.selectedChunkSize(),
        streamingFirstChunkSize: this.selectedChunkSize(),
        pcmQueueCapacity: this.selectedPcmQueueCapacity()
      }
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

  private async submitWarmup(autoTriggered: boolean): Promise<void> {
    if (this.loadingEngine || this.localPlaying || this.savingFile) {
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

    const requestId = this.nextRequestId('warmup');
    this.currentPlayType = PlayType.SYNTHESIZE_ONLY;
    this.requestChunkCount = 0;
    this.requestAudioBytes = 0;
    this.requestStartedAtMs = Date.now();
    this.requestFirstChunkAtMs = 0;
    this.requestSampleRate = DEFAULT_SAMPLE_RATE;
    this.requestPcmChunks.clear();
    this.busy = true;
    this.updateProgressBar('正在 Warmup…');
    this.setStatus(`正在 Warmup：${requestId}`);
    this.setMetrics(this.buildMetricsText('Warmup/待机', 0, undefined, undefined, 0, 0));
    const selectedSpeed = this.selectedSpeed();
    this.appendLog(`${autoTriggered ? '自动' : '提交'} Warmup requestId=${requestId} language=${this.language} speed=${selectedSpeed} chunkSize=${this.selectedChunkSize()} pcmQueueCapacity=${this.selectedPcmQueueCapacity()}`);

    try {
      const warmupParams: SpeakParams = {
        requestId,
        playType: PlayType.SYNTHESIZE_ONLY,
        queueMode: QueueMode.PREEMPT,
        languageContext: this.language === 'en-US' ? 'en-US' : 'zh-en',
        audioType: 'pcm',
        speed: selectedSpeed,
        pitch: 1.0,
        volume: 1.0,
        extraParams: {
          streamingChunkSize: this.selectedChunkSize(),
          streamingFirstChunkSize: this.selectedChunkSize(),
          pcmQueueCapacity: this.selectedPcmQueueCapacity()
        }
      };
      readyEngine.speak(this.language === 'en-US' ? 'hello.' : '你好。', warmupParams);
    } catch (error) {
      this.busy = false;
      this.clearProgressBar();
      this.setStatus(`预热失败：${formatError(error)}`);
      this.appendLog(`warmup failed requestId=${requestId} message=${formatError(error)}`);
    }
  }

  private preloadEngine(language: string, forceReload: boolean): Promise<void> {
    if (!forceReload && this.engine !== undefined && this.engineLanguage === language) {
      this.setStatus(`模型已加载：${language}`);
      this.loadedLanguageText = language;
      return Promise.resolve();
    }
    if (this.loadingEngine && this.loadingLanguage === language && !forceReload) {
      return Promise.resolve();
    }

    const generation = this.engineLoadGeneration + 1;
    this.engineLoadGeneration = generation;
    this.loadingLanguage = language;
    this.loadingEngine = true;
    this.busy = false;
    this.localPlaying = false;
    this.savingFile = false;
    this.updateProgressBar(`正在加载模型：${language}`);
    this.setStatus(`正在加载模型：${language}`);
    this.setMetrics(METRICS_PLACEHOLDER);
    const voiceId = this.voiceIdForLanguage(language);
    this.appendLog(`createEngine language=${language} voiceId=${voiceId}`);
    this.engineLoadStartedAtMs = Date.now();

    void this.player.stop();
    this.releaseEngine();
    this.loadedLanguageText = `切换中：${language}`;

    const params: CreateEngineParams = {
      language,
      mode: RunMode.OFFLINE,
      voiceId,
      extraParams: {
        streamingChunkSize: this.selectedChunkSize(),
        streamingFirstChunkSize: this.selectedChunkSize()
      }
    };

    return new Promise<void>((resolve: () => void): void => {
      const callback = new EngineCreateCallback(this, language, generation, resolve);
      TextToSpeechSdk.createEngine(params, callback);
    });
  }

  handleEngineCreateSuccess(language: string, generation: number, engine: TextToSpeechEngine): void {
    engine.setListener(this.listener);
    if (generation !== this.engineLoadGeneration || this.language !== language) {
      try {
        engine.shutdown();
      } catch (_error) {
      }
      if (generation === this.engineLoadGeneration) {
        this.loadingEngine = false;
        this.loadingLanguage = '';
        this.clearProgressBar();
        void this.preloadEngine(this.language, false);
      }
      return;
    }
    this.engine = engine;
    this.engineLanguage = language;
    this.loadedLanguageText = language;
    this.loadingEngine = false;
    this.loadingLanguage = '';
    this.engineLoadMs = Math.max(0, Date.now() - this.engineLoadStartedAtMs);
    this.clearProgressBar();
    this.setStatus(`模型加载完成：${language}`);
    this.appendLog(`createEngine success language=${language} voiceId=${this.voiceIdForLanguage(language)} loadMs=${this.engineLoadMs}`);
    if (AUTO_WARMUP_ENABLED) {
      void this.submitWarmup(true);
    } else {
      this.warmupDone = true;
      this.appendLog('auto warmup disabled');
    }
  }

  private voiceIdForLanguage(language: string): string {
    return language === 'en-US' ? EN_VOICE_ID : ZH_VOICE_ID;
  }

  handleEngineCreateError(language: string, generation: number, errorCode: number, errorMessage: string): void {
    if (generation !== this.engineLoadGeneration) {
      return;
    }
    this.loadingEngine = false;
    this.loadingLanguage = '';
    if (this.language !== language) {
      void this.preloadEngine(this.language, false);
      return;
    }
    this.engine = undefined;
    this.engineLanguage = '';
    this.loadedLanguageText = '未加载';
    this.warmupDone = false;
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
    if (this.requestFirstChunkAtMs <= 0) {
      this.requestFirstChunkAtMs = Date.now();
      this.appendLog(`first onData requestId=${requestId} firstPacketMs=${this.requestFirstChunkAtMs - this.requestStartedAtMs}`);
    }
    this.requestChunkCount += 1;
    this.requestAudioBytes += audio.byteLength;
    this.requestPcmChunks.set(response.sequence, audio);
  }

  handleSpeakComplete(requestId: string, response: CompleteResponse): void {
    if (response.type === 'SYNTHESIS_COMPLETE') {
      const orderedAudio = concatOrderedAudioChunks(this.requestPcmChunks);
      this.requestPcmChunks.clear();
      const uiSynthesisMs = Math.max(0, Date.now() - this.requestStartedAtMs);
      const uiFirstPacketMs = this.requestFirstChunkAtMs > 0 ? this.requestFirstChunkAtMs - this.requestStartedAtMs : undefined;
      const uiAudioDuration = audioDurationMs(orderedAudio.byteLength, this.requestSampleRate);
      const synthesisMs = response.synthesisMs ?? uiSynthesisMs;
      const firstPacketMs = response.firstPacketMs ?? uiFirstPacketMs;
      const audioDuration = response.audioDurationMs ?? uiAudioDuration;
      this.appendLog(`onData summary requestId=${requestId} chunks=${this.requestChunkCount} bytes=${this.requestAudioBytes}`);
      if (requestId.startsWith('batch-')) {
        this.busy = false;
        this.clearProgressBar();
        this.recordBatchSuccess(firstPacketMs, synthesisMs, audioDuration, this.requestSampleRate);
        return;
      }
      if (this.currentPlayType === PlayType.SYNTHESIZE_ONLY) {
        this.lastAudio = orderedAudio;
        this.lastSampleRate = this.requestSampleRate;
        this.busy = false;
        this.clearProgressBar();
        if (requestId.startsWith('warmup-')) {
          this.warmupDone = true;
          this.setStatus(`Warmup 完成：${requestId}`);
          this.startAutoBatchIfAvailable();
        } else {
          this.setStatus(`合成完成：${requestId}`);
        }
        this.setMetrics(
          this.buildMetricsText(
            requestId.startsWith('warmup-') ? 'Warmup/待机' : '真流式回调',
            this.requestChunkCount,
            firstPacketMs,
            synthesisMs,
            audioDuration,
            this.requestSampleRate
          )
        );
      } else {
        this.setStatus(`合成完成，SDK 正在播报：${requestId}`);
        this.setMetrics(
          this.buildMetricsText('真流式播报', this.requestChunkCount, firstPacketMs, synthesisMs, audioDuration, this.requestSampleRate)
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
    if (requestId.startsWith('batch-')) {
      this.recordBatchError(`${errorCode}:${errorMessage}`);
      this.runNextBatchCase();
    }
  }

  private selectedChunkSize(): number {
    const value = parseInt(this.chunkSize.trim(), 10);
    return Number.isNaN(value) || value <= 0 ? parseInt(DEFAULT_STREAMING_CHUNK_SIZE, 10) : value;
  }

  private selectedPcmQueueCapacity(): number {
    const value = parseInt(this.pcmQueueCapacity.trim(), 10);
    return Number.isNaN(value) || value <= 0 ? parseInt(DEFAULT_PCM_QUEUE_CAPACITY, 10) : value;
  }

  private selectedSpeed(): number {
    const value = Number(this.speed.trim());
    if (!Number.isFinite(value)) {
      return Number(DEFAULT_SPEED);
    }
    return Math.min(2.0, Math.max(0.5, value));
  }

  private buildMetricsText(
    mode: string,
    chunkCount: number,
    firstPacketMs: number | undefined,
    synthesisMs: number | undefined,
    audioDuration: number,
    sampleRate: number
  ): string {
    const engineLoad = this.engineLoadMs >= 0 ? String(this.engineLoadMs) : '--';
    const firstPacket = firstPacketMs === undefined ? '--' : String(firstPacketMs);
    const synthesis = synthesisMs === undefined ? '--' : String(synthesisMs);
    return `模式: ${mode}\n引擎加载: ${engineLoad} ms\n采样率: ${sampleRate} Hz\n首包时延: ${firstPacket} ms\n合成耗时: ${synthesis} ms\n音频时长: ${audioDuration} ms\nRTF: ${formatRtf(synthesisMs ?? 0, audioDuration)}\nChunk数: ${chunkCount}`;
  }

  private startAutoBatchIfAvailable(): void {
    if (!AUTO_BATCH_ENABLED) {
      this.appendLog(`${AUTO_BATCH_LOG_TAG} auto batch disabled`);
      return;
    }
    if (this.autoBatchStarted || this.autoBatchRunning || !this.warmupDone) {
      return;
    }
    const cases = loadAutoBatchCases(AUTO_BATCH_RAWFILE);
    if (cases.length === 0) {
      this.appendLog(`${AUTO_BATCH_LOG_TAG} no rawfile cases found`);
      return;
    }
    this.autoBatchCases = cases;
    this.autoBatchMetrics = [];
    this.autoBatchIndex = 0;
    this.autoBatchStarted = true;
    this.autoBatchRunning = true;
    console.info(`${AUTO_BATCH_LOG_TAG} start model=vocos_current_tn cases=${cases.length}`);
    this.runNextBatchCase();
  }

  private runNextBatchCase(): void {
    if (!this.autoBatchRunning) {
      return;
    }
    if (this.autoBatchIndex >= this.autoBatchCases.length) {
      this.finishAutoBatch();
      return;
    }
    const batchCase = this.autoBatchCases[this.autoBatchIndex];
    this.autoBatchIndex += 1;
    this.submitBatchCase(batchCase);
  }

  private submitBatchCase(batchCase: AutoBatchCase): void {
    const readyEngine = this.engine;
    if (readyEngine === undefined) {
      this.recordBatchError('engine undefined');
      this.runNextBatchCase();
      return;
    }
    this.currentBatchCase = batchCase;
    this.language = batchCase.lang === 'en' ? 'en-US' : 'zh-en';
    this.currentPlayType = PlayType.SYNTHESIZE_ONLY;
    this.requestChunkCount = 0;
    this.requestAudioBytes = 0;
    this.requestStartedAtMs = Date.now();
    this.requestFirstChunkAtMs = 0;
    this.requestSampleRate = DEFAULT_SAMPLE_RATE;
    this.requestPcmChunks.clear();
    this.busy = true;
    const requestId = `batch-${batchCase.case_id}`;
    const speakParams: SpeakParams = {
      requestId,
      playType: PlayType.SYNTHESIZE_ONLY,
      queueMode: QueueMode.PREEMPT,
      languageContext: this.language === 'en-US' ? 'en-US' : 'zh-en',
      audioType: 'pcm',
      speed: this.selectedSpeed(),
      pitch: 1.0,
      volume: 1.0,
      extraParams: {
        streamingChunkSize: this.selectedChunkSize(),
        streamingFirstChunkSize: this.selectedChunkSize(),
        pcmQueueCapacity: this.selectedPcmQueueCapacity()
      }
    };
    console.info(`${AUTO_BATCH_LOG_TAG} submit case_id=${batchCase.case_id} index=${this.autoBatchIndex}/${this.autoBatchCases.length}`);
    try {
      readyEngine.speak(batchCase.text, speakParams);
    } catch (error) {
      this.busy = false;
      this.recordBatchError(formatError(error));
      this.runNextBatchCase();
    }
  }

  private recordBatchSuccess(
    firstPacketMs: number | undefined,
    synthesisMs: number | undefined,
    audioDuration: number,
    sampleRate: number
  ): void {
    const batchCase = this.currentBatchCase;
    if (batchCase === undefined) {
      return;
    }
    const synthesis = synthesisMs ?? Math.max(0, Date.now() - this.requestStartedAtMs);
    const firstPacket = firstPacketMs ?? (this.requestFirstChunkAtMs > 0 ? this.requestFirstChunkAtMs - this.requestStartedAtMs : -1);
    const metric: AutoBatchMetric = {
      model_id: 'vocos_current_tn',
      case_id: batchCase.case_id,
      dataset: batchCase.dataset,
      lang: batchCase.lang,
      tn_mode: batchCase.tn_mode,
      text: batchCase.text,
      reference_text: batchCase.reference_text,
      status: 'ok',
      error: '',
      sample_rate: sampleRate,
      first_audio_ms: firstPacket,
      synthesis_ms: synthesis,
      audio_duration_ms: audioDuration,
      rtf: audioDuration > 0 ? synthesis / audioDuration : -1,
      chunk_count: this.requestChunkCount,
      audio_bytes: this.requestAudioBytes,
      engine_load_ms: this.engineLoadMs
    };
    this.autoBatchMetrics.push(metric);
    console.info(`${AUTO_BATCH_LOG_TAG} ${JSON.stringify(metric)}`);
    this.currentBatchCase = undefined;
    this.runNextBatchCase();
  }

  private recordBatchError(error: string): void {
    const batchCase = this.currentBatchCase;
    if (batchCase === undefined) {
      return;
    }
    const metric: AutoBatchMetric = {
      model_id: 'vocos_current_tn',
      case_id: batchCase.case_id,
      dataset: batchCase.dataset,
      lang: batchCase.lang,
      tn_mode: batchCase.tn_mode,
      text: batchCase.text,
      reference_text: batchCase.reference_text,
      status: 'error',
      error,
      sample_rate: this.requestSampleRate,
      first_audio_ms: -1,
      synthesis_ms: -1,
      audio_duration_ms: 0,
      rtf: -1,
      chunk_count: this.requestChunkCount,
      audio_bytes: this.requestAudioBytes,
      engine_load_ms: this.engineLoadMs
    };
    this.autoBatchMetrics.push(metric);
    console.info(`${AUTO_BATCH_LOG_TAG} ${JSON.stringify(metric)}`);
    this.currentBatchCase = undefined;
  }

  private finishAutoBatch(): void {
    this.autoBatchRunning = false;
    const output = this.autoBatchMetrics.map((metric: AutoBatchMetric): string => JSON.stringify(metric)).join('\n') + '\n';
    const outputPath = joinPath(application.getApplicationContext().filesDir, AUTO_BATCH_OUTPUT_FILE);
    writeTextFile(outputPath, output);
    console.info(`${AUTO_BATCH_LOG_TAG} complete count=${this.autoBatchMetrics.length} path=${outputPath}`);
    this.setStatus(`自动批测完成：${this.autoBatchMetrics.length} 条`);
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
  private readonly generation: number;
  private readonly resolve: () => void;

  constructor(owner: Index, language: string, generation: number, resolve: () => void) {
    this.owner = owner;
    this.language = language;
    this.generation = generation;
    this.resolve = resolve;
  }

  onSuccess(engine: TextToSpeechEngine): void {
    this.owner.handleEngineCreateSuccess(this.language, this.generation, engine);
    this.resolve();
  }

  onError(errorCode: number, errorMessage: string): void {
    this.owner.handleEngineCreateError(this.language, this.generation, errorCode, errorMessage);
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

function writeTextFile(filePath: string, content: string): void {
  writeBinaryFile(filePath, utf8Encode(content));
}

function loadAutoBatchCases(rawfileName: string): Array<AutoBatchCase> {
  try {
    const bytes = application.getApplicationContext().resourceManager.getRawFileContentSync(rawfileName);
    const text = utf8Decode(bytes);
    const cases: Array<AutoBatchCase> = [];
    text.split('\n').forEach((line: string): void => {
      const trimmed = line.trim();
      if (trimmed.length === 0) {
        return;
      }
      const value = JSON.parse(trimmed) as AutoBatchCase;
      if (value.case_id !== undefined && value.text !== undefined) {
        cases.push(value);
      }
    });
    return cases;
  } catch (error) {
    console.info(`${AUTO_BATCH_LOG_TAG} rawfile unavailable name=${rawfileName} message=${formatError(error)}`);
    return [];
  }
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

function utf8Encode(text: string): Uint8Array {
  const bytes: Array<number> = [];
  for (let index = 0; index < text.length; index += 1) {
    let code = text.charCodeAt(index);
    if (code >= 0xD800 && code <= 0xDBFF && index + 1 < text.length) {
      const next = text.charCodeAt(index + 1);
      if (next >= 0xDC00 && next <= 0xDFFF) {
        code = 0x10000 + ((code - 0xD800) << 10) + (next - 0xDC00);
        index += 1;
      }
    }
    if (code < 0x80) {
      bytes.push(code);
    } else if (code < 0x800) {
      bytes.push(0xC0 | (code >> 6), 0x80 | (code & 0x3F));
    } else if (code < 0x10000) {
      bytes.push(0xE0 | (code >> 12), 0x80 | ((code >> 6) & 0x3F), 0x80 | (code & 0x3F));
    } else {
      bytes.push(0xF0 | (code >> 18), 0x80 | ((code >> 12) & 0x3F), 0x80 | ((code >> 6) & 0x3F), 0x80 | (code & 0x3F));
    }
  }
  return new Uint8Array(bytes);
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
