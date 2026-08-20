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
 * Replaces an ASR homophone only when the candidate window overlaps a LAC PER span.
 * Signatures containing multiple configured names are intentionally ignored.
 */
export class PersonNameMatcher {
  private pinyin: Map<string, string>;
  private candidates: NameCandidate[] = [];

  constructor(pinyin: Map<string, string>, names: string[]) {
    this.pinyin = pinyin;
    const bySignature = new Map<string, string[]>();
    const seen = new Set<string>();
    for (let i = 0; i < names.length; i++) {
      const name = names[i].trim();
      if (name.length < 2 || name.length > 6 || seen.has(name)) continue;
      seen.add(name);
      const signature = this.signatureOf(name);
      if (signature === undefined) continue;
      const existing = bySignature.get(signature) ?? [];
      existing.push(name);
      bySignature.set(signature, existing);
    }
    bySignature.forEach((values: string[], signature: string): void => {
      if (values.length === 1) this.candidates.push(new NameCandidate(values[0], signature));
    });
    this.candidates.sort((a: NameCandidate, b: NameCandidate): number =>
      b.value.length - a.value.length);
  }

  normalize(text: string, personSpans: PersonSpan[]): string {
    if (text.length === 0 || personSpans.length === 0 || this.candidates.length === 0) return text;
    const replacements: Replacement[] = [];
    for (let i = 0; i < this.candidates.length; i++) {
      const target = this.candidates[i];
      const width = target.value.length;
      if (width > text.length) continue;
      for (let start = 0; start + width <= text.length; start++) {
        const end = start + width;
        if (!PersonNameMatcher.overlapsPerson(start, end, personSpans)) continue;
        const source = text.substring(start, end);
        if (source === target.value || this.signatureOf(source) !== target.signature) continue;
        if (PersonNameMatcher.overlapsReplacement(start, end, replacements)) continue;
        replacements.push(new Replacement(start, end, target.value));
      }
    }
    replacements.sort((a: Replacement, b: Replacement): number => b.start - a.start);
    let output = text;
    for (let i = 0; i < replacements.length; i++) {
      const replacement = replacements[i];
      output = output.substring(0, replacement.start) + replacement.value +
        output.substring(replacement.end);
    }
    return output;
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
