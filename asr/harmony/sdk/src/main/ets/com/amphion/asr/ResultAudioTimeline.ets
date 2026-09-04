import { AsrResult } from './Types';

/** @internal SDK-to-adapter metadata; never serialized as part of an ASR result. */
export class ResultAudioTimeline {
  private static readonly endpoints: WeakMap<AsrResult, number> = new WeakMap();

  static record(result: AsrResult, endSample: number): void {
    ResultAudioTimeline.endpoints.set(result, endSample);
  }

  static endSample(result: AsrResult): number | undefined {
    return ResultAudioTimeline.endpoints.get(result);
  }
}
