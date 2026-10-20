"""调用方热词(sysGeneralLexicon)的逐词加权必须双端一致。

预置池按 Police 1.4.0 校准停在 1.0,调用方热词单独走 3.0;两档靠 sherpa-onnx hotwords
buffer 的逐行 `<词> :<分>` 语法共存。sherpa 侧那两个前提由
test_sherpa_hotword_score_syntax.py 钉住(它需要 sherpa 源码已检出,因此跑在初始化了
子模块的 job 里)。本文件只读仓库内源码,不依赖子模块。
"""

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
HARMONY_POLICE = REPO_ROOT / (
    "asr/harmony/sdk-police/src/main/ets/com/amphion/police/PoliceEngineConfig.ets"
)
ANDROID_POLICE = REPO_ROOT / (
    "asr/android/sdk-police/src/main/java/com/amphion/police/PoliceEngineConfig.kt"
)

PRESET_SCORE = 1.0
USER_SCORE = 3.0


class UserHotwordWeightTest(unittest.TestCase):
    def test_both_platforms_agree_on_the_two_weights(self) -> None:
        harmony = HARMONY_POLICE.read_text(encoding="utf-8")
        android = ANDROID_POLICE.read_text(encoding="utf-8")

        def constant(text: str, name: str) -> float:
            match = re.search(rf"{name}\s*(?::\s*number)?\s*=\s*([0-9.]+)f?", text)
            self.assertIsNotNone(match, f"{name} not found")
            return float(match.group(1))

        for text in (harmony, android):
            self.assertEqual(PRESET_SCORE, constant(text, "HOTWORDS_SCORE_DEFAULT"))
            self.assertEqual(USER_SCORE, constant(text, "USER_HOTWORDS_SCORE"))

    def test_only_caller_words_carry_a_per_word_weight(self) -> None:
        harmony = HARMONY_POLICE.read_text(encoding="utf-8")
        android = ANDROID_POLICE.read_text(encoding="utf-8")

        # 调用方热词显式带分。
        self.assertIn(
            "append(extraHotwords[i], PoliceEngineConfig.USER_HOTWORDS_SCORE);", harmony
        )
        self.assertIn("userHotwords.forEach { append(it, USER_HOTWORDS_SCORE) }", android)

        # 预置池不带分,回落到全局 hotwordsScore。forEach 直接传 append 会把下标当成
        # score 实参,所以 Harmony 侧必须经 appendPreset 包一层。
        self.assertIn("const appendPreset = (value: string): void => append(value);", harmony)
        for domain in ("terms", "plate", "station"):
            self.assertIn(f"readHotwords(context, '{domain}').forEach(appendPreset)", harmony)
        for preset in ("PoliceTermsHotwords", "PlateHotwords", "PoliceStationHotwords"):
            self.assertIn(f"{preset}.PRESET.forEach {{ append(it) }}", android)


if __name__ == "__main__":
    unittest.main()
