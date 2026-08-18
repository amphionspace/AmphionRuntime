import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import { WavIo } from './WavIo';

export const DEMO_CASE_ROOT: string = '/data/storage/el2/base/files/asr-cases';

export class DemoCaseSaveResult {
  caseId: string = '';
  caseDir: string = '';
}

function writeText(path: string, value: string): void {
  const encoded = new util.TextEncoder().encodeInto(value);
  const data = new ArrayBuffer(encoded.byteLength);
  new Uint8Array(data).set(encoded);
  const fp = fs.openSync(path, fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
  try {
    fs.writeSync(fp.fd, data);
  } finally {
    fs.closeSync(fp);
  }
}

function allocateCaseId(): string {
  const base = `case-${Date.now()}`;
  let caseId = base;
  let suffix = 0;
  while (fs.accessSync(`${DEMO_CASE_ROOT}/${caseId}`)) {
    suffix += 1;
    caseId = `${base}-${suffix}`;
  }
  return caseId;
}

export function saveDemoCase(pcm: ArrayBuffer, note: string,
  metadata: Record<string, Object>): DemoCaseSaveResult {
  if (pcm.byteLength === 0) throw new Error('case audio is empty');
  if (!fs.accessSync(DEMO_CASE_ROOT)) fs.mkdirSync(DEMO_CASE_ROOT);
  const caseId = allocateCaseId();
  const caseDir = `${DEMO_CASE_ROOT}/${caseId}`;
  fs.mkdirSync(caseDir);

  const normalizedNote = note.trim();
  WavIo.writePcmBytes(`${caseDir}/audio.wav`, pcm);
  writeText(`${caseDir}/note.txt`, `${normalizedNote}\n`);
  metadata['caseId'] = caseId;
  metadata['createdAtMs'] = Date.now();
  metadata['audioFile'] = 'audio.wav';
  metadata['noteFile'] = 'note.txt';
  metadata['note'] = normalizedNote;
  // Write metadata last. Its presence is the completion marker consumed by the PC pull tool.
  writeText(`${caseDir}/metadata.json`, `${JSON.stringify(metadata)}\n`);

  const result = new DemoCaseSaveResult();
  result.caseId = caseId;
  result.caseDir = caseDir;
  return result;
}
