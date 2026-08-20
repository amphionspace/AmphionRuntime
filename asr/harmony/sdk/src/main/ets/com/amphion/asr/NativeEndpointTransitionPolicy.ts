export class NativeEndpointTransitionPolicy {
  static readonly HARD_RESTART: number = 0;
  static readonly SOFT_RESET: number = 1;

  static decide(hasEvidence: boolean, nativeStreamSamplesAccepted: number,
    sampleRate: number, rule3MinUtteranceLengthSec: number): number {
    if (!hasEvidence || !Number.isFinite(nativeStreamSamplesAccepted) ||
      !Number.isFinite(sampleRate) || !Number.isFinite(rule3MinUtteranceLengthSec) ||
      nativeStreamSamplesAccepted < 0 || sampleRate <= 0 || rule3MinUtteranceLengthSec <= 0) {
      return NativeEndpointTransitionPolicy.HARD_RESTART;
    }
    const rule3Samples = Math.ceil(rule3MinUtteranceLengthSec * sampleRate);
    return nativeStreamSamplesAccepted >= rule3Samples ?
      NativeEndpointTransitionPolicy.SOFT_RESET : NativeEndpointTransitionPolicy.HARD_RESTART;
  }
}
