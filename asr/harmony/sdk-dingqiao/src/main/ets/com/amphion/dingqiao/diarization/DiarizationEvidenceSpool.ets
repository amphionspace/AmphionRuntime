import { fileIo as fs } from '@kit.CoreFileKit';

export interface DiarizationEvidence {
  segments: Float32Array;
  embeddings: Float32Array;
}

/** Lossless session evidence. Public transcript commits cannot discard model inputs. */
export class DiarizationEvidenceSpool {
  private readonly segmentPath: string;
  private readonly embeddingPath: string;
  private segmentWriter: number = -1;
  private embeddingWriter: number = -1;
  private windows: number = 0;

  constructor(directory: string) {
    this.segmentPath = `${directory}/segments.f32`;
    this.embeddingPath = `${directory}/embeddings.f32`;
  }

  append(segments: Float32Array, embeddings: Float32Array): void {
    if (segments.length !== 589 * 3 || embeddings.length !== 3 * 256) {
      throw new Error('invalid diarization evidence shape');
    }
    if (this.segmentWriter < 0) this.segmentWriter = fs.openSync(this.segmentPath,
      fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.APPEND).fd;
    if (this.embeddingWriter < 0) this.embeddingWriter = fs.openSync(this.embeddingPath,
      fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.APPEND).fd;
    this.write(this.segmentWriter, segments);
    this.write(this.embeddingWriter, embeddings);
    this.windows += 1;
  }

  read(windowCount: number): DiarizationEvidence {
    if (!Number.isInteger(windowCount) || windowCount < 0 || windowCount > this.windows) {
      throw new Error('diarization evidence snapshot exceeds completed windows');
    }
    return {
      segments: new Float32Array(this.readFile(this.segmentPath, windowCount * 589 * 3 * 4)),
      embeddings: new Float32Array(this.readFile(this.embeddingPath, windowCount * 3 * 256 * 4))
    };
  }

  close(): void {
    if (this.segmentWriter >= 0) fs.closeSync(this.segmentWriter);
    this.segmentWriter = -1;
    if (this.embeddingWriter >= 0) fs.closeSync(this.embeddingWriter);
    this.embeddingWriter = -1;
  }

  remove(): void {
    this.close();
    if (fs.accessSync(this.segmentPath)) fs.unlinkSync(this.segmentPath);
    if (fs.accessSync(this.embeddingPath)) fs.unlinkSync(this.embeddingPath);
  }

  private write(fd: number, values: Float32Array): void {
    const bytes = values.buffer.slice(values.byteOffset, values.byteOffset + values.byteLength);
    if (fs.writeSync(fd, bytes) !== bytes.byteLength) throw new Error('incomplete diarization evidence write');
  }

  private readFile(path: string, bytes: number): ArrayBuffer {
    const result = new ArrayBuffer(bytes);
    if (bytes === 0) return result;
    const file = fs.openSync(path, fs.OpenMode.READ_ONLY);
    try {
      if (fs.readSync(file.fd, result, { offset: 0, length: bytes }) !== bytes) {
        throw new Error('incomplete diarization evidence read');
      }
    } finally { fs.closeSync(file.fd); }
    return result;
  }
}
