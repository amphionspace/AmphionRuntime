import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "asr/android/samples/public-demo"


class PublicDemoBoundaryTest(unittest.TestCase):
    def test_public_demo_has_no_network_capability(self) -> None:
        manifest = (DEMO / "src/main/AndroidManifest.xml").read_text(encoding="utf-8")
        gradle = (DEMO / "build.gradle.kts").read_text(encoding="utf-8")

        self.assertNotIn("android.permission.INTERNET", manifest)
        self.assertNotIn("usesCleartextTraffic", manifest)
        self.assertNotIn("okhttp", gradle.lower())
        self.assertNotIn("CLOUD_ASR_API_KEY", gradle)

    def test_public_demo_contains_no_remote_asr_client(self) -> None:
        source_root = DEMO / "src/main"
        sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(source_root.rglob("*"))
            if path.is_file() and path.suffix in {".kt", ".xml"}
        )

        self.assertNotRegex(sources, re.compile(r"wss?://", re.IGNORECASE))
        self.assertNotIn("CloudAsrClient", sources)
        self.assertNotIn("CloudAsrPrefs", sources)

    def test_public_demo_contains_no_internal_evaluation_tools(self) -> None:
        source_root = DEMO / "src/main"
        sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(source_root.rglob("*"))
            if path.is_file() and path.suffix in {".kt", ".xml"}
        )

        self.assertNotIn("BatchEval", sources)
        self.assertNotIn("EvalRecorder", sources)
        self.assertNotIn("batch_eval", sources)

    def test_public_demo_does_not_log_customer_or_recognition_content(self) -> None:
        sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((DEMO / "src/main/java").rglob("*.kt"))
        )

        self.assertNotIn("customer=", sources)
        self.assertNotRegex(sources, re.compile(r"Log\.[vdiew]\([^\n]*(?:raw|norm|text)=", re.I))
        self.assertIn("AmphionOptions(logLevel = AmphionLogLevel.WARN)", sources)

    def test_only_launcher_activity_is_exported(self) -> None:
        manifest = (DEMO / "src/main/AndroidManifest.xml").read_text(encoding="utf-8")
        exported = re.findall(
            r'<activity\s+android:name="([^"]+)"\s+android:exported="true"', manifest
        )

        self.assertEqual(exported, [".MainActivity"])


if __name__ == "__main__":
    unittest.main()
