from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


SCRIPT = Path(__file__).with_name("build_install_smoke.sh")


class BuildInstallSmokeTest(unittest.TestCase):
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
            '"$sherpa_source/harmony-os/SherpaOnnxHar/sherpa_onnx/src/main/cpp/libs/"'
        )
        patch = isolated_build.index('AMPHION_SHERPA_ROOT="$sherpa_destination"')
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


if __name__ == "__main__":
    unittest.main()
