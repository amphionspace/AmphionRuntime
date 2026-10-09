import * as crypto from "crypto";
import { isDeepStrictEqual } from "util";
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
  'campplus.onnx',
  'campplus.LICENSE',
  'community-wespeaker-encoder.int8.onnx',
  'community-wespeaker-pool.fp32.onnx',
  'community-feature.f32',
  'community-plda.f64',
  'pyannote-segmentation-3.0.onnx',
  'pyannote-segmentation-3.0.LICENSE'
];
// Shipped only when present: the MindIR export of the FP32 split encoder that
// the NNRt accelerator path loads. A build without it still packages and runs
// on the CPU session, and a stale copy must not outlive its shared source.
const optionalSharedModelFiles = [
  'community-wespeaker-encoder.fp16.ms'
];

syncSharedModels();

export default {
  system: harTasks,
  plugins: []
};

function syncSharedModels(): void {
  const optionalHashes = optionalSharedModelFiles.map(verifyOptionalModel);
  fs.mkdirSync(rawfileModelDir, { recursive: true });
  // The previous generated graph is replaced by the two weight-preserving
  // graphs below. Do not retain its 26 MB in an incremental HAR build.
  const oldEmbedding = path.join(rawfileModelDir, 'community-wespeaker-masked.fp32.onnx');
  if (fs.existsSync(oldEmbedding)) fs.unlinkSync(oldEmbedding);
  // The INT8 encoder replaced the FP32 one; an incremental build must not ship both.
  const oldEncoder = path.join(rawfileModelDir, 'community-wespeaker-encoder.fp32.onnx');
  if (fs.existsSync(oldEncoder)) fs.unlinkSync(oldEncoder);
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
  optionalSharedModelFiles.forEach((fileName: string, index: number): void => {
    const source = path.join(sharedModelDir, fileName);
    const target = path.join(rawfileModelDir, fileName);
    if (!fs.existsSync(source)) {
      if (fs.existsSync(target)) fs.unlinkSync(target);
      return;
    }
    if (!isUpToDate(source, target)) {
      fs.copyFileSync(source, target);
    }
    if (sha256(target) !== optionalHashes[index]) {
      throw new Error(`Generated Community MindIR differs from its provenance: ${target}`);
    }
  });
}

function sha256(filePath: string): string {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function verifyOptionalModel(fileName: string): string | undefined {
  const model = path.join(sharedModelDir, fileName);
  const sidecar = `${model}.provenance.json`;
  const generatedSidecar = path.join(rawfileModelDir, `${fileName}.provenance.json`);
  if (fs.existsSync(generatedSidecar)) {
    throw new Error(`Community MindIR provenance must not enter rawfile: ${generatedSidecar}`);
  }
  if (!fs.existsSync(model)) {
    if (fs.existsSync(sidecar)) throw new Error(`Orphan Community MindIR provenance: ${sidecar}`);
    return undefined;
  }
  const source = path.join(sharedModelDir, "community-wespeaker-encoder.fp32.onnx");
  [source, model, sidecar].forEach((file: string): void => {
    if (!fs.existsSync(file) || !fs.lstatSync(file).isFile()) {
      throw new Error(`Missing regular Community MindIR source/provenance: ${file}`);
    }
  });
  const record = JSON.parse(fs.readFileSync(sidecar, "utf-8"));
  const signature = {
    inputs: [{ name: "fbank", dtype: "FLOAT", shape: [1, 998, 80] }],
    outputs: [{ name: "/resnet/pool/Reshape_output_0", dtype: "FLOAT", shape: [1, 2560, 125] }]
  };
  const flags = [
    "--fmk=ONNX", "--saveType=MINDIR_LITE", "--fp16=on",
    "--inputDataType=FLOAT", "--outputDataType=FLOAT",
    "--inputShape=fbank:1,998,80", "--optimize=general", "--infer=false",
    "--trainModel=false", "--optimizeTransformer=false"
  ];
  const same = isDeepStrictEqual;
  if (record.schemaVersion !== 1 || record.kind !== "community-encoder-mindir" || record.status !== "VERIFIED" ||
      record.source?.file !== path.basename(source) || record.source?.format !== "ONNX" ||
      record.source?.sha256 !== "8f8c4619237d023770f5ed18012123771e216c5ec358987b8d3c4e486a74d30f" ||
      record.source?.sizeBytes !== 21_301_300 || record.source.sha256 !== sha256(source) ||
      record.source.sizeBytes !== fs.statSync(source).size || !same(record.source.signature, signature) ||
      record.output?.file !== fileName || record.output?.format !== "MINDIR_LITE" ||
      record.output?.sizeBytes !== fs.statSync(model).size || record.output?.sha256 !== sha256(model) ||
      fs.readFileSync(model).subarray(4, 8).toString("ascii") !== "MSL2" ||
      !same(record.output.signature, signature) || record.package?.version !== "2.7.0" ||
      record.package?.sha256 !== "8bb1097100c9fec12675670ba2d4264a2cd6da3a9be093eb56631d00fc0c455b" ||
      record.converter?.version !== "2.7.0" || !same(record.conversion?.flags, flags) ||
      record.conversion?.format !== "MINDIR_LITE" || record.conversion?.execution?.returnCode !== 0 ||
      record.validation?.schema?.status !== "PASS" || record.validation?.schema?.model?.identifier !== "MSL2" ||
      record.validation?.benchmark?.status !== "PASS" || record.validation?.benchmark?.device !== "CPU" ||
      record.validation?.benchmark?.testInput?.realAudio !== false) {
    throw new Error(`Invalid Community MindIR source/provenance: ${sidecar}`);
  }
  return record.output.sha256;
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
