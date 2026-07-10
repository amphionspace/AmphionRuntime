import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';

/**
 * On-disk voiceprint embedding store, byte-compatible with the Android Dingqiao SDK layout so the
 * registration flow and the recognition session share one source of truth:
 *
 *   {workPath}/voiceprints/{id}/embedding.bin   int32 dim (LE) + float32[dim] (LE)
 *   {workPath}/voiceprints/{id}/meta.json       {"voiceprintId":"vp-...","sample":"first.wav"}
 *
 * Embeddings are already L2-normalized by SpeakerEnroller; multi-id merge averages per dimension
 * then re-normalizes, matching Android's loadMergedEmbedding.
 */
export class VoiceprintStore {
  private root: string;

  constructor(workPath: string) {
    this.root = `${workPath}/voiceprints`;
  }

  saveVoiceprint(samplePaths: string[], embedding: Float32Array): string {
    const id = `vp-${util.generateRandomUUID(true)}`;
    const dir = `${this.root}/${id}`;
    this.ensureDir(dir);
    VoiceprintStore.writeEmbedding(`${dir}/embedding.bin`, embedding);
    const firstSample = samplePaths.length > 0 ? baseName(samplePaths[0]) : '';
    const meta = `{"voiceprintId":"${id}","sample":"${firstSample}"}`;
    const fp = fs.openSync(`${dir}/meta.json`, fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
    try {
      fs.writeSync(fp.fd, meta);
    } finally {
      fs.close(fp.fd);
    }
    return id;
  }

  loadEmbedding(id: string): Float32Array | undefined {
    if (!VoiceprintStore.isSafeId(id)) return undefined;
    const file = `${this.root}/${id}/embedding.bin`;
    if (!fs.accessSync(file)) return undefined;
    return VoiceprintStore.readEmbedding(file);
  }

  loadMergedEmbedding(ids: string[]): Float32Array | undefined {
    const embeddings: Float32Array[] = [];
    for (let i = 0; i < ids.length; i++) {
      const e = this.loadEmbedding(ids[i]);
      if (e !== undefined) embeddings.push(e);
    }
    if (embeddings.length === 0) return undefined;
    if (embeddings.length === 1) return embeddings[0];
    const dim = embeddings[0].length;
    const out = new Float32Array(dim);
    for (let i = 0; i < embeddings.length; i++) {
      const e = embeddings[i];
      for (let j = 0; j < Math.min(dim, e.length); j++) out[j] += e[j];
    }
    for (let j = 0; j < dim; j++) out[j] /= embeddings.length;
    let norm = 0;
    for (let j = 0; j < dim; j++) norm += out[j] * out[j];
    norm = Math.sqrt(norm);
    if (norm > 0) {
      for (let j = 0; j < dim; j++) out[j] /= norm;
    }
    return out;
  }

  deleteVoiceprint(id: string): boolean {
    if (!VoiceprintStore.isSafeId(id)) return false;
    const dir = `${this.root}/${id}`;
    if (!fs.accessSync(dir)) return false;
    try {
      const children = fs.listFileSync(dir);
      for (let i = 0; i < children.length; i++) {
        fs.unlinkSync(`${dir}/${children[i]}`);
      }
      fs.rmdirSync(dir);
      return true;
    } catch (e) {
      return false;
    }
  }

  listIds(): string[] {
    if (!fs.accessSync(this.root)) return [];
    try {
      return fs.listFileSync(this.root);
    } catch (e) {
      return [];
    }
  }

  // 声纹 id 直接拼进文件系统路径,必须限定字符集,否则 `../..` 之类可越出 {workPath}/voiceprints 根,
  // deleteVoiceprint 会 unlink+rmdir 沙箱内任意目录、loadEmbedding 会读任意文件。与本模块 isValidSessionId 一致。
  private static isSafeId(id: string): boolean {
    return /^[A-Za-z0-9_-]+$/.test(id);
  }

  private ensureDir(dir: string): void {
    if (fs.accessSync(dir)) return;
    const idx = dir.lastIndexOf('/');
    if (idx > 0) this.ensureDir(dir.substring(0, idx));
    if (!fs.accessSync(dir)) fs.mkdirSync(dir);
  }

  private static writeEmbedding(file: string, emb: Float32Array): void {
    const out = new ArrayBuffer(4 + emb.length * 4);
    const view = new DataView(out);
    view.setInt32(0, emb.length, true);
    for (let i = 0; i < emb.length; i++) {
      view.setFloat32(4 + i * 4, emb[i], true);
    }
    const fp = fs.openSync(file, fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
    try {
      fs.writeSync(fp.fd, out);
    } finally {
      fs.close(fp.fd);
    }
  }

  private static readEmbedding(file: string): Float32Array | undefined {
    const fp = fs.openSync(file);
    try {
      const size = fs.statSync(fp.fd).size;
      if (size < 4) return undefined;
      const raw = new ArrayBuffer(size);
      fs.readSync(fp.fd, raw);
      const view = new DataView(raw);
      const dim = view.getInt32(0, true);
      if (dim <= 0 || size < 4 + dim * 4) return undefined;
      const out = new Float32Array(dim);
      for (let i = 0; i < dim; i++) out[i] = view.getFloat32(4 + i * 4, true);
      return out;
    } finally {
      fs.close(fp.fd);
    }
  }
}

function baseName(path: string): string {
  const idx = path.lastIndexOf('/');
  return idx >= 0 ? path.substring(idx + 1) : path;
}
