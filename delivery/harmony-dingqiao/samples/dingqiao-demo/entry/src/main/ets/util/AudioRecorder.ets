import { audio } from '@kit.AudioKit';

export type PcmListener = (samples: Int16Array) => void;
export type RecorderErrorListener = (message: string) => void;

/**
 * 16 kHz / mono / S16LE microphone capture built on AudioCapturer. Emits Int16Array chunks; the
 * caller is responsible for re-framing (see PcmFrameWriter) and for requesting MICROPHONE permission.
 */
export class AudioRecorder {
  private capturer?: audio.AudioCapturer;
  private readonly onPcm: PcmListener;
  private readonly onError: RecorderErrorListener;
  private running: boolean = false;

  constructor(onPcm: PcmListener, onError: RecorderErrorListener) {
    this.onPcm = onPcm;
    this.onError = onError;
  }

  async start(): Promise<void> {
    if (this.running) return;
    try {
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
      const capturer = await audio.createAudioCapturer({ streamInfo, capturerInfo });
      this.capturer = capturer;
      this.running = true;
      capturer.on('readData', (buffer: ArrayBuffer): void => {
        if (!this.running) return;
        // Copy: the framework may recycle the callback buffer after this returns.
        this.onPcm(new Int16Array(buffer.slice(0)));
      });
      await capturer.start();
    } catch (e) {
      this.running = false;
      this.onError(`${e}`);
    }
  }

  async stop(): Promise<void> {
    if (!this.running && this.capturer === undefined) return;
    this.running = false;
    const capturer = this.capturer;
    this.capturer = undefined;
    if (capturer === undefined) return;
    try {
      capturer.off('readData');
      await capturer.stop();
      await capturer.release();
    } catch (e) {
      // best-effort teardown; the capturer may already be stopped
    }
  }

  isRecording(): boolean {
    return this.running;
  }
}
