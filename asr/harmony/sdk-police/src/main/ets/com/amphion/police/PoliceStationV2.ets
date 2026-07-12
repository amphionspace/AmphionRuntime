import { common } from '@kit.AbilityKit';
import { PoliceAssetPair, PoliceAssets } from './PoliceAssets';

class StationReadingMap {
  private subs: Map<string, Set<string>> = new Map<string, Set<string>>();

  constructor(pairs: PoliceAssetPair[]) {
    for (let p = 0; p < pairs.length; p++) {
      const pair = pairs[p];
      if (pair.from.length === 0 || pair.from.length !== pair.to.length) continue;
      for (let i = 0; i < pair.from.length; i++) {
        const from = pair.from.charAt(i);
        const to = pair.to.charAt(i);
        if (from === to) continue;
        let targets = this.subs.get(from);
        if (targets === undefined) {
          targets = new Set<string>();
          this.subs.set(from, targets);
        }
        targets.add(to);
      }
    }
  }

  allows(from: string, to: string): boolean {
    if (from === to) return true;
    const targets = this.subs.get(from);
    return targets !== undefined && targets.has(to);
  }
}

class RawStationSpan {
  start: number;
  end: number;
  raw: string;

  constructor(start: number, end: number, raw: string) {
    this.start = start;
    this.end = end;
    this.raw = raw;
  }
}

export class PoliceStationV2 {
  private static readonly MAX_SUBS: number = 4;
  private names: string[];
  private known: Set<string>;
  private globalPairs: PoliceAssetPair[] = [];
  private gazetteerPairs: PoliceAssetPair[] = [];
  private readingMap: StationReadingMap;

  constructor(context: common.Context) {
    const pairs = PoliceAssets.readCsvPairs(context, 'police_station/station_homophones.csv');
    for (let i = 0; i < pairs.length; i++) {
      if (pairs[i].category === 'gazetteer') this.gazetteerPairs.push(pairs[i]);
      else this.globalPairs.push(pairs[i]);
    }
    this.names = PoliceAssets.uniqueByLengthDescending(
      PoliceAssets.readLines(context, 'police_station/station_gazetteer.txt'));
    this.known = new Set<string>(this.names);
    this.readingMap = new StationReadingMap(pairs);
  }

  normalize(text: string): string {
    if (text.length === 0 || this.isDecodeCollapse(text)) return text;
    let corrected = this.normalizeAdminPunct(this.applyGlobalPhrases(text));
    const span = this.locateSpan(corrected);
    if (span === undefined) return this.polish(corrected);

    let normalized = this.normalizeSpan(span.raw, corrected);
    normalized = this.normalizeAdminPunct(normalized);
    corrected = corrected.substring(0, span.start) + normalized + corrected.substring(span.end);
    return this.polish(corrected);
  }

  private applyGlobalPhrases(text: string): string {
    let output = text;
    for (let i = 0; i < this.globalPairs.length; i++) {
      output = output.split(this.globalPairs[i].from).join(this.globalPairs[i].to);
    }
    return output;
  }

  private isDecodeCollapse(text: string): boolean {
    const value = text.trim();
    if (value.length === 0) return true;
    if (/[A-Za-z]{4,}|TWIG|NOISE|滚滚滚|呜呜|嗯嗯嗯|帮我帮我|汇总会汇|通通控控/.test(value)) return true;
    if (value.indexOf('派出所') < 0 && value.length < 12) return true;
    if (value.length >= 20) {
      let cjk = 0;
      for (let i = 0; i < value.length; i++) {
        const code = value.charCodeAt(i);
        if (code >= 0x4E00 && code <= 0x9FFF) cjk++;
      }
      if (cjk / value.length < 0.45) return true;
    }
    return false;
  }

  private normalizeAdminPunct(text: string): string {
    return text
      .replace(/([市区县])、/g, '$1')
      .replace(/派出所，/g, '派出所')
      .replace(/，派出所/g, '派出所')
      .replace(/(汇总|统计|导出|整理)，/g, '$1');
  }

