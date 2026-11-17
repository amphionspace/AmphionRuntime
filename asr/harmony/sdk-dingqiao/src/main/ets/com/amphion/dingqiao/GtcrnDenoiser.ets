import { closeGtcrnDenoiser, createGtcrnDenoiser, processGtcrn,
  GtcrnDenoiserHandle, GtcrnNativeResult } from 'libamphion_asr.so';
import { GtcrnFrontend, GtcrnProcessor } from './GtcrnFrontend';

/** Per-session model/cache; callers serialize run and flush in SessionAudioDispatcher. */
export class GtcrnDenoiser implements GtcrnProcessor {
  private handle?: GtcrnDenoiserHandle;
  readonly frontend: GtcrnFrontend;
  readonly modelName: string;
  constructor(context: Context, modelName: string = 'deepfilternet3') {
    this.modelName = modelName;
    // Fail in ArkTS before entering the library if this optional asset was not packaged.
    const assets: string[] = ['df3_enc_stream.onnx', 'df3_erb_dec_stream.onnx', 'df3_df_dec_stream.onnx'];
    for (const asset of assets) context.resourceManager.getRawFileContentSync(`amphion-dingqiao/${asset}`);
    this.handle = createGtcrnDenoiser(context.resourceManager, modelName);
    this.frontend = new GtcrnFrontend(this);
  }
  async process(samples: Float32Array, flush: boolean): Promise<GtcrnNativeResult> {
    const handle = this.handle;
    if (handle === undefined) throw new Error('noise suppressor is closed');
    return await processGtcrn(handle, samples, flush);
  }
  close(): void {
    const handle = this.handle;
    this.handle = undefined;
    if (handle !== undefined) closeGtcrnDenoiser(handle);
  }
}
