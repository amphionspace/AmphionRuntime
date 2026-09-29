"""Delivery gate failures must remain failures, including a wrong compiler."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "harmony_api23", ROOT / "delivery/harmony-dingqiao/delivery/verify_harmony_api23_compiler.py"
)
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class HarmonyApi23CompilerTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name)
        self.har = self.work / "sdk.har"
        self.compiler = self.work / "es2abc"
        self.compiler.write_bytes(b"test compiler")
        self.report = self.work / "report.json"

    def write_har(self, sources):
        with tarfile.open(self.har, "w:gz") as archive:
            for name, text in sources.items():
                data = text.encode()
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))

    @staticmethod
    def old_compiler(args, **kwargs):
        source = Path(args[-1]).read_text()
        if "< unique.length" in source:
            return subprocess.CompletedProcess(args, 1, "", "SyntaxError: Type expected")
        Path(args[args.index("--output") + 1]).write_bytes(b"abc")
        return subprocess.CompletedProcess(args, 0, "", "")

    def test_checks_every_implementation_and_records_har_and_compiler_identity(self):
        self.write_har({"package/a.ts": "export const a = 1;", "package/b.ts": "export const b = 2;",
                        "package/types.d.ts": "declare const a: number;"})
        with patch.object(GATE.subprocess, "run", side_effect=self.old_compiler) as runner:
            result = GATE.verify(self.har, self.compiler, self.report)
        self.assertEqual("PASS", result["status"])
        self.assertEqual({"package/a.ts", "package/b.ts"}, {f["path"] for f in result["files"]})
        self.assertEqual(GATE.sha256(self.har), result["har_sha256"])
        self.assertEqual(GATE.sha256(self.compiler), result["compiler_sha256"])
        self.assertEqual(4, runner.call_count)

    def test_original_customer_syntax_fails_even_after_another_file_passes(self):
        self.write_har({"package/good.ts": "export const a = 1;",
                        "package/identity.ts": "const unique=[0,1]; for(let i=1;i < unique.length;i++) {}"})
        with patch.object(GATE.subprocess, "run", side_effect=self.old_compiler):
            result = GATE.verify(self.har, self.compiler, self.report)
        self.assertEqual("FAIL", result["status"])
        self.assertEqual([0, 1], [f["returncode"] for f in result["files"]])
        self.assertIn("Type expected", self.report.read_text())

    def test_newer_compiler_cannot_silently_pass_the_old_compiler_gate(self):
        self.write_har({"package/a.ts": "export const a = 1;"})
        def new_compiler(args, **kwargs):
            Path(args[args.index("--output") + 1]).write_bytes(b"abc")
            return subprocess.CompletedProcess(args, 0, "", "")
        with patch.object(GATE.subprocess, "run", side_effect=new_compiler):
            result = GATE.verify(self.har, self.compiler, self.report)
        self.assertEqual("FAIL", result["status"])
        self.assertEqual([], result["files"])

    def test_missing_compiler_is_a_recorded_failure_not_a_skip(self):
        self.write_har({"package/a.ts": "export const a = 1;"})
        result = GATE.verify(self.har, self.work / "missing", self.report)
        self.assertEqual("FAIL", result["status"])
        self.assertEqual("FileNotFoundError", result["error"])
        self.assertEqual("FAIL", json.loads(self.report.read_text())["status"])

    def test_empty_har_and_missing_bytecode_fail(self):
        def missing_bytecode(args, **kwargs):
            if Path(args[-1]).name.startswith("source-"):
                return subprocess.CompletedProcess(args, 0, "", "")
            return self.old_compiler(args, **kwargs)
        for sources, compiler in (({}, self.old_compiler),
                                  ({"package/a.ts": "export const a = 1;"},
                                   missing_bytecode)):
            with self.subTest(sources=sources):
                self.write_har(sources)
                output = self.work / f"{len(sources)}.json"
                with patch.object(GATE.subprocess, "run", side_effect=compiler):
                    self.assertEqual("FAIL", GATE.verify(self.har, self.compiler, output)["status"])

    def test_never_overwrites_previous_evidence(self):
        self.report.write_text("previous failure\n")
        with self.assertRaises(FileExistsError):
            GATE.verify(self.har, self.compiler, self.report)
        self.assertEqual("previous failure\n", self.report.read_text())

    def test_packaging_stops_before_build_access_when_compiler_is_not_configured(self):
        output = self.work / "package"
        result = subprocess.run(
            ["bash", str(ROOT / "delivery/harmony-dingqiao/delivery/pack_dingqiao_harmony_customer_delivery.sh"),
             "--sdk-only", str(output)],
            env=dict(os.environ, HARMONY_API23_ES2ABC=""), capture_output=True, text=True,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("set HARMONY_API23_ES2ABC", result.stderr)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
