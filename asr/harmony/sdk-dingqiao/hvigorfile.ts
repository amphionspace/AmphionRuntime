import * as fs from 'fs';
import * as path from 'path';
import { createRequire } from 'module';
import { harTasks } from '@ohos/hvigor-ohos-plugin';

const sharedModelDir = path.resolve(__dirname, '../../../shared/models/asr/dingqiao');
const rawfileModelDir = path.resolve(__dirname, 'src/main/resources/rawfile/amphion-dingqiao');
const resources = createRequire(__filename)('../../tools/nmnet_model_resources.cjs');
resources.sync(resources.shared, path.join(rawfileModelDir, 'nmnet-student/v1'));
// Voiceprint enrollment/verification remains ERes2Net; complementary consumers retain CAMPPlus.
fs.mkdirSync(rawfileModelDir, { recursive: true });
for (const name of ['eres2net.onnx', 'campplus.onnx', 'campplus.LICENSE']) {
  const source = path.join(sharedModelDir, name);
  const target = path.join(rawfileModelDir, name);
  if (!fs.existsSync(source)) throw new Error(`Missing shared voiceprint resource: ${source}`);
  if (!fs.existsSync(target) || !fs.readFileSync(source).equals(fs.readFileSync(target))) fs.copyFileSync(source, target);
}
// Remove only known generated legacy role assets; retain shared source/archive evidence.
for (const name of ['community-wespeaker-encoder.int8.onnx', 'community-wespeaker-encoder.fp32.onnx',
  'community-wespeaker-pool.fp32.onnx', 'community-wespeaker-masked.fp32.onnx',
  'community-wespeaker-encoder.fp16.ms', 'community-wespeaker-encoder.fp16.ms.provenance.json',
  'community-feature.f32', 'community-plda.f64', 'community1-segmentation.onnx',
  'community1-wespeaker.onnx', 'community1-plda.bin', 'pyannote-segmentation-3.0.onnx',
  'pyannote-segmentation-3.0.LICENSE']) {
  const target = path.join(rawfileModelDir, name);
  if (fs.existsSync(target)) fs.unlinkSync(target);
}
export default { system: harTasks, plugins: [] };
