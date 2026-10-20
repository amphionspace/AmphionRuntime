"""调用方热词的逐词加权依赖 sherpa 两个行为,这里把它们钉住。

预置池按 Police 1.4.0 校准停在 1.0,调用方热词单独走 3.0。两档靠 hotwords buffer 的逐行
`<词> :<分>` 语法共存:带分的行由 EncodeHotwords 透出到 boost_scores,未标注的行回落到
ContextGraph 的全局 context_score。若升级或新增 patch 丢掉其中任何一环,修复会静默退化成
「调用方热词也只有 1.0」——识别结果变差,但没有任何构建或测试会失败。

断言对象优先取 prepare_sherpa_source.sh 产出的已打补丁隔离树(真正参与编译的那份),
未设置 AMPHION_SHERPA_ROOT 时回落到子模块。本测试需要 sherpa 源码已检出。
"""

import os
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def sherpa_root() -> Path:
    override = os.environ.get("AMPHION_SHERPA_ROOT", "").strip()
    return Path(override) if override else REPO_ROOT / "third_party/sherpa-onnx"


class SherpaHotwordScoreSyntaxTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = sherpa_root()
        self.utils = self.root / "sherpa-onnx/csrc/utils.cc"
        self.context_graph = self.root / "sherpa-onnx/csrc/context-graph.cc"
        for path in (self.utils, self.context_graph):
            if not path.is_file():
                self.fail(
                    f"sherpa source is not checked out: {path}. "
                    "Initialize third_party/sherpa-onnx or set AMPHION_SHERPA_ROOT."
                )

    def test_per_hotword_scores_are_parsed(self) -> None:
        text = self.utils.read_text(encoding="utf-8")
        # `:<分>` 必须排在短语之后,并由 EncodeHotwords 透出到 boost_scores。
        self.assertIn("case ':':  // boosting score for current keyword", text)
        self.assertIn(
            "return EncodeBase(lines, symbol_table, hotwords, nullptr, boost_scores,", text
        )

    def test_unscored_hotwords_fall_back_to_the_global_weight(self) -> None:
        text = self.context_graph.read_text(encoding="utf-8")
        self.assertIn("score = score == 0.0f ? context_score_ : score;", text)


if __name__ == "__main__":
    unittest.main()
