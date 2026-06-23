import { AssetRegistry, InstalledLayout } from './AssetRegistry';
import { AsrConfig, AsrLanguage, Cancellable } from './Types';

class CompletedCancellable implements Cancellable {
  cancel(): void {}
  isDone(): boolean { return true; }
}

export class AssetInstallResult {
  layout: InstalledLayout = new InstalledLayout();
  installedToFilesDir: boolean = false;
}

export class AssetInstaller {
  /**
   * 首版鸿蒙 SDK 直接从 rawfile 加载模型，与上游 sherpa_onnx HAR 保持一致。
   *
   * Android 版会先把 assets 解包到 filesDir；纯血鸿蒙是否需要解包取决于 rawfile 的
   * 压缩与 mmap 行为，后续真机基准完成后可把这里切换为 rawfile -> filesDir 拷贝。
   */
  static ensureInstalled(_context: Context, language: AsrLanguage, config: AsrConfig): AssetInstallResult {
    const result = new AssetInstallResult();
    result.layout = AssetRegistry.rawfileLayout(language, config);
    result.installedToFilesDir = false;
    return result;
  }

  static preInstall(_context: Context, _language: AsrLanguage, _config: AsrConfig, onProgress?: (doneBytes: number, totalBytes: number) => void): Cancellable {
    onProgress?.(1, 1);
    return new CompletedCancellable();
  }
}
