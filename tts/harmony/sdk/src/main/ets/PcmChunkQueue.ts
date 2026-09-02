export interface PcmQueueTakeResult {
  chunk?: ArrayBuffer;
  done: boolean;
}

export class PcmChunkQueue {
  private readonly capacity: number;
  private readonly chunks: Array<ArrayBuffer> = [];
  private closed: boolean = false;
  private waitingTakers: Array<(result: PcmQueueTakeResult) => void> = [];
  private waitingPutters: Array<() => void> = [];
  private prebufferWaiters: Array<() => void> = [];

  constructor(capacity: number, maxCapacity: number) {
    this.capacity = clampInt(Math.round(capacity), 1, maxCapacity);
  }

  async put(chunk: ArrayBuffer): Promise<void> {
    while (!this.closed && this.chunks.length >= this.capacity) {
      await new Promise<void>((resolve: () => void): void => {
        this.waitingPutters.push(resolve);
      });
    }
    if (this.closed) {
      return;
    }
    const taker = this.waitingTakers.shift();
    if (taker !== undefined) {
      taker({ chunk, done: false });
      return;
    }
    this.chunks.push(chunk);
    this.notifyPrebufferWaiters();
  }

  async take(): Promise<PcmQueueTakeResult> {
    const chunk = this.chunks.shift();
    if (chunk !== undefined) {
      this.notifyPutters();
      return { chunk, done: false };
    }
    if (this.closed) {
      return { done: true };
    }
    return new Promise<PcmQueueTakeResult>((resolve: (result: PcmQueueTakeResult) => void): void => {
      this.waitingTakers.push(resolve);
    });
  }

  async waitForPrebuffer(targetChunks: number): Promise<void> {
    const target = Math.min(Math.max(1, targetChunks), this.capacity);
    while (!this.closed && this.chunks.length < target) {
      await new Promise<void>((resolve: () => void): void => {
        this.prebufferWaiters.push(resolve);
      });
    }
  }

  close(): void {
    this.closed = true;
    this.waitingTakers.splice(0).forEach((resolve: (result: PcmQueueTakeResult) => void): void => {
      resolve({ done: true });
    });
    this.notifyPutters();
    this.notifyPrebufferWaiters();
  }

  private notifyPutters(): void {
    this.waitingPutters.splice(0).forEach((resolve: () => void): void => resolve());
  }

  private notifyPrebufferWaiters(): void {
    this.prebufferWaiters.splice(0).forEach((resolve: () => void): void => resolve());
  }
}

function clampInt(value: number, minValue: number, maxValue: number): number {
  return Math.min(maxValue, Math.max(minValue, value));
}
