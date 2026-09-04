import { fileIo as fs } from '@kit.CoreFileKit';

const CHUNK_BYTES: number = 16000 * 2 * 10;

/** Append-only ten-second blocks; only consumed blocks can be removed. */
export class DiarizationPcmSpool {
  private totalBytes: number = 0;
  private firstChunk: number = 0;
  private writer: number = -1;
  private readonly directory: string;

  constructor(directory: string) { this.directory = directory; }

  append(audio: ArrayBuffer): void {
    const bytes = new Uint8Array(audio);
    let offset = 0;
    while (offset < bytes.length) {
      const chunk = Math.floor(this.totalBytes / CHUNK_BYTES);
      const position = this.totalBytes % CHUNK_BYTES;
      if (this.writer < 0) this.writer = fs.openSync(this.path(chunk),
        fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.APPEND).fd;
      const count = Math.min(bytes.length - offset, CHUNK_BYTES - position);
      const part = bytes.slice(offset, offset + count);
      const written = fs.writeSync(this.writer, part.buffer);
      if (written !== count) throw new Error('incomplete diarization PCM write');
      this.totalBytes += count;
      offset += count;
      if (this.totalBytes % CHUNK_BYTES === 0) this.close();
    }
  }

  read(offsetBytes: number, count: number): ArrayBuffer {
    const result = new Uint8Array(count);
    let copied = 0;
    while (copied < count) {
      const absolute = offsetBytes + copied;
      const chunk = Math.floor(absolute / CHUNK_BYTES);
      const position = absolute % CHUNK_BYTES;
      const take = Math.min(count - copied, CHUNK_BYTES - position);
      const part = new ArrayBuffer(take);
      const file = fs.openSync(this.path(chunk), fs.OpenMode.READ_ONLY);
      try {
        if (fs.readSync(file.fd, part, { offset: position, length: take }) !== take) {
          throw new Error('incomplete diarization PCM read');
        }
      } finally { fs.closeSync(file.fd); }
      result.set(new Uint8Array(part), copied);
      copied += take;
    }
    return result.buffer;
  }

  discardBefore(offsetBytes: number): void {
    const until = Math.floor(Math.min(offsetBytes, this.totalBytes) / CHUNK_BYTES);
    while (this.firstChunk < until) {
      fs.unlinkSync(this.path(this.firstChunk));
      this.firstChunk += 1;
    }
  }

  close(): void {
    if (this.writer >= 0) fs.closeSync(this.writer);
    this.writer = -1;
  }

  remove(): void { this.close(); this.discardBefore(this.totalBytes);
    if (this.totalBytes % CHUNK_BYTES !== 0) fs.unlinkSync(this.path(this.firstChunk));
  }

  endOffset(): number { return this.totalBytes; }
  private path(chunk: number): string { return `${this.directory}/pcm-${chunk}.bin`; }
}
