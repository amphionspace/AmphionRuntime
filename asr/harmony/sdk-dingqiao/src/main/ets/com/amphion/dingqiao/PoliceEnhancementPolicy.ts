export function policeFinalText(
  rawText: string,
  enabled: boolean,
  enhance: (rawText: string) => string
): string {
  return enabled ? enhance(rawText) : rawText;
}

const MAX_BOUNDARY_DEDUP_CHARS: number = 24;
const MIN_BOUNDARY_DEDUP_CHARS: number = 2;

function ignoredForBoundaryDedup(value: string): boolean {
  return /[\s，。！？、；：,.!?;:'"“”‘’（）()\[\]{}<>《》…—~-]/.test(value);
}

function boundaryKey(value: string): string {
  let key = '';
  const lower = value.toLowerCase();
  for (let i = 0; i < lower.length; i++) {
    if (!ignoredForBoundaryDedup(lower[i])) key += lower[i];
  }
  return key;
}

function rawPrefixEndForKeyChars(value: string, keyChars: number): number {
  let observed = 0;
  for (let i = 0; i < value.length; i++) {
    if (ignoredForBoundaryDedup(value[i])) continue;
    observed += 1;
    if (observed === keyChars) return i + 1;
  }
  return 0;
}

function trimIgnoredPrefix(value: string): string {
  let start = 0;
  while (start < value.length && ignoredForBoundaryDedup(value[start])) start += 1;
  return value.slice(start).trim();
}

/** Remove only text that can be attributed to replayed boundary audio. */
export function deduplicateBoundaryPrefix(previous: string, current: string,
  overlapPrefixSamples: number): string {
  if (overlapPrefixSamples <= 0 || previous.length === 0 || current.length === 0) return current;
  const previousKey = boundaryKey(previous);
  const currentKey = boundaryKey(current);
  const maximum = Math.min(MAX_BOUNDARY_DEDUP_CHARS, previousKey.length, currentKey.length);
  for (let length = maximum; length >= MIN_BOUNDARY_DEDUP_CHARS; length--) {
    if (previousKey.slice(previousKey.length - length) !== currentKey.slice(0, length)) continue;
    const rawEnd = rawPrefixEndForKeyChars(current, length);
    return rawEnd > 0 ? trimIgnoredPrefix(current.slice(rawEnd)) : current;
  }
  return current;
}

export interface PoliceFinalPayload {
  isLast: boolean;
  result: string;
}

/** Per-session final adapter used by the public engine callback path. */
export class PoliceFinalSession {
  private enabled: boolean;
  private enhance: (rawText: string) => string;
  private previousFinalText: string = '';

  constructor(enabled: boolean, enhance: (rawText: string) => string) {
    this.enabled = enabled;
    this.enhance = enhance;
  }

  dispatch(
    payload: PoliceFinalPayload,
    rawText: string,
    onResult: () => void,
    onLast: () => void,
    overlapPrefixSamples: number = 0
  ): void {
    const enhanced = policeFinalText(rawText, this.enabled, this.enhance);
    payload.result = deduplicateBoundaryPrefix(this.previousFinalText, enhanced, overlapPrefixSamples);
    if (payload.result.length > 0) this.previousFinalText = payload.result;
    onResult();
    if (payload.isLast) onLast();
  }
}
