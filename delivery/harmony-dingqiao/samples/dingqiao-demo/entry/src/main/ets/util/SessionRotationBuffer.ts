export class SessionRotationDrain {
  frames: ArrayBuffer[] = [];
  droppedFrames: number = 0;
}

/** Keeps recorder PCM continuous while a finished session hands off to its replacement. */
export class SessionRotationBuffer {
  private maxFrames: number;
  private frames: ArrayBuffer[] = [];
  private droppedFrames: number = 0;

  constructor(maxFrames: number) {
    if (maxFrames <= 0) throw new Error('maxFrames must be positive');
    this.maxFrames = maxFrames;
  }

  append(frame: ArrayBuffer): boolean {
    if (this.frames.length >= this.maxFrames) {
      this.droppedFrames += 1;
      return false;
    }
    this.frames.push(frame.slice(0));
    return true;
  }

  drain(): SessionRotationDrain {
    const result = new SessionRotationDrain();
    result.frames = this.frames;
    result.droppedFrames = this.droppedFrames;
    this.frames = [];
    this.droppedFrames = 0;
    return result;
  }

  reset(): void {
    this.frames = [];
    this.droppedFrames = 0;
  }

  size(): number {
    return this.frames.length;
  }
}
