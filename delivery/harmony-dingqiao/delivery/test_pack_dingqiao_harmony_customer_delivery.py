from __future__ import annotations

import re
from pathlib import Path
import subprocess
import unittest


SCRIPT = Path(__file__).with_name("pack_dingqiao_harmony_customer_delivery.sh")


class PackDingqiaoHarmonyCustomerDeliveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_shell_syntax_and_help_expose_sdk_only(self) -> None:
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
        self.assertIn('VERSION="${AMPHION_RUNTIME_VERSION:-0.2.0}"', self.source)
        result = subprocess.run(
            ["bash", str(SCRIPT), "--help"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        self.assertIn("--sdk-only", result.stdout)
        self.assertIn("no demo HAP", result.stdout)
        self.assertIn('FINAL_OUT_ROOT="$PWD/$FINAL_OUT_ROOT"', self.source)

        conflict = subprocess.run(
            ["bash", str(SCRIPT), "--asr-only", "--sdk-only"],
            text=True,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(2, conflict.returncode)
        self.assertIn("mutually exclusive", conflict.stderr)

    def test_sdk_only_guards_every_demo_hap_operation(self) -> None:
        match = re.search(
            r'if \[\[ "\$SDK_ONLY" != true \]\]; then\n'
            r'  HAP_SRC=""(?P<body>.*?)\nfi\n\n'
            r'if \[\[ "\$ASR_ONLY"',
            self.source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match, "demo HAP work must be inside the SDK-only guard")
        body = match.group("body")
        self.assertIn("verify_demo_inputs.sh", body)
        self.assertIn('copy_required "$HAP_SRC" "$OUT_ROOT/demo/dingqiao-demo.hap"', body)

        source_without_guarded_body = self.source[: match.start()] + self.source[match.end() :]
        self.assertNotIn("HAP_SRC", source_without_guarded_body)
        self.assertNotIn("verify_demo_inputs.sh", source_without_guarded_body)

    def test_sdk_only_provenance_and_ascii_api_name_exclude_hap(self) -> None:
        self.assertIn('"sdk_only": sdk_only', self.source)
        self.assertIn(
            'if not sdk_only:\n    artifacts.append(fingerprint("demo/dingqiao-demo.hap"))',
            self.source,
        )
        self.assertIn('"$OUT_ROOT/docs/ASR_SDK_API_HARMONY.md"', self.source)
        self.assertRegex(
            self.source,
            r'build_identity = None\nif not sdk_only:\n'
            r'    build_identity = json\.loads\(build_identity_path\.read_text',
        )
        self.assertIn(
            'if [[ "$SDK_ONLY" != true ]]; then\n'
            '  python3 "$SCRIPT_DIR/harmony_build_identity.py" --verify "$BUILD_IDENTITY"',
            self.source,
        )
        self.assertIn(
            'mkdir -p "$OUT_ROOT/har" "$OUT_ROOT/docs"\n'
            'if [[ "$SDK_ONLY" != true ]]; then\n  mkdir -p "$OUT_ROOT/demo"',
            self.source,
        )

    def test_customer_docs_include_troubleshooting_and_onnx_license(self) -> None:
        self.assertIn(
            '"$REPO_ROOT/delivery/harmony-dingqiao/docs/TROUBLESHOOTING.md"',
            self.source,
        )
        self.assertIn('"$OUT_ROOT/docs/third-party/ONNX-Runtime-MIT.txt"', self.source)
        self.assertIn(
            '"$REPO_ROOT/tts/harmony/sdk/src/main/cpp/third_party/onnxruntime/LICENSE"',
            self.source,
        )
        self.assertRegex(
            self.source,
            r'if \[\[ "\$SDK_ONLY" != true \]\]; then\n'
            r'  cp -v .*SDK_LIFECYCLE_PERFORMANCE_20260713\.md',
        )
        self.assertIn("SDK_LIFECYCLE_PERFORMANCE_SUMMARY_20260713.md", self.source)
        self.assertRegex(
            self.source,
            r'if \[\[ "\$SDK_ONLY" != true \]\]; then\n'
            r'  cp -v .*MODEL_LOAD_PERFORMANCE\.md',
        )
        self.assertIn('"$OUT_ROOT/README.md"', self.source)


if __name__ == "__main__":
    unittest.main()
