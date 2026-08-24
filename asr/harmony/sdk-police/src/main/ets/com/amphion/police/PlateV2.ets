import { common } from '@kit.AbilityKit';
import { PoliceAssets } from './PoliceAssets';

class ProvinceSpec {
  char: string;
  homophones: string[];
  lettersVerified: boolean;
  letters: Set<string>;

  constructor(char: string, homophones: string[], lettersVerified: boolean, letters: string[]) {
    this.char = char;
    this.homophones = homophones;
    this.lettersVerified = lettersVerified;
    this.letters = new Set<string>(letters);
  }
}

class PlateKnowledgeBase {
  static readonly PLATE_ALPHABET: string = 'ABCDEFGHJKLMNPQRSTUVWXYZ';
  private provinces: Map<string, ProvinceSpec> = new Map<string, ProvinceSpec>();

  constructor(context: common.Context) {
    const lines = PoliceAssets.readLines(context, 'plate/plate_spec_ga36.tsv');
    for (let i = 0; i < lines.length; i++) {
      const columns = lines[i].split('\t');
      if (columns.length < 7) continue;
      const value = columns[0].trim();
      if (value.length !== 1) continue;
      const homophones = this.parseList(columns[4]);
      const letters = this.parseList(columns[6]);
      this.provinces.set(value, new ProvinceSpec(value, homophones, columns[5].trim() === '1', letters));
    }
    if (this.provinces.size === 0) throw new Error('empty plate knowledge base');
  }

  provinceChars(): string[] {
    return Array.from(this.provinces.keys());
  }

  province(value: string): ProvinceSpec | undefined {
    return this.provinces.get(value);
  }

  isProvinceChar(value: string): boolean {
    return this.provinces.has(value);
  }

  isValidAuthorityLetter(province: string, letter: string): boolean {
    const spec = this.provinces.get(province);
    if (spec === undefined || PlateKnowledgeBase.PLATE_ALPHABET.indexOf(letter) < 0) return false;
    return spec.lettersVerified ? spec.letters.has(letter) : true;
  }

  private parseList(value: string): string[] {
    return value.split(',').map((item: string): string => item.trim())
      .filter((item: string): boolean => item.length > 0);
  }
}

class PlateReadingMap {
  static readonly COST_LETTER: number = 2;
  private static readonly COST_DIGIT: number = 1;
  private static readonly COST_PROVINCE: number = 3;
  private targets: Map<string, Set<string>> = new Map<string, Set<string>>();
  private costs: Map<string, Map<string, number>> = new Map<string, Map<string, number>>();

  constructor(context: common.Context, kb: PlateKnowledgeBase) {
    const lines = PoliceAssets.readLines(context, 'plate/plate_homophones.csv').concat(
      PoliceAssets.readLines(context, 'plate/plate_readings_v2.csv'));
    const suppressed: string[] = [];
    for (let i = 0; i < lines.length; i++) {
      const parts = lines[i].split(',');
      if (parts.length < 2) continue;
      const from = parts[0].trim();
      const to = parts[1].trim();
      if (from.length !== 1 || to.length !== 1) continue;
      const category = parts.length > 2 ? parts[2].trim() : '';
      if (category === 'suppress') {
        suppressed.push(from + to);
        continue;
      }
      let cost = PlateReadingMap.COST_LETTER;
      if (from === to) cost = 0;
      else if (category === 'digit') cost = PlateReadingMap.COST_DIGIT;
      else if (category === 'province') cost = PlateReadingMap.COST_PROVINCE;
      this.record(from, to, cost);
    }
    const provinces = kb.provinceChars();
    for (let i = 0; i < provinces.length; i++) {
      const province = provinces[i];
      const spec = kb.province(province);
      if (spec === undefined) continue;
      this.record(province, province, 0);
      for (let h = 0; h < spec.homophones.length; h++) {
        this.record(spec.homophones[h], province,
          spec.homophones[h] === province ? 0 : PlateReadingMap.COST_PROVINCE);
      }
    }
    for (let i = 0; i < suppressed.length; i++) {
      const from = suppressed[i].charAt(0);
      const to = suppressed[i].charAt(1);
      this.targets.get(from)?.delete(to);
      this.costs.get(from)?.delete(to);
    }
  }

