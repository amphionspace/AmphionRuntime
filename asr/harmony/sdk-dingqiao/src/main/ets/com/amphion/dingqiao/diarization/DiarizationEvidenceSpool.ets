import { fileIo as fs } from '@kit.CoreFileKit';

export interface DiarizationEvidence {
  segments: Float32Array;
  embeddings: Float32Array;
  runEmbeddings: Float32Array;
  runRanges: Float32Array;
  runRms: Float32Array;
}

/** Lossless session evidence. Public transcript commits cannot discard model inputs. */
export class DiarizationEvidenceSpool {
  private readonly segmentPath: string;
  private readonly embeddingPath: string;
  private readonly runEmbeddingPath: string;
  private readonly runRangePath: string;
  private readonly runRmsPath: string;
  private segmentWriter: number = -1;
  private embeddingWriter: number = -1;
  private runEmbeddingWriter: number = -1;
  private runRangeWriter: number = -1;
  private runRmsWriter: number = -1;
  private windows: number = 0;
  private readonly runCounts: number[] = [];

  constructor(directory: string) {
    this.segmentPath = `${directory}/segments.f32`;
    this.embeddingPath = `${directory}/embeddings.f32`;
    this.runEmbeddingPath = `${directory}/run-embeddings.f32`;
    this.runRangePath = `${directory}/run-ranges.f32`;
    this.runRmsPath = `${directory}/run-rms.f32`;
  }

  append(segments: Float32Array, embeddings: Float32Array,
    runEmbeddings: Float32Array = new Float32Array(0), runRanges: Float32Array = new Float32Array(0),
    runRms: Float32Array = new Float32Array(0)): void {
    if (segments.length !== 589 * 3 || embeddings.length !== 3 * 256) {
      throw new Error('invalid diarization evidence shape');
    }
    if (runRanges.length % 4 !== 0 || runEmbeddings.length !== runRanges.length / 4 * 256 ||
      runRms.length !== runRanges.length / 4) {
      throw new Error('invalid diarization run evidence shape');
    }
    if (this.segmentWriter < 0) this.segmentWriter = fs.openSync(this.segmentPath,
      fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.APPEND).fd;
    if (this.embeddingWriter < 0) this.embeddingWriter = fs.openSync(this.embeddingPath,
      fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.APPEND).fd;
    if (runEmbeddings.length > 0 && this.runEmbeddingWriter < 0) this.runEmbeddingWriter = fs.openSync(this.runEmbeddingPath,
      fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.APPEND).fd;
    if (runRanges.length > 0 && this.runRangeWriter < 0) this.runRangeWriter = fs.openSync(this.runRangePath,
      fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.APPEND).fd;
    if (runRms.length > 0 && this.runRmsWriter < 0) this.runRmsWriter = fs.openSync(this.runRmsPath,
      fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.APPEND).fd;
    this.writeFloat32(this.segmentWriter, segments);
    this.writeFloat32(this.embeddingWriter, embeddings);
    if (runEmbeddings.length > 0) this.writeFloat32(this.runEmbeddingWriter, runEmbeddings);
    if (runRanges.length > 0) this.writeFloat32(this.runRangeWriter, runRanges);
    if (runRms.length > 0) this.writeFloat32(this.runRmsWriter, runRms);
    this.runCounts.push(runRanges.length / 4);
    this.windows += 1;
  }

  read(windowCount: number): DiarizationEvidence {
    if (!Number.isInteger(windowCount) || windowCount < 0 || windowCount > this.windows) {
      throw new Error('diarization evidence snapshot exceeds completed windows');
    }
    return {
      segments: new Float32Array(this.readFile(this.segmentPath, windowCount * 589 * 3 * 4)),
      embeddings: new Float32Array(this.readFile(this.embeddingPath, windowCount * 3 * 256 * 4)),
      runEmbeddings: new Float32Array(this.readFile(this.runEmbeddingPath,
        this.runCountPrefix(windowCount) * 256 * 4)),
      runRanges: this.readRunRanges(windowCount),
      runRms: new Float32Array(this.readFile(this.runRmsPath, this.runCountPrefix(windowCount) * 4))
    };
  }

  close(): void {
    if (this.segmentWriter >= 0) fs.closeSync(this.segmentWriter);
    this.segmentWriter = -1;
    if (this.embeddingWriter >= 0) fs.closeSync(this.embeddingWriter);
    this.embeddingWriter = -1;
    if (this.runEmbeddingWriter >= 0) fs.closeSync(this.runEmbeddingWriter);
    this.runEmbeddingWriter = -1;
    if (this.runRangeWriter >= 0) fs.closeSync(this.runRangeWriter);
    this.runRangeWriter = -1;
    if (this.runRmsWriter >= 0) fs.closeSync(this.runRmsWriter);
    this.runRmsWriter = -1;
  }

  remove(): void {
    this.close();
    if (fs.accessSync(this.segmentPath)) fs.unlinkSync(this.segmentPath);
    if (fs.accessSync(this.embeddingPath)) fs.unlinkSync(this.embeddingPath);
    if (fs.accessSync(this.runEmbeddingPath)) fs.unlinkSync(this.runEmbeddingPath);
    if (fs.accessSync(this.runRangePath)) fs.unlinkSync(this.runRangePath);
    if (fs.accessSync(this.runRmsPath)) fs.unlinkSync(this.runRmsPath);
  }

  private writeFloat32(fd: number, values: Float32Array): void {
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

  private runCountPrefix(windowCount: number): number {
    let count = 0;
    for (let index = 0; index < windowCount; index++) count += this.runCounts[index] ?? 0;
    return count;
  }

  private readRunRanges(windowCount: number): Float32Array {
    const ranges = new Float32Array(this.readFile(this.runRangePath, this.runCountPrefix(windowCount) * 4 * 4));
    let offset = 0;
    for (let window = 0; window < windowCount; window++) {
      const count = this.runCounts[window] ?? 0;
      for (let run = 0; run < count; run++) ranges[offset + run * 4] = window;
      offset += count * 4;
    }
    return ranges;
  }
}
