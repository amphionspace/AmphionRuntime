import * as fs from 'fs';
import * as path from 'path';

import { harTasks } from '@ohos/hvigor-ohos-plugin';

const sharedLacEncoder = path.resolve(
  __dirname,
  '../../../shared/models/asr/police/lac/v1/lac_encoder.onnx'
);
const rawfileLacEncoder = path.resolve(
  __dirname,
  'src/main/resources/rawfile/amphion-police/lac/v1/lac_encoder.onnx'
);

syncSharedLacEncoder();

export default {
  system: harTasks,
  plugins: []
};

function syncSharedLacEncoder(): void {
  if (!fs.existsSync(sharedLacEncoder)) {
    throw new Error(`Missing shared LAC encoder model: ${sharedLacEncoder}`);
  }
  fs.mkdirSync(path.dirname(rawfileLacEncoder), { recursive: true });
  const sourceStat = fs.statSync(sharedLacEncoder);
  if (fs.existsSync(rawfileLacEncoder)) {
    const targetStat = fs.statSync(rawfileLacEncoder);
    if (sourceStat.size === targetStat.size &&
      fs.readFileSync(sharedLacEncoder).equals(fs.readFileSync(rawfileLacEncoder))) {
      return;
    }
  }
  fs.copyFileSync(sharedLacEncoder, rawfileLacEncoder);
}