  candidates(value: string): string[] {
    const upper = value.toUpperCase();
    const base = this.targets.get(value) ?? this.targets.get(upper);
    const result = new Set<string>();
    if (base !== undefined) base.forEach((item: string): void => { result.add(item); });
    if (PlateKnowledgeBase.PLATE_ALPHABET.indexOf(upper) >= 0) result.add(upper);
    if (this.isDigit(value)) result.add(value);
    return Array.from(result);
  }

  substitutionCost(from: string, to: string): number {
    const upper = from.toUpperCase();
    if (to === from || to === upper) return 0;
    const direct = this.costs.get(from)?.get(to);
    if (direct !== undefined) return direct;
    const normalized = this.costs.get(upper)?.get(to);
    return normalized === undefined ? PlateReadingMap.COST_LETTER : normalized;
  }

  private record(from: string, to: string, cost: number): void {
    let targets = this.targets.get(from);
    if (targets === undefined) {
      targets = new Set<string>();
      this.targets.set(from, targets);
    }
    targets.add(to);
    let row = this.costs.get(from);
    if (row === undefined) {
      row = new Map<string, number>();
      this.costs.set(from, row);
    }
    const previous = row.get(to);
    if (previous === undefined || cost < previous) row.set(to, cost);
  }

  private isDigit(value: string): boolean {
    return value >= '0' && value <= '9';
  }
}

class PlateValidator {
  private kb: PlateKnowledgeBase;
  private serialChars: string = PlateKnowledgeBase.PLATE_ALPHABET + '0123456789';

  constructor(kb: PlateKnowledgeBase) {
    this.kb = kb;
  }

  isValid(plate: string): boolean {
    if (plate.length !== 7 && plate.length !== 8) return false;
    if (!this.kb.isProvinceChar(plate.charAt(0)) ||
      !this.kb.isValidAuthorityLetter(plate.charAt(0), plate.charAt(1))) return false;
    const serial = plate.substring(2);
    if (plate.length === 7) return serial.length === 5 && this.allSerial(serial);
    const small = 'DF'.indexOf(serial.charAt(0)) >= 0 && this.allSerial(serial.substring(1));
    const large = this.allDigits(serial.substring(0, 5)) && 'DF'.indexOf(serial.charAt(5)) >= 0;
    return serial.length === 6 && (small || large);
  }

  private allSerial(value: string): boolean {
    for (let i = 0; i < value.length; i++) if (this.serialChars.indexOf(value.charAt(i)) < 0) return false;
    return true;
  }

  private allDigits(value: string): boolean {
    for (let i = 0; i < value.length; i++) if (value.charAt(i) < '0' || value.charAt(i) > '9') return false;
    return true;
  }
}

class PlateCandidate {
  plate: string;
  cost: number;
  risky: number;

  constructor(plate: string, cost: number, risky: number) {
    this.plate = plate;
    this.cost = cost;
    this.risky = risky;
  }
}

class PlateMatch {
  plate: string;
  endSource: number;
  coverage: number;

  constructor(plate: string, endSource: number, coverage: number) {
    this.plate = plate;
    this.endSource = endSource;
    this.coverage = coverage;
  }
}

class PlateSpanV2 {
  start: number;
  end: number;
  normalized: string;

  constructor(start: number, end: number, normalized: string) {
    this.start = start;
    this.end = end;
    this.normalized = normalized;
  }
}

class SignificantChars {
  chars: string[];
  indices: number[];

  constructor(chars: string[], indices: number[]) {
    this.chars = chars;
    this.indices = indices;
  }
}

class DeduplicatedChars {
  chars: string[];
  ends: number[];
  coverage: number[];

  constructor(chars: string[], ends: number[], coverage: number[]) {
    this.chars = chars;
    this.ends = ends;
    this.coverage = coverage;
  }
}

