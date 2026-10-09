"""Small, standard-library fixtures for the optional Harmony MindIR payload gate."""

import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile

from asr.tools import verify_community_encoder_mindir as gate


class MindirFixture(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="community mindir ")
        self.addCleanup(directory.cleanup)
        self.repo = Path(directory.name)
        self.shared = self.repo / gate.SHARED_DIR
        self.shared.mkdir(parents=True)
        self.source = self.shared / gate.SOURCE_FILE
        self.output = self.shared / gate.MODEL_FILE
        self.provenance = self.shared / gate.PROVENANCE_FILE
        self.generated = self.repo / gate.GENERATED_DIR
        self.source.write_bytes(b"explicit test-only FP32 source")
        self.output.write_bytes(b"\x10\x00\x00\x00MSL2explicit-test-only-model")
        source = gate.converter.file_identity(self.source)
        pins = mock.patch.multiple(gate.converter, EXPECTED_SOURCE_SHA256=source["sha256"],
                                   EXPECTED_SOURCE_BYTES=source["sizeBytes"])
        pins.start()
        self.addCleanup(pins.stop)

        def execution(tool, flags=(), files=()):
            executable = "/test-only/package/" + gate.converter.CONVERTER if tool == "converter_lite" else "/test-only/" + tool
            return {"argv": [executable, *flags, *files], "returnCode": 0,
                    "stdout": "AvgRunTime: test-only", "stderr": ""}

        signature = gate.converter.EXPECTED_SIGNATURE
        self.record = {
            "schemaVersion": 1, "kind": "community-encoder-mindir", "status": "VERIFIED",
            "source": {**source, "format": "ONNX", "signature": signature,
                       "opsets": [{"domain": "", "version": 17}], "operatorCounts": {"Conv": 36},
                       "onnxVersion": "test-only"},
            "output": {**gate.converter.file_identity(self.output), "format": "MINDIR_LITE", "signature": signature},
            "package": {"sha256": gate.converter.EXPECTED_PACKAGE_SHA256, "version": "2.7.0",
                        "sizeBytes": gate.converter.EXPECTED_PACKAGE_BYTES, "platform": "linux-x86_64"},
            "converter": {**gate.converter.EXPECTED_COMPONENTS[gate.converter.CONVERTER], "version": "2.7.0"},
            "conversion": {
                "format": "MINDIR_LITE", "flags": gate.converter.CONVERSION_FLAGS,
                "precisionScope": gate.converter.PRECISION_SCOPE,
                "environment": {"PATH": "/usr/bin:/bin", "HOME": "/test-only", "TMPDIR": "/test-only",
                                "LANG": "C", "LC_ALL": "C",
                                "LD_LIBRARY_PATH": "/test-only/package/tools/converter/lib:/test-only/package/runtime/lib"},
                "helpProbe": execution("converter_lite", ["--help"]),
                "execution": execution("converter_lite", gate.converter.CONVERSION_FLAGS,
                                       [f"--modelFile=/test-only/{self.source.name}",
                                        f"--outputFile=/test-only/{self.output.stem}"]),
            },
            "validation": {
                "scope": gate.converter.VALIDATION_SCOPE,
                "schema": {
                    "status": "PASS", "method": "package-schema VerifyMetaGraphBuffer",
                    "model": {"identifier": "MSL2", "version": "2.7.0", "nodeCount": 1, "tensorCount": 2,
                              "storedFloat16TensorCount": 1, "externalDataTensorCount": 0, **signature},
                    "helperSourceSha256": hashlib.sha256(gate.converter.SCHEMA_VERIFIER_CPP.encode()).hexdigest(),
                    "schema": gate.converter.EXPECTED_COMPONENTS[gate.converter.SCHEMA],
                    "compile": execution("c++"), "execution": execution("verify_mindir"),
                },
                "benchmark": {
                    "status": "PASS", "device": "CPU", "testInput": gate.converter.synthetic_input_record(),
                    "executable": gate.converter.EXPECTED_COMPONENTS[gate.converter.BENCHMARK],
                    "helpProbe": execution("benchmark", ["--help"]),
                    "execution": execution("benchmark", gate.converter.BENCHMARK_FLAGS,
                                           [f"--modelFile=/test-only/{self.output.name}",
                                            "--inDataFile=/test-only/synthetic-zero-fbank.f32"]),
                },
            },
            "host": {"system": "Linux", "machine": "x86_64"},
            "tool": gate.converter.file_identity(Path(gate.converter.__file__).resolve()),
        }
        schema = self.record["validation"]["schema"]
        schema["execution"]["stdout"] = json.dumps(schema["model"])
        self.write_provenance()

    def write_provenance(self):
        self.provenance.write_text(json.dumps(self.record), encoding="utf-8")

    def sync_generated(self):
        self.generated.mkdir(parents=True, exist_ok=True)
        (self.generated / gate.MODEL_FILE).write_bytes(self.output.read_bytes())

    def write_archive(self, kind="zip", entries=None):
        path = self.repo / ("test.hap" if kind == "zip" else "test.har")
        if entries is None:
            member = gate.HAP_MEMBER if kind == "zip" else "package/src/main/" + gate.HAP_MEMBER
            entries = [(member, self.output.read_bytes())]
        if kind == "zip":
            with zipfile.ZipFile(path, "w") as archive:
                for member, data in entries:
                    archive.writestr(member, data)
        else:
            with tarfile.open(path, "w:gz") as archive:
                for member, data in entries:
                    info = tarfile.TarInfo(member)
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
        return path


