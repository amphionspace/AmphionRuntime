import {
  closeTargetSpeakerEnhancer,
  createTargetSpeakerEnhancer,
  isTargetSpeakerEnhancementModelLoaded,
  loadTargetSpeakerEnhancementModel,
  preloadTargetSpeakerEnhancementModelAsync,
  processTargetSpeakerChunk,
  TargetSpeakerEnhancementNativeResult,
  TargetSpeakerEnhancerHandle,
  unloadTargetSpeakerEnhancementModel
} from 'libamphion_asr.so';
import {
  TargetSpeakerEnhancementChunk,
  TargetSpeakerEnhancementProcessor
} from './TargetSpeakerEnhancementStream';

const TARGET_SPEAKER_SEPARATOR_RAWFILE: string =
  'amphion-dingqiao/convtasnet_16k.ort';
const TARGET_SPEAKER_THRESHOLD: number = 0.25;

/** Owns per-session target state and a reference to the shared native separator model. */
export class TargetSpeakerEnhancer implements TargetSpeakerEnhancementProcessor {
  private static preloadTask?: Promise<void>;
  private handle?: TargetSpeakerEnhancerHandle;

  constructor(context: Context, speakerModelPath: string,
    targetEmbedding: Float32Array) {
    TargetSpeakerEnhancer.ensureModelLoaded(context);
    this.handle = createTargetSpeakerEnhancer(
      speakerModelPath,
      context.resourceManager,
      targetEmbedding,
      TARGET_SPEAKER_THRESHOLD
    );
  }

  /** Keeps the heavyweight separator aligned with the SDK L2 model lifecycle. */
  static unloadModel(): void {
    TargetSpeakerEnhancer.preloadTask = undefined;
    unloadTargetSpeakerEnhancementModel();
  }

  /** Loads the separator and a reusable scorer pair on native async work. */
  static async preload(context: Context, speakerModelPath: string,
    targetDimension: number): Promise<void> {
    const active = TargetSpeakerEnhancer.preloadTask;
    if (active !== undefined) {
      await active;
      return;
    }
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
    const task = preloadTargetSpeakerEnhancementModelAsync(
      separatorModel,
      speakerModelPath,
      context.resourceManager,
      targetDimension
    );
    TargetSpeakerEnhancer.preloadTask = task;
    try {
      await task;
    } finally {
      if (TargetSpeakerEnhancer.preloadTask === task) {
        TargetSpeakerEnhancer.preloadTask = undefined;
      }
    }
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

  private static ensureModelLoaded(context: Context): void {
    if (isTargetSpeakerEnhancementModelLoaded()) return;
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
    loadTargetSpeakerEnhancementModel(separatorModel);
  }
}
