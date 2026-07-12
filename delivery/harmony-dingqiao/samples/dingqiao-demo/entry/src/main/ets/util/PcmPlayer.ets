import { audio } from '@kit.AudioKit';

const CHUNK_BYTES = 8192;
const SAMPLE_RATE = 16000;
const BYTES_PER_SAMPLE = 2;
const DRAIN_PADDING_MS = 500;
const DRAIN_WAIT_MAX_MS = 60000;
const CANCEL_POLL_MS = 100;

/** Plays a 16 kHz / mono / PCM16 sample through AudioRenderer; used to preview enrollment recordings. */
export class PcmPlayer {
  private renderer?: audio.AudioRenderer;
  private playing: boolean = false;
  private generation: number = 0;

  async play(pcm: Int16Array, onComplete: () => void): Promise<void> {
    // A token gives each async play call ownership of only its own renderer. A newer play/stop
    // invalidates all older continuations so an old finally block can never release the new player.
    const token = ++this.generation;
    this.playing = false;
    const previous = this.renderer;
    this.renderer = undefined;
    if (previous !== undefined) await this.releaseRenderer(previous);
    if (!this.ownsToken(token)) return;
    if (pcm.length === 0) {
      onComplete();
      return;
    }

    this.playing = true;
    let localRenderer: audio.AudioRenderer | undefined;
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
      localRenderer = await audio.createAudioRenderer({ streamInfo, rendererInfo });
      if (!this.isCurrent(token)) {
        await this.releaseRenderer(localRenderer);
        localRenderer = undefined;
        return;
      }
      this.renderer = localRenderer;
      await localRenderer.start();
      if (!this.isCurrent(token)) return;

      const playbackStartedAt = Date.now();
      const total = pcm.length * BYTES_PER_SAMPLE;
      const full = new ArrayBuffer(total);
      new Int16Array(full).set(pcm, 0);
      let offset = 0;
      while (this.isCurrent(token) && offset < total) {
        const end = Math.min(offset + CHUNK_BYTES, total);
        const written = await localRenderer.write(full.slice(offset, end));
        if (written <= 0) break;
        offset += Math.min(written, end - offset);
      }
      if (this.isCurrent(token) && offset === total) {
        // write() only confirms that bytes entered the renderer buffer. Wait for the buffer to be
        // consumed before stop/release; otherwise preview audio is truncated and sounds intermittent.
        await localRenderer.drain();
        await this.waitForPlaybackComplete(total, playbackStartedAt, token);
      }
    } catch (e) {
      // Ignore playback errors in the demo; ownership-safe teardown still runs below.
    } finally {
      // A newer play/stop detaches and owns teardown of this renderer. Only the still-attached
      // invocation may clear/release it here.
      if (localRenderer !== undefined && this.renderer === localRenderer) {
        this.renderer = undefined;
        await this.releaseRenderer(localRenderer);
      }
      if (this.ownsToken(token)) {
        this.playing = false;
        onComplete();
      }
    }
  }

  async stop(): Promise<void> {
    ++this.generation;
    this.playing = false;
    const current = this.renderer;
    this.renderer = undefined;
    if (current !== undefined) await this.releaseRenderer(current);
  }

  private isCurrent(token: number): boolean {
    return this.generation === token && this.playing;
  }

  private ownsToken(token: number): boolean {
    return this.generation === token;
  }

  private async releaseRenderer(renderer: audio.AudioRenderer): Promise<void> {
    try {
      await renderer.stop();
    } catch (e) {
      // best-effort teardown
    }
    try {
      await renderer.release();
    } catch (e) {
      // best-effort teardown
    }
  }

  private async waitForPlaybackComplete(totalBytes: number, playbackStartedAt: number,
    token: number): Promise<void> {
    if (!this.isCurrent(token) || totalBytes <= 0 || playbackStartedAt <= 0) return;
    const audioMs = Math.ceil(totalBytes * 1000 / (SAMPLE_RATE * BYTES_PER_SAMPLE));
    const elapsedMs = Math.max(0, Date.now() - playbackStartedAt);
    let remainingMs = Math.min(Math.max(audioMs - elapsedMs + DRAIN_PADDING_MS, DRAIN_PADDING_MS),
      DRAIN_WAIT_MAX_MS);
    while (this.isCurrent(token) && remainingMs > 0) {
      const waitMs = Math.min(remainingMs, CANCEL_POLL_MS);
      await new Promise<void>((resolve: () => void): void => {
        setTimeout(resolve, waitMs);
      });
      remainingMs -= waitMs;
    }
  }
}
