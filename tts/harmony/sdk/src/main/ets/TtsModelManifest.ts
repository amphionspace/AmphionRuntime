export const STREAM_CONDITION_FINAL_MODEL_FILE: string = 'lits_stream_condition_final.onnx';

export interface StreamFinalConditionPolicy {
  useChunkConditionForFinal: boolean;
  finalModelFile: string;
}

export function resolveStreamFinalConditionPolicy(
  zeroPadWithChunkCondition: boolean,
  declaredFinalModelFile: string | undefined
): StreamFinalConditionPolicy | undefined {
  if (zeroPadWithChunkCondition) {
    return {
      useChunkConditionForFinal: true,
      finalModelFile: ''
    };
  }
  if (declaredFinalModelFile !== STREAM_CONDITION_FINAL_MODEL_FILE) {
    return undefined;
  }
  return {
    useChunkConditionForFinal: false,
    finalModelFile: STREAM_CONDITION_FINAL_MODEL_FILE
  };
}
