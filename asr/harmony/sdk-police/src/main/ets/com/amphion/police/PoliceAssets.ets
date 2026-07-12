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
