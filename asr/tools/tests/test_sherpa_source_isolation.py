from pathlib import Path
import os
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[3]
CANONICAL = ROOT / "third_party/sherpa-onnx"
PREPARE = ROOT / "asr/tools/prepare_sherpa_source.sh"
APPLY = ROOT / "asr/tools/apply_sherpa_patches.sh"
ANDROID_BUILD = ROOT / "asr/tools/04_build_android_so.sh"
AGC_BUILD = ROOT / "asr/tools/03_build_agc_native.sh"
ANDROID_PACKAGE = ROOT / "asr/tools/05_package_aar_libs.sh"


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, text=True, capture_output=True
    ).stdout.strip()


class SherpaSourceIsolationTest(unittest.TestCase):
    def test_android_native_builds_redact_host_paths_before_packaging(self) -> None:
        sherpa_build = ANDROID_BUILD.read_text(encoding="utf-8")
        agc_build = AGC_BUILD.read_text(encoding="utf-8")
        package = ANDROID_PACKAGE.read_text(encoding="utf-8")

        for source in (sherpa_build, agc_build):
            self.assertIn("-ffile-prefix-map=", source)
            self.assertIn("-fmacro-prefix-map=", source)
        self.assertIn("verify_no_host_paths", package)
        self.assertIn("/Users/", package)
        self.assertIn("/home/", package)

    def test_build_entrypoints_never_reset_the_canonical_submodule(self) -> None:
        gitmodules = (ROOT / ".gitmodules").read_text(encoding="utf-8")
        self.assertNotIn("ignore = all", gitmodules)
        for relative in (
            "asr/tools/prepare_sherpa_source.sh",
            "asr/tools/apply_sherpa_patches.sh",
            "asr/tools/04_build_android_so.sh",
            "asr/tools/04_build_harmony_so.sh",
            "asr/tools/07_sync_kotlin_from_upstream.sh",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("reset --hard", source, relative)
        self.assertIn(
            'SHERPA_ROOT="$(bash "$SCRIPT_DIR/prepare_sherpa_source.sh")"',
            (ROOT / "asr/tools/04_build_android_so.sh").read_text(encoding="utf-8"),
        )
        self.assertIn(
            'SHERPA_ROOT="$(bash "$SCRIPT_DIR/prepare_sherpa_source.sh")"',
            (ROOT / "asr/tools/04_build_harmony_so.sh").read_text(encoding="utf-8"),
        )
        kotlin_sync = (
            ROOT / "asr/tools/07_sync_kotlin_from_upstream.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('SHERPA_ROOT="${AMPHION_SHERPA_ROOT:-}"', kotlin_sync)
        self.assertIn(
            'SHERPA_ROOT="$(bash "$SCRIPT_DIR/prepare_sherpa_source.sh")"',
            kotlin_sync,
        )
        prepare = PREPARE.read_text(encoding="utf-8")
        self.assertIn('PATCH_FILES=("$PATCH_DIR"/*.patch)', prepare)
        self.assertIn('if [[ ${#PATCH_FILES[@]} -eq 0 ]]', prepare)
        harmony_cmake = (
            ROOT / "asr/harmony/sdk/src/main/cpp/CMakeLists.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("third_party/.derived/sherpa-onnx", harmony_cmake)
        self.assertNotIn("third_party/sherpa-onnx", harmony_cmake)

    @unittest.skipUnless((CANONICAL / ".git").exists(), "sherpa submodule is not initialized")
    def test_prepare_is_idempotent_and_preserves_canonical_checkout(self) -> None:
        head_before = git("rev-parse", "HEAD", cwd=CANONICAL)
        status_before = git("status", "--porcelain", cwd=CANONICAL)

        first = subprocess.run(
            ["bash", str(PREPARE)], cwd=ROOT, check=True, text=True, capture_output=True
        ).stdout.strip()
        second = subprocess.run(
            ["bash", str(PREPARE)], cwd=ROOT, check=True, text=True, capture_output=True
        ).stdout.strip()

        derived = Path(first).resolve()
        self.assertEqual(first, second)
        self.assertNotEqual(CANONICAL.resolve(), derived)
        self.assertTrue((derived / ".amphion-source-identity").is_file())
        self.assertTrue((derived / ".amphion-patches-applied").is_file())
        self.assertEqual(head_before, git("rev-parse", "HEAD", cwd=CANONICAL))
        self.assertEqual(status_before, git("status", "--porcelain", cwd=CANONICAL))
        self.assertEqual("", git("status", "--porcelain", "--untracked-files=no", cwd=derived))

    @unittest.skipUnless((CANONICAL / ".git").exists(), "sherpa submodule is not initialized")
    def test_low_level_patch_command_refuses_canonical_submodule(self) -> None:
        result = subprocess.run(
            ["bash", str(APPLY)],
            cwd=ROOT,
            env={**os.environ, "AMPHION_SHERPA_ROOT": str(CANONICAL)},
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("refusing to patch the canonical", result.stderr)


if __name__ == "__main__":
    unittest.main()
