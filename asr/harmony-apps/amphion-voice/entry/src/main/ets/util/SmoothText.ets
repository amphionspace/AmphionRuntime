/**
 * Turns bursty recognition updates into steady, readable typing.
 *
 * Recognizers deliver text in chunks (a partial every 0.5–1 s, sometimes revising earlier
 * characters). Showing each chunk at once makes the line burst and then stall. The smoother instead
 * paces each chunk over roughly the time until the next one is expected, so typing looks continuous.
 * Revisions overwrite the diverging characters in place (no backspace-then-retype), and every shown
 * character remembers when it last changed, so the page can draw fresh preview words lighter and let
 * them settle into ink once they stop changing. Text typed from a final is settled immediately.
 */
export class SmoothText {
  private display: string = '';
  private target: string = '';
  private allowShrink: boolean = true;
  // Per shown character: when it last changed (ms), or 0 when it came from a final.
  private bornAt: number[] = [];
  // Estimated time between preview updates; the reveal of each update is spread over most of it.
  private cadenceMs: number = 600;
  private lastArrivalAt: number = 0;
  private ratePerMs: number = 0;
  private budget: number = 0;
  private lastTickAt: number = 0;
  private hurry: boolean = false;

  /**
   * A preview character unchanged this long is drawn as settled text. Longer than the ~1.1 s the
   * on-device engine may take to reject another speaker, so withdrawn words never turn ink first.
   */
  static readonly SETTLE_MS: number = 1200;
  /** A final's remaining characters are typed within this time. */
  private static readonly FINAL_WINDOW_MS: number = 250;
  /** Older finals waiting behind newer ones are typed within this time. */
  private static readonly HURRY_WINDOW_MS: number = 100;
  /** The typing never trails the recognizer by more than this. */
  private static readonly MAX_LAG_MS: number = 1000;
  /** Slowest typing speed, so a single character never crawls. */
  private static readonly MIN_RATE_PER_MS: number = 1 / 90;
  private static readonly MAX_PREVIEW_ROLLBACK: number = 4;

  /**
   * allowShrink=false is for previews: when the recognizer momentarily returns a shorter version of
   * what is already on screen, the shown words stay put until it catches up (no backspacing).
   * Finals always use allowShrink=true so the committed text is exactly what was recognized.
   * hurry is set while further finals are queued behind this one.
   */
  setTarget(text: string, allowShrink: boolean = true, hurry: boolean = false): void {
    const changed = text !== this.target || allowShrink !== this.allowShrink || hurry !== this.hurry;
    if (!changed) return;
    const now = Date.now();
    if (!allowShrink && text !== this.target) {
      if (this.lastArrivalAt > 0) {
        const interval = Math.min(1000, Math.max(250, now - this.lastArrivalAt));
        this.cadenceMs = this.cadenceMs * 0.6 + interval * 0.4;
      }
      this.lastArrivalAt = now;
    }
    this.target = text;
    this.allowShrink = allowShrink;
    this.hurry = hurry;
    const work = this.pendingWork();
    const window = hurry ? SmoothText.HURRY_WINDOW_MS :
      allowShrink ? SmoothText.FINAL_WINDOW_MS : this.cadenceMs * 0.85;
    this.ratePerMs = Math.max(SmoothText.MIN_RATE_PER_MS, work / window, work / SmoothText.MAX_LAG_MS);
  }

  /** Replaces what is shown immediately (used when a span is withdrawn, e.g. another speaker). */
  reset(text: string = ''): void {
    this.display = text;
    this.target = text;
    this.bornAt = text.split('').map((): number => 0);
    this.budget = 0;
    this.lastArrivalAt = 0;
  }

  current(): string {
    return this.display;
  }

  /** How many leading shown characters have stopped changing and can be drawn as settled text. */
  settledLength(now: number = Date.now()): number {
    let i = 0;
    while (i < this.bornAt.length && this.bornAt[i] <= now - SmoothText.SETTLE_MS) i++;
    return i;
  }

  settled(): boolean {
    return this.display === this.target || this.holdingLonger();
  }

  /**
   * Previews never take back more than a short tail. A preview that would erase more (the recognizer
   * restarting its window, or briefly returning less) is treated as unreliable: the screen keeps what
   * it shows until a consistent preview or the final arrives.
   */
  private holdingLonger(): boolean {
    if (this.allowShrink || this.target.length === 0) return false;
    const keep = SmoothText.alignedPrefix(this.display, this.target);
    if (keep === this.target.length) return true;
    return this.display.length - SmoothText.shownLength(this.display, this.target, keep) >
      SmoothText.MAX_PREVIEW_ROLLBACK;
  }

