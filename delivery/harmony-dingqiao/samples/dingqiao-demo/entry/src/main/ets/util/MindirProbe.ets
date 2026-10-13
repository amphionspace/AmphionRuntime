import hilog from '@ohos.hilog';
import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { probeMindSporeBackend, probeMindSporeChainPaced, probeOrtBackend } from 'amphion_asr';
import { PowerSampler } from './PowerSampler';

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
  /** Chain mode: comma-separated .ms paths run in order once per tick. */
  chainModels: string = '';
  /** Chain mode: tick period in milliseconds; one tick is one audio chunk. */
  paceMs: number = 640;
  /** Chain mode: how long to keep ticking, in milliseconds. */
  durationMs: number = 60_000;
  /** ORT mode: absolute path of an .onnx file to time on the CPU path. */
  ortModel: string = '';
  /** ORT mode: intra-op thread count; 4 is what the engine uses. */
  ortThreads: number = 4;
  /** Log battery voltage and current for the duration of the run. */
  samplePower: boolean = false;
}

/**
 * Runs the diagnostics MindSpore Lite probe and records its JSON report. This
 * exists to decide whether a candidate MindIR graph is accepted by the device
 * accelerator at all; it feeds zeros, so it proves nothing about accuracy.
 */
export async function runMindirProbe(context: common.UIAbilityContext,
  options: MindirProbeOptions): Promise<void> {
  let report = '';
  const power: PowerSampler | undefined =
    options.samplePower ? new PowerSampler(options.runId, 1000) : undefined;
  power?.start();
  try {
    if (options.ortModel.length > 0) {
      if (!fs.accessSync(options.ortModel)) throw new Error(`missing onnx model: ${options.ortModel}`);
      const size = fs.statSync(options.ortModel).size;
      hilog.info(DOMAIN, TAG,
        'MINDIR_PROBE|BEGIN|runId=%{public}s|runtime=onnxruntime|threads=%{public}d|bytes=%{public}d',
        options.runId, options.ortThreads, size);
      report = await probeOrtBackend(options.ortModel, options.ortThreads, options.iterations);
    } else if (options.chainModels.length > 0) {
      const paths = options.chainModels.split(',').filter((value: string): boolean => value.length > 0);
      let bytes = 0;
      for (const path of paths) {
        if (!fs.accessSync(path)) throw new Error(`missing chain model: ${path}`);
        bytes += fs.statSync(path).size;
      }
      hilog.info(DOMAIN, TAG,
        'MINDIR_PROBE|BEGIN|runId=%{public}s|backend=%{public}s|models=%{public}d|bytes=%{public}d|paceMs=%{public}d|durationMs=%{public}d',
        options.runId, options.backend, paths.length, bytes, options.paceMs, options.durationMs);
      report = await probeMindSporeChainPaced(paths, options.backend, options.paceMs, options.durationMs);
    } else {
      if (options.modelPath.length === 0) throw new Error('mindirProbeModel is required');
      if (!fs.accessSync(options.modelPath)) throw new Error(`missing model: ${options.modelPath}`);
      const size = fs.statSync(options.modelPath).size;
      hilog.info(DOMAIN, TAG, 'MINDIR_PROBE|BEGIN|runId=%{public}s|backend=%{public}s|bytes=%{public}d',
        options.runId, options.backend, size);
      report = await probeMindSporeBackend(options.modelPath, options.backend, options.iterations);
    }
  } catch (e) {
    report = `{"status":"FAIL","stage":"carrier","detail":"${`${e}`.replace(/[^A-Za-z0-9_.:\- ]/g, '_')}"}`;
  }
  power?.stop();
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
