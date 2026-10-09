import hilog from '@ohos.hilog';
import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { probeMindSporeBackend } from 'amphion_asr';

const DOMAIN: number = 0x0000;
const TAG: string = 'MindirProbe';

export class MindirProbeOptions {
  /** Absolute path of a .ms file already present in this app's sandbox. */
  modelPath: string = '';
  /** 'cpu', 'npu', or an explicit NNRt device-name substring. */
  backend: string = 'cpu';
  iterations: number = 3;
  /** Optional sandbox path the JSON report is written to for host retrieval. */
  resultPath: string = '';
  runId: string = 'manual';
}

/**
 * Runs the diagnostics MindSpore Lite probe and records its JSON report. This
 * exists to decide whether a candidate MindIR graph is accepted by the device
 * accelerator at all; it feeds zeros, so it proves nothing about accuracy.
 */
export async function runMindirProbe(context: common.UIAbilityContext,
  options: MindirProbeOptions): Promise<void> {
  let report = '';
  try {
    if (options.modelPath.length === 0) throw new Error('mindirProbeModel is required');
    if (!fs.accessSync(options.modelPath)) throw new Error(`missing model: ${options.modelPath}`);
    const size = fs.statSync(options.modelPath).size;
    hilog.info(DOMAIN, TAG, 'MINDIR_PROBE|BEGIN|runId=%{public}s|backend=%{public}s|bytes=%{public}d',
      options.runId, options.backend, size);
    report = await probeMindSporeBackend(options.modelPath, options.backend, options.iterations);
  } catch (e) {
    report = `{"status":"FAIL","stage":"carrier","detail":"${`${e}`.replace(/[^A-Za-z0-9_.:\- ]/g, '_')}"}`;
  }
  hilog.info(DOMAIN, TAG, 'MINDIR_PROBE|RESULT|runId=%{public}s|%{public}s', options.runId, report);
  if (options.resultPath.length > 0) {
    try {
      const file = fs.openSync(options.resultPath, fs.OpenMode.CREATE | fs.OpenMode.READ_WRITE | fs.OpenMode.TRUNC);
      fs.writeSync(file.fd, `${report}\n`);
      fs.closeSync(file);
    } catch (e) {
      hilog.error(DOMAIN, TAG, 'MINDIR_PROBE|WRITE_FAILED|%{public}s', `${e}`);
    }
  }
  hilog.info(DOMAIN, TAG, 'MINDIR_PROBE|END|runId=%{public}s', options.runId);
}