class MindirPayloadTest(MindirFixture):
    def test_cpu_without_optional_pair_is_allowed_but_required_fails(self):
        self.output.unlink()
        self.provenance.unlink()
        self.assertIsNone(gate.verify_assets(self.repo))
        with self.assertRaisesRegex(gate.VerificationError, "required.*missing"):
            gate.verify_assets(self.repo, required=True)

    def test_source_only_does_not_require_generated_resource(self):
        metadata = gate.verify_assets(self.repo, source_only=True, required=True)
        self.assertEqual(self.record["output"]["sha256"], metadata["sha256"])
        self.assertEqual(self.record["source"]["sha256"], metadata["source_sha256"])
        self.assertEqual(gate.file_identity(self.provenance)["sha256"], metadata["provenance_sha256"])
        with self.assertRaisesRegex(gate.VerificationError, "missing regular MindIR input"):
            gate.verify_assets(self.repo)

    def test_reuses_converter_audit_without_running_linux_or_onnx(self):
        with mock.patch.object(gate.converter, "verify_provenance", wraps=gate.converter.verify_provenance) as verifier:
            gate.verify_assets(self.repo, source_only=True)
        verifier.assert_called_once_with(self.output, self.source)

    def test_orphan_sidecar_and_missing_sidecar_fail(self):
        self.output.unlink()
        with self.assertRaisesRegex(gate.VerificationError, "orphan"):
            gate.verify_assets(self.repo, source_only=True)
        self.output.write_bytes(b"\x10\x00\x00\x00MSL2missing-proof")
        self.provenance.unlink()
        with self.assertRaisesRegex(gate.VerificationError, "invalid MindIR source/provenance"):
            gate.verify_assets(self.repo, source_only=True)

    def test_bad_json_flags_source_signature_and_scope_fail(self):
        self.provenance.write_text("not-json", encoding="utf-8")
        with self.assertRaises(gate.VerificationError):
            gate.verify_assets(self.repo, source_only=True)
        original = json.dumps(self.record)
        for section, field, value in [("conversion", "flags", ["--fp16=off"]),
                                      ("source", "file", "community-wespeaker-encoder.int8.onnx"),
                                      ("output", "signature", {"inputs": [], "outputs": []}),
                                      ("validation", "scope", "real-audio accuracy accepted")]:
            with self.subTest(field=field):
                self.record = json.loads(original)
                self.record[section][field] = value
                self.write_provenance()
                with self.assertRaises(gate.VerificationError):
                    gate.verify_assets(self.repo, source_only=True)

    def test_changed_source_and_corrupted_output_fail(self):
        source_bytes = self.source.read_bytes()
        self.source.write_bytes(b"changed" + source_bytes[7:])
        with self.assertRaisesRegex(gate.VerificationError, "FP32 source identity mismatch"):
            gate.verify_assets(self.repo, source_only=True)
        self.source.write_bytes(source_bytes)
        self.output.write_bytes(self.output.read_bytes()[:-1] + b"!")
        with self.assertRaisesRegex(gate.VerificationError, "output hash, bytes"):
            gate.verify_assets(self.repo, source_only=True)

    def test_full_check_rejects_stale_generated_resource_and_packaged_sidecar(self):
        self.sync_generated()
        gate.verify_assets(self.repo)
        target = self.generated / gate.MODEL_FILE
        target.write_bytes(target.read_bytes()[:-1] + b"!")
        with self.assertRaisesRegex(gate.VerificationError, "stale generated"):
            gate.verify_assets(self.repo)
        self.sync_generated()
        (self.generated / gate.PROVENANCE_FILE).write_bytes(self.provenance.read_bytes())
        with self.assertRaisesRegex(gate.VerificationError, "must not enter generated"):
            gate.verify_assets(self.repo)

    def test_cpu_full_check_rejects_stale_target(self):
        self.sync_generated()
        self.output.unlink()
        self.provenance.unlink()
        with self.assertRaisesRegex(gate.VerificationError, "stale generated"):
            gate.verify_assets(self.repo)
        self.assertIsNone(gate.verify_assets(self.repo, source_only=True))

    def test_zip_hap_and_tar_har_bytes_match_verified_shared_and_generated(self):
        self.sync_generated()
        hap, har = self.write_archive(), self.write_archive("tar")
        metadata = gate.verify_assets(self.repo, archives=[hap, har], required=True)
        self.assertEqual(self.record["output"]["sizeBytes"], metadata["size_bytes"])

    def test_zip_and_tar_corruption_missing_member_and_sidecar_fail(self):
        for kind in ["zip", "tar"]:
            member = gate.HAP_MEMBER if kind == "zip" else "package/src/main/" + gate.HAP_MEMBER
            cases = [([(member, self.output.read_bytes()[:-1] + b"!")], "archive SHA-256/bytes mismatch"),
                     ([], "missing MindIR archive"),
                     ([(member, self.output.read_bytes()), (member + ".provenance.json", b"{}")] , "must not be packaged"),
                     ([("wrong/" + gate.MODEL_FILE, self.output.read_bytes())], "unexpected MindIR archive path")]
            for entries, error in cases:
                with self.subTest(kind=kind, error=error):
                    archive = self.write_archive(kind, entries)
                    with self.assertRaisesRegex(gate.VerificationError, error):
                        gate.verify_assets(self.repo, source_only=True, archives=[archive])

    def test_archive_model_cannot_replace_missing_sources(self):
        archive = self.write_archive()
        self.output.unlink()
        self.provenance.unlink()
        with self.assertRaisesRegex(gate.VerificationError, "no verified shared source/provenance"):
            gate.verify_assets(self.repo, source_only=True, archives=[archive])

    def test_duplicate_tar_model_and_symlink_are_rejected(self):
        member = "package/src/main/" + gate.HAP_MEMBER
        data = self.output.read_bytes()
        archive = self.write_archive("tar", [(member, data), (member, data)])
        with self.assertRaisesRegex(gate.VerificationError, "duplicate"):
            gate.verify_assets(self.repo, source_only=True, archives=[archive])
        with tarfile.open(archive, "w:gz") as package:
            link = tarfile.TarInfo(member)
            link.type = tarfile.SYMTYPE
            link.linkname = "outside/model.ms"
            package.addfile(link)
        with self.assertRaisesRegex(gate.VerificationError, "not a regular file"):
            gate.verify_assets(self.repo, source_only=True, archives=[archive])

    def test_cli_optional_cpu_and_required_npu_are_distinct(self):
        self.output.unlink()
        self.provenance.unlink()
        command = [sys.executable, str(Path(gate.__file__).resolve()), "--repo-root", str(self.repo), "--source-only"]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("CPU", result.stdout)
        result = subprocess.run([*command, "--required"], capture_output=True, text=True)
        self.assertEqual(1, result.returncode)
        self.assertIn("required Community MindIR", result.stderr)


if __name__ == "__main__":
    unittest.main()
