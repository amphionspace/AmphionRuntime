export class SessionCallbackGate {
  private closed: boolean = false;
  private invocationDepth: number = 0;

  isClosed(): boolean {
    return this.closed;
  }

  isInvoking(): boolean {
    return this.invocationDepth > 0;
  }

  close(): boolean {
    if (this.closed) return false;
    this.closed = true;
    return true;
  }

  invoke(callback: () => void): boolean {
    if (this.closed) return false;
    this.invocationDepth += 1;
    try {
      callback();
    } finally {
      this.invocationDepth -= 1;
    }
    return !this.closed;
  }
}
