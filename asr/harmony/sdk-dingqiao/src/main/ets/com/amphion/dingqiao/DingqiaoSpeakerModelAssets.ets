import { fileIo as fs } from '@kit.CoreFileKit';

const SPEAKER_MODEL_FILENAME = 'eres2net.onnx';
const SPEAKER_MODEL_RAWFILE = `amphion-dingqiao/${SPEAKER_MODEL_FILENAME}`;
// Exact size of the checked-in model; rejects interrupted copies and stale manually imported files.
const SPEAKER_MODEL_EXPECTED_BYTES = 39593761;

/** Owns installation of the SDK-bundled speaker model into the configured work directory. */
export class DingqiaoSpeakerModelAssets {
  static preferredLoadPath(workPath: string): string {
    const installed = DingqiaoSpeakerModelAssets.modelPath(workPath);
    return DingqiaoSpeakerModelAssets.isReady(installed) ? installed : SPEAKER_MODEL_RAWFILE;
  }

  static modelPath(workPath: string): string {
    if (workPath.trim().length === 0) throw new Error('SpeechRecognizeSdk.setWorkPath must be called first');
    return `${workPath}/${SPEAKER_MODEL_FILENAME}`;
  }

  static isReady(path: string): boolean {
    if (!fs.accessSync(path)) return false;
    try {
      return fs.statSync(path).size === SPEAKER_MODEL_EXPECTED_BYTES;
    } catch (e) {
      return false;
    }
  }

  static ensureInstalled(context: Context, workPath: string): string {
    const destination = DingqiaoSpeakerModelAssets.modelPath(workPath);
    if (DingqiaoSpeakerModelAssets.isReady(destination)) return destination;

    if (!fs.accessSync(workPath)) fs.mkdirSync(workPath, true);
    const temporary = `${destination}.tmp`;
    let output: fs.File | undefined;
    try {
      if (fs.accessSync(temporary)) fs.unlinkSync(temporary);
      const bytes = context.resourceManager.getRawFileContentSync(SPEAKER_MODEL_RAWFILE);
      output = fs.openSync(temporary, fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
      fs.writeSync(output.fd, bytes.buffer);
      fs.fsyncSync(output.fd);
      fs.closeSync(output);
      output = undefined;

      if (!DingqiaoSpeakerModelAssets.isReady(temporary)) {
        throw new Error(`embedded speaker model is incomplete: ${fs.statSync(temporary).size} bytes`);
      }
      if (fs.accessSync(destination)) fs.unlinkSync(destination);
      fs.renameSync(temporary, destination);
      return destination;
    } catch (e) {
      if (output !== undefined) fs.closeSync(output);
      if (fs.accessSync(temporary)) fs.unlinkSync(temporary);
      throw new Error(`speaker model install failed: ${SPEAKER_MODEL_RAWFILE} -> ${destination}: ${e}`);
    }
  }
}
