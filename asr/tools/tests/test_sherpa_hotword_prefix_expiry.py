"""热词半匹配前缀必须有过期上限，这里把 0036 补丁钉住。

modified beam search 里，一条假设停在未完成的热词前缀上时，只要一直输出 blank 就不用
结算回退扣分，而任何真实 token 都要一次性扣回全部加分。调用方热词 3.0 时，这会让
解码器"宁可沉默"，把后面整段（客户现场是 11 位手机号）全部删掉。0036 补丁给这种停留
设了 1 s 的上限：连续 kMaxContextBlankFrames 个 blank 帧后结算扣分并回到根节点，之后直到
路径经真实 token 回到根节点前不再发放加分（否则兄弟路径重发首字会二次领取加分，出现
"中中原"这类重复首字）。上限取 1 s 是因为加分会让热词首字在前导静音里提前最多约 0.9 s
发出，这段等待不能被当作停滞。
若升级 sherpa 或重排补丁时丢掉它，不会有构建失败，只会在真机上重新出现删数字。

补丁文件随仓库发布，这里直接断言补丁内容与 README 登记；若隔离树已准备好，再核对
真正参与编译的源码。
"""

import os
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PATCH_DIR = REPO_ROOT / "third_party/patches/sherpa-amphion"
PATCH = PATCH_DIR / "0036-fix-asr-expire-stale-hotword-prefixes.patch"
FIRST_TOKEN_PATCH = PATCH_DIR / "0037-fix-asr-cap-first-token-hotword-bonus.patch"


def derived_root() -> "Path | None":
    override = os.environ.get("AMPHION_SHERPA_ROOT", "").strip()
    candidate = Path(override) if override else REPO_ROOT / "third_party/.derived/sherpa-onnx"
    return candidate if (candidate / ".amphion-patches-applied").is_file() else None


class SherpaHotwordPrefixExpiryTest(unittest.TestCase):
    def test_patch_bounds_blank_runs_on_a_hotword_prefix(self) -> None:
        text = PATCH.read_text(encoding="utf-8")
        self.assertIn("static constexpr int32_t kMaxContextBlankFrames = 25;", text)
        self.assertIn("++new_hyp.context_blank_frames;", text)
        self.assertIn("ss[b]->GetContextGraph()->Finalize(context_state);", text)
        # Expiry must only touch paths that actually sit on a partial match.
        self.assertIn("context_state != ss[b]->GetContextGraph()->Root()", text)
        # A continued match resets the run so real hotwords keep their bonus.
        self.assertIn("new_hyp.context_blank_frames = 0;", text)
        # After an expiry no bonus is granted until the path is back at the root.
        self.assertIn("new_hyp.context_bonus_suppressed = true;", text)
        self.assertIn("if (new_hyp.context_bonus_suppressed) {", text)

    def test_first_token_bonus_is_capped(self) -> None:
        """0037：首字加分封顶，且扣下的额度不补发到第二个 token。"""
        text = FIRST_TOKEN_PATCH.read_text(encoding="utf-8")
        self.assertIn("static constexpr float kFirstTokenMaxContextScore = 1.0f;", text)
        self.assertIn("std::min(score, kFirstTokenMaxContextScore)", text)
        # 单字短语必须保持原加分；补发会把劫持挪到第二个字，不能出现 2.0f * score。
        self.assertIn("j == 0 && phrase_length > 1", text)
        self.assertNotIn("2.0f * score", text)

    def test_patch_is_registered(self) -> None:
        readme = (PATCH_DIR / "README.md").read_text(encoding="utf-8")
        self.assertIn("`0036-*`", readme)
        self.assertIn("`0037-*`", readme)

    def test_prepared_source_carries_the_expiry(self) -> None:
        root = derived_root()
        if root is None:
            self.skipTest("patched sherpa tree not prepared; patch text is asserted separately")
        decoder = root / "sherpa-onnx/csrc/online-transducer-modified-beam-search-decoder.cc"
        text = decoder.read_text(encoding="utf-8")
        self.assertIn("kMaxContextBlankFrames", text)
        hypothesis = (root / "sherpa-onnx/csrc/hypothesis.h").read_text(encoding="utf-8")
        self.assertIn("int32_t context_blank_frames = 0;", hypothesis)
        graph = (root / "sherpa-onnx/csrc/context-graph.cc").read_text(encoding="utf-8")
        self.assertIn("kFirstTokenMaxContextScore", graph)


if __name__ == "__main__":
    unittest.main()
