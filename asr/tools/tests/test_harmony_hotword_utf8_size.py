import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
PATCH = REPO_ROOT / (
    "third_party/patches/sherpa-amphion/"
    "0014-fix-harmony-size-hotword-buffer-as-utf8.patch"
)


class HarmonyHotwordUtf8SizeTest(unittest.TestCase):
    def test_harmony_binding_owns_native_hotword_byte_length(self) -> None:
        runtime = RUNTIME.read_text(encoding="utf-8")
        patch = PATCH.read_text(encoding="utf-8")

        self.assertIn(
            "rc.hotwordsBuf = config.hotwords.join('\\n');",
            runtime,
        )
        self.assertIn(
            "c.hotwords_buf_size = c.hotwords_buf == nullptr",
            patch,
        )
        self.assertIn(
            "std::strlen(c.hotwords_buf));",
            patch,
        )

        hotwords = "余祈根\n黄晋飞\n王光辉\n潘聪\n文斌成"
        self.assertEqual(len(hotwords), 18)
        self.assertEqual(len(hotwords.encode("utf-8")), 46)


if __name__ == "__main__":
    unittest.main()
