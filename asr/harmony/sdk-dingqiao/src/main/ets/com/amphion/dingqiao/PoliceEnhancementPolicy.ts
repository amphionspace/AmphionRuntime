export function policeFinalText(
  rawText: string,
  enabled: boolean,
  enhance: (rawText: string) => string
): string {
  return enabled ? enhance(rawText) : rawText;
}

export interface PoliceFinalPayload {
  isLast: boolean;
  result: string;
}

export interface PoliceTextSpan {
  sourceBegin: number;
  sourceEnd: number;
  textBegin: number;
  textEnd: number;
}

export interface PoliceTextProvenance {
  sourceText: string;
  spans: PoliceTextSpan[];
}

const CLAUSE_END = '，。！？；';

/** Per-session final adapter used by the public engine callback path. */
export class PoliceFinalSession {
  private enabled: boolean;
  private enhance: (rawText: string) => string;

  constructor(enabled: boolean, enhance: (rawText: string) => string) {
    this.enabled = enabled;
    this.enhance = enhance;
  }

  dispatch(
    payload: PoliceFinalPayload,
    rawText: string,
    onResult: () => void,
    onLast: () => void
  ): void {
    payload.result = policeFinalText(rawText, this.enabled, this.enhance);
    onResult();
    if (payload.isLast) onLast();
  }

  /**
   * Clause records for a final the enhancer rewrote. The enhancer has no offset
   * map, so each punctuation clause is enhanced on its own; only an exact
   * rebuild of the published text counts as provenance. A rule spanning
   * clauses yields no record, and the whole final stays one uncertain unit.
   */
  provenance(sourceText: string, finalText: string): PoliceTextProvenance | undefined {
    if (!this.enabled || sourceText === finalText) return undefined;
    const clauses: string[] = [];
    let begin = 0;
    for (let index = 0; index < sourceText.length; index++) {
      if (CLAUSE_END.indexOf(sourceText[index]) >= 0 &&
        (index + 1 === sourceText.length || CLAUSE_END.indexOf(sourceText[index + 1]) < 0)) {
        clauses.push(sourceText.slice(begin, index + 1));
        begin = index + 1;
      }
    }
    if (begin < sourceText.length) clauses.push(sourceText.slice(begin));
    const spans: PoliceTextSpan[] = [];
    let sourceBegin = 0;
    let text = '';
    for (const clause of clauses) {
      const output = clauses.length === 1 ? finalText : this.enhance(clause);
      spans.push({ sourceBegin, sourceEnd: sourceBegin + clause.length,
        textBegin: text.length, textEnd: text.length + output.length });
      sourceBegin += clause.length;
      text += output;
    }
    return text === finalText ? { sourceText, spans } : undefined;
  }
}