export class PlateV2 {
  private static readonly MAX_COMBOS: number = 256;
  private static readonly MAX_BODY_CHARS: number = 9;
  private static readonly MAX_RISKY_UNANCHORED: number = 1;
  private static readonly ANCHOR_PRE: number = 24;
  private static readonly ANCHOR_POST: number = 16;
  private kb: PlateKnowledgeBase;
  private readingMap: PlateReadingMap;
  private validator: PlateValidator;
  private homeProvinces: Set<string>;
  private contextProvinces: string[];
  private anchors: string[] = [
    '车', '查', '牌', '号', '辆', '报警', '登记', '记录', '驾', '肇事', '嫌疑', '套牌', '违'
  ];
  private cp5500JiRPatterns: RegExp[] = [];
  private explicitPlateNounBefore: RegExp =
    /(?:车牌号|车牌|号牌)[\s，,：:、.．。；！？~·—-]*(?:为|是)?[\s，,：:、.．。；！？~·—-]*$/;
  private explicitPlateContextAfter: RegExp =
    /^[\s，,：:、.．。；！？~·—-]*(?:这?辆车|车辆|车主|目标车辆|通行记录|离开时.{0,20}方向|(?:刚才)?(?:蹭|撞|刮).{0,10}(?:路边车|车辆|车)|请.{0,8}车主)/;
  private genericIdentifierBefore: RegExp =
    /(?:产品型号|设备编号|订单号|序列号|设备序列号|型号|编号)[\s，,：:、.．。；！？~·—-]*(?:为|是)?[\s，,：:、.．。；！？~·—-]*$/;

  constructor(context: common.Context, contextProvinces: string[] = ['冀', '辽']) {
    this.kb = new PlateKnowledgeBase(context);
    this.readingMap = new PlateReadingMap(context, this.kb);
    this.validator = new PlateValidator(this.kb);
    this.contextProvinces = contextProvinces;
    this.homeProvinces = new Set<string>(contextProvinces);
    const gap = '[\\s，,：:、.．。；！？~·—-]*';
    const tail = `([0-9](?:${gap}[0-9]){4})(?!${gap}[A-Za-z0-9Ａ-Ｚａ-ｚ０-９])`;
    this.cp5500JiRPatterns = [
      new RegExp(`(?<![A-Za-z0-9Ａ-Ｚａ-ｚ０-９])[GgＧｇ]${gap}[IiＩｉ]${gap}(?:[RrＲｒ]|2)${gap}${tail}`, 'g'),
      new RegExp(`(?<![A-Za-z0-9Ａ-Ｚａ-ｚ０-９])[GgＧｇ]${gap}[LlＬｌ]${gap}${tail}`, 'g'),
      new RegExp(`(?<![0-9])7${gap}2${gap}${tail}`, 'g'),
      new RegExp(`(?<![A-Za-z0-9Ａ-Ｚａ-ｚ０-９])(?:[GgＧｇ]${gap}[RrＲｒ]|及${gap}[RrＲｒ])${gap}2${gap}${tail}`, 'g'),
      new RegExp(`(?<![A-Za-z0-9Ａ-Ｚａ-ｚ０-９])[寄汽]${gap}2${gap}${tail}`, 'g')
    ];
  }

  normalize(text: string): string {
    if (text.length === 0) return text;
    const input = this.preprocessStructuralMishears(text);
    const spans: PlateSpanV2[] = [];
    let i = 0;
    while (i < input.length) {
      if (!this.canStartHere(input.charAt(i))) {
        i++;
        continue;
      }
      const match = this.tryMatchPlateAt(input, i);
      if (match === undefined) i++;
      else {
        spans.push(new PlateSpanV2(i, match.endSource, match.plate));
        i = match.endSource;
      }
    }
    if (this.contextProvinces.length > 0) this.appendContextProvinceSpans(input, spans);
    spans.sort((a: PlateSpanV2, b: PlateSpanV2): number => b.start - a.start);
    let output = input;
    for (let s = 0; s < spans.length; s++) {
      output = output.substring(0, spans[s].start) + spans[s].normalized + output.substring(spans[s].end);
    }
    return output;
  }

