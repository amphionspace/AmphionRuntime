from __future__ import annotations

import json
import re
from pathlib import Path
import subprocess
import unittest


SCRIPT = Path(__file__).with_name("pack_dingqiao_harmony_customer_delivery.sh")
REPO = SCRIPT.parents[3]


class PackDingqiaoHarmonyCustomerDeliveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_shell_syntax_and_help_expose_sdk_only(self) -> None:
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
        self.assertIn('VERSION="${AMPHION_RUNTIME_VERSION:-0.2.4}"', self.source)
        result = subprocess.run(
            ["bash", str(SCRIPT), "--help"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        self.assertIn("--sdk-only", result.stdout)
        self.assertIn("no demo HAP", result.stdout)

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

    def test_sdk_only_provenance_and_docs_match_previous_delivery_shape(self) -> None:
        self.assertIn('"sdk_only": sdk_only', self.source)
        self.assertIn(
            'if not sdk_only:\n    artifacts.append(fingerprint("demo/dingqiao-demo.hap"))',
            self.source,
        )
        self.assertIn('"$OUT_ROOT/docs/ASR_SDK_API_HARMONY.md"', self.source)
        self.assertIn('"$OUT_ROOT/docs/third-party/ONNX-Runtime-MIT.txt"', self.source)
        self.assertIn('"$OUT_ROOT/README.md"', self.source)

    def test_clean_customer_host_generates_ignored_hvigor_config(self) -> None:
        verifier = SCRIPT.with_name("verify_selfcontained_dingqiao_har.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('"$CUSTOMER_PROJECT/hvigor/hvigor-config.json5"', verifier)
        self.assertIn('hvigor_config_path.parent.mkdir(parents=True, exist_ok=True)', verifier)
        self.assertIn('"modelVersion": "5.0.0"', verifier)

    def test_public_versions_are_consistent(self) -> None:
        version = "0.2.4"
        relative_files = [
            "asr/harmony/oh-package.json5",
            "asr/harmony/sdk/oh-package.json5",
            "asr/harmony/sdk-police/oh-package.json5",
            "asr/harmony/sdk-dingqiao/oh-package.json5",
            "asr/harmony/sdk/src/main/cpp/types/libamphion_asr/oh-package.json5",
            "delivery/harmony-dingqiao/oh-package.json5",
            "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/oh-package.json5",
        ]
        for relative in relative_files:
            actual = json.loads((REPO / relative).read_text(encoding="utf-8"))["version"]
            self.assertEqual(version, actual, relative)

        runtime = (REPO / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets").read_text(
            encoding="utf-8"
        )
        self.assertIn("SDK_VERSION: string = '0.2.4-harmony'", runtime)
        self.assertIn("SDK_RELEASE_DATE: string = '2026-07-15'", runtime)


if __name__ == "__main__":
    unittest.main()
