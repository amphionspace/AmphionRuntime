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
    if (this.runtimeRelease !== undefined) return true;
    if (this.modelUnload === undefined) this.modelUnload = unload;
    if (!this.retryFailedSessionCloses()) return true;
    const deferred = this.activeSessions > 0;
    this.flush();
    return deferred;
  }

  requestRuntimeRelease(release: () => void): Promise<void> {
    return new Promise<void>((resolve: () => void, reject: (error: Error) => void): void => {
      this.runtimeWaiters.push(new RuntimeReleaseWaiter(resolve, reject));
      if (this.runtimeRelease === undefined) this.runtimeRelease = release;
      // Publish the stronger release before retrying close. A successful retry may synchronously
      // flush the gate, and must see Runtime release rather than the weaker pending model unload.
      // If retry still fails, failPendingRelease rejects this waiter but preserves modelUnload.
      if (!this.retryFailedSessionCloses()) return;
      this.flush();
    });
  }

  isReleasePending(): boolean {
    return this.modelUnload !== undefined || this.runtimeRelease !== undefined;
  }

  diagnosticState(): Record<string, Object> {
    const state: Record<string, Object> = {};
    state['activeSessions'] = this.activeSessions;
    state['failedStreamCloses'] = this.failedLeases.length;
    state['modelUnloadPending'] = this.modelUnload !== undefined;
    state['runtimeReleasePending'] = this.runtimeRelease !== undefined;
    return state;
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
    // Runtime release has a Promise waiter that can observe failure. Model unload does not, so keep
    // its callback pending until a later explicit unload/release request retries the failed close.
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
