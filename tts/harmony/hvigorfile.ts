import * as fs from 'fs';
import * as path from 'path';

import { appTasks } from '@ohos/hvigor-ohos-plugin';

const MODEL_ID = 'lits_delivery_16k_hifigan';
const MODEL_VERSION = '1.0.0';
const MODEL_FILES = [
  'manifest.json',
  'export_report.json',
  'smoke_tokens.json',
  'frontend_golden.json',
  'chinese_lexicon.txt',
  'cmudict.txt',
  'pinyin_2_bpmf.txt',
  'polychar.txt',
  'zh_en_symbols.json',
  'pinyin_to_tokens.json',
  'arpabet_to_tokens.json',
  'lits_acoustic.onnx',
  'hifigan_vocoder.onnx'
];

const modelSourceDir = path.resolve(
  __dirname,
  '../../tools/trial-export',
  MODEL_ID,
  MODEL_VERSION
);
const modelTargetDir = path.resolve(
  __dirname,
  'sdk/src/main/resources/rawfile/lits-models/tts',
  MODEL_ID,
  MODEL_VERSION
);

syncBundledModelResources();

export default {
  system: appTasks,
  plugins: []
};

function syncBundledModelResources(): void {
  assertModelSourceDir();

  if (isModelTargetUpToDate()) {
    return;
  }

  fs.mkdirSync(modelTargetDir, { recursive: true });
  MODEL_FILES.forEach((fileName: string): void => {
    fs.copyFileSync(
      path.join(modelSourceDir, fileName),
      path.join(modelTargetDir, fileName)
    );
  });
}

function assertModelSourceDir(): void {
  if (!fs.existsSync(modelSourceDir)) {
    throw new Error(`Missing HarmonyOS model source directory: ${modelSourceDir}`);
  }

  MODEL_FILES.forEach((fileName: string): void => {
    const sourceFile = path.join(modelSourceDir, fileName);
    if (!fs.existsSync(sourceFile)) {
      throw new Error(`Missing HarmonyOS model file: ${sourceFile}`);
    }
  });
}

function isModelTargetUpToDate(): boolean {
  return MODEL_FILES.every((fileName: string): boolean => {
    const sourceFile = path.join(modelSourceDir, fileName);
    const targetFile = path.join(modelTargetDir, fileName);
    if (!fs.existsSync(targetFile)) {
      return false;
    }

    const sourceStat = fs.statSync(sourceFile);
    const targetStat = fs.statSync(targetFile);
    return sourceStat.size === targetStat.size && targetStat.mtimeMs >= sourceStat.mtimeMs;
  });
}