  /** Character edits still needed to turn what is shown into the target. */
  private pendingWork(): number {
    const keep = SmoothText.alignedPrefix(this.display, this.target);
    const kept = SmoothText.shownLength(this.display, this.target, keep);
    return Math.max(this.display.length - kept, this.target.length - keep);
  }

  /** Advances one frame. Returns true when the visible text changed. */
  tick(): boolean {
    const now = Date.now();
    const dt = this.lastTickAt > 0 ? Math.min(100, now - this.lastTickAt) : 33;
    this.lastTickAt = now;
    if (this.display === this.target || this.holdingLonger()) {
      this.budget = 0;
      return false;
    }
    this.budget += this.ratePerMs * dt;
    // The first character of a new line appears without waiting for the pace to build up.
    if (this.display.length === 0 && this.budget < 1) this.budget = 1;
    let changed = false;
    while (this.budget >= 1 && this.display !== this.target) {
      this.budget -= 1;
      if (!this.step(now)) {
        // Alignment found nothing to edit (should not happen); show the target rather than stall.
        this.display = this.target;
        this.bornAt = this.target.split('').map((): number => this.allowShrink ? 0 : now);
      }
      changed = true;
    }
    return changed;
  }

  /**
   * One character edit. The aligned prefix is taken from the target (so punctuation the final adds
   * to words already on screen slips in place), then the first diverging character is overwritten,
   * appended, or, when the target is shorter, the last surplus character is removed.
   */
  private step(now: number): boolean {
    const born = this.allowShrink ? 0 : now;
    const keep = SmoothText.alignedPrefix(this.display, this.target);
    const kept = SmoothText.shownLength(this.display, this.target, keep);
    const head = this.target.substring(0, keep);
    const headBorn = this.realignBorn(kept, keep, born);
    const oldTail = this.display.substring(kept);
    const newTail = this.target.substring(keep);
    let next: string;
    let nextBorn: number[];
    if (oldTail.length > 0 && newTail.length > 0) {
      next = head + newTail.charAt(0) + oldTail.substring(1);
      nextBorn = headBorn.concat([born]).concat(this.bornAt.slice(kept + 1));
    } else if (oldTail.length > 0) {
      next = head + oldTail.substring(0, oldTail.length - 1);
      nextBorn = headBorn.concat(this.bornAt.slice(kept, this.display.length - 1));
    } else {
      next = head + newTail.charAt(0);
      nextBorn = headBorn.concat([born]);
    }
    const changed = next !== this.display;
    this.display = next;
    this.bornAt = nextBorn;
    return changed;
  }

  /** Stamps for the aligned prefix, whose length may differ from what was shown by punctuation. */
  private realignBorn(kept: number, keep: number, born: number): number[] {
    const out = this.bornAt.slice(0, Math.min(kept, keep));
    while (out.length < keep) out.push(born);
    return out;
  }

  /**
   * Length of the target prefix that already matches what is shown, ignoring punctuation on either
   * side (previews are unpunctuated, finals are punctuated).
   */
  static alignedPrefix(shown: string, target: string): number {
    let i = 0;
    let j = 0;
    let covered = 0;
    while (i < shown.length && j < target.length) {
      if (shown.charCodeAt(i) === target.charCodeAt(j)) {
        i++;
        j++;
        covered = j;
      } else if (SmoothText.isPunct(target.charAt(j))) {
        j++;
      } else if (SmoothText.isPunct(shown.charAt(i))) {
        i++;
      } else {
        break;
      }
    }
    return covered;
  }

  /** How many characters of `shown` correspond to the first `covered` characters of `target`. */
  private static shownLength(shown: string, target: string, covered: number): number {
    let i = 0;
    let j = 0;
    while (i < shown.length && j < covered) {
      if (shown.charCodeAt(i) === target.charCodeAt(j)) {
        i++;
        j++;
      } else if (SmoothText.isPunct(target.charAt(j))) {
        j++;
      } else {
        i++;
      }
    }
    return i;
  }

  private static isPunct(ch: string): boolean {
    return '，。？！、；：,.?!;: '.indexOf(ch) >= 0;
  }

  static commonPrefix(a: string, b: string): number {
    const n = Math.min(a.length, b.length);
    let i = 0;
    while (i < n && a.charCodeAt(i) === b.charCodeAt(i)) i++;
    return i;
  }
}
