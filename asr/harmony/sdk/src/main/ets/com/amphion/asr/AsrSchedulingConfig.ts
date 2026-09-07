/** Engine-wide ASR scheduling requests. They do not grant background execution. */
export class AsrSchedulingConfig {
  /** default leaves the system policy unchanged. */
  qos: string = 'default';
  /** Experimental, zero-based CPU IDs. Empty leaves affinity unchanged. */
  cpuIds: number[] = [];
  /** Existing ORT default; false trades wake-up latency for less busy waiting. */
  allowSpinning: boolean = true;
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
  const copy = new AsrSchedulingConfig();
  copy.qos = source.qos;
  copy.allowSpinning = source.allowSpinning;
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
