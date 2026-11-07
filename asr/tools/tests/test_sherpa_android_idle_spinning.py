"""Android ORT session 必须在 Run 之间停止空转，这里把 0038 补丁钉住。

流式 ASR 每个 chunk 调一次 Run，然后等下一段音频。ORT 默认让 intra-op worker 在 Run
返回后继续自旋等待；EC521S（MT6853）上 simpleperf 显示 SDK 一半以上的 CPU 时间花在
WorkerLoop 空转里。0038 与 Harmony 的 0029 相同，只设置 `session.force_spinning_stop=1`：
Run 期间的自旋和线程数都不变，所以实时性不受影响。
若升级 sherpa 或重排补丁时丢掉它，不会有构建失败，只会让真机 CPU 和发热回升。
"""

import os
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PATCH_DIR = REPO_ROOT / "third_party/patches/sherpa-amphion"
PATCH = PATCH_DIR / "0038-perf-android-stop-idle-asr-spinning.patch"
GUARD = '"session.force_spinning_stop", "1"'


def derived_root() -> "Path | None":
    override = os.environ.get("AMPHION_SHERPA_ROOT", "").strip()
    candidate = Path(override) if override else REPO_ROOT / "third_party/.derived/sherpa-onnx"
    return candidate if (candidate / ".amphion-patches-applied").is_file() else None


def android_block(text: str) -> str:
    start = text.index("#if defined(__ANDROID__)")
    return text[start:text.index("#endif", start)]


class SherpaAndroidIdleSpinningTest(unittest.TestCase):
    def test_patch_stops_idle_spinning_only(self) -> None:
        text = PATCH.read_text(encoding="utf-8")
        added = "\n".join(line[1:] for line in text.splitlines() if line.startswith("+") and not line.startswith("+++"))
        block = android_block(added)
        self.assertIn(GUARD, block)
        # 只停 Run 之间的空转；关掉 Run 期间的自旋或改线程数会影响实时性，不属于此补丁。
        self.assertNotIn("allow_spinning", block)
        self.assertNotIn("NumThreads", block)

    def test_patch_is_registered(self) -> None:
        readme = (PATCH_DIR / "README.md").read_text(encoding="utf-8")
        self.assertIn("`0038-*`", readme)

    def test_prepared_source_carries_the_guard(self) -> None:
        root = derived_root()
        if root is None:
            self.skipTest("patched sherpa tree not prepared; patch text is asserted separately")
        session = (root / "sherpa-onnx/csrc/session.cc").read_text(encoding="utf-8")
        impl = session[session.index("Ort::SessionOptions GetSessionOptionsImpl("):]
        self.assertIn("#if defined(__ANDROID__)", impl, "0038 not applied to the prepared tree")
        self.assertIn(GUARD, android_block(impl))


if __name__ == "__main__":
    unittest.main()