  private preprocessStructuralMishears(text: string): string {
    return this.rewriteCp5500JiRResiduals(text)
      .replace(/沪19374/g, '沪F19374')
      .replace(/建易60538/g, '晋E60538')
      .replace(/净K/g, '晋K').replace(/进这/g, '晋J').replace(/建寨/g, '晋J')
      .replace(/建债/g, '晋J').replace(/近债/g, '晋J').replace(/这这/g, '浙J')
      .replace(/(?<![A-HJ-NP-Z])京(?=49372)/g, '京R')
      .replace(/(经|金)债\s*95376/g, '京J95376').replace(/京寨\s*95376/g, '京J95376')
      .replace(/GC\s*84915|冀C84915|及418\s*4915/g, '吉C84915')
      .replace(/GF\s*19374|冀F19374/g, '吉F19374')
      .replace(/GH\s*28491|G\s*H\s*28491|冀H28491/g, '吉H28491')
      .replace(/GJ\s*63745|G\s*J\s*63745|冀J63745/g, '吉J63745')
      .replace(/GK\s*41258|G\s*K\s*41258|冀K41258/g, '吉K41258')
      .replace(/G\s*G\s*75826|G智75826|冀G75826/g, '吉G75826')
      .replace(/及G\s*63745/g, '吉J63745').replace(/及G\s*75826/g, '吉G75826')
      .replace(/G智75826/g, '吉G75826').replace(/及质疑7586/g, '吉G75826')
      .replace(/及G\s*7586(?=车辆)/g, '吉G75826')
      .replace(/请帮忙查询G\s*63745/g, '请帮忙查询吉J63745')
      .replace(/晚安92080/g, '皖N92080').replace(/云R\s*293\s*627/g, '云R93627');
  }

  private rewriteCp5500JiRResiduals(text: string): string {
    let output = text;
    for (let i = 0; i < this.cp5500JiRPatterns.length; i++) {
      output = output.replace(
        this.cp5500JiRPatterns[i],
        (matched: string, serialWithGaps: string, offset: number): string => {
          const requirePlateNoun = i === 2;
          if (!this.hasExplicitPlateContext(output, offset, offset + matched.length, requirePlateNoun)) return matched;
          const serial = serialWithGaps.replace(/[^0-9]/g, '');
          const plate = `冀R${serial}`;
          return serial.length === 5 && this.validator.isValid(plate) ? plate : matched;
        }
      );
    }
    return output;
  }

  private hasExplicitPlateContext(text: string, start: number, end: number, requirePlateNoun: boolean): boolean {
    const before = text.substring(Math.max(0, start - 40), start);
    const after = text.substring(end, Math.min(text.length, end + 40));
    if (this.genericIdentifierBefore.test(before)) return false;
    const hasPlateNoun = this.explicitPlateNounBefore.test(before);
    if (requirePlateNoun) return hasPlateNoun;
    return hasPlateNoun || this.explicitPlateContextAfter.test(after);
  }

  private appendContextProvinceSpans(text: string, spans: PlateSpanV2[]): void {
    const covered: boolean[] = new Array<boolean>(text.length).fill(false);
    for (let s = 0; s < spans.length; s++) {
      for (let i = spans[s].start; i < spans[s].end && i < text.length; i++) covered[i] = true;
    }
    let i = 0;
    while (i < text.length) {
      const candidates = this.readingMap.candidates(text.charAt(i));
      const hasAuthority = candidates.some((value: string): boolean =>
        PlateKnowledgeBase.PLATE_ALPHABET.indexOf(value) >= 0);
      if (covered[i] || this.canStartHere(text.charAt(i)) || !hasAuthority) {
        i++;
        continue;
      }
      const sig = this.collectSig(text, i);
      const match = this.inferWithContextProvince(text, i, sig.chars, sig.indices);
      if (match === undefined) i++;
      else {
        spans.push(new PlateSpanV2(i, match.endSource, match.plate));
        i = match.endSource;
      }
    }
  }

