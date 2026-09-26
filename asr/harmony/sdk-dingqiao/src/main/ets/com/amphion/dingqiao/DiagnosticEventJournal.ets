import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import { DiagnosticEvent } from './DiagnosticsCore';
import { NdjsonDiagnosticSink } from './DiagnosticSinks';

interface DiagnosticEventLocation {
  offset: number;
  length: number;
}

/** Immutable event bytes are shared by periodic, per-session and final exports. */
export class DiagnosticEventJournal {
  private readonly path: string;
  private readonly locations: Map<number, DiagnosticEventLocation> = new Map();
  private readonly encoder: util.TextEncoder = new util.TextEncoder();
  private readonly sink: NdjsonDiagnosticSink = new NdjsonDiagnosticSink();
  private length: number = 0;

  constructor(path: string) { this.path = path; }

  persist(events: DiagnosticEvent[]): void {
    const file = fs.openSync(this.path, fs.OpenMode.READ_WRITE | fs.OpenMode.CREATE);
    try {
      fs.lseek(file.fd, this.length, fs.WhenceType.SEEK_SET);
      for (const event of events) {
        if (this.locations.has(event.sequence)) continue;
        const bytes = this.encoder.encodeInto(`${this.sink.encode(event)}\n`);
        try {
          const count = fs.writeSync(file.fd, bytes.buffer, { length: bytes.byteLength });
          if (count !== bytes.byteLength) throw new Error('incomplete diagnostic event write');
        } catch (error) {
          // Failed persistence must retain the original fields for a later export.
          fs.truncateSync(file.fd, this.length);
          throw new Error(`${error}`);
        }
        this.locations.set(event.sequence, { offset: this.length, length: bytes.byteLength });
        this.length += bytes.byteLength;
        if (event.event === 'DIARIZATION_COMMUNITY_WINDOW' ||
          event.event === 'DIARIZATION_COMMUNITY_SAMPLES' ||
          event.event === 'DIARIZATION_COMMUNITY_COMMIT') {
          // The full decision remains in the journal; summaries need only scalars.
          // Do not retain every historical posterior matrix on the ArkTS heap.
          const scalars: Record<string, Object> = {};
          for (const key of Object.keys(event.fields)) {
            const value = event.fields[key];
            if (typeof value === 'number' || typeof value === 'string' || typeof value === 'boolean') {
              scalars[key] = value;
            }
          }
          event.fields = scalars;
        }
      }
    } finally { fs.closeSync(file.fd); }
  }

  write(events: DiagnosticEvent[], append: (bytes: ArrayBuffer, length: number) => void,
    jsonArray: boolean = false): void {
    const file = fs.openSync(this.path, fs.OpenMode.READ_ONLY);
    const buffer = new ArrayBuffer(64 * 1024);
    const separator = new ArrayBuffer(2);
    const punctuation = new Uint8Array(separator);
    try {
      if (jsonArray) { punctuation[0] = 91; append(separator, 1); }
      for (let index = 0; index < events.length; index++) {
        const location = this.locations.get(events[index].sequence);
        if (location === undefined) throw new Error('diagnostic event has not been persisted');
        const length = location.length - (jsonArray ? 1 : 0);
        fs.lseek(file.fd, location.offset, fs.WhenceType.SEEK_SET);
        let copied = 0;
        while (copied < length) {
          const count = Math.min(buffer.byteLength, length - copied);
          if (fs.readSync(file.fd, buffer, { length: count }) !== count) {
            throw new Error('incomplete diagnostic event read');
          }
          append(buffer, count);
          copied += count;
        }
        if (jsonArray && index + 1 < events.length) { punctuation[0] = 44; append(separator, 1); }
      }
      if (jsonArray) { punctuation[0] = 93; punctuation[1] = 10; append(separator, 2); }
    } finally { fs.closeSync(file.fd); }
  }
}