  private findLongestIn(text: string): string | undefined {
    for (let i = 0; i < this.names.length; i++) {
      if (text.indexOf(this.names[i]) >= 0) return this.names[i];
    }
    return undefined;
  }

  private locateSpan(text: string): RawStationSpan | undefined {
    const known = this.findLongestIn(text);
    if (known !== undefined) {
      const start = text.indexOf(known);
      return new RawStationSpan(start, start + known.length, known);
    }
    const regex = /[\u4e00-\u9fff0-9]{2,28}派出所/g;
    let best: RegExpExecArray | undefined = undefined;
    let match = regex.exec(text);
    while (match !== null) {
      if (best === undefined || match[0].length < best[0].length) best = match;
      match = regex.exec(text);
    }
    return best === undefined ? undefined : new RawStationSpan(best.index, best.index + best[0].length, best[0]);
  }

  private normalizeSpan(raw: string, context: string): string {
    if (this.known.has(raw)) return raw;
    const equal = this.matchTier(raw, false);
    if (equal !== undefined) return equal;
    const fuzzy = this.matchTier(raw, true);
    if (fuzzy !== undefined) return fuzzy;
    const inRaw = this.findLongestIn(raw);
    if (inRaw !== undefined) return inRaw;
    const inContext = this.findLongestIn(context);
    if (inContext !== undefined) return inContext;
    return raw;
  }

  private matchTier(raw: string, fuzzy: boolean): string | undefined {
    let best = '';
    let bestCost = Number.MAX_SAFE_INTEGER;
    let ambiguous = false;
    for (let i = 0; i < this.names.length; i++) {
      const name = this.names[i];
      const cost = fuzzy ? this.fuzzyTailCost(raw, name) : this.tailSubCost(raw, name);
      if (cost < 0) continue;
      if (best.length === 0 || name.length > best.length) {
        best = name; bestCost = cost; ambiguous = false;
      } else if (name.length === best.length && cost < bestCost) {
        best = name; bestCost = cost; ambiguous = false;
      } else if (name.length === best.length && cost === bestCost && name !== best) {
        ambiguous = true;
      }
    }
    return best.length > 0 && !ambiguous ? best : undefined;
  }

  private tailSubCost(raw: string, name: string): number {
    if (name.length > raw.length) return -1;
    const offset = raw.length - name.length;
    let cost = 0;
    for (let i = 0; i < name.length; i++) {
      const from = raw.charAt(offset + i);
      const to = name.charAt(i);
      if (from === to) continue;
      if (!this.readingMap.allows(from, to)) return -1;
      if (++cost > PoliceStationV2.MAX_SUBS) return -1;
    }
    return cost;
  }

  private fuzzyTailCost(raw: string, name: string): number {
    const inf = PoliceStationV2.MAX_SUBS + 1;
    let previous: number[] = [];
    for (let j = 0; j <= name.length; j++) previous.push(j);
    for (let i = 1; i <= raw.length; i++) {
      const current: number[] = [0];
      const from = raw.charAt(i - 1);
      for (let j = 1; j <= name.length; j++) {
        const to = name.charAt(j - 1);
        const substitution = from === to ? 0 : (this.readingMap.allows(from, to) ? 1 : inf);
        current.push(Math.min(inf, previous[j - 1] + substitution, previous[j] + 1, current[j - 1] + 1));
      }
      previous = current;
    }
    return previous[name.length] <= PoliceStationV2.MAX_SUBS ? previous[name.length] : -1;
  }

  private polish(text: string): string {
    let output = text.trim();
    if (output.length === 0) return output;
    output = output
      .replace(/麻烦和一下/g, '麻烦核一下')
      .replace(/麻烦和/g, '麻烦核')
      .replace(/接警数据，按(派警|日期|天分)/g, '接警数据按$1')
      .replace(/接警情况，/g, '接警情况')
      .replace(/接警多少[？?]$/g, '接警多少起。')
      .replace(/接警多[。]?$/g, '接警多少起。')
      .replace(/接警数[。]?$/g, '接警数据。');
    if (output.endsWith('？') || output.endsWith('?')) output = output.substring(0, output.length - 1) + '。';
    if (!output.endsWith('。')) output += '。';
    return output;
  }
}
