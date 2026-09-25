import hilog from '@ohos.hilog';
import { DiagnosticEvent } from './DiagnosticsCore';

export interface DiagnosticSink {
  write(event: DiagnosticEvent): void;
}

/** Bounded test sink; production state remains owned by DiagnosticsCore. */
export class MemoryDiagnosticSink implements DiagnosticSink {
  private readonly events: DiagnosticEvent[] = [];
  private readonly capacity: number;

  constructor(capacity: number = 512) { this.capacity = capacity; }

  write(event: DiagnosticEvent): void {
    this.events.push(event);
    while (this.events.length > Math.max(1, this.capacity)) this.events.shift();
  }

  snapshot(): DiagnosticEvent[] { return this.events.slice(); }
}

/** Human-readable secondary channel. Structured NDJSON remains the source of truth. */
export class HilogDiagnosticSink implements DiagnosticSink {
  write(event: DiagnosticEvent): void {
    hilog.info(0x0000, 'AmphionDiagnostics',
      'seq=%{public}d event=%{public}s session=%{public}s stream=%{public}d',
      event.sequence, event.event, event.sessionId, event.streamGeneration);
  }
}

export class NdjsonDiagnosticSink {
  write(events: DiagnosticEvent[], append: (value: string) => void,
    jsonArray: boolean = false): void {
    if (jsonArray) append('[');
    for (let i = 0; i < events.length; i++) {
      const separator = jsonArray ? (i + 1 < events.length ? ',' : '') : '\n';
      // Tensor snapshots stay compact while retained. Materialize flat JSON
      // arrays for one event only, preserving the existing diagnostic schema.
      const event = events[i];
      const fields: Record<string, Object> = {};
      for (const key of Object.keys(event.fields)) {
        const value = event.fields[key];
        fields[key] = value instanceof Float32Array ? Array.from(value) : value;
      }
      const serializable: DiagnosticEvent = {
        schemaVersion: event.schemaVersion,
        sequence: event.sequence,
        wallTimeMs: event.wallTimeMs,
        monotonicTimeNs: event.monotonicTimeNs,
        runId: event.runId,
        engineId: event.engineId,
        sessionId: event.sessionId,
        sessionGeneration: event.sessionGeneration,
        streamGeneration: event.streamGeneration,
        thread: event.thread,
        event: event.event,
        fields
      };
      const encoded = JSON.stringify(serializable);
      append(`${encoded}${separator}`);
    }
    if (jsonArray) append(']\n');
  }
}
