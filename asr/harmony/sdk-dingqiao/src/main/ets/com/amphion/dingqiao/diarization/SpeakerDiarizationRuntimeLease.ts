export class SpeakerDiarizationRuntimeLease {
  private released: boolean = false;

  release(): void {
    if (this.released) return;
    this.released = true;
    SpeakerDiarizationRuntimeLeaseRegistry.releaseOne();
  }
}

/** Keeps SDK teardown from crossing an active diarization finish barrier. */
export class SpeakerDiarizationRuntimeLeaseRegistry {
  private static activeLeases: number = 0;
  private static releaseRequests: number = 0;
  private static idleResolvers: Array<() => void> = [];

  static acquire(): SpeakerDiarizationRuntimeLease {
    if (this.releaseRequests > 0) {
      throw new Error('speaker diarization runtime release is pending');
    }
    this.activeLeases += 1;
    return new SpeakerDiarizationRuntimeLease();
  }

  static beginRelease(): Promise<void> {
    this.releaseRequests += 1;
    if (this.activeLeases === 0) return Promise.resolve();
    return new Promise<void>((resolve: () => void): void => {
      this.idleResolvers.push(resolve);
    });
  }

  static endRelease(): void {
    if (this.releaseRequests > 0) this.releaseRequests -= 1;
  }

  static isReleasePending(): boolean { return this.releaseRequests > 0; }

  static releaseOne(): void {
    if (this.activeLeases <= 0) return;
    this.activeLeases -= 1;
    if (this.activeLeases !== 0) return;
    const resolvers = this.idleResolvers;
    this.idleResolvers = [];
    for (let i = 0; i < resolvers.length; i++) resolvers[i]();
  }
}
