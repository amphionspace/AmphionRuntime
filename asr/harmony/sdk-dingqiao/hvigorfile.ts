import * as fs from 'fs';
import * as path from 'path';

import { harTasks } from '@ohos/hvigor-ohos-plugin';

const sharedModelDir = path.resolve(__dirname, '../../../shared/models/asr/dingqiao');
const rawfileModelDir = path.resolve(
  __dirname,
  'src/main/resources/rawfile/amphion-dingqiao'
);
const sharedModelFiles = [
  'eres2net.onnx',
  'pyannote-segmentation-3.0.onnx',
  'pyannote-segmentation-3.0.LICENSE'
];

syncSharedModels();

export default {
  system: harTasks,
  plugins: []
};

function syncSharedModels(): void {
  fs.mkdirSync(rawfileModelDir, { recursive: true });
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

function isUpToDate(source: string, target: string): boolean {
  if (!fs.existsSync(target)) {
    return false;
  }
  const sourceStat = fs.statSync(source);
  const targetStat = fs.statSync(target);
  return sourceStat.size === targetStat.size &&
    fs.readFileSync(source).equals(fs.readFileSync(target));
}
