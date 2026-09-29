/** One local rewrite, in the coordinates of the step's input text. */
export class PoliceTextEdit {
  begin: number;
  end: number;
  text: string;

  constructor(begin: number, end: number, text: string) {
    this.begin = begin;
    this.end = end;
    this.text = text;
  }
}

/** Source range [sourceBegin, sourceEnd) of the enhancer input became [textBegin, textEnd). */
export interface PoliceTextSpan {
  sourceBegin: number;
  sourceEnd: number;
  textBegin: number;
  textEnd: number;
}

/** Contiguous records from the enhancer input to its output; equal slices were copied. */
export interface PoliceTextProvenance {
  sourceText: string;
  spans: PoliceTextSpan[];
}

/** Records a replacement made by String.replace and returns it unchanged. */
export function recordEdit(edits: PoliceTextEdit[], matched: string, offset: number, value: string): string {
  if (value !== matched) edits.push(new PoliceTextEdit(offset, offset + matched.length, value));
  return value;
}

/**
 * String.replace with a global pattern and a replacement function, recording
 * each changed match. Groups that did not participate are '' as in a `$n`
 * template; `offset` is the match position in `text`.
 */
export function replaceMatches(text: string, pattern: RegExp, edits: PoliceTextEdit[],
  replacement: (matched: string, groups: string[], offset: number) => string): string {
  return text.replace(pattern, (matched: string, ...args: (string | number | undefined)[]): string => {
    let index = 0;
    while (index < args.length && typeof args[index] !== 'number') index++;
    const offset = args[index] as number;
    const groups: string[] = [];
    for (let i = 0; i < index; i++) groups.push((args[i] as string | undefined) ?? '');
    return recordEdit(edits, matched, offset, replacement(matched, groups, offset));
  });
}

/** text.split(from).join(to) for a non-empty `from`, with its edits. */
export function replaceLiteral(text: string, from: string, to: string, edits: PoliceTextEdit[]): string {
  if (from.length === 0 || from === to) return text.split(from).join(to);
  let output = '';
  let cursor = 0;
  let index = text.indexOf(from);
  while (index >= 0) {
    output += text.substring(cursor, index) + to;
    edits.push(new PoliceTextEdit(index, index + from.length, to));
    cursor = index + from.length;
    index = text.indexOf(from, cursor);
  }
  return output + text.substring(cursor);
}

class TraceSegment {
  text: string;
  sourceBegin: number;
  sourceEnd: number;
  copied: boolean;

  constructor(text: string, sourceBegin: number, sourceEnd: number, copied: boolean) {
    this.text = text;
    this.sourceBegin = sourceBegin;
    this.sourceEnd = sourceEnd;
    this.copied = copied;
  }
}

/**
 * Composes the local edits of every enhancement step into provenance for the
 * final text. A copied segment maps character for character; a rewritten one
 * is indivisible. A step whose input is not the traced text, or whose edits do
 * not rebuild its output exactly, makes the trace opaque: no provenance is
 * better than a wrong one.
 */
export class PoliceTextTrace {
  private source: string;
  private text: string;
  private segments: TraceSegment[] = [];
  private opaque: boolean = false;

  constructor(source: string) {
    this.source = source;
    this.text = source;
    if (source.length > 0) this.segments.push(new TraceSegment(source, 0, source.length, true));
  }

  step(input: string, output: string, edits: PoliceTextEdit[]): void {
    if (this.opaque || input === output) return;
    if (input !== this.text) {
      this.opaque = true;
      return;
    }
    let cursor = 0;
    let rebuilt = '';
    for (let i = 0; i < edits.length; i++) {
      const edit = edits[i];
      if (edit.begin < cursor || edit.end < edit.begin || edit.end > input.length) {
        this.opaque = true;
        return;
      }
      rebuilt += input.substring(cursor, edit.begin) + edit.text;
      cursor = edit.end;
    }
    if (rebuilt + input.substring(cursor) !== output) {
      this.opaque = true;
      return;
    }
    // Right to left keeps each remaining edit's coordinates valid.
    for (let i = edits.length - 1; i >= 0; i--) this.apply(edits[i]);
    this.text = output;
  }

  /** Whether the traced steps produced exactly `text`. */
  matches(text: string): boolean {
    return !this.opaque && this.text === text;
  }

  provenance(): PoliceTextProvenance | undefined {
    if (this.opaque || this.text === this.source) return undefined;
    const spans: PoliceTextSpan[] = [];
    let textBegin = 0;
    for (let i = 0; i < this.segments.length; i++) {
      const segment = this.segments[i];
      const textEnd = textBegin + segment.text.length;
      const previous = spans.length > 0 ? spans[spans.length - 1] : undefined;
      if (previous !== undefined && segment.copied && this.segments[i - 1].copied) {
        previous.sourceEnd = segment.sourceEnd;
        previous.textEnd = textEnd;
      } else {
        spans.push({ sourceBegin: segment.sourceBegin, sourceEnd: segment.sourceEnd, textBegin, textEnd });
      }
      textBegin = textEnd;
    }
    // One record over everything carries no more than no record at all.
    if (spans.length === 1) return undefined;
    return { sourceText: this.source, spans };
  }

  private apply(edit: PoliceTextEdit): void {
    this.split(edit.begin);
    this.split(edit.end);
    let start = 0;
    let first = -1;
    let last = -1;
    let insertAt = this.segments.length;
    for (let i = 0; i < this.segments.length; i++) {
      const end = start + this.segments[i].text.length;
      const inside = edit.begin < edit.end ? start < edit.end && end > edit.begin :
        start < edit.begin && end > edit.begin;
      if (inside) {
        if (first < 0) first = i;
        last = i;
      }
      if (insertAt === this.segments.length && start >= edit.begin) insertAt = i;
      start = end;
    }
    if (first < 0) {
      // A pure insertion between segments: a zero-width source anchor.
      if (edit.text.length === 0) return;
      const anchor = insertAt > 0 ? this.segments[insertAt - 1].sourceEnd : 0;
      this.segments.splice(insertAt, 0, new TraceSegment(edit.text, anchor, anchor, false));
      return;
    }
    let firstStart = 0;
    for (let i = 0; i < first; i++) firstStart += this.segments[i].text.length;
    let covered = '';
    for (let i = first; i <= last; i++) covered += this.segments[i].text;
    // Rewritten segments are indivisible: keep their text outside the edit.
    const text = covered.substring(0, edit.begin - firstStart) + edit.text +
      covered.substring(edit.end - firstStart);
    const merged = new TraceSegment(text, this.segments[first].sourceBegin, this.segments[last].sourceEnd, false);
    this.segments.splice(first, last - first + 1, merged);
  }

  /** Splits a copied segment at a text position strictly inside it. */
  private split(position: number): void {
    let start = 0;
    for (let i = 0; i < this.segments.length; i++) {
      const segment = this.segments[i];
      const end = start + segment.text.length;
      if (position > start && position < end) {
        if (!segment.copied) return;
        const offset = position - start;
        const left = new TraceSegment(segment.text.substring(0, offset), segment.sourceBegin,
          segment.sourceBegin + offset, true);
        const right = new TraceSegment(segment.text.substring(offset), segment.sourceBegin + offset,
          segment.sourceEnd, true);
        this.segments.splice(i, 1, left, right);
        return;
      }
      start = end;
    }
  }
}
