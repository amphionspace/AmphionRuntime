/**
 * Public identities for the four Sortformer slots.
 *
 * The model orders its slots by arrival and keeps them for the session, so no
 * clustering or re-labelling happens here. What this decides is only when a
 * slot becomes a published role: on the first *final* chunk in which it speaks,
 * in order of first speech, up to maxSpeakers. A slot that only ever shows up
 * in a preview has not been confirmed by the speaker cache and stays UNKNOWN
 * until its chunk commits; a slot beyond the caller's cap stays anonymous, as
 * the product contract requires.
 */
export interface SortformerIdentityMapping {
  /** slot -> published role index (0-based) or -1 for UNKNOWN. */
  mapping: number[];
  before: number;
  after: number;
}

export class SortformerSpeakerIdentity {
  private readonly slots: number[] = [-1, -1, -1, -1];
  private nextId: number = 0;
  private readonly maxSpeakers: number;

  constructor(maxSpeakers: number) { this.maxSpeakers = maxSpeakers; }

  /**
   * Commits final evidence: `firstSpeechFrame[slot]` is the earliest active
   * frame of that slot inside the final runs just received, or -1 when silent.
   * Ties and ordering follow the model's slot order, which is arrival order.
   */
  commit(firstSpeechFrame: number[]): SortformerIdentityMapping {
    const before = this.nextId;
    const order: number[] = [];
    for (let slot = 0; slot < this.slots.length; slot++) {
      if (this.slots[slot] < 0 && (firstSpeechFrame[slot] ?? -1) >= 0) order.push(slot);
    }
    order.sort((left: number, right: number): number =>
      firstSpeechFrame[left] - firstSpeechFrame[right] || left - right);
    for (const slot of order) {
      if (this.nextId >= this.maxSpeakers) break;
      this.slots[slot] = this.nextId;
      this.nextId += 1;
    }
    return { mapping: this.slots.slice(), before, after: this.nextId };
  }

  mapping(): number[] { return this.slots.slice(); }

  publishedCount(): number { return this.nextId; }
}
