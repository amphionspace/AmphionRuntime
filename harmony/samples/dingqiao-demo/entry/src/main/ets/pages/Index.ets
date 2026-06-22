import { audio } from '@kit.AudioKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { abilityAccessCtrl, common, Permissions } from '@kit.AbilityKit';
import {
  AudioInfo,
  CreateEngineParams,
  RecognitionListener,
  SpeechRecognitionEngine,
  SpeechRecognitionResult,
  SpeechRecognizeSdk,
  StartParams
} from 'amphion_dingqiao';
import {
  PlayType,
  RunMode,
  SpeakParams,
  TextToSpeechEngine,
  TextToSpeechSdk,
  TtsCreateEngineParams
} from 'amphion_tts';

@Entry
@Component
struct Index {
  @State status: string = '未初始化';
  @State partialText: string = '';
  @State finalText: string = '';
  @State listening: boolean = false;
  @State ttsText: string = '请核查接警数据。';
  @State ttsStatus: string = 'TTS 未初始化';

  private engine?: SpeechRecognitionEngine;
  private ttsEngine?: TextToSpeechEngine;
  private mic?: audio.AudioCapturer;
  private sessionId: string = 'demo-session';

  aboutToAppear(): void {
    const ctx = getContext(this) as common.UIAbilityContext;
    SpeechRecognizeSdk.init(ctx);
    TextToSpeechSdk.init(ctx);
    SpeechRecognizeSdk.setWorkPath(`${ctx.filesDir}/dingqiao_work`);
    const params = new CreateEngineParams();
    params.language = 'zh-CN';
    params.online = 1;
    this.engine = SpeechRecognizeSdk.createEngine(params);
    const listener: RecognitionListener = {
      onStart: (_sessionId: string): void => { this.status = '识别已开始'; },
      onEvent: (_sessionId: string, eventCode: number, message: string): void => { this.status = `${eventCode}: ${message}`; },
      onResult: (_sessionId: string, result: SpeechRecognitionResult): void => {
        if (result.isFinal) this.finalText += `${result.result}\n`;
        else this.partialText = result.result;
      },
      onComplete: (_sessionId: string): void => { this.status = '识别完成'; this.listening = false; },
      onError: (_sessionId: string, errorCode: number, message: string): void => { this.status = `${errorCode}: ${message}`; this.listening = false; }
    };
    this.engine.setListener(listener);
    const ttsParams = new TtsCreateEngineParams();
    ttsParams.language = 'zh-en';
    ttsParams.mode = RunMode.OFFLINE;
    ttsParams.voiceId = 'kokoro-zh-en';
    try {
      this.ttsEngine = TextToSpeechSdk.createEngine(ttsParams);
      this.ttsEngine.setListener({
        onStart: (requestId): void => { this.ttsStatus = `${requestId} 合成开始`; },
        onData: (requestId, audio): void => { this.ttsStatus = `${requestId} 返回 ${audio.byteLength} 字节 PCM`; },
        onComplete: (requestId): void => { this.ttsStatus = `${requestId} 合成完成`; },
        onError: (requestId, code, message): void => { this.ttsStatus = `${requestId} ${code}: ${message}`; }
      });
      this.ttsStatus = 'TTS 初始化完成';
    } catch (e) {
      this.ttsStatus = `TTS 初始化失败：${e}`;
    }
    this.status = '初始化完成';
  }

  async requestMicPermission(): Promise<boolean> {
    const ctx = getContext(this) as common.UIAbilityContext;
    const atManager = abilityAccessCtrl.createAtManager();
    const permissions: Permissions[] = ['ohos.permission.MICROPHONE'];
    const result = await atManager.requestPermissionsFromUser(ctx, permissions);
    return result.authResults.length > 0 && result.authResults[0] === 0;
  }

  async startMic(): Promise<void> {
    if (this.engine === undefined) return;
    const ok = await this.requestMicPermission();
    if (!ok) { this.status = '麦克风权限被拒绝'; return; }

    const streamInfo: audio.AudioStreamInfo = {
      samplingRate: audio.AudioSamplingRate.SAMPLE_RATE_16000,
      channels: audio.AudioChannel.CHANNEL_1,
      sampleFormat: audio.AudioSampleFormat.SAMPLE_FORMAT_S16LE,
      encodingType: audio.AudioEncodingType.ENCODING_TYPE_RAW
    };
    const capturerInfo: audio.AudioCapturerInfo = {
      source: audio.SourceType.SOURCE_TYPE_MIC,
      capturerFlags: 0
    };
    this.mic = await audio.createAudioCapturer({ streamInfo, capturerInfo });
    this.mic.on('readData', (buffer: ArrayBuffer): void => {
      if (!this.listening) return;
      const frameBytes = 640;
      let offset = 0;
      while (offset + frameBytes <= buffer.byteLength) {
        const frame = buffer.slice(offset, offset + frameBytes);
        this.engine?.writeAudio(this.sessionId, frame);
        offset += frameBytes;
      }
    });

    const startParams = new StartParams();
    startParams.sessionId = this.sessionId;
    startParams.audioInfo = new AudioInfo();
    this.engine.startListening(startParams);
    await this.mic.start();
    this.listening = true;
    this.partialText = '';
    this.status = '麦克风采集中';
  }

  async stopMic(): Promise<void> {
    if (!this.listening) return;
    this.listening = false;
    this.engine?.finish(this.sessionId);
    await this.mic?.stop();
    await this.mic?.release();
    this.mic = undefined;
  }



  speakDemo(): void {
    if (this.ttsEngine === undefined) {
      this.ttsStatus = 'TTS 引擎不可用，请确认 rawfile/amphion-tts/kokoro-zh-en 模型已打包';
      return;
    }
    const params = new SpeakParams();
    params.requestId = `tts-${Date.now()}`;
    params.playType = PlayType.SYNTHESIZE_AND_PLAY;
    this.ttsEngine.speak(this.ttsText, params);
  }

  build() {
    Column({ space: 16 }) {
      Text('鼎桥离线语音识别 Demo').fontSize(24).fontWeight(FontWeight.Bold)
      Text(this.status).fontSize(14).fontColor(Color.Gray)
      Button(this.listening ? '停止识别' : '开始识别')
        .onClick(() => { if (this.listening) this.stopMic(); else this.startMic(); })
      Text('中间结果').fontSize(18).fontWeight(FontWeight.Medium)
      Text(this.partialText).width('100%').minHeight(80).backgroundColor('#f5f5f5').padding(12)
      Text('最终结果').fontSize(18).fontWeight(FontWeight.Medium)
      Text(this.finalText).width('100%').minHeight(160).backgroundColor('#f5f5f5').padding(12)
      Text('TTS 合成').fontSize(18).fontWeight(FontWeight.Medium)
      TextInput({ text: this.ttsText, placeholder: '输入要合成的文本' })
        .onChange((value: string) => { this.ttsText = value; })
      Button('合成 TTS').onClick(() => this.speakDemo())
      Text(this.ttsStatus).fontSize(14).fontColor(Color.Gray)
    }
    .padding(20)
    .width('100%')
    .height('100%')
  }
}
