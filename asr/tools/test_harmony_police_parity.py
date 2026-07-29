#!/usr/bin/env python3
"""Run Harmony police ArkTS V2 code under Node against the shared parity corpus."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "asr/harmony/sdk-police/src/main/ets/com/amphion/police"
RAWFILE = ROOT / "asr/harmony/sdk-police/src/main/resources/rawfile"
CASES = ROOT / "asr/harmony/sdk-police/tests/police_v2_parity.tsv"
NODE = Path("/Applications/DevEco-Studio.app/Contents/tools/node/bin/node")
TSC = Path("/Applications/DevEco-Studio.app/Contents/tools/hvigor/hvigor/node_modules/typescript/bin/tsc")


def write_mocks(work: Path) -> None:
    ability = work / "node_modules/@kit.AbilityKit"
    arkts = work / "node_modules/@kit.ArkTS"
    ability.mkdir(parents=True)
    arkts.mkdir(parents=True)
    (ability / "index.d.ts").write_text(
        "export namespace common { export interface Context { resourceManager: any } }\n",
        encoding="utf-8",
    )
    (ability / "index.js").write_text("exports.common = {};\n", encoding="utf-8")
    (ability / "package.json").write_text(
        '{"name":"@kit.AbilityKit","main":"index.js","types":"index.d.ts"}\n', encoding="utf-8")
    (arkts / "index.d.ts").write_text("export const util: any;\n", encoding="utf-8")
    (arkts / "index.js").write_text(
        "exports.util={TextDecoder:{create:()=>({decodeToString:(v)=>new TextDecoder().decode(v)})}};\n",
        encoding="utf-8",
    )
    (arkts / "package.json").write_text(
        '{"name":"@kit.ArkTS","main":"index.js","types":"index.d.ts"}\n', encoding="utf-8")


def write_runner(work: Path) -> None:
    runner = r"""
const fs = require('fs');
const path = require('path');
const { PlateV2 } = require('./src/PlateV2');
const { PoliceTermsV2 } = require('./src/PoliceTermsV2');
const { PoliceStationV2 } = require('./src/PoliceStationV2');
const rawRoot = process.argv[2];
const casesPath = process.argv[3];
const context = { resourceManager: { getRawFileContentSync: (p) => new Uint8Array(fs.readFileSync(path.join(rawRoot, p))) } };
const engines = { plate: new PlateV2(context), terms: new PoliceTermsV2(context), station: new PoliceStationV2(context) };
const lines = fs.readFileSync(casesPath, 'utf8').split(/\r?\n/).filter((line) => line && !line.startsWith('#'));
let failures = 0;
for (const [index, line] of lines.entries()) {
  const [domain, assertion, input, expected] = line.split('\t');
  const actual = domain === 'terms-polish' ? engines.terms.polish(input) : engines[domain].normalize(input);
  const ok = assertion === 'contains' ? actual.includes(expected) : actual === expected;
  if (!ok) {
    failures++;
    console.error(`FAIL ${index + 1} ${domain}: ${JSON.stringify(input)} => ${JSON.stringify(actual)}, expected ${assertion} ${JSON.stringify(expected)}`);
  }
}
if (failures) process.exit(1);
console.log(`[OK] Harmony police V2 parity corpus: ${lines.length} cases`);
"""
    (work / "runner.js").write_text(runner, encoding="utf-8")


def main() -> None:
    if not NODE.is_file() or not TSC.is_file():
        raise SystemExit("DevEco Studio Node/TypeScript toolchain is required")
    with tempfile.TemporaryDirectory(prefix="harmony-police-parity.") as temp:
        work = Path(temp)
        source = work / "src"
        source.mkdir()
        for name in ("PoliceAssets", "PlateV2", "PoliceTermsV2", "PoliceStationV2"):
            shutil.copyfile(SOURCE / f"{name}.ets", source / f"{name}.ts")
        write_mocks(work)
        write_runner(work)
        sources = [str(path.relative_to(work)) for path in sorted(source.glob("*.ts"))]
        subprocess.run(
            [str(NODE), str(TSC), "--target", "ES2020", "--module", "commonjs", "--skipLibCheck", *sources],
            cwd=work,
            check=True,
            shell=False,
        )
        subprocess.run([str(NODE), "runner.js", str(RAWFILE), str(CASES)], cwd=work, check=True)


if __name__ == "__main__":
    main()
