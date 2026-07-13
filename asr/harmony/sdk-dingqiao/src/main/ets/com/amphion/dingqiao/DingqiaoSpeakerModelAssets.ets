const SPEAKER_MODEL_FILENAME = 'eres2net.onnx';
const SPEAKER_MODEL_RAWFILE = `amphion-dingqiao/${SPEAKER_MODEL_FILENAME}`;

/** Provides the single SDK-owned model identity used by registration and recognition. */
export class DingqiaoSpeakerModelAssets {
  static bundledPath(): string {
    return SPEAKER_MODEL_RAWFILE;
  }
}
