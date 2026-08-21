export class NativeEndpointTransition {
  static readonly HARD_RESTART = new NativeEndpointTransition('hard-restart');
  static readonly NATIVE_CHECKPOINT = new NativeEndpointTransition('native-checkpoint');

  private readonly value: string;

  private constructor(value: string) {
    this.value = value;
  }
}

export class NativeEndpointTransitionPolicy {
  static decide(isRule3Endpoint: boolean, hasEvidence: boolean,
    speakerVadEnabled: boolean): NativeEndpointTransition {
    return isRule3Endpoint && hasEvidence && !speakerVadEnabled ?
      NativeEndpointTransition.NATIVE_CHECKPOINT : NativeEndpointTransition.HARD_RESTART;
  }
}
