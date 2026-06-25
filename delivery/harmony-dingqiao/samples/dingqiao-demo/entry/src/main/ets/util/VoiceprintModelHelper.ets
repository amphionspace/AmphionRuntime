import { fileIo as fs, picker } from '@kit.CoreFileKit';
import { common } from '@kit.AbilityKit';

const MODEL_FILENAME = 'eres2net.onnx';
const MIN_BYTES = 30 * 1024 * 1024; // eres2net.onnx is ~38 MB; below this it is partial/wrong

/** Detects the speaker model in workPath and imports one via the system file picker. */
export class VoiceprintModelHelper {
  static modelPath(workPath: string): string {
    return `${workPath}/${MODEL_FILENAME}`;
  }

  static isReady(workPath: string): boolean {
    const path = VoiceprintModelHelper.modelPath(workPath);
    if (!fs.accessSync(path)) return false;
    try {
      return fs.statSync(path).size >= MIN_BYTES;
    } catch (e) {
      return false;
    }
  }

  static async importViaPicker(context: common.UIAbilityContext, workPath: string): Promise<boolean> {
    const uris = await VoiceprintModelHelper.pickFile(context);
    if (uris.length === 0) return false;
    return VoiceprintModelHelper.copyUriToModel(uris[0], workPath);
  }

  private static async pickFile(context: common.UIAbilityContext): Promise<string[]> {
    const options = new picker.DocumentSelectOptions();
    options.maxSelectNumber = 1;
    const documentPicker = new picker.DocumentViewPicker(context);
    try {
      return await documentPicker.select(options);
    } catch (e) {
      return [];
    }
  }

  private static copyUriToModel(uri: string, workPath: string): boolean {
    const dest = VoiceprintModelHelper.modelPath(workPath);
    let src: fs.File | undefined;
    let dst: fs.File | undefined;
    try {
      if (!fs.accessSync(workPath)) fs.mkdirSync(workPath);
      src = fs.openSync(uri, fs.OpenMode.READ_ONLY);
      dst = fs.openSync(dest, fs.OpenMode.READ_WRITE | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
      fs.copyFileSync(src.fd, dst.fd);
      return VoiceprintModelHelper.isReady(workPath);
    } catch (e) {
      return false;
    } finally {
      if (src !== undefined) fs.closeSync(src);
      if (dst !== undefined) fs.closeSync(dst);
    }
  }
}
