export class NativeSegmentDecision {
  segmentIndex: number = 0;
  pcmBytesAccepted: number = 0;
  durationMs: number = 0;
  firstPartialLatencyMs: number = -1;
  endpointReason: string = '';
  hasEvidence: boolean = false;
  nativeTextLength: number = 0;
  nativeTokenCount: number = 0;
  published: boolean = false;
  publicSpanSegments: number = 0;
  suppressedSincePublic: number = 0;
}

/**
 * Tracks recognizer-native boundaries independently from public finals.
 *
 * A token-only endpoint can be intentionally suppressed by the public result
 * policy. It still ended and reset a native stream, so its PCM duration and
 * first-partial latency must not leak into the next public utterance metric.
 */
export class NativeSegmentTracker {
  private segmentIndex: number = 0;
  private pcmBytesAccepted: number = 0;
  private firstPcmMs: number = -1;
  private firstPartialLatencyMs: number = -1;
  private publicSpanSegments: number = 0;
  private suppressedSincePublic: number = 0;

  acceptPcm(byteLength: number, nowMs: number = Date.now()): void {
    if (byteLength <= 0) return;
    if (this.firstPcmMs < 0) this.firstPcmMs = nowMs;
    this.pcmBytesAccepted += byteLength;
  }

  observePartial(nowMs: number = Date.now()): void {
    if (this.firstPartialLatencyMs >= 0 || this.firstPcmMs < 0) return;
    this.firstPartialLatencyMs = Math.max(0, nowMs - this.firstPcmMs);
  }

  replaceCurrentPcm(byteLength: number, nowMs: number = Date.now()): void {
    this.pcmBytesAccepted = Math.max(0, byteLength);
    this.firstPcmMs = this.pcmBytesAccepted > 0 ? nowMs : -1;
    this.firstPartialLatencyMs = -1;
  }

  finish(endpointReason: string, hasEvidence: boolean, nativeTextLength: number,
    nativeTokenCount: number, published: boolean): NativeSegmentDecision {
    this.segmentIndex += 1;
    this.publicSpanSegments += 1;
    if (!published) this.suppressedSincePublic += 1;

    const result = new NativeSegmentDecision();
    result.segmentIndex = this.segmentIndex;
    result.pcmBytesAccepted = this.pcmBytesAccepted;
    result.durationMs = Math.round(this.pcmBytesAccepted * 1000 / 32000);
    result.firstPartialLatencyMs = this.firstPartialLatencyMs;
    result.endpointReason = endpointReason;
    result.hasEvidence = hasEvidence;
    result.nativeTextLength = Math.max(0, nativeTextLength);
    result.nativeTokenCount = Math.max(0, nativeTokenCount);
    result.published = published;
    result.publicSpanSegments = this.publicSpanSegments;
    result.suppressedSincePublic = this.suppressedSincePublic;

    this.pcmBytesAccepted = 0;
    this.firstPcmMs = -1;
    this.firstPartialLatencyMs = -1;
    if (published) {
      this.publicSpanSegments = 0;
      this.suppressedSincePublic = 0;
    }
    return result;
  }
}
