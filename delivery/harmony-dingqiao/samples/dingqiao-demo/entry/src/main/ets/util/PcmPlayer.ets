import { audio } from '@kit.AudioKit';

const CHUNK_BYTES = 8192;

/** Plays a 16 kHz / mono / PCM16 sample through AudioRenderer; used to preview enrollment recordings. */
export class PcmPlayer {
  private renderer?: audio.AudioRenderer;
  private playing: boolean = false;

  async play(pcm: Int16Array, onComplete: () => void): Promise<void> {
    await this.stop();
    if (pcm.length === 0) {
      onComplete();
      return;
    }
    try {
      const streamInfo: audio.AudioStreamInfo = {
        samplingRate: audio.AudioSamplingRate.SAMPLE_RATE_16000,
        channels: audio.AudioChannel.CHANNEL_1,
        sampleFormat: audio.AudioSampleFormat.SAMPLE_FORMAT_S16LE,
        encodingType: audio.AudioEncodingType.ENCODING_TYPE_RAW
      };
      const rendererInfo: audio.AudioRendererInfo = {
        usage: audio.StreamUsage.STREAM_USAGE_MUSIC,
        rendererFlags: 0
      };
      const renderer = await audio.createAudioRenderer({ streamInfo, rendererInfo });
      this.renderer = renderer;
      this.playing = true;
      await renderer.start();
      const total = pcm.length * 2;
      const full = new ArrayBuffer(total);
      new Int16Array(full).set(pcm, 0);
      let offset = 0;
      while (this.playing && offset < total) {
        const end = Math.min(offset + CHUNK_BYTES, total);
        const written = await renderer.write(full.slice(offset, end));
        if (written <= 0) break;
        offset += written;
      }
    } catch (e) {
      // ignore playback errors in the demo
    } finally {
      await this.releaseRenderer();
      onComplete();
    }
  }

  async stop(): Promise<void> {
    this.playing = false;
    await this.releaseRenderer();
  }

  private async releaseRenderer(): Promise<void> {
    const renderer = this.renderer;
    this.renderer = undefined;
    if (renderer === undefined) return;
    try {
      await renderer.stop();
      await renderer.release();
    } catch (e) {
      // best-effort teardown
    }
  }
}
