import * as crypto from "crypto";
import * as fs from 'fs';
import * as path from 'path';

import { harTasks } from '@ohos/hvigor-ohos-plugin';

const sharedModelDir = path.resolve(__dirname, '../../../shared/models/asr/dingqiao');
const rawfileModelDir = path.resolve(
  __dirname,
  'src/main/resources/rawfile/amphion-dingqiao'
);
const sharedModelFiles = [
  'df3_enc_stream.onnx',
  'df3_erb_dec_stream.onnx',
  'df3_df_dec_stream.onnx',
  'df3.LICENSE',
  'df3.manifest.json',
  'noise_suppression.manifest.json',
  'eres2net.onnx',
  'campplus.onnx',
  'campplus.LICENSE',
  'pyannote-segmentation-3.0.onnx',
  'pyannote-segmentation-3.0.LICENSE'
];
// Assets of the replaced windowed role-separation chain. An incremental HAR
// build must not keep shipping them from an earlier checkout.
const staleModelFiles = [
  'ulunas_stream.onnx',
  'ulunas.LICENSE',
  'gtcrn_stream.onnx',
  'gtcrn.LICENSE',
  'gtcrn.manifest.json',

  'community-wespeaker-masked.fp32.onnx',
  'community-wespeaker-encoder.fp32.onnx',
  'community-wespeaker-encoder.int8.onnx',
  'community-wespeaker-encoder.fp16.ms',
  'community-wespeaker-pool.fp32.onnx',
  'community-feature.f32',
  'community-plda.f64'
];
// Sortformer-66M-4spk streaming diarization: the four ORT-format graphs, the
// learnable silence embedding and the two mel tables. Every file must match
// the manifest byte for byte; a stale or hand-edited copy fails the build.
const sortformerModelSubdir = 'sortformer-66M-4spk';
const sortformerManifest = path.resolve(
  __dirname, '../../../delivery/harmony-dingqiao/delivery/sortformer_diarization_v1.json');

syncSharedModels();
syncSortformerModels();

export default {
  system: harTasks,
  plugins: []
};

function syncSharedModels(): void {
  const denoising = JSON.parse(fs.readFileSync(path.join(sharedModelDir, 'noise_suppression.manifest.json'), 'utf-8'));
  for (const entry of denoising.files) {
    const bytes = fs.readFileSync(path.join(sharedModelDir, entry.file));
    if (bytes.length !== entry.bytes || crypto.createHash('sha256').update(bytes).digest('hex') !== entry.sha256) {
      throw new Error(`Noise suppression model mismatch: ${entry.file}`);
    }
  }
  fs.mkdirSync(rawfileModelDir, { recursive: true });
  staleModelFiles.forEach((fileName: string): void => {
    const stale = path.join(rawfileModelDir, fileName);
    if (fs.existsSync(stale)) fs.unlinkSync(stale);
  });
  sharedModelFiles.forEach((fileName: string): void => {
    const source = path.join(sharedModelDir, fileName);
    const target = path.join(rawfileModelDir, fileName);
    if (!fs.existsSync(source)) {
      throw new Error(`Missing shared Dingqiao model resource: ${source}`);
    }
    if (!isUpToDate(source, target)) {
      fs.copyFileSync(source, target);
    }
  });
}

function syncSortformerModels(): void {
  const manifest = JSON.parse(fs.readFileSync(sortformerManifest, 'utf-8'));
  const sourceDir = path.join(sharedModelDir, sortformerModelSubdir);
  const targetDir = path.join(rawfileModelDir, sortformerModelSubdir);
  fs.mkdirSync(targetDir, { recursive: true });
  const expected = new Set<string>();
  for (const entry of manifest.files) {
    expected.add(entry.file);
    const source = path.join(sourceDir, entry.file);
    const target = path.join(targetDir, entry.file);
    if (!fs.existsSync(source)) {
      throw new Error(`Missing shared Sortformer model resource: ${source}`);
    }
    if (fs.statSync(source).size !== entry.sizeBytes || sha256(source) !== entry.sha256) {
      throw new Error(`Sortformer model differs from sortformer_diarization_v1.json: ${source}`);
    }
    if (!isUpToDate(source, target)) {
      fs.copyFileSync(source, target);
    }
  }
  // Nothing outside the manifest ships from this directory.
  for (const name of fs.readdirSync(targetDir)) {
    if (!expected.has(name)) fs.unlinkSync(path.join(targetDir, name));
  }
}

function sha256(filePath: string): string {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function isUpToDate(source: string, target: string): boolean {
  if (!fs.existsSync(target)) {
    return false;
  }
  const sourceStat = fs.statSync(source);
  const targetStat = fs.statSync(target);
  return sourceStat.size === targetStat.size &&
    fs.readFileSync(source).equals(fs.readFileSync(target));
}
