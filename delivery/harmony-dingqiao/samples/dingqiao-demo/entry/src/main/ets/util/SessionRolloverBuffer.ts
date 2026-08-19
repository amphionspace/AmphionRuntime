export type SessionRolloverRoute = 'write' | 'buffer' | 'finish';

/** Keeps recorder frames ordered while one public ASR session finishes and its successor starts. */
export class SessionRolloverBuffer {
  private readonly rotateAfterMs: number;
  private readonly maxPendingFrames: number;
  private pendingFrames: ArrayBuffer[] = [];
  private rotating: boolean = false;
  private droppedFrames: number = 0;

  constructor(rotateAfterMs: number, maxPendingFrames: number) {
    this.rotateAfterMs = rotateAfterMs;
    this.maxPendingFrames = maxPendingFrames;
  }

  route(frame: ArrayBuffer, enabled: boolean, sessionAudioMs: number,
    sessionId: string): SessionRolloverRoute {
    if (this.rotating) {
      this.enqueue(frame);
      return 'buffer';
    }
    if (!enabled || sessionId.length === 0 || sessionAudioMs < this.rotateAfterMs) return 'write';
    this.rotating = true;
    this.enqueue(frame);
    return 'finish';
  }

  isRotating(): boolean {
    return this.rotating;
  }

  complete(): ArrayBuffer[] {
    const buffered = this.pendingFrames;
    this.pendingFrames = [];
    this.rotating = false;
    return buffered;
  }

  reset(): void {
    this.pendingFrames = [];
    this.rotating = false;
    this.droppedFrames = 0;
  }

  pendingCount(): number {
    return this.pendingFrames.length;
  }

  droppedCount(): number {
    return this.droppedFrames;
  }

  private enqueue(frame: ArrayBuffer): void {
    if (this.pendingFrames.length < this.maxPendingFrames) {
      this.pendingFrames.push(frame);
    } else {
      this.droppedFrames += 1;
    }
  }
}
