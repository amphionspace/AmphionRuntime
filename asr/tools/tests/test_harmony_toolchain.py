from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
ENV_SCRIPT = ROOT / "asr/tools/harmony_env.sh"
CLI_SCRIPT = ROOT / "asr/tools/deveco_cli.sh"
DELIVERY = ROOT / "delivery/harmony-dingqiao/delivery"


class HarmonyToolchainTest(unittest.TestCase):
    def test_shell_selects_clt_and_independent_java_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory(prefix="harmony clt ") as directory:
            clt = Path(directory)
            java_home = clt / "independent jdk"
            env = {"HOME": directory, "PATH": os.defpath,
                   "DEVECO_CLI_CLT_PATH": directory,
                   "DEVECO_CLI_STUDIO_PATH": "/missing/Studio.app",
                   "JAVA_HOME": str(java_home)}
            result = subprocess.run(
                ["bash", "-c", 'source "$1"; printf "%s\\n" "$NODE" "$HVIGOR" '
                 '"$OHPM" "$HDC" "$LLVM_NM" "$JAVA_BIN" "$HAP_SIGN_TOOL_JAR" '
                 '"${DEVECO_CLI_STUDIO_PATH-unset}" "$DEVECO_CLI_DISABLE_TELEMETRY"',
                 "bash", str(ENV_SCRIPT)], env=env, text=True, capture_output=True, check=True,
            )
            sdk = clt / "sdk/default/openharmony"
            self.assertEqual(result.stdout.splitlines(), [
                str(clt / "tool/node/bin/node"), str(clt / "hvigor/bin/hvigorw.js"),
                str(clt / "ohpm/bin/ohpm"), str(sdk / "toolchains/hdc"),
                str(sdk / "native/llvm/bin/llvm-nm"), str(java_home / "bin/java"),
                str(sdk / "toolchains/lib/hap-sign-tool.jar"), "unset", "1",
            ])

    def test_cli_preserves_arguments_working_directory_and_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="harmony cli ") as directory:
            base = Path(directory)
            cli = base / "devecocli"
            cli.write_text('#!/usr/bin/env python3\nimport json, os, sys\n'
                           'print(json.dumps([sys.argv[1:], os.getcwd(), '
                           'os.environ["DEVECO_CLI_CLT_PATH"], '
                           'os.environ.get("DEVECO_CLI_STUDIO_PATH")]))\n'
                           'sys.exit(23)\n', encoding="utf-8")
            cli.chmod(0o755)
            env = dict(os.environ, PATH=f"{base}:{os.environ['PATH']}",
                       DEVECO_CLI_CLT_PATH=str(base / "standalone tools"),
                       DEVECO_CLI_STUDIO_PATH="/missing/Studio.app")
            args = ["build", "--modules", "amphion_asr@default", "--build-mode", "diagnostics"]
            result = subprocess.run(["bash", str(CLI_SCRIPT), *args], cwd=base, env=env,
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 23, result.stderr)
            self.assertEqual(json.loads(result.stdout),
                             [args, str(base.resolve()), str(base / "standalone tools"), None])

    def test_all_device_entrypoints_use_clt_or_explicit_hdc(self) -> None:
        with tempfile.TemporaryDirectory(prefix="harmony device ") as directory:
            clt = Path(directory)
            hdc = clt / "sdk/default/openharmony/toolchains/hdc"
            hdc.parent.mkdir(parents=True)
            hdc.touch()
            override = clt / "custom hdc"
            override.touch()
            names = ["collect_asr_diagnostics.py", "pull_demo_cases.py", "run_device_stress.py",
                     "run_model_load_bench.py", "run_hotword_device_eval.py"]
            for name in names:
                with self.subTest(script=name):
                    module = runpy.run_path(str(DELIVERY / name))
                    with mock.patch.dict(os.environ, {"DEVECO_CLI_CLT_PATH": directory}, clear=True):
                        self.assertEqual(module["locate_hdc"](), hdc)
                        with mock.patch.dict(os.environ, {"HDC": str(override)}):
                            self.assertEqual(module["locate_hdc"](), override)
                        hdc.unlink()
                        try:
                            with self.assertRaises(RuntimeError):
                                module["locate_hdc"]()
                        finally:
                            hdc.touch()


if __name__ == "__main__":
    unittest.main()
