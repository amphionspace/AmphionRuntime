import {
  closeLacPersonNer,
  createLacPersonNer,
  findLacPersonSpans,
  LacPersonNerHandle,
  LacPersonSpan
} from 'libamphion_asr.so';

export class PersonEntitySpan {
  start: number = 0;
  end: number = 0;
}

/** Native Baidu LAC ONNX wrapper used by the police name correction layer. */
export class LacPersonNer {
  private handle?: LacPersonNerHandle;

  constructor(modelPath: string, transitionsPath: string, wordPath: string,
    tagPath: string, q2bPath: string) {
    this.handle = createLacPersonNer(modelPath, transitionsPath, wordPath, tagPath, q2bPath);
  }

  findPersonSpans(text: string): PersonEntitySpan[] {
    if (this.handle === undefined || text.length === 0) return [];
    const nativeSpans: LacPersonSpan[] = findLacPersonSpans(this.handle, text);
    const result: PersonEntitySpan[] = [];
    for (let i = 0; i < nativeSpans.length; i++) {
      const span = new PersonEntitySpan();
      span.start = nativeSpans[i].start;
      span.end = nativeSpans[i].end;
      result.push(span);
    }
    return result;
  }

  close(): void {
    if (this.handle === undefined) return;
    closeLacPersonNer(this.handle);
    this.handle = undefined;
  }
}
