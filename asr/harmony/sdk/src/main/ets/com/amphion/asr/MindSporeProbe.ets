import { probeMindSporeModel } from 'libamphion_asr.so';

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
