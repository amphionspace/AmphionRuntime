// Shared, offline build-time resource synchronization for Harmony and Android.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const names = ['nmnet-student-mel.onnx', 'nmnet-student-nest.onnx',
  'nmnet-student-segmentation.onnx', 'nmnet-ecapa-mel.onnx', 'nmnet-ecapa.onnx'];
const shared = path.resolve(__dirname, '../../shared/models/asr/dingqiao/nmnet-student/v1');
function digest(file) {
  const hash = crypto.createHash('sha256');
  const fd = fs.openSync(file, 'r');
  const buffer = Buffer.alloc(1024 * 1024);
  try {
    let count;
    while ((count = fs.readSync(fd, buffer, 0, buffer.length, null)) > 0) hash.update(buffer.subarray(0, count));
  } finally { fs.closeSync(fd); }
  return hash.digest('hex');
}
function readManifest(directory) {
  const manifest = JSON.parse(fs.readFileSync(path.join(directory, 'manifest.json'), 'utf8'));
  if (manifest.schemaVersion !== 1 || manifest.backend !== 'nmnet-student' ||
      manifest.modelVersion !== 'v1' || manifest.ortVersion !== '1.16.3' ||
      manifest.windowSamples !== 320000 || manifest.hopSamples !== 32000 ||
      manifest.sampleRate !== 16000 || manifest.embeddingDimension !== 192 ||
      manifest.files?.length !== names.length || manifest.files.some((entry, i) =>
        entry.file !== names[i] || !Number.isSafeInteger(entry.sizeBytes) || entry.sizeBytes <= 0 ||
        !/^[a-f0-9]{64}$/.test(entry.sha256))) throw new Error('Invalid NMNet resource manifest');
  return manifest;
}
function matches(file, entry) {
  return fs.existsSync(file) && fs.lstatSync(file).isFile() &&
    fs.statSync(file).size === entry.sizeBytes && digest(file) === entry.sha256;
}
function verify(directory, manifest = readManifest(directory)) {
  for (const entry of manifest.files) {
    if (!matches(path.join(directory, entry.file), entry)) throw new Error(`Missing/corrupt NMNet model: ${entry.file}`);
  }
  return manifest;
}
function sync(source, destination, manifestDirectory = source) {
  const manifest = readManifest(manifestDirectory);
  // Verify the whole source before touching an existing generated package.
  verify(source, manifest);
  for (const name of ['NOTICE.md', 'ECAPA-MODEL-CARD.md', 'ECAPA-LICENSE']) {
    if (!fs.statSync(path.join(manifestDirectory, name)).isFile()) throw new Error(`Missing NMNet notice: ${name}`);
  }
  fs.mkdirSync(destination, { recursive: true });
  for (const entry of manifest.files) {
    const target = path.join(destination, entry.file);
    if (matches(target, entry)) continue;
    const temp = `${target}.${process.pid}.tmp`;
    try {
      fs.copyFileSync(path.join(source, entry.file), temp);
      if (!matches(temp, entry)) throw new Error(`NMNet copy verification failed: ${entry.file}`);
      fs.renameSync(temp, target);
    } finally { if (fs.existsSync(temp)) fs.unlinkSync(temp); }
  }
  for (const name of ['NOTICE.md', 'ECAPA-MODEL-CARD.md', 'ECAPA-LICENSE']) {
    if (path.resolve(manifestDirectory) !== path.resolve(destination))
      fs.copyFileSync(path.join(manifestDirectory, name), path.join(destination, name));
  }
  // Publish manifest last. No partially synchronized set can pass verify().
  if (path.resolve(manifestDirectory) !== path.resolve(destination))
    fs.copyFileSync(path.join(manifestDirectory, 'manifest.json'), path.join(destination, 'manifest.json'));
  verify(destination, manifest);
  return manifest;
}
module.exports = { shared, names, readManifest, verify, sync };
if (require.main === module) {
  try {
    const [command, argument] = process.argv.slice(2);
    if (command === 'restore' && argument) sync(path.resolve(argument), shared, shared);
    else if (command === 'sync' && argument) sync(shared, path.resolve(argument));
    else if (command === 'verify') verify(argument ? path.resolve(argument) : shared);
    else throw new Error('Usage: node nmnet_model_resources.cjs restore <export-dir> | sync <target-dir> | verify [dir]');
    console.log(`NMNet resources ${command}: PASS`);
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
