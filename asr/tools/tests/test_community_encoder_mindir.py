"""Offline contract tests with fake ONNX/package/converter/benchmark/compiler.

These fixtures exercise fail-closed orchestration, not Lite implementation or
model accuracy. Real package-schema inspection is a separate host-only check.
"""

from contextlib import ExitStack
import copy
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from asr.tools import convert_community_encoder as tool


FAKE_VERIFIER = r'''
import json
from pathlib import Path
import sys
data = Path(sys.argv[1]).read_bytes()
if data[4:8] != b"MSL2":
    sys.exit("VerifyMetaGraphBuffer failed: expected MSL2")
print(json.dumps(json.loads(data[8:])))
'''


def fake_value(spec):
    shape = SimpleNamespace(dim=[SimpleNamespace(dim_value=n, HasField=lambda _: True)
                                 for n in spec["shape"]])
    return SimpleNamespace(name=spec["name"], type=SimpleNamespace(
        tensor_type=SimpleNamespace(elem_type=1, shape=shape, HasField=lambda _: True)))


class CommunityEncoderMindirTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="community-mindir-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.source = self.directory / tool.DEFAULT_SOURCE.name
        self.source.write_bytes(b"fake ONNX bytes, never used for inference")
        self.output = self.directory / "community-wespeaker-encoder.fp16.ms"
        self.cache = self.directory / "cache"
        self.root = self.directory / tool.PACKAGE_DIRECTORY
        self.package = self.directory / (tool.PACKAGE_DIRECTORY + ".tar.gz")
        self.cxx = self.directory / "fake-cxx"
        self.model = SimpleNamespace(
            graph=SimpleNamespace(input=[fake_value(v) for v in tool.EXPECTED_SIGNATURE["inputs"]],
                                  output=[fake_value(v) for v in tool.EXPECTED_SIGNATURE["outputs"]],
                                  initializer=[], node=[SimpleNamespace(op_type="Conv") for _ in range(36)]),
            opset_import=[SimpleNamespace(domain="", version=17)])
        self.onnx = SimpleNamespace(
            __version__="1.15.0", load=mock.Mock(side_effect=lambda *a, **k: self.model),
            checker=SimpleNamespace(check_model=mock.Mock()),
            TensorProto=SimpleNamespace(EXTERNAL=1, DataType=SimpleNamespace(
                Name=lambda value: "FLOAT" if value == 1 else "FLOAT16")))
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.dict(sys.modules, {"onnx": self.onnx}))
        self.stack.enter_context(mock.patch.object(tool, "EXPECTED_SOURCE_SHA256", tool.file_identity(self.source)["sha256"]))
        self.stack.enter_context(mock.patch.object(tool, "EXPECTED_SOURCE_BYTES", self.source.stat().st_size))
        self.stack.enter_context(mock.patch.object(tool.platform, "system", return_value="Linux"))
        self.stack.enter_context(mock.patch.object(tool.platform, "machine", return_value="x86_64"))
        self.stack.enter_context(mock.patch.object(tool, "EXPECTED_PACKAGE_SHA256", ""))
        self.stack.enter_context(mock.patch.object(tool, "EXPECTED_PACKAGE_BYTES", 0))
        self.stack.enter_context(mock.patch.object(tool, "EXPECTED_COMPONENTS", {}))
        self.make_package()
        self.write_executable(self.cxx, """
import os
from pathlib import Path
import sys
assert 'VerifyMetaGraphBuffer' in Path(sys.argv[sys.argv.index('-o') - 1]).read_text()
output = Path(sys.argv[sys.argv.index('-o') + 1])
output.write_text(%r)
os.chmod(output, 0o755)
""" % (f"#!{sys.executable}\n" + FAKE_VERIFIER))

    def write_executable(self, path, code):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!{sys.executable}\n" + code, encoding="utf-8")
        path.chmod(0o755)

    def make_package(self, mode="ok", signature=None):
        signature = copy.deepcopy(signature or tool.EXPECTED_SIGNATURE)
        signature.update(identifier="MSL2", version="MindSpore Lite 2.7.0", nodeCount=36,
                         tensorCount=100, storedFloat16TensorCount=36, externalDataTensorCount=0)
        if mode == "version":
            signature["version"] = "MindSpore Lite 2.6.0"
        if mode == "dtype":
            signature["inputs"][0]["dtype"] = "FLOAT16"
        if mode == "shape":
            signature["outputs"][0]["shape"] = [1, 125, 2560]
        if mode == "no-fp16":
            signature["storedFloat16TensorCount"] = 0
        converter_code = """
import json
import os
from pathlib import Path
import sys
flags = %r
mode = %r
if '--help' in sys.argv:
    print(' '.join(flags + ['--modelFile', '--outputFile']) if mode != 'unsupported' else '--fmk')
    sys.exit(0)
assert sys.argv[1:1 + len(flags)] == flags
assert not any(k.startswith('MS_') or k in ('LD_PRELOAD', 'MSLITE_API_TYPE', 'CONVERTER_FLAGS') for k in os.environ)
assert '/external/lib' not in os.environ['LD_LIBRARY_PATH']
output = Path(next(a.split('=', 1)[1] for a in sys.argv if a.startswith('--outputFile=')) + '.ms')
if mode == 'missing':
    sys.exit(0)
data = b'\\x08\\x00\\x00\\x00MSL2' + json.dumps(%r).encode()
if mode == 'format':
    data = b'MINDIR protobuf, not a Lite FlatBuffer'
output.write_bytes(data)
if mode == 'fail':
    sys.exit(7)
print('CONVERT RESULT SUCCESS')
""" % (tool.CONVERSION_FLAGS, mode, signature)
        self.write_executable(self.root / tool.CONVERTER, converter_code)
        self.write_executable(self.root / tool.BENCHMARK, """
from pathlib import Path
import sys
flags = %r
mode = %r
if '--help' in sys.argv:
    print(' '.join(flags + ['--modelFile', '--inDataFile']))
    sys.exit(0)
assert sys.argv[1:1 + len(flags)] == flags
data = Path(next(a.split('=', 1)[1] for a in sys.argv if a.startswith('--inDataFile='))).read_bytes()
assert data == bytes(998 * 80 * 4)
if mode == 'benchmark-fail':
    sys.exit(8)
print('Model = fake, AvgRunTime = 0.01 ms' if mode != 'benchmark-empty' else 'help only')
""" % (tool.BENCHMARK_FLAGS, mode))
        files = {tool.SCHEMA: "// fake schema header\n",
                 "tools/converter/include/api/data_type.h": "// fake dtype header\n",
                 "tools/converter/lib/libfake-converter.so": "fake converter library\n",
                 "runtime/lib/libmindspore-lite.so": "fake runtime library\n",
                 "runtime/third_party/glog/libmindspore_glog.so.0": "fake glog library\n",
                 "runtime/third_party/libjpeg-turbo/lib/libjpeg.so.62": "fake jpeg library\n"}
        for relative, text in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        with tarfile.open(self.package, "w:gz") as archive:
            archive.add(self.root, arcname=tool.PACKAGE_DIRECTORY)
        tool.EXPECTED_PACKAGE_SHA256 = tool.file_identity(self.package)["sha256"]
        tool.EXPECTED_PACKAGE_BYTES = self.package.stat().st_size
        tool.EXPECTED_COMPONENTS = {p: tool.file_identity(self.root / p)
                                    for p in (tool.CONVERTER, tool.BENCHMARK, tool.SCHEMA)}

    def convert(self, root=None):
        return tool.convert(self.source, self.package, root, self.output, self.cache, str(self.cxx))

    def assert_unpublished(self):
        self.assertFalse(self.output.exists())
        self.assertFalse(tool.provenance_path(self.output).exists())

    def test_success_is_bound_to_recipe_signatures_bytes_and_input(self):
        with mock.patch.dict(os.environ, {"LD_LIBRARY_PATH": "/external/lib", "LD_PRELOAD": "/external/preload.so",
                                         "CONVERTER_FLAGS": "--saveType=MINDIR", "MSLITE_API_TYPE": "C"}):
            record = self.convert(self.root)
        self.assertEqual(record, tool.verify_provenance(self.output, self.source))
        self.assertEqual(record["output"]["sha256"], tool.file_identity(self.output)["sha256"])
        self.assertEqual(record["output"]["signature"], tool.EXPECTED_SIGNATURE)
        self.assertEqual(record["conversion"]["flags"], tool.CONVERSION_FLAGS)
        self.assertEqual(record["validation"]["benchmark"]["testInput"], tool.synthetic_input_record())
        env = record["conversion"]["environment"]
        self.assertIn(str(self.root / "runtime/third_party/glog"), env["LD_LIBRARY_PATH"])
        self.assertNotIn("LD_PRELOAD", env)
        self.assertIn("does not prove", record["conversion"]["precisionScope"])
        self.assertFalse(list(self.directory.glob(".community-encoder-*")))

    def test_package_only_extracts_into_cache(self):
        self.convert()
        self.assertEqual(tool.verify_provenance(self.output, self.source)["package"]["sha256"],
                         tool.file_identity(self.package)["sha256"])
        self.assertFalse(list(self.cache.glob("package-*")))

    def test_source_hash_and_size_are_checked_before_onnx_or_converter(self):
        self.source.write_bytes(b"wrong source")
        with self.assertRaisesRegex(tool.ConversionError, "source identity mismatch"):
            self.convert()
        self.onnx.load.assert_not_called()
        self.assert_unpublished()

    def test_source_signature_name_shape_dtype_and_opset_rejected(self):
        for mutation in ("name", "shape", "dtype", "opset", "operators", "dynamic"):
            with self.subTest(mutation=mutation):
                original = copy.deepcopy(self.model)
                tensor = self.model.graph.input[0]
                if mutation == "name":
                    tensor.name = "not-fbank"
                elif mutation == "shape":
                    tensor.type.tensor_type.shape.dim[1].dim_value = 1000
                elif mutation == "dtype":
                    tensor.type.tensor_type.elem_type = 10
                elif mutation == "opset":
                    self.model.opset_import[0].version = 16
                elif mutation == "operators":
                    self.model.graph.node.append(SimpleNamespace(op_type="If"))
                else:
                    tensor.type.tensor_type.shape.dim[1].HasField = lambda _: False
                with self.assertRaises(tool.ConversionError):
                    tool.inspect_source(self.source)
                self.model = original
        self.assert_unpublished()

    def test_missing_onnx_has_actionable_existing_venv_hint(self):
        with mock.patch.dict(sys.modules, {"onnx": None}):
            with self.assertRaisesRegex(tool.ConversionError, "venv-harmony-ort-1.16.3"):
                tool.inspect_source(self.source)

    def test_package_hash_and_root_member_mismatch_rejected(self):
        with mock.patch.object(tool, "EXPECTED_PACKAGE_SHA256", "0" * 64):
            with self.assertRaisesRegex(tool.ConversionError, "package SHA-256 mismatch"):
                self.convert(self.root)
        (self.root / tool.CONVERTER).write_text("modified executable")
        with self.assertRaisesRegex(tool.ConversionError, "differs from package"):
            self.convert(self.root)
        self.assert_unpublished()

    def test_extra_package_library_cannot_change_loader_behavior(self):
        (self.root / "tools/converter/lib/libinjected.so").write_bytes(b"injected")
        with self.assertRaisesRegex(tool.ConversionError, "inventory"):
            self.convert(self.root)
        self.assert_unpublished()

    def test_failure_wrong_format_version_signature_missing_output_never_publish(self):
        for mode in ("fail", "missing", "format", "version", "dtype", "shape", "no-fp16",
                     "unsupported", "benchmark-fail", "benchmark-empty"):
            with self.subTest(mode=mode):
                self.make_package(mode)
                with self.assertRaises(tool.ConversionError):
                    self.convert(self.root)
                self.assert_unpublished()
        failures = list(self.directory.glob(".community-encoder-*/failure.json"))
        self.assertEqual(len(failures), 10)
        self.assertTrue(all(json.loads(p.read_text())["status"] == "FAIL" for p in failures))

    def test_existing_output_or_evidence_and_dangling_link_are_preserved(self):
        for path in (self.output, tool.provenance_path(self.output)):
            path.write_bytes(b"existing evidence")
            with self.assertRaisesRegex(tool.ConversionError, "refusing to overwrite"):
                self.convert()
            self.assertEqual(path.read_bytes(), b"existing evidence")
            path.unlink()
        self.output.symlink_to(self.directory / "missing-target")
        with self.assertRaisesRegex(tool.ConversionError, "refusing to overwrite"):
            self.convert()
        self.assertTrue(self.output.is_symlink())

    def test_publish_race_rolls_back_only_own_model_without_clobbering_evidence(self):
        real_link = os.link

        def race(source, target):
            if Path(target) == tool.provenance_path(self.output):
                Path(target).write_bytes(b"concurrent evidence")
                raise FileExistsError("concurrent provenance")
            real_link(source, target)

        with mock.patch.object(tool.os, "link", side_effect=race):
            with self.assertRaisesRegex(tool.ConversionError, "without overwriting"):
                self.convert()
        self.assertFalse(self.output.exists())
        self.assertEqual(tool.provenance_path(self.output).read_bytes(), b"concurrent evidence")

    def test_provenance_tampering_is_rejected_without_rewriting(self):
        original = self.convert(self.root)
        path = tool.provenance_path(self.output)
        mutations = [
            lambda r: r["output"].update(sha256="0" * 64),
            lambda r: r["output"].update(format="MINDIR"),
            lambda r: r["converter"].update(version="2.6.0"),
            lambda r: r["converter"].update(sha256="0" * 64),
            lambda r: r["conversion"]["flags"].append("--fp16=off"),
            lambda r: r["conversion"]["execution"]["argv"].append("--saveType=MINDIR"),
            lambda r: r["validation"]["schema"]["model"].update(identifier="MSL1"),
            lambda r: r["validation"]["benchmark"]["testInput"].update(realAudio=True),
            lambda r: r["validation"]["benchmark"]["execution"].update(returnCode=7),
            lambda r: r["conversion"]["environment"].update(LD_PRELOAD="/external/preload.so"),
            lambda r: r["validation"]["schema"]["execution"].update(stdout="{}"),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                record = copy.deepcopy(original)
                mutation(record)
                text = json.dumps(record)
                path.write_text(text)
                with self.assertRaises(tool.ConversionError):
                    tool.verify_provenance(self.output, self.source)
                self.assertEqual(path.read_text(), text)
        path.write_text(json.dumps(original))
        self.output.write_bytes(self.output.read_bytes() + b"changed")
        with self.assertRaisesRegex(tool.ConversionError, "hash, bytes"):
            tool.verify_provenance(self.output, self.source)

    def test_verify_on_mac_runs_only_host_schema_verifier(self):
        self.convert(self.root)
        original = tool.run_tool
        seen = []

        def host_only(argv, *args, **kwargs):
            self.assertNotIn(Path(argv[0]).name, ("converter_lite", "benchmark"))
            seen.append(argv)
            return original(argv, *args, **kwargs)

        with mock.patch.object(tool.platform, "system", return_value="Darwin"), \
                mock.patch.object(tool, "run_tool", side_effect=host_only):
            result = tool.verify_existing(self.source, self.package, self.root, self.output,
                                          self.cache, str(self.cxx))
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["linuxBinariesExecuted"])
        self.assertEqual(len(seen), 2)

    def test_non_linux_or_arm64_fails_before_package_or_subprocess(self):
        for system, machine in (("Darwin", "arm64"), ("Linux", "aarch64")):
            with self.subTest(system=system), mock.patch.object(tool.platform, "system", return_value=system), \
                    mock.patch.object(tool.platform, "machine", return_value=machine), \
                    mock.patch.object(tool, "run_tool") as run:
                with self.assertRaisesRegex(tool.ConversionError, "Linux x86_64/amd64"):
                    self.convert()
                run.assert_not_called()
        self.assert_unpublished()

    def test_non_lite_output_suffix_is_rejected_before_execution(self):
        self.output = self.output.with_suffix(".mindir")
        with self.assertRaisesRegex(tool.ConversionError, "explicit Lite .ms"):
            self.convert()
        self.assert_unpublished()

    def test_timeout_preserves_partial_stdout_stderr(self):
        import subprocess

        error = subprocess.TimeoutExpired(["converter"], 1, output=b"partial output", stderr=b"partial error")
        with mock.patch.object(tool.subprocess, "run", side_effect=error):
            with self.assertRaisesRegex(tool.ConversionError, "timed out"):
                tool.run_tool(["converter"], self.directory, {}, "timeout", timeout=1)
        record = json.loads((self.directory / "timeout.json").read_text())
        self.assertEqual(record["status"], "TIMEOUT")
        self.assertEqual(record["stdout"], "partial output")
        self.assertEqual(record["stderr"], "partial error")

    def test_inspect_is_read_only_and_marks_execution_unverified(self):
        argv = ["convert_community_encoder.py", "--inspect", "--source", str(self.source),
                "--package", str(self.package), "--converter-root", str(self.root)]
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", argv), mock.patch.object(sys, "stdout", stdout), \
                mock.patch.object(tool, "run_tool") as run:
            self.assertEqual(tool.main(), 0)
            run.assert_not_called()
        result = json.loads(stdout.getvalue())
        self.assertIn("NOT_EXECUTED", result["conversionAndBenchmark"])
        self.assertFalse(result["linuxBinariesExecuted"])
        self.assert_unpublished()


if __name__ == "__main__":
    unittest.main()
