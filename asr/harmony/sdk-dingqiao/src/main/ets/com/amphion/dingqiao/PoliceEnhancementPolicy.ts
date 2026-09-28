export function policeFinalText(
  rawText: string,
  enabled: boolean,
  enhance: (rawText: string) => PoliceFinalText
): PoliceFinalText {
  return enabled ? enhance(rawText) : { text: rawText };
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

/** The enhancer's records from its input text to the published final text. */
export interface PoliceTextProvenance {
  sourceText: string;
  spans: PoliceTextSpan[];
}

export interface PoliceFinalText {
  text: string;
  provenance?: PoliceTextProvenance;
}

/** Per-session final adapter used by the public engine callback path. */
export class PoliceFinalSession {
  private enabled: boolean;
  private enhance: (rawText: string) => PoliceFinalText;

  constructor(enabled: boolean, enhance: (rawText: string) => PoliceFinalText) {
    this.enabled = enabled;
    this.enhance = enhance;
  }

  dispatch(
    payload: PoliceFinalPayload,
    rawText: string,
    onResult: (provenance?: PoliceTextProvenance) => void,
    onLast: () => void
  ): void {
    const final = policeFinalText(rawText, this.enabled, this.enhance);
    payload.result = final.text;
    // Records describe this rawText only; a changed final without them stays unaligned.
    onResult(final.text !== rawText && final.provenance?.sourceText === rawText ? final.provenance : undefined);
    if (payload.isLast) onLast();
  }
}
