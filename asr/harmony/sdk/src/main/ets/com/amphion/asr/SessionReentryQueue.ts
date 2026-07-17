export const SESSION_OPERATION_AUDIO: number = 1;
export const SESSION_OPERATION_STOP: number = 2;

class SessionOperation {
  kind: number;
  samples: Float32Array;

  constructor(kind: number, samples: Float32Array = new Float32Array(0)) {
    this.kind = kind;
    this.samples = samples;
  }
}

// Public APIs may be called synchronously from a result/event callback. Keep those calls ordered,
// but execute them only after the native stream transition that produced the callback has returned.
export class SessionReentryQueue {
  private operations: SessionOperation[] = [];
  private draining: boolean = false;
  private stopQueued: boolean = false;

  enqueueAudio(samples: Float32Array): void {
    if (samples.length === 0 || this.stopQueued) return;
    this.operations.push(new SessionOperation(SESSION_OPERATION_AUDIO, samples.slice()));
  }

  enqueueStop(): void {
    if (this.stopQueued) return;
    this.stopQueued = true;
    this.operations.push(new SessionOperation(SESSION_OPERATION_STOP));
  }

  // If an endpoint callback synchronously requested only stop(), the endpoint that produced the
  // callback is already the terminal speech boundary. Consume that exact request so its text can be
  // published as isLast instead of resetting the stream and manufacturing a second empty final.
  // Audio queued before stop must retain FIFO semantics and therefore prevents boundary consumption.
  consumeStopAtEndpoint(): boolean {
    if (this.operations.length !== 1 || this.operations[0].kind !== SESSION_OPERATION_STOP) return false;
    this.operations = [];
    this.stopQueued = false;
    return true;
  }

  drain(isClosed: () => boolean, acceptAudio: (samples: Float32Array) => void,
    stop: () => void): void {
    if (this.draining) return;
    this.draining = true;
    try {
      while (this.operations.length > 0 && !isClosed()) {
        const operation = this.operations.shift();
        if (operation === undefined) break;
        if (operation.kind === SESSION_OPERATION_STOP) {
          stop();
          this.operations = [];
          break;
        }
        acceptAudio(operation.samples);
      }
      if (isClosed()) this.operations = [];
    } finally {
      if (this.operations.length === 0) this.stopQueued = false;
      this.draining = false;
    }
  }

  clear(): void {
    this.operations = [];
    this.stopQueued = false;
  }
}
