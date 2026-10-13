import batteryInfo from '@ohos.batteryInfo';
import hilog from '@ohos.hilog';

const DOMAIN: number = 0x0000;
const TAG: string = 'PowerSampler';

/**
 * Diagnostics-only battery power sampler.
 *
 * Every thermal conclusion in this repo so far rests on CPU occupancy standing
 * in for energy, which is an inference, not a measurement. This reads the
 * public battery voltage and current and logs them so a run can be scored in
 * milliwatts instead.
 *
 * Read the sign convention before using the numbers: `nowCurrent` is the
 * battery's own current, negative while discharging and positive while
 * charging. With USB attached the charger supplies both the system and the
 * battery, so the absolute value is NOT system draw; only differences between
 * two runs under the same charger state are meaningful, because extra system
 * load shows up as reduced charging current. Unplugged, the magnitude is the
 * system draw directly. `chargingStatus` and `pluggedType` are logged every
 * sample so the reader can tell which regime a run was in.
 */
export class PowerSampler {
  private timer: number = -1;
  private index: number = 0;
  private readonly runId: string;
  private readonly intervalMs: number;

  constructor(runId: string, intervalMs: number = 1000) {
    this.runId = runId;
    this.intervalMs = Math.max(200, intervalMs);
  }

  start(): void {
    if (this.timer !== -1) return;
    this.emit();
    this.timer = setInterval((): void => {
      this.emit();
    }, this.intervalMs);
    hilog.info(DOMAIN, TAG, 'POWER|START|runId=%{public}s|intervalMs=%{public}d',
      this.runId, this.intervalMs);
  }

  stop(): void {
    if (this.timer === -1) return;
    clearInterval(this.timer);
    this.timer = -1;
    hilog.info(DOMAIN, TAG, 'POWER|STOP|runId=%{public}s|samples=%{public}d', this.runId, this.index);
  }

  private emit(): void {
    try {
      const microvolt: number = batteryInfo.voltage;
      const milliamp: number = batteryInfo.nowCurrent;
      // voltage is microvolts and current milliamps, so the product is nanowatts
      // scaled by 1e-3; keep it in milliwatts with one decimal of resolution.
      const milliwatt: number = Math.round(microvolt * 1e-6 * milliamp * 10) / 10;
      hilog.info(DOMAIN, TAG,
        'POWER|SAMPLE|runId=%{public}s|i=%{public}d|uv=%{public}d|ma=%{public}d|mw=%{public}s|soc=%{public}d|charge=%{public}d|plug=%{public}d|battC=%{public}d',
        this.runId, this.index, microvolt, milliamp, `${milliwatt}`,
        batteryInfo.batterySOC, batteryInfo.chargingStatus, batteryInfo.pluggedType,
        batteryInfo.batteryTemperature);
    } catch (e) {
      hilog.error(DOMAIN, TAG, 'POWER|READ_FAILED|runId=%{public}s|%{public}s',
        this.runId, `${e}`);
    }
    this.index += 1;
  }
}
