const SPEAKER_MODEL_FILENAME = 'eres2net.onnx';
const SPEAKER_MODEL_RAWFILE = `amphion-dingqiao/${SPEAKER_MODEL_FILENAME}`;

/** Provides the single SDK-owned model identity used by registration and recognition. */
export class DingqiaoSpeakerModelAssets {
  static bundledPath(): string {
    return SPEAKER_MODEL_RAWFILE;
  }

  static complementaryDiarizationPath(): string {
    return 'amphion-dingqiao/campplus.onnx';
  }

  static communityDiarizationPath(): string {
    return 'amphion-dingqiao/community1-wespeaker.onnx';
  }

  static communitySegmentationPath(): string {
    return 'amphion-dingqiao/community1-segmentation.onnx';
  }

  static communityPldaPath(): string {
    return 'amphion-dingqiao/community1-plda.npz';
  }

  static communityXvecTransformPath(): string {
    return 'amphion-dingqiao/community1-xvec-transform.npz';
  }

  static communityPldaRuntimePath(): string {
    return 'amphion-dingqiao/community1-plda.bin';
  }
}
