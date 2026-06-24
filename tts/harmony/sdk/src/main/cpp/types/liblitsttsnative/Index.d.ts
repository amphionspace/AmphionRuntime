declare const nativeModule: {
  createRuntime: (acousticPath: string, vocoderPath: string) => object;
  releaseRuntime: (runtimeHandle: object) => void;
  synthesize: (runtimeHandle: object, tokenIds: Array<number>, speakerId: number) => ArrayBuffer;
};

export default nativeModule;
