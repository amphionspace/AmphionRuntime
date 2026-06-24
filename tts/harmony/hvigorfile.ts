import * as fs from 'fs';
import * as path from 'path';

import { appTasks } from '@ohos/hvigor-ohos-plugin';

const MODEL_ID = 'transsion_lits_en_zh_vocos24k_streaming_proto_external_loop';
const MODEL_VERSION = '0.1.0';
const MODEL_FILES = [
  'manifest.json',
  'export_report.json',
  'frontend_golden.json',
  'chinese_lexicon.txt',
  'chinese_lexicon.bin',
  'cmudict.txt',
  'cmudict.bin',
  'pinyin_2_bpmf.txt',
  'polychar.txt',
  'zh_en_symbols.json',
  'pinyin_to_tokens.json',
  'arpabet_to_tokens.json',
  'tn-bin/arm64-v8a/zh_tts',
  'tn-bin/arm64-v8a/en_tts',
  'rules/zh.json',
  'rules/en.json',
  'rules/zh_pinyin.json',
  'rules_v2/zh.full.json',
  'rules_v2/en.full.json',
  'lits_hidden_encoder.onnx',
  'external_loop_export_report.json',
  'lits_stream_condition_chunk.onnx',
  'lits_stream_condition_final.onnx',
  'lits_stream_decoder_step.onnx',
  'vocos_vocoder.onnx'
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
const harmonyTnDir = path.resolve(__dirname, 'build-ohos-tn');
const HARMONY_TN_FILES = new Set<string>([
  'tn-bin/arm64-v8a/zh_tts',
  'tn-bin/arm64-v8a/en_tts'
]);

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
    const harmonyTnFile = path.join(harmonyTnDir, path.basename(fileName));
    const sourceFile = HARMONY_TN_FILES.has(fileName) && fs.existsSync(harmonyTnFile)
      ? harmonyTnFile
      : path.join(modelSourceDir, fileName);
    fs.copyFileSync(
      sourceFile,
      path.join(modelTargetDir, fileName)
    );
  });
}

function assertModelSourceDir(): void {
  if (!fs.existsSync(modelSourceDir)) {
    if (MODEL_FILES.every((fileName: string): boolean => fs.existsSync(path.join(modelTargetDir, fileName)))) {
      return;
    }
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
  if (!fs.existsSync(modelSourceDir)) {
    return MODEL_FILES.every((fileName: string): boolean => fs.existsSync(path.join(modelTargetDir, fileName)));
  }
  return MODEL_FILES.every((fileName: string): boolean => {
    const harmonyTnFile = path.join(harmonyTnDir, path.basename(fileName));
    const sourceFile = HARMONY_TN_FILES.has(fileName) && fs.existsSync(harmonyTnFile)
      ? harmonyTnFile
      : path.join(modelSourceDir, fileName);
    const targetFile = path.join(modelTargetDir, fileName);
    if (!fs.existsSync(targetFile)) {
      return false;
    }

    const sourceStat = fs.statSync(sourceFile);
    const targetStat = fs.statSync(targetFile);
    return sourceStat.size === targetStat.size && targetStat.mtimeMs >= sourceStat.mtimeMs;
  });
}
