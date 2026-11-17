import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HARMONY_API = ROOT / "tts/harmony/sdk/src/main/ets/TextToSpeechApi.ets"
ANDROID_FRONTEND = ROOT / "tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/LitsTtsFrontend.kt"
ANDROID_TN = ROOT / "tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/LitsTnNormalizer.kt"


class TtsQuestionMarkFrontendContractTest(unittest.TestCase):
    """缺陷 #94：英文「?」后面紧跟字母时不得被当成技术符号读成 question mark / 问号。

    双端同一条规则：只有 URL 查询串（"?key="）或 URL/路径样 token 里的 '?' 才是技术符号；
    其余贴着字母的 '?' 在 TN 入口先与下一句分开，分句器也不再把它当成 token 内部字符。
    """

    def test_harmony_frontend_separates_glued_question_marks_before_tn(self) -> None:
        source = HARMONY_API.read_text(encoding="utf-8")
        self.assertIn("static separateGluedSentencePunctuation(text: string): string", source)
        self.assertIn("static isQueryQuestionMark(text: string, index: number): boolean", source)
        self.assertIn("LitsTtsFrontend.normalizeText(LitsTtsFrontend.separateGluedSentencePunctuation(text), languageContext)", source)
        technical = re.search(r"private static isPunctuationInsideTechnicalToken\(.*?\n  \}", source, re.S)
        self.assertIsNotNone(technical)
        body = technical.group(0)
        self.assertIn("if (char === '?') {", body)
        self.assertIn("return LitsTtsFrontend.isQueryQuestionMark(text, index);", body)
        self.assertNotIn("char === '?' || char === '='", body)

    def test_android_frontend_mirrors_the_same_rule(self) -> None:
        frontend = ANDROID_FRONTEND.read_text(encoding="utf-8")
        tn = ANDROID_TN.read_text(encoding="utf-8")
        self.assertIn("internal fun separateGluedSentencePunctuation(text: String): String", frontend)
        self.assertIn("if (char == '?') return isQueryQuestionMark(text, index)", frontend)
        # 3.x 线先做换行归一化再分开粘连标点，只要求该调用存在于 TN 入口
        self.assertIn("LitsTtsFrontend.separateGluedSentencePunctuation(", tn)
        self.assertIn("val normalized = separateGluedSentencePunctuation(", frontend)

    def test_glued_question_mark_regex_behaves_the_same_on_both_platforms(self) -> None:
        # 两端共用同一组正则；用 Python 的等价表达验证样例口径，避免双端悄悄分叉。
        glued = re.compile(r"(?<=[A-Za-z0-9\u4e00-\u9fff)\]\"'])(\?+|\.{2,}|\u2026+|\.)(?=[A-Za-z\u4e00-\u9fff])")
        query = re.compile(r"^\?[A-Za-z0-9_%\-]+=")
        urlish = re.compile(r"(://|^www\.|/|@)", re.I)

        def letter(c):
            return c is not None and c.isascii() and c.isalpha()

        def separate(text: str) -> str:
            def token_at(index: int) -> str:
                start = text.rfind(" ", 0, index) + 1
                end = text.find(" ", index)
                return text[start:end if end >= 0 else len(text)]

            def repl(match: re.Match) -> str:
                run = match.group(0)
                first, last = match.start(), match.end() - 1
                if run[0] == "?":
                    keep = bool(urlish.search(token_at(last)) or query.match(text[last:]))
                elif len(run) >= 2:
                    keep = False
                else:
                    nxt, prev = text[last + 1], text[first - 1]
                    before = text[first - 2] if first >= 2 else None
                    sentence_start = ("A" <= nxt <= "Z") or ("\u4e00" <= nxt <= "\u9fff")
                    keep = (not sentence_start) or bool(urlish.search(token_at(first))) or (letter(prev) and not letter(before))
                return run if keep else run + " "
            return glued.sub(repl, text)

        self.assertEqual("Are you ready? Yes, I am.", separate("Are you ready?Yes, I am."))
        self.assertEqual("你好吗? 好的", separate("你好吗?好的"))
        self.assertEqual("What?? Really", separate("What??Really"))
        self.assertEqual("Open https://a.com/x?id=1 now.", separate("Open https://a.com/x?id=1 now."))
        self.assertEqual("www.a.com/search?q=lits", separate("www.a.com/search?q=lits"))
        self.assertEqual("ready? ", separate("ready? "))
        self.assertEqual("ready?", separate("ready?"))
        self.assertEqual("Are you ready. Yes I am.", separate("Are you ready.Yes I am."))
        self.assertEqual("Ready... Yes", separate("Ready...Yes"))
        self.assertEqual("Ready\u2026 Yes", separate("Ready\u2026Yes"))
        self.assertEqual("Version 1.2. Next", separate("Version 1.2.Next"))
        self.assertEqual("结束. Next句", separate("结束.Next句"))
        self.assertEqual("是OK. 好的", separate("是OK.好的"))
        self.assertEqual("readme.txt", separate("readme.txt"))
        self.assertEqual("www.a.com", separate("www.a.com"))
        self.assertEqual("a@b.com", separate("a@b.com"))
        self.assertEqual("v1.2.3", separate("v1.2.3"))
        self.assertEqual("U.S.A", separate("U.S.A"))


if __name__ == "__main__":
    unittest.main()
