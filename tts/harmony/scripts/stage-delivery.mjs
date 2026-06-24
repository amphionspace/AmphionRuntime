import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, '..');
const repoRoot = path.resolve(projectRoot, '..', '..');
const sdkPackage = JSON.parse(
  fs.readFileSync(path.join(projectRoot, 'sdk', 'oh-package.json5'), 'utf8')
);
const deliveryRoot = path.join(
  projectRoot,
  'build',
  'delivery',
  `lits-tts-harmony-sdk-${sdkPackage.version}`
);
const runtimeRoot = path.join(deliveryRoot, 'harmonyos', 'AmphionRuntime');

fs.rmSync(deliveryRoot, { recursive: true, force: true });
fs.mkdirSync(runtimeRoot, { recursive: true });

copyRuntimePath('AppScope');
copyRuntimePath('docs');
copyRuntimePath('hvigor');
copyRuntimePath('sample');
copyRuntimePath('sdk');
copyRuntimePath('.gitignore');
copyRuntimePath('build-profile.json5');
copyRuntimePath('hvigorfile.ts');
copyRuntimePath('oh-package.json5');
copyRuntimePath('oh-package-lock.json5');
copyRuntimePath('README.md');

copyRepoPath(
  path.join('tools', 'README.md'),
  path.join(deliveryRoot, 'tools', 'README.md')
);
copyRepoPath(
  path.join('tools', 'verify_lits_harmony_package.mjs'),
  path.join(deliveryRoot, 'tools', 'verify_lits_harmony_package.mjs')
);
copyRepoPath(
  path.join('tools', 'trial-export', 'lits_delivery_16k_hifigan', '1.0.0', '.gitkeep'),
  path.join(
    deliveryRoot,
    'tools',
    'trial-export',
    'lits_delivery_16k_hifigan',
    '1.0.0',
    '.gitkeep'
  )
);

console.log(`Staged HarmonyOS delivery to ${deliveryRoot}`);

function copyRuntimePath(relativePath) {
  copyFiltered(
    path.join(projectRoot, relativePath),
    path.join(runtimeRoot, relativePath)
  );
}

function copyRepoPath(sourceRelativePath, targetAbsolutePath) {
  copyFiltered(path.join(repoRoot, sourceRelativePath), targetAbsolutePath);
}

function copyFiltered(sourcePath, targetPath) {
  if (!fs.existsSync(sourcePath)) {
    return;
  }

  const stat = fs.statSync(sourcePath);
  if (stat.isDirectory()) {
    fs.mkdirSync(targetPath, { recursive: true });
    for (const entry of fs.readdirSync(sourcePath, { withFileTypes: true })) {
      const childSource = path.join(sourcePath, entry.name);
      if (shouldSkip(childSource)) {
        continue;
      }
      copyFiltered(childSource, path.join(targetPath, entry.name));
    }
    return;
  }

  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  fs.copyFileSync(sourcePath, targetPath);
}

function shouldSkip(sourcePath) {
  const normalized = sourcePath.replace(/\\/g, '/');
  return normalized.includes('/.hvigor/')
    || normalized.includes('/.idea/')
    || normalized.includes('/.signing-local/')
    || normalized.includes('/oh_modules/')
    || normalized.includes('/verification/')
    || normalized.includes('/build/')
    || normalized.includes('/sdk/.cxx/')
    || normalized.includes('/sdk/src/main/resources/rawfile/lits-models/')
    || normalized.endsWith('/build-profile.json5.bak-before-signing-spinner');
}
