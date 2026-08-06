import {
  closeTargetSpeakerEnhancer,
  createTargetSpeakerEnhancer,
  processTargetSpeakerChunk,
  TargetSpeakerEnhancementNativeResult,
  TargetSpeakerEnhancerHandle
} from 'libamphion_asr.so';
import {
  TargetSpeakerEnhancementChunk,
  TargetSpeakerEnhancementProcessor
} from './TargetSpeakerEnhancementStream';

const TARGET_SPEAKER_SEPARATOR_RAWFILE: string =
  'amphion-dingqiao/convtasnet_16k.onnx';
const TARGET_SPEAKER_THRESHOLD: number = 0.25;

/** Owns the native separator and speaker scorer for one public session. */
export class TargetSpeakerEnhancer implements TargetSpeakerEnhancementProcessor {
  private handle?: TargetSpeakerEnhancerHandle;

  constructor(context: Context, speakerModelPath: string,
    targetEmbedding: Float32Array) {
    let separatorModel: Uint8Array;
    try {
      separatorModel = context.resourceManager.getRawFileContentSync(
        TARGET_SPEAKER_SEPARATOR_RAWFILE
      );
    } catch (_) {
      throw new Error(
        'target speaker enhancement model is not bundled: ' +
        TARGET_SPEAKER_SEPARATOR_RAWFILE
      );
    }
    this.handle = createTargetSpeakerEnhancer(
      separatorModel,
      speakerModelPath,
      context.resourceManager,
      targetEmbedding,
      TARGET_SPEAKER_THRESHOLD
    );
  }

  async process(chunk: TargetSpeakerEnhancementChunk): Promise<Float32Array> {
    const handle = this.handle;
    if (handle === undefined) throw new Error('target speaker enhancer is closed');
    const result: TargetSpeakerEnhancementNativeResult =
      await processTargetSpeakerChunk(handle, chunk.samples);
    return result.samples;
  }

  close(): void {
    const handle = this.handle;
    this.handle = undefined;
    if (handle !== undefined) closeTargetSpeakerEnhancer(handle);
  }
}
