import { PoliceTextEdit, PoliceTextTrace } from './PoliceTextTrace';

export interface PersonSpan {
  start: number;
  end: number;
}

class NameCandidate {
  value: string;
  signature: string;

  constructor(value: string, signature: string) {
    this.value = value;
    this.signature = signature;
  }
}

/**
 * 声母混淆组。归一到同一个代表音后，组内声母视为同一个音。
 *
 * 只放 n/l：客户名单里的「倪凯」被识别成「李凯」(ni2 vs li3)，n/l 不分是中文 ASR 与
 * 大量方言区共有的混淆，且「倪」在模型词表里没有整字单元、解码期永远纠不回来
 * （实测把热词分数抬到 30.0 只会吐乱码）。其余混淆组（zh/z、前后鼻音等）要各自
 * 拿数据证明收益大于误替换，不在这里顺手加。
 */
const INITIAL_CONFUSIONS: string[][] = [['n', 'l']];

class Replacement {
  start: number;
  end: number;
  value: string;

  constructor(start: number, end: number, value: string) {
    this.start = start;
    this.end = end;
    this.value = value;
  }
}

/**
 * Replaces an ASR homophone when the candidate window overlaps a LAC PER span.
 * Three-character names also get an exact-pinyin fallback, because LAC can miss
 * a person span when the preceding character is ambiguous.
 * Signatures containing multiple configured names are intentionally ignored.
 *
 * 精确签名命中不了的，再走一条有界的模糊通道：去声调 + 声母 n↔l 归一。它只在 LAC 人名
 * 区间内生效，而且 2 字和 3 字一视同仁都要求 PER 证据——模糊证据弱于精确，不能再享受
 * 三字的纯拼音兜底。同一个模糊签名命中多个配置名时整体忽略：名单里同时有「李凯」和
 * 「倪凯」，两者都不改写，退回模型原始输出。
 */
export class PersonNameMatcher {
  private pinyin: Map<string, string>;
  private candidates: NameCandidate[] = [];
  private fuzzyCandidates: NameCandidate[] = [];
  private configured: Set<string> = new Set<string>();

  constructor(pinyin: Map<string, string>, names: string[]) {
    this.pinyin = pinyin;
    const bySignature = new Map<string, string[]>();
    const byFuzzySignature = new Map<string, string[]>();
    const seen = new Set<string>();
    for (let i = 0; i < names.length; i++) {
      const name = names[i].trim();
      if (name.length < 2 || name.length > 3 || seen.has(name)) continue;
      seen.add(name);
      const signature = this.signatureOf(name);
      if (signature === undefined) continue;
      this.configured.add(name);
      const existing = bySignature.get(signature) ?? [];
      existing.push(name);
      bySignature.set(signature, existing);
      const fuzzy = this.fuzzySignatureOf(name);
      if (fuzzy === undefined) continue;
      const fuzzyExisting = byFuzzySignature.get(fuzzy) ?? [];
      fuzzyExisting.push(name);
      byFuzzySignature.set(fuzzy, fuzzyExisting);
    }
    bySignature.forEach((values: string[], signature: string): void => {
      if (values.length === 1) this.candidates.push(new NameCandidate(values[0], signature));
    });
    byFuzzySignature.forEach((values: string[], signature: string): void => {
      if (values.length === 1) this.fuzzyCandidates.push(new NameCandidate(values[0], signature));
    });
    const byLengthDesc = (a: NameCandidate, b: NameCandidate): number =>
      b.value.length - a.value.length;
    this.candidates.sort(byLengthDesc);
    this.fuzzyCandidates.sort(byLengthDesc);
  }

