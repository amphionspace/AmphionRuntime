import { common } from '@kit.AbilityKit';
import { util } from '@kit.ArkTS';

export class PoliceAssetPair {
  from: string;
  to: string;
  category: string;

  constructor(from: string, to: string, category: string = '') {
    this.from = from;
    this.to = to;
    this.category = category;
  }
}

export class PoliceAssets {
  private static readonly ROOT: string = 'amphion-police';
  /** 只随包发行解码期热词表、不含后处理资产的发行变体标记。 */
  private static readonly VARIANT_HOTWORDS_ONLY: string = 'hotwords-only';

  static readText(context: common.Context, path: string): string {
    const bytes = context.resourceManager.getRawFileContentSync(`${PoliceAssets.ROOT}/${path}`);
    return util.TextDecoder.create('utf-8').decodeToString(bytes);
  }

  static readLines(context: common.Context, path: string): string[] {
    return PoliceAssets.readText(context, path)
      .split(/\r?\n/)
      .map((line: string): string => line.trim())
      .filter((line: string): boolean => line.length > 0 && !line.startsWith('#'));
  }

  static readCsvPairs(context: common.Context, path: string): PoliceAssetPair[] {
    const pairs: PoliceAssetPair[] = [];
    const lines = PoliceAssets.readLines(context, path);
    for (let i = 0; i < lines.length; i++) {
      const parts = lines[i].split(',');
      if (parts.length < 2) continue;
      const from = parts[0].trim();
      const to = parts[1].trim();
      if (from.length === 0 || to.length === 0) continue;
      pairs.push(new PoliceAssetPair(from, to, parts.length > 2 ? parts[2].trim().toLowerCase() : ''));
    }
    pairs.sort((a: PoliceAssetPair, b: PoliceAssetPair): number => b.from.length - a.from.length);
    return pairs;
  }

  /**
   * 后处理资产是否随包发行。
   *
   * 「四川话 / 无警务后处理」交付包用 trim_police_postprocessing.py 把术语、车牌、
   * 派出所的 FST 词典与 LAC 人名模型裁掉（约 36 MB），只留 hotwords.json，并在
   * 资产 manifest 上打 variant=hotwords-only。后处理在那种包里既不执行也无数据可读，
   * 所以引擎据此判定不构造后处理流水线。
   *
   * 读不到或读不懂 manifest 时按「可用」处理：既有交付包的行为不因这段新增代码改变。
   */
  static postprocessingAvailable(context: common.Context): boolean {
    let variant: Object | undefined = undefined;
    try {
      const parsed = JSON.parse(PoliceAssets.readText(context, 'manifest.json')) as Record<string, Object>;
      variant = parsed['variant'];
    } catch (e) {
      return true;
    }
    return variant === undefined || `${variant}` !== PoliceAssets.VARIANT_HOTWORDS_ONLY;
  }

  static readHotwords(context: common.Context, domain: string): string[] {
    let parsed: Record<string, Object> = {};
    try {
      parsed = JSON.parse(PoliceAssets.readText(context, 'hotwords.json')) as Record<string, Object>;
    } catch (e) {
      throw new Error(`invalid police hotwords asset: ${e}`);
    }
    const value = parsed[domain];
    return Array.isArray(value) ? value as string[] : [];
  }

  static uniqueByLengthDescending(values: string[]): string[] {
    const seen = new Set<string>();
    const result: string[] = [];
    for (let i = 0; i < values.length; i++) {
      const value = values[i].trim();
      if (value.length === 0 || seen.has(value)) continue;
      seen.add(value);
      result.push(value);
    }
    result.sort((a: string, b: string): number => b.length - a.length);
    return result;
  }
}
