from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from asr.tools import verify_community_encoder_mindir as gate
from asr.tools.tests.test_verify_community_encoder_mindir import MindirFixture


SCRIPT = Path(__file__).with_name("build_install_smoke.sh")


class BuildInstallSmokeTest(unittest.TestCase):
    def test_mindir_source_preflight_does_not_require_unbuilt_rawfile(self) -> None:
        source = SCRIPT.with_name("verify_demo_inputs.sh").read_text(encoding="utf-8")
        self.assertIn("--source-only", source)
        self.assertIn("verify_community_encoder_mindir.py", source)
        self.assertIn("MINDIR_VERIFY_ARGS+=(--archive", source)

    def test_prepare_only_skips_device_and_signing_requirements(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("--prepare-only", source)
        self.assertIn('if [[ "$PREPARE_ONLY" != true && -z "$DEVICE" ]]', source)
        self.assertIn('if [[ "$PREPARE_ONLY" == true ]]', source)
        self.assertLess(source.index("prepare_build_workspace"), source.index("apply_local_signing"))

    def test_isolated_build_copies_the_agc_public_header(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        prepare = source.index("prepare_build_workspace()")
        apply_signing = source.index("apply_local_signing()")
        isolated_build = source[prepare:apply_signing]
        self.assertIn('"$REPO_ROOT/asr/native/audio-processing/include"', isolated_build)
        self.assertIn('"$temp_repo/asr/native/audio-processing/include"', isolated_build)

    def test_isolated_build_copies_shared_asr_models(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        prepare = source.index("prepare_build_workspace()")
        apply_signing = source.index("apply_local_signing()")
        isolated_build = source[prepare:apply_signing]
        self.assertIn('"$REPO_ROOT/shared/models/asr"', isolated_build)
        self.assertIn('"$temp_repo/shared/models/asr"', isolated_build)

    def test_isolated_build_recreates_ignored_hvigor_config(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        prepare = source.index("prepare_build_workspace()")
        apply_signing = source.index("apply_local_signing()")
        isolated_build = source[prepare:apply_signing]
        self.assertIn('mkdir -p "$temp_repo/delivery/harmony-dingqiao/hvigor"', isolated_build)
        self.assertIn(
            'cat >"$temp_repo/delivery/harmony-dingqiao/hvigor/hvigor-config.json5"',
            isolated_build,
        )

    def test_isolated_build_applies_the_versioned_sherpa_patch_series(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        prepare = source.index("prepare_build_workspace()")
        apply_signing = source.index("apply_local_signing()")
        isolated_build = source[prepare:apply_signing]
        clone = isolated_build.index(
            'git clone --quiet --no-hardlinks "$sherpa_source" "$sherpa_destination"'
        )
        checkout = isolated_build.index(
            'git -C "$sherpa_destination" checkout --quiet --detach "$sherpa_commit"'
        )
        native_libs = isolated_build.index(
            '"$sherpa_native_source/harmony-os/SherpaOnnxHar/sherpa_onnx/src/main/cpp/libs/"'
        )
        patch = isolated_build.index('AMPHION_SHERPA_ROOT="$sherpa_destination"')
        self.assertIn(
            'local sherpa_destination="$temp_repo/third_party/.derived/sherpa-onnx"',
            isolated_build,
        )
        self.assertLess(clone, checkout)
        self.assertLess(checkout, native_libs)
        self.assertLess(native_libs, patch)
        self.assertNotIn(
            'bash "$REPO_ROOT/asr/tools/apply_sherpa_patches.sh"\n  BUILD_WORKSPACE=',
            isolated_build,
        )

    def test_hvigor_failures_stop_the_isolated_build(self) -> None:
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
        source = SCRIPT.read_text(encoding="utf-8")
        install = source.index('"$OHPM" install --all')
        assemble_hap = source.index('if ! "$NODE" "$HVIGOR" assembleHap')
        self.assertLess(install, assemble_hap)
        self.assertIn('if ! "$NODE" "$HVIGOR" assembleHap', source)
        self.assertIn('if ! "$NODE" "$HVIGOR" assembleHar', source)

    def test_test_carrier_install_allows_a_version_downgrade(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"$HDC" -t "$DEVICE" install -r -d "$HAP"', source)


    def test_install_retries_only_unsupported_downgrade_syntax(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        block = source[source.index('echo "[INFO] installing HAP'):source.index('"$HDC" -t "$DEVICE" shell power-shell wakeup')]
        for response, expected_calls, succeeds in [
            ("install bundle successfully", 1, True),
            ("msg:usage: bm install <options>", 2, True),
            ("signature verification failed", 1, False),
        ]:
            with self.subTest(response=response), tempfile.TemporaryDirectory() as directory:
                setup = '''set -euo pipefail
HDC=mock_hdc
DEVICE=test-device
HAP=test.hap
INSTALL_LOG=install.log
mock_hdc() {
  echo call >> calls
  if [[ "$*" == *" -d "* ]]; then
    echo "$RESPONSE"
  else
    echo 'install bundle successfully'
  fi
}
'''
                result = subprocess.run(["bash", "-c", setup + block], cwd=directory,
                                        env={"RESPONSE": response}, capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, succeeds, result.stderr)
                self.assertEqual(len((Path(directory) / "calls").read_text().splitlines()), expected_calls)


class PublishMindirTest(MindirFixture):
    def setUp(self):
        super().setUp()
        self.workspace = self.repo / "isolated workspace"
        self.isolated = self.workspace / "repo" / gate.GENERATED_DIR
        self.isolated.mkdir(parents=True)
        self.generated.mkdir(parents=True)
        (self.generated / gate.MODEL_FILE).write_bytes(b"previous-target")
        (self.generated / gate.PROVENANCE_FILE).write_bytes(b"previous-sidecar")
        self.hap = self.write_archive()
        # Execute the real verifier in the child process with test-only source pins.
        verifier = self.repo / "asr/tools/verify_community_encoder_mindir.py"
        verifier.parent.mkdir(parents=True)
        source_sha = self.record["source"]["sha256"]
        verifier.write_text(
            "import sys\n"
            f"sys.path.insert(0, {str(gate.ROOT)!r})\n"
            "from asr.tools import verify_community_encoder_mindir as gate\n"
            f"gate.converter.EXPECTED_SOURCE_SHA256 = {source_sha!r}\n"
            f"gate.converter.EXPECTED_SOURCE_BYTES = {self.source.stat().st_size}\n"
            "raise SystemExit(gate.main())\n"
        )

    def publish(self, succeeds=True):
        import shlex
        source = SCRIPT.read_text(encoding="utf-8")
        block = source[source.index("publish_community_mindir() {"):source.index("prepare_build_workspace() {")]
        setup = "set -euo pipefail\n" + "\n".join(
            f"{name}={shlex.quote(str(value))}" for name, value in {
                "BUILD_WORKSPACE": self.workspace, "REPO_ROOT": self.repo,
                "BUILD_HAP": self.hap, "LICENSE_PYTHON": sys.executable,
            }.items()) + "\n"
        result = subprocess.run(["bash", "-c", setup + block + "publish_community_mindir\n"],
                                capture_output=True, text=True)
        self.assertEqual(succeeds, result.returncode == 0, result.stderr)
        return result

    def test_verified_isolated_rawfile_is_published_before_identity_without_sidecar(self):
        (self.isolated / gate.MODEL_FILE).write_bytes(self.output.read_bytes())
        self.publish()
        self.assertEqual(self.output.read_bytes(), (self.generated / gate.MODEL_FILE).read_bytes())
        self.assertFalse((self.generated / gate.PROVENANCE_FILE).exists())
        gate.verify_assets(self.repo)

    def test_cpu_build_removes_both_stale_generated_model_and_sidecar(self):
        self.output.unlink()
        self.provenance.unlink()
        self.hap = self.write_archive(entries=[])
        self.publish()
        self.assertFalse((self.generated / gate.MODEL_FILE).exists())
        self.assertFalse((self.generated / gate.PROVENANCE_FILE).exists())

    def test_corrupt_isolated_model_fails_without_overwriting_previous_target(self):
        (self.isolated / gate.MODEL_FILE).write_bytes(self.output.read_bytes()[:-1] + b"!")
        result = self.publish(succeeds=False)
        self.assertIn("stale generated", result.stderr)
        self.assertEqual(b"previous-target", (self.generated / gate.MODEL_FILE).read_bytes())


if __name__ == "__main__":
    unittest.main()