  normalize(text: string, personSpans: PersonSpan[], trace?: PoliceTextTrace): string {
    if (text.length === 0 ||
      (this.candidates.length === 0 && this.fuzzyCandidates.length === 0)) return text;
    const replacements: Replacement[] = [];
    for (let i = 0; i < this.candidates.length; i++) {
      const target = this.candidates[i];
      const width = target.value.length;
      if (width > text.length) continue;
      for (let start = 0; start + width <= text.length; start++) {
        const end = start + width;
        const overlapsPerson = PersonNameMatcher.overlapsPerson(start, end, personSpans);
        if (!overlapsPerson && width < 3) continue;
        const source = text.substring(start, end);
        if (source === target.value || this.signatureOf(source) !== target.signature) continue;
        if (PersonNameMatcher.overlapsReplacement(start, end, replacements)) continue;
        replacements.push(new Replacement(start, end, target.value));
      }
    }
    // 精确通道没能命中的，再走有界模糊：声母 n↔l 归一 + 忽略声调。证据比精确弱，所以
    // 每个长度都必须压在 LAC 人名区间上，且不碰本身就是配置名的文本。
    for (let i = 0; i < this.fuzzyCandidates.length; i++) {
      const target = this.fuzzyCandidates[i];
      const width = target.value.length;
      if (width > text.length) continue;
      for (let start = 0; start + width <= text.length; start++) {
        const end = start + width;
        if (!PersonNameMatcher.overlapsPerson(start, end, personSpans)) continue;
        const source = text.substring(start, end);
        if (source === target.value || this.configured.has(source)) continue;
        if (this.fuzzySignatureOf(source) !== target.signature) continue;
        if (PersonNameMatcher.overlapsReplacement(start, end, replacements)) continue;
        replacements.push(new Replacement(start, end, target.value));
      }
    }
    replacements.sort((a: Replacement, b: Replacement): number => b.start - a.start);
    let output = text;
    const edits: PoliceTextEdit[] = [];
    for (let i = 0; i < replacements.length; i++) {
      const replacement = replacements[i];
      edits.unshift(new PoliceTextEdit(replacement.start, replacement.end, replacement.value));
      output = output.substring(0, replacement.start) + replacement.value +
        output.substring(replacement.end);
    }
    trace?.step(text, output, edits);
    return output;
  }

  /** 去声调 + 声母按 INITIAL_CONFUSIONS 归一；任一字查不到拼音就放弃整条签名。 */
  private fuzzySignatureOf(text: string): string | undefined {
    const syllables: string[] = [];
    for (let i = 0; i < text.length; i++) {
      const value = this.pinyin.get(text.charAt(i));
      if (value === undefined || value.length === 0) return undefined;
      syllables.push(PersonNameMatcher.fuzzySyllable(value));
    }
    return syllables.join('|');
  }

  private static fuzzySyllable(value: string): string {
    let syllable = value;
    const last = syllable.charAt(syllable.length - 1);
    if (last >= '0' && last <= '9') syllable = syllable.substring(0, syllable.length - 1);
    if (syllable.length === 0) return syllable;
    const initial = syllable.charAt(0);
    for (let i = 0; i < INITIAL_CONFUSIONS.length; i++) {
      const group = INITIAL_CONFUSIONS[i];
      if (group.indexOf(initial) >= 0) return group[0] + syllable.substring(1);
    }
    return syllable;
  }

  private signatureOf(text: string): string | undefined {
    const syllables: string[] = [];
    for (let i = 0; i < text.length; i++) {
      const value = this.pinyin.get(text.charAt(i));
      if (value === undefined || value.length === 0) return undefined;
      syllables.push(value);
    }
    return syllables.join('|');
  }

  private static overlapsPerson(start: number, end: number, spans: PersonSpan[]): boolean {
    for (let i = 0; i < spans.length; i++) {
      if (start < spans[i].end && end > spans[i].start) return true;
    }
    return false;
  }

  private static overlapsReplacement(start: number, end: number, values: Replacement[]): boolean {
    for (let i = 0; i < values.length; i++) {
      if (start < values[i].end && end > values[i].start) return true;
    }
    return false;
  }
}
