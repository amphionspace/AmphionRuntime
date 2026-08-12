class RuntimeReleaseWaiter {
  resolve: () => void;
  reject: (error: Error) => void;

  constructor(resolve: () => void, reject: (error: Error) => void) {
    this.resolve = resolve;
    this.reject = reject;
  }
}

/** An idempotent ownership token for one session's use of process-wide native resources. */
export class RuntimeSessionLease {
  private gate: RuntimeReleaseGate;
  private released: boolean = false;
  private closePending: boolean = false;
  private closeAction?: () => void;

  constructor(gate: RuntimeReleaseGate) {
    this.gate = gate;
  }

  release(): void {
    if (this.released) return;
    this.released = true;
    this.closePending = false;
    this.gate.sessionReleased(this);
  }

  releaseAfterClose(close: () => void): boolean {
    if (this.released) return true;
    this.closeAction = close;
    return this.retryClose();
  }

  retryClose(): boolean {
    if (this.released) return true;
    const close = this.closeAction;
    if (close === undefined) return false;
    try {
      close();
    } catch (e) {
      this.closePending = true;
      this.gate.sessionCloseFailed(this, new Error(`native stream close failed: ${e}`));
      return false;
    }
    this.release();
    return true;
  }

  hasPendingClose(): boolean {
    return this.closePending && !this.released;
  }
}

/**
 * Owns the boundary between active native sessions and process-wide model/runtime release.
 * A session lease is held until its last in-flight native call has returned and its stream closes.
 */
export class RuntimeReleaseGate {
  private activeSessions: number = 0;
  private modelUnload?: () => void;
  private runtimeRelease?: () => void;
  private runtimeWaiters: RuntimeReleaseWaiter[] = [];
  private failedLeases: RuntimeSessionLease[] = [];

  retainSession(): RuntimeSessionLease | undefined {
    if (this.isReleasePending()) return undefined;
    this.activeSessions += 1;
    return new RuntimeSessionLease(this);
  }

  sessionReleased(lease: RuntimeSessionLease): void {
    const failedIndex = this.failedLeases.indexOf(lease);
    if (failedIndex >= 0) this.failedLeases.splice(failedIndex, 1);
    if (this.activeSessions === 0) return;
    this.activeSessions -= 1;
    this.flush();
  }

  sessionCloseFailed(lease: RuntimeSessionLease, error: Error): void {
    if (this.failedLeases.indexOf(lease) < 0) this.failedLeases.push(lease);
    this.failPendingRelease(error);
  }

  /** Returns true when the model unload was deferred or a failed stream close blocked it. */
  requestModelUnload(unload: () => void): boolean {
    if (!this.retryFailedSessionCloses()) return true;
    if (this.runtimeRelease !== undefined) return true;
    if (this.activeSessions === 0) {
      unload();
      return false;
    }
    if (this.modelUnload === undefined) this.modelUnload = unload;
    return true;
  }

  requestRuntimeRelease(release: () => void): Promise<void> {
    return new Promise<void>((resolve: () => void, reject: (error: Error) => void): void => {
      if (!this.retryFailedSessionCloses()) {
        reject(new Error('native stream close retry failed'));
        return;
      }
      this.runtimeWaiters.push(new RuntimeReleaseWaiter(resolve, reject));
      if (this.runtimeRelease === undefined) this.runtimeRelease = release;
      // Runtime release already includes model unload and therefore supersedes it.
      this.modelUnload = undefined;
      this.flush();
    });
  }

  isReleasePending(): boolean {
    return this.modelUnload !== undefined || this.runtimeRelease !== undefined;
  }

  private flush(): void {
    if (this.activeSessions > 0) return;
    const release = this.runtimeRelease;
    if (release !== undefined) {
      this.runtimeRelease = undefined;
      this.modelUnload = undefined;
      try {
        release();
      } catch (e) {
        this.rejectWaiters(new Error(`Runtime release failed: ${e}`));
        return;
      }
      const waiters = this.takeWaiters();
      for (let i = 0; i < waiters.length; i++) waiters[i].resolve();
      return;
    }
    const unload = this.modelUnload;
    if (unload === undefined) return;
    this.modelUnload = undefined;
    unload();
  }

  private retryFailedSessionCloses(): boolean {
    const pending = this.failedLeases.slice();
    for (let i = 0; i < pending.length; i++) {
      if (pending[i].hasPendingClose() && !pending[i].retryClose()) return false;
    }
    return true;
  }

  private failPendingRelease(error: Error): void {
    this.runtimeRelease = undefined;
    this.modelUnload = undefined;
    this.rejectWaiters(error);
  }

  private rejectWaiters(error: Error): void {
    const waiters = this.takeWaiters();
    for (let i = 0; i < waiters.length; i++) waiters[i].reject(error);
  }

  private takeWaiters(): RuntimeReleaseWaiter[] {
    const waiters = this.runtimeWaiters;
    this.runtimeWaiters = [];
    return waiters;
  }
}
