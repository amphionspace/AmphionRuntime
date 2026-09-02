import * as fs from 'fs';
import * as path from 'path';
import { execFileSync } from 'child_process';

import { appTasks } from '@ohos/hvigor-ohos-plugin';

const MODEL_ID = 'dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop';
const MODEL_VERSION = '0.1.0';
const BASE_MODEL_FILES = [
  'manifest.json',
  'export_report.json',
  'frontend_golden.json',
  'chinese_lexicon.txt',
  'chinese_lexicon.bin',
  'chinese_surname_lexicon.txt',
  'cmudict.txt',
  'cmudict.bin',
  'supplement_lexicon.json',
  'frontend_rules.json',
  'pinyin_2_bpmf.txt',
  'polychar.txt',
  'zh_en_symbols.json',
  'pinyin_to_tokens.json',
  'arpabet_to_tokens.json',
  'polyphone_context.txt',
  'polyphone_phrases.txt',
  'tn-bin/arm64-v8a/zh_tts',
  'tn-bin/arm64-v8a/en_tts',
  'rules_v2/zh.full.json',
  'rules_v2/en.full.json',
  'rules_v2/zh_pinyin.json',
  'lits_hidden_encoder.onnx',
  'external_loop_export_report.json',
  'lits_stream_condition_chunk.onnx',
  'lits_stream_decoder_step.onnx',
  'vocos_vocoder.onnx'
];
const STREAM_CONDITION_FINAL_MODEL_FILE = 'lits_stream_condition_final.onnx';

const modelSourceDir = path.resolve(
  __dirname,
  '../tools/trial-export',
  MODEL_ID,
  MODEL_VERSION
);
const frontendBinaryBuilder = path.resolve(
  __dirname,
  '../../tools/dingqiao-android/build_frontend_binary_assets.py'
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

buildFrontendBinaryAssets();
syncBundledModelResources();

export default {
  system: appTasks,
  plugins: []
};

function syncBundledModelResources(): void {
  assertModelSourceDir();
  const modelFiles = requiredModelFiles();

  if (isModelTargetUpToDate()) {
    return;
  }

  fs.rmSync(modelTargetDir, { recursive: true, force: true });
  fs.mkdirSync(modelTargetDir, { recursive: true });
  modelFiles.forEach((fileName: string): void => {
    const sourceFile = resolveModelSource(fileName);
    const targetFile = path.join(modelTargetDir, fileName);
    fs.mkdirSync(path.dirname(targetFile), { recursive: true });
    fs.copyFileSync(
      sourceFile,
      targetFile
    );
  });
}

function buildFrontendBinaryAssets(): void {
  try {
    execFileSync('python3', [frontendBinaryBuilder, '--model-dir', modelSourceDir], {
      encoding: 'utf8',
      stdio: 'inherit'
    });
  } catch (error) {
    throw new Error(`Failed to build frontend binary assets: ${String(error)}`);
  }
}

function assertModelSourceDir(): void {
  const modelFiles = requiredModelFiles();
  if (!fs.existsSync(modelSourceDir)) {
    if (modelFiles.every((fileName: string): boolean => fs.existsSync(resolveModelSource(fileName)))) {
      return;
    }
    throw new Error(`Missing HarmonyOS model source directory: ${modelSourceDir}`);
  }

  modelFiles.forEach((fileName: string): void => {
    const sourceFile = resolveModelSource(fileName);
    if (!fs.existsSync(sourceFile)) {
      throw new Error(`Missing HarmonyOS model file: ${sourceFile}`);
    }
  });
}

function resolveModelSource(fileName: string): string {
  if (HARMONY_TN_FILES.has(fileName)) {
    const harmonyTnFile = path.join(harmonyTnDir, path.basename(fileName));
    if (fs.existsSync(harmonyTnFile)) {
      return harmonyTnFile;
    }
  }
  return path.join(modelSourceDir, fileName);
}

function isModelTargetUpToDate(): boolean {
  const modelFiles = requiredModelFiles();
  if (usesChunkConditionForFinal() && fs.existsSync(path.join(modelTargetDir, STREAM_CONDITION_FINAL_MODEL_FILE))) {
    return false;
  }
  if (!fs.existsSync(modelSourceDir)) {
    return modelFiles.every((fileName: string): boolean => fs.existsSync(path.join(modelTargetDir, fileName)));
  }
  return modelFiles.every((fileName: string): boolean => {
    const sourceFile = resolveModelSource(fileName);
    const targetFile = path.join(modelTargetDir, fileName);
    if (!fs.existsSync(targetFile)) {
      return false;
    }

    const sourceStat = fs.statSync(sourceFile);
    const targetStat = fs.statSync(targetFile);
    return sourceStat.size === targetStat.size && targetStat.mtimeMs >= sourceStat.mtimeMs;
  });
}

function requiredModelFiles(): Array<string> {
  const files = BASE_MODEL_FILES.slice();
  if (!usesChunkConditionForFinal()) {
    files.push(STREAM_CONDITION_FINAL_MODEL_FILE);
  }
  return files;
}

function usesChunkConditionForFinal(): boolean {
  const sourceManifest = path.join(modelSourceDir, 'manifest.json');
  const manifestPath = fs.existsSync(sourceManifest)
    ? sourceManifest
    : path.join(modelTargetDir, 'manifest.json');
  if (!fs.existsSync(manifestPath)) {
    return false;
  }
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8')) as {
    stream_final_zero_pad_with_chunk_condition?: boolean;
  };
  return manifest.stream_final_zero_pad_with_chunk_condition === true;
}
