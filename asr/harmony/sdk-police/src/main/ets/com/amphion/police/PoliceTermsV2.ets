import { common } from '@kit.AbilityKit';
import { PoliceAssetPair, PoliceAssets } from './PoliceAssets';

class TermMatch {
  term: string;
  consumed: number;

  constructor(term: string, consumed: number) {
    this.term = term;
    this.consumed = consumed;
  }
}

class TermReadingMap {
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

class TermsHomophones {
  private pairs: PoliceAssetPair[];

  constructor(pairs: PoliceAssetPair[]) {
    this.pairs = pairs;
  }

  apply(text: string): string {
    let output = text;
    for (let i = 0; i < this.pairs.length; i++) {
      const pair = this.pairs[i];
      if (pair.from === pair.to) continue;
      output = pair.to.startsWith(pair.from) ?
        this.replaceExtending(output, pair.from, pair.to) : output.split(pair.from).join(pair.to);
    }
    return output;
  }

  private replaceExtending(text: string, from: string, to: string): string {
    let output = '';
    let cursor = 0;
    while (cursor <= text.length) {
      const index = text.indexOf(from, cursor);
      if (index < 0) return output + text.substring(cursor);
      output += text.substring(cursor, index);
      if (index + to.length <= text.length && text.substring(index, index + to.length) === to) {
        output += to;
        cursor = index + to.length;
      } else {
        output += to;
        cursor = index + from.length;
      }
    }
    return output;
  }
}

class RadioDigits {
  private static readonly STRONG: Map<string, string> = new Map<string, string>([
    ['洞', '0'], ['幺', '1'], ['拐', '7'], ['勾', '9'], ['钩', '9']
  ]);
  private static readonly WEAK: Map<string, string> = new Map<string, string>([
    ['两', '2'], ['三', '3'], ['四', '4'], ['五', '5'], ['六', '6'], ['八', '8'],
    ['沟', '9'], ['腰', '1'], ['撩', '1']
  ]);
  private static readonly MISHEAR: Map<string, string> = new Map<string, string>([
    ['栋', '0'], ['动', '0'], ['梁', '2']
  ]);

  private static isArabic(value: string): boolean {
    return value >= '0' && value <= '9';
  }

  private static isConvertible(value: string): boolean {
    return RadioDigits.isArabic(value) || RadioDigits.STRONG.has(value) ||
      RadioDigits.WEAK.has(value) || RadioDigits.MISHEAR.has(value);
  }

  static normalize(text: string): string {
    let output = '';
    let i = 0;
    while (i < text.length) {
      if (!RadioDigits.isConvertible(text.charAt(i))) {
        output += text.charAt(i++);
        continue;
      }
      let end = i;
      while (end < text.length && RadioDigits.isConvertible(text.charAt(end))) end++;
      output += RadioDigits.convertSegment(text.substring(i, end));
      i = end;
    }
    return output;
  }

  private static convertSegment(segment: string): string {
    let arabic = 0;
    let strong = 0;
    for (let i = 0; i < segment.length; i++) {
      const value = segment.charAt(i);
      if (RadioDigits.isArabic(value)) arabic++;
      else if (RadioDigits.STRONG.has(value)) strong++;
    }
    if (arabic + strong < 2 && (strong < 1 || segment.length < 3)) return segment;
    const allowMishear = arabic >= 3;
    let output = '';
    for (let i = 0; i < segment.length; i++) {
      const value = segment.charAt(i);
      if (RadioDigits.isArabic(value)) output += value;
      else if (RadioDigits.STRONG.has(value)) output += RadioDigits.STRONG.get(value);
      else if (RadioDigits.WEAK.has(value)) output += RadioDigits.WEAK.get(value);
      else if (allowMishear && RadioDigits.MISHEAR.has(value)) output += RadioDigits.MISHEAR.get(value);
      else output += value;
    }
    return output;
  }
}

export class PoliceTermsV2 {
  private static readonly MIN_FUZZY_LEN: number = 4;
  private static readonly MIN_VAR_LEN: number = 5;
  private terms: string[];
  private known: Set<string>;
  private homophones: TermsHomophones;
  private readingMap: TermReadingMap;

