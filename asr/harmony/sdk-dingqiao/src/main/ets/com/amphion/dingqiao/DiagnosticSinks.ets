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
  serialize(events: DiagnosticEvent[]): string {
    let output = '';
    for (let i = 0; i < events.length; i++) output += `${JSON.stringify(events[i])}\n`;
    return output;
  }
}
