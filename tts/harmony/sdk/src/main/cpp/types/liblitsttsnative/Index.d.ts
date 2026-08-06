declare const nativeModule: {
  createRuntime: (
    hiddenEncoderPath: string,
    streamConditionChunkPath: string,
    streamConditionFinalPath: string,
    streamDecoderStepPath: string,
    vocoderPath: string,
    chunkSize: number,
    preLookaheadLen: number,
    melCacheLen: number,
    hopLength: number,
    decoderTimesteps: number,
    decoderTemperature: number
  ) => object;
  releaseRuntime: (runtimeHandle: object) => void;
  cancelRuntime: (runtimeHandle: object) => void;
  synthesize: (runtimeHandle: object, tokenIds: Array<number>, speakerId: number) => ArrayBuffer;
  synthesizeAsync: (runtimeHandle: object, tokenIds: Array<number>, speakerId: number) => Promise<ArrayBuffer>;
  synthesizeStreaming: (
    runtimeHandle: object,
    tokenIds: Array<number>,
    speakerId: number,
    lengthScale: number,
    chunkSizeOverride: number,
    onChunk: (chunk: ArrayBuffer, sequence: number) => void
  ) => Promise<{
    synthesisMs: number;
    firstChunkMs: number;
    audioBytes: number;
    chunkCount: number;
  }>;
  normalizeTnSegment: (binaryPath: string, workingDir: string, text: string) => string;
  releaseTnResources: () => void;
};

export default nativeModule;
