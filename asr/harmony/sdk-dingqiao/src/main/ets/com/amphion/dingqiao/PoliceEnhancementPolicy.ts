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
}
