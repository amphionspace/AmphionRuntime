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
