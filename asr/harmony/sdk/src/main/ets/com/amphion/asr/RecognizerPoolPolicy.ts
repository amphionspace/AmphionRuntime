export class RecognizerPoolPolicy {
  static readonly REUSE: number = 0;
  static readonly PUBLISH: number = 1;
  static readonly DEDICATED: number = 2;

  static decide(pooledConfigKey: string | undefined, requestedConfigKey: string): number {
    if (pooledConfigKey === undefined) return RecognizerPoolPolicy.PUBLISH;
    return pooledConfigKey === requestedConfigKey ?
      RecognizerPoolPolicy.REUSE : RecognizerPoolPolicy.DEDICATED;
  }
}
