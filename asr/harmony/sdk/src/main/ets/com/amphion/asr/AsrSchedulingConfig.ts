/** Engine-wide ASR scheduling requests. They do not grant background execution. */
export class AsrSchedulingConfig {
  /** default leaves the system policy unchanged. */
  qos: string = 'default';
  /** Experimental, zero-based CPU IDs. Empty leaves affinity unchanged. */
  cpuIds: number[] = [];
  /** Existing ORT default; false trades wake-up latency for less busy waiting. */
  allowSpinning: boolean = true;
  /**
   * Where the Community speaker encoder runs when role separation is on:
   * 'cpu' keeps the ORT session, 'npu' requires an NNRt accelerator and fails
   * the load without one, 'auto' prefers the accelerator and falls back.
   * Recognition itself is unaffected; this does not join the ASR provider key.
   */
  diarizationEncoder: string = 'cpu';
  /**
   * Where the scheduler is allowed to run the role-separation workers.
   *
   * On this hardware heat tracks how high the governor is driven, not CPU time
   * spent: the per-window burst of segmentation, features, encoder and pooling
   * occupies roughly 150 ms of every second and pushes the big cluster to its
   * top frequency, while a flat load of the same size costs little. Those stages
   * have a 1500 ms budget per window and use about a tenth of it, so there is
   * slack to finish them at a lower operating point. 'inherit' keeps the
   * pre-0.3.22 policy; 'utility' and 'background' trade window latency for a
   * lower frequency step. Role results are unchanged in every case.
   *
   * The default 'auto' resolves to 'background' while the window cadence leaves
   * room for it (hop >= 2000 ms) and to 'inherit' otherwise, so a caller that
   * explicitly asks for a faster cadence keeps a configuration that fits rather
   * than being rejected. Asking for 'background' outright at a shorter hop is
   * still an error: that pair was measured to leave 5% of the window budget.
   */
  diarizationQos: string = 'auto';
  /**
   * How often role separation opens a new 10 s analysis window, in
   * milliseconds. The default 1000 means every second of audio is analysed by
   * about ten overlapping windows, which is what makes role boundaries precise
   * and what the segmentation, feature, encoder and pooling cost scale with.
   * Raising it trades boundary resolution for proportionally less of that work.
   * Recognition is unaffected: the window cadence never reaches the recognizer.
   */
  diarizationHopMs: number = 2000;
}

/**
 * Resolves the 'auto' role-worker placement against the window cadence.
 *
 * Kept separate from the snapshot, which carries the request verbatim: a
 * snapshot that stored the decision would reject a later cadence change that
 * is perfectly legal. The field is a request; this is the decision, and every
 * read site must go through here.
 */
export function resolveDiarizationQos(diarizationQos: string, diarizationHopMs: number): string {
  if (diarizationQos !== 'auto') return diarizationQos;
  return diarizationHopMs >= 2000 ? 'background' : 'inherit';
}

export function snapshotAsrScheduling(source: AsrSchedulingConfig = new AsrSchedulingConfig()): AsrSchedulingConfig {
  if (source.qos !== 'default' && source.qos !== 'user-initiated' &&
    source.qos !== 'user-interactive') {
    throw new Error('ASR qos must be default, user-initiated, or user-interactive');
  }
  if (!Array.isArray(source.cpuIds) || source.cpuIds.length > 128 ||
    typeof source.allowSpinning !== 'boolean') {
    throw new Error('invalid ASR scheduling configuration');
  }
  const diarizationEncoder = source.diarizationEncoder ?? 'cpu';
  if (diarizationEncoder !== 'cpu' && diarizationEncoder !== 'npu' && diarizationEncoder !== 'auto') {
    throw new Error('ASR diarizationEncoder must be cpu, npu, or auto');
  }
  const diarizationQos = source.diarizationQos ?? 'auto';
  if (diarizationQos !== 'auto' && diarizationQos !== 'inherit' &&
    diarizationQos !== 'background' && diarizationQos !== 'utility' &&
    diarizationQos !== 'default') {
    throw new Error('ASR diarizationQos must be auto, inherit, background, utility, or default');
  }
  const diarizationHopMs = source.diarizationHopMs ?? 2000;
  if (!Number.isInteger(diarizationHopMs) || diarizationHopMs < 250 || diarizationHopMs > 10000) {
    throw new Error('ASR diarizationHopMs must be an integer in [250, 10000] milliseconds');
  }
  // A lower operating point stretches every per-window stage. Measured on
  // Mate 80 at the default 1000 ms hop, 'background' takes the worst-case
  // embedding from 647 ms to 1421 ms against a 1500 ms window budget, leaving
  // 5% of margin; a slower part or heavier throttling would start dropping
  // windows. Halving the window rate pulls the same arm back to 1029 ms (69%).
  // So the two knobs are only safe together, and that is enforced here rather
  // than left to a documentation note.
  // 'utility' is a milder step and is not constrained here: its window cost has
  // not been measured yet, so guessing a limit for it would be unfounded.
  if (resolveDiarizationQos(diarizationQos, diarizationHopMs) === 'background' &&
    diarizationHopMs < 2000) {
    throw new Error(
      'ASR diarizationQos background requires diarizationHopMs >= 2000: ' +
      'a lower operating point stretches each window past its budget at a 1000 ms hop');
  }
  const copy = new AsrSchedulingConfig();
  copy.qos = source.qos;
  copy.diarizationQos = diarizationQos;
  copy.allowSpinning = source.allowSpinning;
  copy.diarizationEncoder = diarizationEncoder;
  copy.diarizationHopMs = diarizationHopMs;
  for (const cpu of source.cpuIds) {
    if (!Number.isInteger(cpu) || cpu < 0 || cpu >= 128 || copy.cpuIds.indexOf(cpu) >= 0) {
      throw new Error('ASR cpuIds must contain unique integer CPU IDs in [0, 127]');
    }
    copy.cpuIds.push(cpu);
  }
  copy.cpuIds.sort((a: number, b: number): number => a - b);
  return copy;
}

/** Uses the existing provider options seam; no C API layout change. */
export function asrCpuProvider(disablePrepack: boolean, source?: AsrSchedulingConfig): string {
  const config = snapshotAsrScheduling(source);
  let provider = disablePrepack ? 'cpu;DisablePrepacking=1' : 'cpu';
  if (config.qos !== 'default') provider += `;AmphionQos=${config.qos}`;
  if (config.cpuIds.length > 0) provider += `;AmphionCpuIds=${config.cpuIds.join(',')}`;
  if (!config.allowSpinning) provider += ';AmphionAllowSpinning=0';
  return provider;
}