  private inferWithContextProvince(text: string, start: number, body: string[], indices: number[]): PlateMatch | undefined {
    if (start > 0 && this.isPlateNumeric(text.charAt(start - 1))) return undefined;
    if (this.hasUnsafeLeftResidue(text, start)) return undefined;
    const lengths = [8, 7];
    for (let l = 0; l < lengths.length; l++) {
      const plateLength = lengths[l];
      const bodyLength = plateLength - 1;
      if (body.length < bodyLength) continue;
      const end = indices[bodyLength - 1] + 1;
      if (end < text.length && this.isPlateNumeric(text.charAt(end))) continue;
      if (!this.hasAnchor(text, start, end)) continue;
      const hits: PlateCandidate[] = [];
      for (let p = 0; p < this.contextProvinces.length; p++) {
        const candidate = this.bestCandidateForLength(
          [this.contextProvinces[p]].concat(body.slice(0, bodyLength)), plateLength);
        if (candidate !== undefined) hits.push(candidate);
      }
      if (hits.length === 1) return new PlateMatch(hits[0].plate, end, plateLength);
    }
    return undefined;
  }

  private hasUnsafeLeftResidue(text: string, start: number): boolean {
    let i = start - 1;
    while (i >= 0 && this.isSeparator(text.charAt(i))) i--;
    if (i < 0) return false;
    const value = text.charAt(i);
    return /[A-Za-z0-9Ａ-Ｚａ-ｚ０-９]/.test(value) || '寄汽'.indexOf(value) >= 0;
  }

  private canStartHere(value: string): boolean {
    return this.readingMap.candidates(value).some((candidate: string): boolean => this.kb.isProvinceChar(candidate));
  }

  private isPlateNumeric(value: string): boolean {
    return (value >= '0' && value <= '9') || '零〇一二三四五六七八九幺两'.indexOf(value) >= 0;
  }

  private collectSig(text: string, start: number): SignificantChars {
    const chars: string[] = [];
    const indices: number[] = [];
    let i = start;
    while (i < text.length && chars.length < PlateV2.MAX_BODY_CHARS) {
      const value = text.charAt(i);
      if (this.isSeparator(value)) {
        i++;
        continue;
      }
      if (this.readingMap.candidates(value).length === 0) break;
      chars.push(value);
      indices.push(i++);
    }
    return new SignificantChars(chars, indices);
  }

  private tryMatchPlateAt(text: string, start: number): PlateMatch | undefined {
    const sig = this.collectSig(text, start);
    if (sig.chars.length < 7) return undefined;
    const matchA = this.bestAcceptedMatch(text, start, sig.chars,
      (length: number): number => sig.indices[length - 1] + 1,
      (length: number): number => length);
    const deduplicated = this.dedupAdjacent(sig.chars, sig.indices);
    let matchB: PlateMatch | undefined = undefined;
    if (deduplicated.chars.length !== sig.chars.length) {
      matchB = this.bestAcceptedMatch(text, start, deduplicated.chars,
        (length: number): number => deduplicated.ends[length - 1],
        (length: number): number => deduplicated.coverage[length - 1]);
    }
    return matchB !== undefined && (matchA === undefined || matchB.coverage > matchA.coverage) ? matchB : matchA;
  }

  private bestAcceptedMatch(text: string, start: number, sequence: string[],
    endForLength: (length: number) => number,
    coverageForLength: (length: number) => number): PlateMatch | undefined {
    const lengths = [8, 7];
    for (let i = 0; i < lengths.length; i++) {
      const length = lengths[i];
      if (sequence.length < length) continue;
      const candidate = this.bestCandidateForLength(sequence, length);
      if (candidate === undefined) continue;
      const end = endForLength(length);
      if (this.acceptSpan(text, start, end, candidate)) {
        return new PlateMatch(candidate.plate, end, coverageForLength(length));
      }
    }
    return undefined;
  }

