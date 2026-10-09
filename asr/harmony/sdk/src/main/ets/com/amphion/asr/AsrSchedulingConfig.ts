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
   * historical policy; 'utility' and 'background' trade window latency for a
   * lower frequency step. Role results are unchanged in every case.
   */
  diarizationQos: string = 'inherit';
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
  const diarizationQos = source.diarizationQos ?? 'inherit';
  if (diarizationQos !== 'inherit' && diarizationQos !== 'background' &&
    diarizationQos !== 'utility' && diarizationQos !== 'default') {
    throw new Error('ASR diarizationQos must be inherit, background, utility, or default');
  }
  const copy = new AsrSchedulingConfig();
  copy.qos = source.qos;
  copy.diarizationQos = diarizationQos;
  copy.allowSpinning = source.allowSpinning;
  copy.diarizationEncoder = diarizationEncoder;
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
