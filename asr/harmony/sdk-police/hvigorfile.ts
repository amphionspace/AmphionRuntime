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
const policeManifest = path.resolve(
  __dirname,
  'src/main/resources/rawfile/amphion-police/manifest.json'
);

syncSharedLacEncoder();

export default {
  system: harTasks,
  plugins: []
};

function syncSharedLacEncoder(): void {
  // 「无警务后处理」交付包用 trim_police_postprocessing.py 裁掉后处理资产，并在
  // 资产 manifest 上打 variant=hotwords-only。LAC 人名模型只服务于后处理，
  // 那种包里不得随包发行 —— 否则这里会把 30 MB 的模型又拷回 rawfile，裁剪白做。
  if (isHotwordsOnlyVariant()) {
    if (fs.existsSync(rawfileLacEncoder)) {
      fs.rmSync(rawfileLacEncoder);
    }
    return;
  }
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

function isHotwordsOnlyVariant(): boolean {
  if (!fs.existsSync(policeManifest)) {
    return false;
  }
  try {
    return JSON.parse(fs.readFileSync(policeManifest, 'utf-8')).variant === 'hotwords-only';
  } catch (error) {
    throw new Error(`Unreadable police asset manifest: ${policeManifest}: ${error}`);
  }
}