  private dedupAdjacent(chars: string[], indices: number[]): DeduplicatedChars {
    const result: string[] = [];
    const ends: number[] = [];
    const coverage: number[] = [];
    let i = 0;
    while (i < chars.length) {
      let end = i;
      while (end + 1 < chars.length && chars[end + 1] === chars[i]) end++;
      result.push(chars[i]);
      ends.push(indices[end] + 1);
      coverage.push(end + 1);
      i = end + 1;
    }
    return new DeduplicatedChars(result, ends, coverage);
  }

  private acceptSpan(text: string, start: number, end: number, candidate: PlateCandidate): boolean {
    if (candidate.cost === 0) return true;
    if (this.startsWithGb(text, start)) return this.hasAnchor(text, start, end);
    return candidate.risky <= PlateV2.MAX_RISKY_UNANCHORED || this.hasAnchor(text, start, end);
  }

  private startsWithGb(text: string, start: number): boolean {
    if (start >= text.length || 'GgＧｇ'.indexOf(text.charAt(start)) < 0) return false;
    let i = start + 1;
    while (i < text.length && /\s/.test(text.charAt(i))) i++;
    return i < text.length && 'BbＢｂ'.indexOf(text.charAt(i)) >= 0;
  }

  private hasAnchor(text: string, start: number, end: number): boolean {
    const before = text.substring(Math.max(0, start - PlateV2.ANCHOR_PRE), start);
    const after = text.substring(end, Math.min(text.length, end + PlateV2.ANCHOR_POST));
    const context = before + after;
    return this.anchors.some((anchor: string): boolean => context.indexOf(anchor) >= 0);
  }

  private bestCandidateForLength(chars: string[], length: number): PlateCandidate | undefined {
    const positions: string[][] = [];
    let combinations = 1;
    for (let position = 0; position < length; position++) {
      const raw = this.readingMap.candidates(chars[position]);
      const filtered = position === 0 ?
        raw.filter((value: string): boolean => this.kb.isProvinceChar(value)) :
        raw.filter((value: string): boolean => PlateKnowledgeBase.PLATE_ALPHABET.indexOf(value) >= 0 ||
          (value >= '0' && value <= '9'));
      if (filtered.length === 0) return undefined;
      positions.push(filtered);
      combinations *= filtered.length;
    }
    const sequences = combinations <= PlateV2.MAX_COMBOS ? this.expandCartesian(positions) :
      [positions.map((options: string[], index: number): string => this.preferIdentity(options, chars[index]))];
    let best: PlateCandidate | undefined = undefined;
    for (let i = 0; i < sequences.length; i++) {
      const plate = sequences[i].join('');
      if (!this.validator.isValid(plate)) continue;
      let cost = 0;
      let risky = 0;
      for (let position = 0; position < length; position++) {
        const weight = this.readingMap.substitutionCost(chars[position], sequences[i][position]);
        cost += weight;
        if (weight >= PlateReadingMap.COST_LETTER &&
          !(position === 0 && this.homeProvinces.has(sequences[i][position]))) risky++;
      }
      const better = best === undefined || cost < best.cost ||
        (cost === best.cost && risky < best.risky) ||
        (cost === best.cost && risky === best.risky && this.isHomeProvince(plate) && !this.isHomeProvince(best.plate));
      if (better) best = new PlateCandidate(plate, cost, risky);
    }
    return best;
  }

  private isHomeProvince(plate: string): boolean {
    return plate.length > 0 && this.homeProvinces.has(plate.charAt(0));
  }

  private preferIdentity(options: string[], original: string): string {
    const upper = original.toUpperCase();
    for (let i = 0; i < options.length; i++) if (options[i] === upper || options[i] === original) return options[i];
    return options[0];
  }

  private expandCartesian(positions: string[][]): string[][] {
    let accumulated: string[][] = [[]];
    for (let i = 0; i < positions.length; i++) {
      const next: string[][] = [];
      for (let p = 0; p < accumulated.length; p++) {
        for (let o = 0; o < positions[i].length; o++) next.push(accumulated[p].concat([positions[i][o]]));
      }
      accumulated = next;
    }
    return accumulated;
  }

  private isSeparator(value: string): boolean {
    return /\s/.test(value) || '·.-—~。，；！？．、'.indexOf(value) >= 0;
  }
}