  constructor(context: common.Context) {
    const pairs = PoliceAssets.readCsvPairs(context, 'police_terms/term_homophones.csv');
    this.terms = PoliceAssets.uniqueByLengthDescending(
      PoliceAssets.readLines(context, 'police_terms/term_gazetteer.txt'));
    this.known = new Set<string>(this.terms);
    this.homophones = new TermsHomophones(pairs);
    this.readingMap = new TermReadingMap(pairs);
  }

  normalize(text: string): string {
    if (text.length === 0) return text;
    return RadioDigits.normalize(this.fuzzyCorrect(this.homophones.apply(text)));
  }

  private maxSubsFor(length: number): number {
    return length >= 7 ? 2 : 1;
  }

  private fuzzyCorrect(text: string): string {
    let output = '';
    let i = 0;
    while (i < text.length) {
      const match = this.bestEqualLenAt(text, i) ?? this.bestVarLenAt(text, i);
      if (match === undefined) {
        output += text.charAt(i++);
      } else {
        output += match.term;
        i += match.consumed;
      }
    }
    return output;
  }

  private bestEqualLenAt(text: string, start: number): TermMatch | undefined {
    let best = '';
    let bestCost = Number.MAX_SAFE_INTEGER;
    let ambiguous = false;
    for (let i = 0; i < this.terms.length; i++) {
      const term = this.terms[i];
      const length = term.length;
      if (length < PoliceTermsV2.MIN_FUZZY_LEN) break;
      if (start + length > text.length) continue;
      const cost = this.subCost(text, start, term);
      if (cost < 0) continue;
      if (best.length === 0 || length > best.length) {
        best = term; bestCost = cost; ambiguous = false;
      } else if (length === best.length && cost < bestCost) {
        best = term; bestCost = cost; ambiguous = false;
      } else if (length === best.length && cost === bestCost && term !== best) {
        ambiguous = true;
      }
    }
    return best.length > 0 && !ambiguous ? new TermMatch(best, best.length) : undefined;
  }

  private bestVarLenAt(text: string, start: number): TermMatch | undefined {
    let best = '';
    let bestConsumed = 0;
    let bestCost = Number.MAX_SAFE_INTEGER;
    let ambiguous = false;
    for (let i = 0; i < this.terms.length; i++) {
      const term = this.terms[i];
      if (term.length < PoliceTermsV2.MIN_VAR_LEN) break;
      const widths = [term.length - 1, term.length + 1];
      for (let w = 0; w < widths.length; w++) {
        const width = widths[w];
        if (start + width > text.length) continue;
        const cost = this.varCost(text, start, term, width);
        if (cost < 0) continue;
        if (best.length === 0 || term.length > best.length) {
          best = term; bestConsumed = width; bestCost = cost; ambiguous = false;
        } else if (term.length === best.length && cost < bestCost) {
          best = term; bestConsumed = width; bestCost = cost; ambiguous = false;
        } else if (term.length === best.length && cost === bestCost &&
          (term !== best || width !== bestConsumed)) {
          ambiguous = true;
        }
      }
    }
    return best.length > 0 && !ambiguous ? new TermMatch(best, bestConsumed) : undefined;
  }

  private subCost(text: string, start: number, term: string): number {
    const budget = this.maxSubsFor(term.length);
    let cost = 0;
    for (let i = 0; i < term.length; i++) {
      const from = text.charAt(start + i);
      const to = term.charAt(i);
      if (from === to) continue;
      if (!this.readingMap.allows(from, to)) return -1;
      if (++cost > budget) return -1;
    }
    return cost;
  }

  private varCost(text: string, start: number, term: string, width: number): number {
    const budget = this.maxSubsFor(term.length);
    const inf = budget + 1;
    let previous: number[] = [];
    for (let j = 0; j <= term.length; j++) previous.push(j);
    for (let i = 1; i <= width; i++) {
      const current: number[] = [i];
      const raw = text.charAt(start + i - 1);
      for (let j = 1; j <= term.length; j++) {
        const expected = term.charAt(j - 1);
        const substitution = raw === expected ? 0 : (this.readingMap.allows(raw, expected) ? 1 : inf);
        current.push(Math.min(inf, previous[j - 1] + substitution, previous[j] + 1, current[j - 1] + 1));
      }
      previous = current;
    }
    const cost = previous[term.length];
    return cost >= 1 && cost <= budget ? cost : -1;
  }
}
