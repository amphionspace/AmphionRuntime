import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "asr/tools/android_native_cache.py"
SPEC = importlib.util.spec_from_file_location("android_native_cache", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AndroidNativeCacheTest(unittest.TestCase):
    def _source_root(self, root: Path) -> Path:
        for index, relative in enumerate(MODULE.SOURCE_INPUTS):
            path = root / relative
            if relative in MODULE.SOURCE_DIRECTORIES:
                path.mkdir(parents=True, exist_ok=True)
                path = path / f"fixture-{index}.txt"
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{relative}\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        return root

    def _configuration(self) -> dict[str, str]:
        return {
            "abi": "arm64-v8a",
            "android_platform": "android-24",
            "cmake_version": "3.22.1",
            "meson_version": "1.7.0",
            "ndk_version": "26.3.11579264",
            "ninja_version": "1.11.1.4",
            "onnxruntime_version": "1.24.3",
        }

    def test_fingerprint_is_stable_and_binds_every_source_and_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._source_root(Path(directory))
            configuration = self._configuration()
            original = MODULE.source_fingerprint(root, "a" * 40, configuration)

            self.assertEqual(
                original,
                MODULE.source_fingerprint(root, "a" * 40, dict(reversed(configuration.items()))),
            )

            for relative in MODULE.tracked_source_files(root):
                path = root / relative
                previous = path.read_bytes()
                path.write_bytes(previous + b"changed\n")
                self.assertNotEqual(
                    original,
                    MODULE.source_fingerprint(root, "a" * 40, configuration),
                    relative,
                )
                path.write_bytes(previous)

            self.assertNotEqual(
                original,
                MODULE.source_fingerprint(root, "b" * 40, configuration),
            )
            for key in configuration:
                changed_configuration = dict(configuration)
                changed_configuration[key] += "-changed"
                self.assertNotEqual(
                    original,
                    MODULE.source_fingerprint(root, "a" * 40, changed_configuration),
                    key,
                )

            unrelated = root / "docs/unrelated.md"
            unrelated.parent.mkdir(parents=True)
            unrelated.write_text("not a native input\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            self.assertEqual(
                original,
                MODULE.source_fingerprint(root, "a" * 40, configuration),
            )

    def test_manifest_verification_binds_fingerprint_and_artifact_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in MODULE.ARTIFACTS:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(relative.encode("utf-8"))
            manifest = root / "native-cache-manifest.json"
            MODULE.write_manifest(root, manifest, "c" * 64, self._configuration())

            MODULE.verify_manifest(root, manifest, "c" * 64, self._configuration())
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(MODULE.MANIFEST_SCHEMA, payload["schema"])
            self.assertEqual(set(MODULE.ARTIFACTS), set(payload["artifacts"]))

            with self.assertRaisesRegex(MODULE.CacheIdentityError, "fingerprint"):
                MODULE.verify_manifest(root, manifest, "d" * 64, self._configuration())

            changed_configuration = self._configuration()
            changed_configuration["ndk_version"] = "different"
            with self.assertRaisesRegex(MODULE.CacheIdentityError, "configuration"):
                MODULE.verify_manifest(root, manifest, "c" * 64, changed_configuration)

            artifact = root / MODULE.ARTIFACTS[0]
            artifact.write_bytes(b"tampered")
            with self.assertRaisesRegex(MODULE.CacheIdentityError, "SHA-256"):
                MODULE.verify_manifest(root, manifest, "c" * 64, self._configuration())

    def test_manifest_rejects_missing_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in MODULE.ARTIFACTS:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"artifact")
            manifest = root / "native-cache-manifest.json"
            MODULE.write_manifest(root, manifest, "e" * 64, self._configuration())
            (root / MODULE.ARTIFACTS[-1]).unlink()

            with self.assertRaisesRegex(MODULE.CacheIdentityError, "missing"):
                MODULE.verify_manifest(root, manifest, "e" * 64, self._configuration())

    def test_versioned_configuration_is_consumed_by_native_build_scripts(self) -> None:
        agc = (ROOT / "asr/tools/03_build_agc_native.sh").read_text(encoding="utf-8")
        sherpa = (ROOT / "asr/tools/04_build_android_so.sh").read_text(encoding="utf-8")

        self.assertIn('ANDROID_PLATFORM="${ANDROID_PLATFORM:-android-24}"', agc)
        self.assertIn("aarch64-linux-android${ANDROID_API}-clang++", agc)
        self.assertIn('NDK_VER="${NDK_VERSION:-26.3.11579264}"', sherpa)
        self.assertIn('ONNX_VER="${ONNXRT_VERSION:-1.24.3}"', sherpa)
        self.assertIn(
            'SHERPA_ONNX_ANDROID_PLATFORM="${ANDROID_PLATFORM:-android-24}"',
            sherpa,
        )


if __name__ == "__main__":
    unittest.main()
