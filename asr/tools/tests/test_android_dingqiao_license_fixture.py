import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ANDROID_TEST = ROOT / "asr/android/samples/dingqiao-demo/src/androidTest"
LICENSES = ANDROID_TEST / "assets/licenses"


class AndroidDingqiaoLicenseFixtureTest(unittest.TestCase):
    def test_positive_device_tests_use_demo_apk_license(self) -> None:
        sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ANDROID_TEST / "java").rglob("*.kt")
        )

        self.assertNotIn('"licenses/valid.lic"', sources)
        self.assertIn('targetContext.assets.open(DQ_LICENSE_ASSET)', sources)

    def test_no_expiring_positive_license_is_tracked_as_test_asset(self) -> None:
        self.assertEqual(
            {path.name for path in LICENSES.glob("*.lic")},
            {"expired.lic", "malformed.lic"},
            "androidTest may only track deterministic negative license fixtures",
        )


if __name__ == "__main__":
    unittest.main()
