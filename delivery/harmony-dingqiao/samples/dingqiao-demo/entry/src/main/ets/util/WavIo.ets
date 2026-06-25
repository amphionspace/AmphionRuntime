import { fileIo as fs } from '@kit.CoreFileKit';

const SAMPLE_RATE = 16000;
const HEADER_BYTES = 44;

/** Minimal 16 kHz / mono / PCM16 WAV reader and writer for voiceprint enrollment samples. */
export class WavIo {
  static write(path: string, pcm: Int16Array, sampleRate: number = SAMPLE_RATE): void {
    const dataBytes = pcm.length * 2;
    const buf = new ArrayBuffer(HEADER_BYTES + dataBytes);
    const view = new DataView(buf);
    WavIo.writeAscii(view, 0, 'RIFF');
    view.setUint32(4, 36 + dataBytes, true);
    WavIo.writeAscii(view, 8, 'WAVE');
    WavIo.writeAscii(view, 12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    WavIo.writeAscii(view, 36, 'data');
    view.setUint32(40, dataBytes, true);
    for (let i = 0; i < pcm.length; i++) view.setInt16(HEADER_BYTES + i * 2, pcm[i], true);
    const fp = fs.openSync(path, fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
    try {
      fs.writeSync(fp.fd, buf);
    } finally {
      fs.close(fp.fd);
    }
  }

  static readPcm(path: string): Int16Array {
    if (!fs.accessSync(path)) return new Int16Array(0);
    const fp = fs.openSync(path);
    try {
      const size = fs.statSync(fp.fd).size;
      if (size <= HEADER_BYTES) return new Int16Array(0);
      const buf = new ArrayBuffer(size);
      fs.readSync(fp.fd, buf);
      const count = Math.floor((size - HEADER_BYTES) / 2);
      const view = new DataView(buf);
      const out = new Int16Array(count);
      for (let i = 0; i < count; i++) out[i] = view.getInt16(HEADER_BYTES + i * 2, true);
      return out;
    } finally {
      fs.close(fp.fd);
    }
  }

  static durationLabel(sampleCount: number, sampleRate: number = SAMPLE_RATE): string {
    return `${(sampleCount / sampleRate).toFixed(1)}s`;
  }

  /** WAV file byte length -> audio duration in seconds (subtracts the fixed header). */
  static durationSecFromBytes(byteLength: number): number {
    const dataBytes = Math.max(0, byteLength - HEADER_BYTES);
    return dataBytes / (SAMPLE_RATE * 2);
  }

  private static writeAscii(view: DataView, offset: number, text: string): void {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  }
}
