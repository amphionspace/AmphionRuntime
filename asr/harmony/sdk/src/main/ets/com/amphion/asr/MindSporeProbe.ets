import { probeMindSporeChain, probeMindSporeModel, probeOrtModel } from 'libamphion_asr.so';

/**
 * Diagnostics-only MindSpore Lite backend probe. It builds the MindIR file at
 * modelPath on the requested backend and times Predict on zero-filled inputs,
 * so it answers "does this accelerator accept this graph, and how fast is one
 * call" without touching recognition or diarization state. The outputs are
 * meaningless by construction; never read accuracy from this.
 *
 * backend: 'cpu', 'npu' (any NNRt accelerator whose name contains "kirin"), or
 * an explicit NNRt device-name substring. Resolves a JSON report.
 */
export async function probeMindSporeBackend(modelPath: string, backend: string = 'cpu',
  iterations: number = 3): Promise<string> {
  if (modelPath.length === 0) throw new Error('modelPath is required');
  if (!Number.isInteger(iterations) || iterations < 1 || iterations > 100) {
    throw new Error('iterations must be an integer in [1, 100]');
  }
  return probeMindSporeModel(modelPath, backend, iterations);
}

/**
 * Diagnostics-only paced chain probe. It builds every MindIR in modelPaths once
 * on the requested backend, then runs them in order once per paceMs tick until
 * durationMs elapses. That is what a long thermal arm needs: the real chunk
 * cadence without a rebuild per call. Inputs stay zero-filled and are never
 * carried between models, so this measures placement, pacing and host CPU cost,
 * never accuracy.
 */
export async function probeMindSporeChainPaced(modelPaths: string[], backend: string = 'cpu',
  paceMs: number = 640, durationMs: number = 60_000): Promise<string> {
  if (modelPaths.length === 0) throw new Error('modelPaths is required');
  for (const path of modelPaths) {
    if (path.length === 0) throw new Error('modelPaths entries must be non-empty');
    if (path.includes(',')) throw new Error('modelPaths entries must not contain a comma');
  }
  if (!Number.isInteger(paceMs) || paceMs < 1 || paceMs > 60_000) {
    throw new Error('paceMs must be an integer in [1, 60000]');
  }
  if (!Number.isInteger(durationMs) || durationMs < 1 || durationMs > 14_400_000) {
    throw new Error('durationMs must be an integer in [1, 14400000]');
  }
  return probeMindSporeChain(modelPaths.join(','), backend, paceMs, durationMs);
}

/**
 * Diagnostics-only ONNX Runtime probe. It loads the ONNX file at modelPath with
 * the runtime and thread count the engine itself uses and times Run on
 * zero-filled inputs. This is the baseline the accelerator has to beat: the
 * shipped encoder is INT8 on ORT, not fp16 on MindSpore Lite, so a comparison
 * against the latter overstates any saving. Outputs are meaningless here.
 */
export async function probeOrtBackend(modelPath: string, threads: number = 4,
  iterations: number = 3): Promise<string> {
  if (modelPath.length === 0) throw new Error('modelPath is required');
  if (!Number.isInteger(threads) || threads < 1 || threads > 8) {
    throw new Error('threads must be an integer in [1, 8]');
  }
  if (!Number.isInteger(iterations) || iterations < 1 || iterations > 100) {
    throw new Error('iterations must be an integer in [1, 100]');
  }
  return probeOrtModel(modelPath, threads, iterations);
}
