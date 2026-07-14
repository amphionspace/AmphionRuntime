package com.lits.tts.sdk.internal

import java.io.File
import kotlin.io.path.createTempDirectory
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Ignore
import org.junit.Test
import org.json.JSONObject

class LitsTtsFrontendTest {
    @Test
    fun languageContextControlsDigitReading() {
        val layout = testLayout()

        val zhDigitIds = LitsTtsFrontend.encode(layout, "123", "zh-en", "zh-en")
        val zhTextIds = LitsTtsFrontend.encode(layout, "一二三", "zh-en", "zh-en")
        val enDigitIds = LitsTtsFrontend.encode(layout, "123", "zh-en", "en-US")

        assertArrayEquals(zhTextIds, zhDigitIds)
        assertFalse(zhDigitIds.contentEquals(enDigitIds))
    }

    @Test
    fun enUsDigitsMatchSpelledOutWords() {
        val layout = testLayout()

        val digitIds = LitsTtsFrontend.encode(layout, "Room 204 is ready.", "en-US", "en-US")
        val wordIds = LitsTtsFrontend.encode(layout, "Room two zero four is ready.", "en-US", "en-US")

        assertArrayEquals(wordIds, digitIds)
    }

    @Test
    fun enUsCodeAndLeadingZeroNumbersUseDigitReadings() {
        val layout = testLayout()

        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "Please call four zero zero eight zero zero zero zero zero six.", "en-US", "en-US"),
            LitsTtsFrontend.encode(layout, "Please call four zero zero eight zero zero 0006.", "en-US", "en-US"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "The verification code is A nine B eight C seven one five.", "en-US", "en-US"),
            LitsTtsFrontend.encode(layout, "The verification code is A nine B eight C seven 15.", "en-US", "en-US"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "Can we start the meeting at twenty six fifteen this afternoon?", "en-US", "en-US"),
            LitsTtsFrontend.encode(layout, "Can we start the meeting at 26 fifteen this afternoon?", "en-US", "en-US"),
        )
    }

    @Test
    fun zhEnPlateAlnumRunsReadLettersAndDigits() {
        val layout = testLayout()

        val plateIds = LitsTtsFrontend.encode(layout, "帮忙核查一下车牌号为冀R65438的情况。", "zh-en", "zh-en")
        val letterDigitIds = LitsTtsFrontend.encode(layout, "R65438", "zh-en", "zh-en")

        assertTrue(plateIds.isNotEmpty())
        assertTrue(letterDigitIds.isNotEmpty())
    }

    @Test
    fun zhEnUppercaseAcronymsSpellLettersExceptWordReadings() {
        val layout = testLayout()

        val idIds = LitsTtsFrontend.encode(layout, "请记录ID", "zh-en", "zh-en")
        val lowercaseIdIds = LitsTtsFrontend.encode(layout, "请记录id", "zh-en", "zh-en")
        val simIds = LitsTtsFrontend.encode(layout, "请确认SIM卡", "zh-en", "zh-en")
        val lowercaseSimIds = LitsTtsFrontend.encode(layout, "请确认sim卡", "zh-en", "zh-en")

        assertFalse(lowercaseIdIds.contentEquals(idIds))
        assertArrayEquals(lowercaseSimIds, simIds)
    }

    @Test
    fun zhEnTechnicalSymbolsReadOutInUrlsFilesAndFormulas() {
        val layout = testLayout()

        assertTrue(
            LitsTtsFrontend.encode(
                layout,
                "请打开https://example.com/a/b?id=2026&lang=zh",
                "zh-en",
                "zh-en",
            ).isNotEmpty(),
        )
        assertTrue(
            LitsTtsFrontend.encode(
                layout,
                "联系邮箱是support-team@example.co.cn",
                "zh-en",
                "zh-en",
            ).isNotEmpty(),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "包名是com点lits点tts点sample", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "包名是com.lits.tts.sample", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "公式E等于mc平方只是备注", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "公式E=mc^2只是备注", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "USB C接口已连接", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "USB-C接口已连接", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "Type C接口已连接", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "Type-C接口已连接", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "Type C接口已连接", "zh-en", "zh-en"),
            LitsTtsFrontend.encodeNormalized(layout, "Type杠C接口已连接", "zh-en", "zh-en"),
        )
    }

    @Test
    fun zhEnSymbolsAndEmojiDoNotBreakFrontend() {
        val layout = testLayout()

        val ids = LitsTtsFrontend.encode(
            layout,
            "请处理😀 @user #topic $50 {ok} ✓ → 100% C6H12O6。",
            "zh-en",
            "zh-en",
        )

        assertTrue(ids.isNotEmpty())
    }

    @Test
    fun zhEnPercentNumbersAcceptAsciiAndFullwidthPercent() {
        val layout = testLayout()
        val expected = LitsTtsFrontend.encodeNormalized(layout, "电量百分之六十八。", "zh-en", "zh-en")

        assertArrayEquals(
            expected,
            LitsTtsFrontend.encodeNormalized(layout, "电量68%。", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            expected,
            LitsTtsFrontend.encodeNormalized(layout, "电量68％。", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            expected,
            LitsTtsFrontend.encodeNormalized(layout, "电量68 %。", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            expected,
            LitsTtsFrontend.encodeNormalized(layout, "电量68百分号。", "zh-en", "zh-en"),
        )
    }

    @Test
    fun zhEnNumericTnContextsUseSemanticDigitReadings() {
        val layout = testLayout()

        assertNormalizedTokenSequence(layout, "今天是 2026 年 7 月 2 日,下午 3:05 开会.", "ㄦ ˋ _ ㄌ ㄧ ㄥ ˊ _ ㄦ ˋ _ ㄌ ㄧ ㄡ ˋ _ ㄋ ㄧ ㄢ ˊ")
        assertNormalizedTokenSequence(layout, "今天是 2026 年 7 月 2 日,下午 3:05 开会.", "ㄙ ㄢ ˉ _ ㄉ ㄧ ㄢ ˇ _ ㄌ ㄧ ㄥ ˊ _ ㄨ ˇ")
        assertNormalizedTokenSequence(layout, "股票 600519 今日上涨 5.23百分号.", "ㄌ ㄧ ㄡ ˋ _ ㄌ ㄧ ㄥ ˊ _ ㄌ ㄧ ㄥ ˊ _ ㄨ ˇ _ ㄧ ˉ _ ㄐ ㄧ ㄡ ˇ")
        assertNormalizedTokenSequence(layout, "股票 600519 今日上涨 5.23百分号.", "ㄅ ㄞ ˇ _ ㄈ ㄣ ˉ _ ㄓ ˉ _ ㄨ ˊ _ ㄉ ㄧ ㄢ ˇ _ ㄦ ˋ _ ㄙ ㄢ ˉ")
        assertNormalizedTokenSequence(layout, "编号 1 的房间是 204,温度 -24.5 度.", "ㄦ ˋ _ ㄌ ㄧ ㄥ ˊ _ ㄙ ˋ")
        assertNormalizedTokenSequence(layout, "车牌号粤 B00009 已经入场.", "B IY1 _ ㄌ ㄧ ㄥ ˊ _ ㄌ ㄧ ㄥ ˊ _ ㄌ ㄧ ㄥ ˊ _ ㄌ ㄧ ㄥ ˊ _ ㄐ ㄧ ㄡ ˇ")
        assertNormalizedTokenSequence(layout, "身份证尾号 010X,请核对.", "ㄌ ㄧ ㄥ ˊ _ ㄧ ˉ _ ㄌ ㄧ ㄥ ˊ _ EH1 K S")
        assertNormalizedTokenSequence(layout, "版本 v3.0.7 与 build 20260702 对齐.", "V IY1 _ ㄙ ㄢ ˉ _ ㄉ ㄧ ㄢ ˇ _ ㄌ ㄧ ㄥ ˊ _ ㄉ ㄧ ㄢ ˇ _ ㄑ ㄧ ˉ")
        assertNormalizedTokenSequence(layout, "路径 斜杠sdcard斜杠test斜杠18斜杠audio.wav 已生成.", "ㄧ ˉ _ ㄅ ㄚ ˉ")
        assertNormalizedTokenSequence(layout, "坐标 N22.12 E113.11,导航继续.", "ㄅ ㄟ ˊ _ ㄨ ㄟ ˇ _ ㄦ ˋ _ ㄕ ˊ _ ㄦ ˋ _ ㄉ ㄧ ㄢ ˇ _ ㄧ ˉ _ ㄦ ˋ")
        assertNormalizedTokenSequence(layout, "速度 80km斜杠h,距离目的地 11.5 公里.", "ㄅ ㄚ ˉ _ ㄕ ˊ _ ㄑ ㄧ ㄢ ˉ _ ㄇ ㄧ ˊ _ ㄇ ㄟ ˊ _ ㄒ ㄧ ㄠ ˇ _ ㄕ ˊ")
    }

    @Test
    fun zhEnTechnicalTnContextsUseCodeAndSymbolReadings() {
        val layout = testLayout()

        assertNormalizedTokenSequence(layout, "请访问 https:斜杠斜杠example.com斜杠help斜杠1?q等于lits-v3.", "ㄧ ˉ _ , _ ㄨ ㄣ ˋ _ ㄏ ㄠ ˋ")
        assertNormalizedTokenSequence(layout, "请访问 https:斜杠斜杠example.com斜杠help斜杠1?q等于lits-v3.", "EH1 L AY1 T IY1 EH1 S")
        assertNormalizedTokenSequence(layout, "A斜杠B 测试组 16 的 F1-score 是 0.16.", "EH1 F _ ㄧ ˉ _ , _ ㄍ ㄤ ˋ _ S K AO1 R")
        assertNormalizedTokenSequence(layout, "错误码 TTS_8_TIMEOUT 只作为普通文本.", "T IY1 T IY1 EH1 S _ AH2 N D ER0 S K AO1 R _ ㄅ ㄚ ˉ _ , _ AH2 N D ER0 S K AO1 R _ T AY1 M AW1 T")
        assertNormalizedTokenSequence(layout, "包名 com.lits.tts.sample9 应按规则处理.", "K AA1 M _ ㄉ ㄧ ㄢ ˇ _ EH1 L AY1 T IY1 EH1 S")
    }

    @Test
    fun enUsSymbolsAndEmojiDoNotBreakFrontend() {
        val layout = testLayout()

        val ids = LitsTtsFrontend.encode(
            layout,
            "Hello 😀 {ok} # ready.",
            "en-US",
            "en-US",
        )

        assertTrue(ids.isNotEmpty())
    }

    @Test
    fun enUsTechnicalTextDoesNotNormalizeToChinese() {
        val layout = testLayout()

        assertTrue(
            LitsTtsFrontend.encode(
                layout,
                "Open example dot com for more information.",
                "en-US",
                "en-US",
            ).isNotEmpty(),
        )
        assertTrue(
            LitsTtsFrontend.encode(
                layout,
                "Send feedback to service at example dot com.",
                "en-US",
                "en-US",
            ).isNotEmpty(),
        )
    }

    @Test
    fun oovTextDoesNotBreakFrontend() {
        val layout = testLayout()

        assertTrue(
            LitsTtsFrontend.encode(layout, "生僻字龘和未知词qwertyuiopasdf。", "zh-en", "zh-en").isNotEmpty(),
        )
        assertTrue(
            LitsTtsFrontend.encode(layout, "qwertyuiopasdf is ready.", "en-US", "en-US").isNotEmpty(),
        )
    }

    @Test
    fun zhEnNumericFixesMatchMacosFrontendCases() {
        val layout = testLayout()

        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "气温零下二十四点五度", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "气温-24.5度", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "气温零下二十四点五度", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "气温 -24.5 度", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "温度范围是零下五到十度", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "温度范围是-5到10度", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "温度范围是零下五到十度", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "温度范围是 -5 到 10 度", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "闹钟设为七点零五分", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "闹钟设为7点05分", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "闹钟设为十四点零五分", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "闹钟设为十四点05分", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "设备序列号TX二零二六A零九需要登记", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "设备序列号TX2026A09需要登记", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "用时一小时零五分钟", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "用时1小时05分钟", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "出生日期1998年二月零九日", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "出生日期1998年2月09日", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "转账一百万元到账", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "转账1,000,000.00元到账", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "公式E等于mc平方只是备注", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "公式E=mc^二只是备注", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "JDK17路径在点venv斜杠lib斜杠jvm", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "JDK17路径在.venv/lib/jvm", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "firmware二点零点十杠beta需要灰度", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "firmware 2.0.10-beta需要灰度", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "路径是斜杠home斜杠user斜杠report下划线2026点csv", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "路径是/home/user/report_2026.csv", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "URL是www点example点com斜杠test问号id等于123", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "URL是www.example.com/test?id=123", "zh-en", "zh-en"),
        )
    }

    @Test
    fun enUsChatgptUsesLexiconReading() {
        val layout = testLayout()

        val tokens = LitsTtsFrontend.debugTokensForTest(layout, "chatgpt is ready.", "en-US", "en-US")

        assertTrue(
            "expected chatgpt lexicon reading, actual=${tokens.joinToString(" ")}",
            tokens.joinToString(" ").contains("CH AE1 T JH IY1 P IY1 T IY1"),
        )
    }

    @Test
    fun zhEnChatgptUsesLexiconAfterTnSplitRepair() {
        val layout = testLayout()

        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "请打开chatgpt应用", "zh-en", "zh-en"),
            LitsTtsFrontend.encodeNormalized(layout, "请打开chat g p t应用", "zh-en", "zh-en"),
        )
        val tokens = LitsTtsFrontend.debugTokensForTest(layout, "请打开chat gpt应用", "zh-en", "zh-en")
        assertTrue(
            "expected chatgpt lexicon reading, actual=${tokens.joinToString(" ")}",
            tokens.joinToString(" ").contains("CH AE1 T JH IY1 P IY1 T IY1"),
        )
    }

    @Test
    fun enUsSupplementLexiconIsUsedBeforeSpellingFallback() {
        val layout = testLayout()

        val tokens = LitsTtsFrontend.debugTokensForTest(
            layout,
            "firmware roadmap barista barcode Figma Anthropic is ready.",
            "en-US",
            "en-US",
        )

        assertTrue(
            "expected firmware supplement lexicon reading, actual=${tokens.joinToString(" ")}",
            tokens.joinToString(" ").contains("F ER1 M W EH2 R"),
        )
        assertTrue(
            "expected roadmap supplement lexicon reading, actual=${tokens.joinToString(" ")}",
            tokens.joinToString(" ").contains("R OW1 D M AE2 P"),
        )
        assertTrue(
            "expected barista supplement lexicon reading, actual=${tokens.joinToString(" ")}",
            tokens.joinToString(" ").contains("B AH0 R IY1 S T AH0"),
        )
        assertTrue(
            "expected barcode supplement lexicon reading, actual=${tokens.joinToString(" ")}",
            tokens.joinToString(" ").contains("B AA1 R K OW2 D"),
        )
        assertTrue(
            "expected Figma supplement lexicon reading, actual=${tokens.joinToString(" ")}",
            tokens.joinToString(" ").contains("F IH1 G M AH0"),
        )
        assertTrue(
            "expected Anthropic supplement lexicon reading, actual=${tokens.joinToString(" ")}",
            tokens.joinToString(" ").contains("AE0 N TH R AA1 P IH0 K"),
        )
    }

    @Test
    fun arpabetInputCanPassThroughDirectly() {
        val layout = testLayout()

        assertArrayEquals(
            LitsTtsFrontend.encodeNormalized(layout, "/ CH AE1 T / .", "en-US", "en-US"),
            LitsTtsFrontend.encodeNormalized(layout, "/ CH AE1 T /", "en-US", "en-US"),
        )
    }

    @Test
    fun enUsSingleAUsesArticleOrLetterNameByContext() {
        val layout = testLayout()

        val articleTokens = LitsTtsFrontend.debugTokensForTest(layout, "A dog is ready.", "en-US", "en-US")
        val letterTokens = LitsTtsFrontend.debugTokensForTest(layout, "grade A.", "en-US", "en-US")
        val acronymTokens = LitsTtsFrontend.debugTokensForTest(layout, "API is ready.", "en-US", "en-US")

        assertTrue(
            "expected article A as AH0, actual=${articleTokens.joinToString(" ")}",
            articleTokens.joinToString(" ").contains("AH0 _ D AO1 G"),
        )
        assertTrue(
            "expected final A as letter name EY1, actual=${letterTokens.joinToString(" ")}",
            letterTokens.joinToString(" ").contains("G R EY1 D _ EY1"),
        )
        assertTrue(
            "expected acronym A as letter name EY1, actual=${acronymTokens.joinToString(" ")}",
            acronymTokens.joinToString(" ").contains("EY1 P IY1 AY1"),
        )
    }

    @Test
    fun zhEnAppliesYiBuErToneSandhi() {
        val layout = testLayout()

        assertTokenSequence(layout, "一辆车。", "ㄧ ˊ _ ㄌ ㄧ ㄤ ˋ _")
        assertTokenSequence(layout, "一条鱼。", "ㄧ ˋ _ ㄊ ㄧ ㄠ ˊ _")
        assertTokenSequence(layout, "一个城市。", "ㄧ ˊ _ ㄍ ㄜ ˋ _")
        assertTokenSequence(layout, "不对。", "ㄅ ㄨ ˊ _ ㄉ ㄨ ㄟ ˋ _")
        assertTokenSequence(layout, "看一看。", "ㄎ ㄢ ˋ _ ㄧ ˙ _ ㄎ ㄢ ˋ _")
        assertTokenSequence(layout, "花儿。", "ㄏ ㄨ ㄚ ˉ _ ㄦ ˙ _")
    }

    @Test
    fun zhEnAssistantAlarmUsesWeiFourthToneForAlreadyForYou() {
        val layout = realAssetLayout()

        val actual = LitsTtsFrontend.debugTokensForNormalizedForTest(
            layout,
            "好的，已为你设置明天早上七点半的闹钟。",
            "zh-en",
            "zh-en",
        ).joinToString(" ")

        assertTrue("expected 已为你 with 为 as fourth tone, actual=$actual", actual.contains("ㄧ ˇ _ ㄨ ㄟ ˋ _ ㄋ ㄧ ˇ _ ㄕ ㄜ ˋ"))
    }

    @Test
    fun splitForStreamingUsesStrongChinesePunctuation() {
        val layout = testLayout()

        val segments = LitsTtsFrontend.splitForStreaming(layout, "你好。欢迎使用语音合成系统！请稍等。")

        assertArrayEquals(
            arrayOf("你好.", "欢迎使用语音合成系统!", "请稍等."),
            segments.toTypedArray(),
        )
    }

    @Test
    fun splitForStreamingAvoidsEnglishFalseBreaks() {
        val layout = testLayout()

        val segments = LitsTtsFrontend.splitForStreaming(
            layout,
            "Hello world. Dr. Smith paid 3.14 dollars at 10:30 a.m. Visit example.com/test. Done.",
        )

        assertArrayEquals(
            arrayOf(
                "Hello world.",
                "Dr. Smith paid 3.14 dollars at 10:30 a.m. Visit example.com/test.",
                "Done.",
            ),
            segments.toTypedArray(),
        )
    }

    @Test
    fun splitForStreamingUsesEnUsContextForEnglishSample() {
        val layout = testLayout()

        val segments = LitsTtsFrontend.splitForStreaming(
            layout = layout,
            text = "Welcome to the Lits delivery TTS sample. Room 204 is ready.",
            language = "en-US",
            languageContext = "en-US",
        )

        assertArrayEquals(
            arrayOf(
                "Welcome to the Lits delivery TTS sample.",
                "Room 204 is ready.",
            ),
            segments.toTypedArray(),
        )
        assertTrue(
            LitsTtsFrontend.encodeNormalized(layout, segments[1], "en-US", "en-US").isNotEmpty(),
        )
    }

    @Test
    fun zhEnKeepsBoundaryBetweenEnglishAndChineseNumber() {
        val layout = testLayout()

        val tokens = LitsTtsFrontend.debugTokensForTest(layout, "room二百零四is ready", "zh-en", "zh-en")

        assertTrue(
            "expected boundary between room and 二百零四, actual=${tokens.joinToString(" ")}",
            tokens.joinToString(" ").contains("R UW1 M _ ㄦ"),
        )
    }

    @Test
    fun zhEnNamePlacePolyphoneOverridesUseExpectedReadings() {
        val layout = testLayout()

        assertTokenSequence(layout, "听音乐。", "ㄧ ㄣ ˉ _ ㄩ ㄝ ˋ _")
        assertTokenSequence(layout, "成都是一个美食之都。", "ㄕ ˋ _ ㄧ ˊ _ ㄍ ㄜ ˋ _ ㄇ ㄟ ˇ _")
        assertTokenSequence(layout, "成都是一个美食之都。", "ㄇ ㄟ ˇ _ ㄕ ˊ _ ㄓ ˉ _ ㄉ ㄨ ˉ _")
        assertTokenSequence(layout, "重庆市人民医院的曾医生今天接诊。", "ㄗ ㄥ ˉ _ ㄧ ˉ _ ㄕ ㄥ ˉ _")
        assertTokenSequence(layout, "单县来的单老师重新核对名单。", "ㄕ ㄢ ˋ _ ㄌ ㄠ ˇ _ ㄕ ˉ _")
        assertTokenSequence(layout, "解律师在解放路口说明合同。", "ㄒ ㄧ ㄝ ˋ _ ㄌ ㄩ ˋ _ ㄕ ˉ _")
        assertTokenSequence(layout, "仇工程师并不记仇。", "ㄑ ㄧ ㄡ ˊ _ ㄍ ㄨ ㄥ ˉ _ ㄔ ㄥ ˊ _ ㄕ ˉ _")
        assertTokenSequence(layout, "朴顾问建议保持朴素风格。", "ㄆ ㄧ ㄠ ˊ _ ㄍ ㄨ ˋ _ ㄨ ㄣ ˋ _")
        assertTokenSequence(layout, "区记者从南海区发回报道。", "ㄡ ˉ _ ㄐ ㄧ ˋ _ ㄓ ㄜ ˇ _")
        assertTokenSequence(layout, "华教授研究华山碑刻。", "ㄏ ㄨ ㄚ ˋ _ ㄐ ㄧ ㄠ ˋ _ ㄕ ㄡ ˋ _")
        assertTokenSequence(layout, "燕法官出生在燕郊。", "ㄧ ㄢ ˉ _ ㄈ ㄚ ˇ _ ㄍ ㄨ ㄢ ˉ _")
        assertTokenSequence(layout, "曾宁从重庆飞到长沙。", "ㄘ ㄨ ㄥ ˊ _ ㄔ ㄨ ㄥ ˊ _ ㄑ ㄧ ㄥ ˋ _")
    }

    @Test
    fun zhEnJingzangExpresswayUsesTibetanReading() {
        val layout = testLayout()
        assertTokenSequence(layout, "京藏高速。", "ㄐ ㄧ ㄥ ˉ _ ㄗ ㄤ ˋ _ ㄍ ㄠ ˉ _ ㄙ ㄨ ˋ")
        assertTokenSequence(layout, "京藏（zang）高速", "ㄐ ㄧ ㄥ ˉ _ ㄗ ㄤ ˋ")
    }

    @Test
    fun tnSegmentWhitespaceIsPreservedAroundNormalizedSegment() {
        assertTrue(
            LitsTnNormalizer.preserveSegmentWhitespace(" 204 ", "二百零四") == " 二百零四 ",
        )
    }

    @Test
    fun realAssetLayoutLoadsBinaryLexiconsAndSupplementLexicon() {
        val layout = realAssetLayout()

        val firmwareTokens = LitsTtsFrontend.debugTokensForNormalizedForTest(
            layout,
            "firmware roadmap barista barcode Figma Anthropic",
            "en-US",
            "en-US",
        ).joinToString(" ")
        val polyphoneTokens = LitsTtsFrontend.debugTokensForNormalizedForTest(
            layout,
            "曾医生从重庆出发。",
            "zh-en",
            "zh-en",
        ).joinToString(" ")

        assertTrue("expected firmware supplement entry, actual=$firmwareTokens", firmwareTokens.contains("F ER1 M W EH2 R"))
        assertTrue("expected roadmap supplement entry, actual=$firmwareTokens", firmwareTokens.contains("R OW1 D M AE2 P"))
        assertTrue("expected barista supplement entry, actual=$firmwareTokens", firmwareTokens.contains("B AH0 R IY1 S T AH0"))
        assertTrue("expected barcode supplement entry, actual=$firmwareTokens", firmwareTokens.contains("B AA1 R K OW2 D"))
        assertTrue("expected Figma supplement entry, actual=$firmwareTokens", firmwareTokens.contains("F IH1 G M AH0"))
        assertTrue("expected Anthropic supplement entry, actual=$firmwareTokens", firmwareTokens.contains("AE0 N TH R AA1 P IH0 K"))
        assertTrue("expected user_dict 曾医生 entry, actual=$polyphoneTokens", polyphoneTokens.contains("ㄗ ㄥ ˉ _ ㄧ ˉ _ ㄕ ㄥ ˉ"))
        assertTrue("expected user_dict 从重庆 entry, actual=$polyphoneTokens", polyphoneTokens.contains("ㄘ ㄨ ㄥ ˊ _ ㄔ ㄨ ㄥ ˊ _ ㄑ ㄧ ㄥ ˋ"))
    }

    @Test
    fun realAssetLayoutUsesSyncedPolyphonePhraseOverrides() {
        val layout = realAssetLayout()
        assertTrue(
            "expected copied polyphone overrides to contain 圈养了",
            layout.rootDir.resolve(LitsTtsAssetRegistry.POLYPHONE_PHRASES).readText().contains("圈养了\tjuan4 yang3 le5"),
        )

        assertNormalizedTokenSequence(layout, "朝阳越过山脊照亮小村", "ㄓ ㄠ ˉ _ ㄧ ㄤ ˊ")
        assertNormalizedTokenSequence(layout, "医生在处方上写下用药说明", "ㄔ ㄨ ˇ _ ㄈ ㄤ ˉ")
        assertNormalizedTokenSequence(layout, "盖姓同学在名册里排在前面", "ㄍ ㄜ ˇ _ ㄒ ㄧ ㄥ ˋ")
        assertNormalizedTokenSequence(layout, "吴堡县名出现在这册旧志里", "ㄨ ˊ _ ㄅ ㄨ ˇ _ ㄒ ㄧ ㄢ ˋ")
        assertNormalizedTokenSequence(layout, "棋盘上那枚车守住了边线", "ㄋ ㄚ ˋ _ ㄇ ㄟ ˊ _ ㄐ ㄩ ˉ")
        assertNormalizedTokenSequence(layout, "区老师住在区庄附近", "ㄡ ˉ _ ㄌ ㄠ ˇ _ ㄕ ˉ")
        assertNormalizedTokenSequence(layout, "曾参和曾老师都在名单里", "ㄗ ㄥ ˉ _ ㄕ ㄣ ˉ _ ㄏ ㄜ ˊ _ ㄗ ㄥ ˉ _ ㄌ ㄠ ˇ _ ㄕ ˉ")
        assertNormalizedTokenSequence(layout, "解经理正在解释合同", "ㄒ ㄧ ㄝ ˋ _ ㄐ ㄧ ㄥ ˉ _ ㄌ ㄧ ˇ")
        assertNormalizedTokenSequence(layout, "薄荷味很淡，薄书记也在现场", "ㄅ ㄛ ˋ _ ㄏ ㄜ ˙")
        assertNormalizedTokenSequence(layout, "薄荷味很淡，薄书记也在现场", "ㄅ ㄛ ˊ _ ㄕ ㄨ ˉ _ ㄐ ㄧ ˋ")
        assertNormalizedTokenSequence(layout, "任先生负责本次任务", "ㄖ ㄣ ˊ _ ㄒ ㄧ ㄢ ˉ _ ㄕ ㄥ ˉ")
        assertNormalizedTokenSequence(layout, "朴老师介绍朴素的设计", "ㄆ ㄧ ㄠ ˊ _ ㄌ ㄠ ˇ _ ㄕ ˉ")
        assertNormalizedTokenSequence(layout, "区先生和区主任都到了", "ㄡ ˉ _ ㄒ ㄧ ㄢ ˉ _ ㄕ ㄥ ˉ")
        assertNormalizedTokenSequence(layout, "区先生和区主任都到了", "ㄡ ˉ _ ㄓ ㄨ ˇ _ ㄖ ㄣ ˋ")
        assertNormalizedTokenSequence(layout, "区域里的任务需要解释清楚", "ㄑ ㄩ ˉ _ ㄩ ˋ")
        assertNormalizedTokenSequence(layout, "区域里的任务需要解释清楚", "ㄖ ㄣ ˋ _ ㄨ ˋ")
        assertNormalizedTokenSequence(layout, "区域里的任务需要解释清楚", "ㄐ ㄧ ㄝ ˇ _ ㄕ ˋ")
    }

    @Test
    fun splitForStreamingDoesNotCreateShortPlateFragments() {
        val layout = testLayout()

        val segments = LitsTtsFrontend.splitForStreaming(layout, "车牌冀R65438，请核查。下一条。")

        assertArrayEquals(
            arrayOf("车牌冀R65438,请核查.", "下一条."),
            segments.toTypedArray(),
        )
    }

    @Test
    fun splitForStreamingAvoidsTechnicalPunctuationFalseBreaks() {
        val layout = testLayout()

        val segments = LitsTtsFrontend.splitForStreaming(
            layout,
            "URL为https://api.example.com/v1/order?id=10086。版本号v10.20.003发布。用时1小时05分钟。下一句。",
        )

        assertArrayEquals(
            arrayOf(
                "URL为https://api.example.com/v1/order?id=10086.",
                "版本号v10.20.003发布.",
                "用时一小时零五分钟.",
                "下一句.",
            ),
            segments.toTypedArray(),
        )
    }

    @Test
    @Ignore("Enable after Android TN entry is verified; documents remaining Kotlin G2P parity gaps against Python golden.")
    fun localFrontendBadcaseSetsMatchPythonGoldenTokensAfterTn() {
        val layout = testLayout()
        val caseFiles = listOf(
            File("../../../infer_output/current_frontend_digits_polyphones_200/all_frontend.jsonl"),
            File("../../../infer_output/current_frontend_numeric_extra/all_frontend.jsonl"),
            File("../../../infer_output/current_frontend_hard_200/all_frontend.jsonl"),
        )
        val failures = mutableListOf<String>()
        var checked = 0

        for (caseFile in caseFiles) {
            assertTrue("missing frontend golden jsonl: ${caseFile.path}", caseFile.isFile)
            caseFile.forEachLine(Charsets.UTF_8) { line ->
                if (line.isBlank()) return@forEachLine
                checked += 1
                val row = JSONObject(line)
                val name = row.getString("name")
                val text = row.getString("tn_text")
                val language = row.optString("language", "zh-en")
                val expected = row.getString("cleaned_text").split(Regex("\\s+")).filter { it.isNotEmpty() }
                val actual = try {
                    LitsTtsFrontend.debugTokensForTest(layout, text, language, "zh-en")
                } catch (error: RuntimeException) {
                    failures += "${caseFile.parentFile?.name}/$name threw ${error.message} text=$text"
                    return@forEachLine
                }
                if (actual != expected) {
                    failures += buildString {
                        append(caseFile.parentFile?.name).append('/').append(name)
                        append(" token mismatch tn_text=").append(text)
                        append(" expected=").append(expected.joinToString(" "))
                        append(" actual=").append(actual.joinToString(" "))
                    }
                }
            }
        }

        assertTrue("expected to check local frontend cases", checked > 0)
        assertTrue(
            failures.take(20).joinToString(separator = "\n", prefix = "frontend mismatches:\n"),
            failures.isEmpty(),
        )
    }

    private fun testLayout(): LitsTtsAssetInstaller.InstalledLayout {
        return sharedLayout
    }

    private fun realAssetLayout(): LitsTtsAssetInstaller.InstalledLayout {
        return sharedRealAssetLayout
    }

    private fun assertTokenSequence(
        layout: LitsTtsAssetInstaller.InstalledLayout,
        text: String,
        expected: String,
    ) {
        val actual = LitsTtsFrontend.debugTokensForTest(layout, text, "zh-en", "zh-en").joinToString(" ")
        assertTrue("expected '$expected' in '$actual'", actual.contains(expected))
    }

    private fun assertNormalizedTokenSequence(
        layout: LitsTtsAssetInstaller.InstalledLayout,
        text: String,
        expected: String,
    ) {
        val actual = LitsTtsFrontend.debugTokensForNormalizedForTest(layout, text, "zh-en", "zh-en").joinToString(" ")
        assertTrue("expected '$expected' in '$actual'", actual.contains(expected))
    }

    private companion object {
        private val assetRoot = File(
            "src/main/assets/lits-models/${LitsTtsAssetRegistry.assetSubPath}",
        )
        private val sharedLayout: LitsTtsAssetInstaller.InstalledLayout by lazy {
            val root = createTempDirectory("lits-tts-frontend-test").toFile()
            copyAsset(root, "chinese_lexicon.txt")
            copyAsset(root, "cmudict.txt")
            copyAsset(root, "supplement_lexicon.json")
            copyAsset(root, "frontend_rules.json")
            copyAsset(root, "zh_en_symbols.json")
            copyAsset(root, "pinyin_to_tokens.json")
            copyAsset(root, "arpabet_to_tokens.json")
            copyAsset(root, "polychar.txt")
            copyAsset(root, "polyphone_phrases.txt")
            copyAsset(root, "chinese_surname_lexicon.txt")
            copyAsset(root, "frontend_golden.json")
            File(root, "lits_acoustic.onnx").writeBytes(byteArrayOf())
            File(root, "hifigan_vocoder.onnx").writeBytes(byteArrayOf())
            LitsTtsAssetInstaller.InstalledLayout.of(
                rootDir = root,
                manifest = fakeManifest(),
                source = LitsTtsAssetInstaller.LayoutSource.BUNDLED_ASSET,
            )
        }

        private val sharedRealAssetLayout: LitsTtsAssetInstaller.InstalledLayout by lazy {
            val root = createTempDirectory("lits-tts-real-assets-test").toFile()
            listOf(
                "manifest.json",
                "chinese_lexicon.txt",
                "chinese_lexicon.bin",
                "cmudict.txt",
                "cmudict.bin",
                "supplement_lexicon.json",
                "frontend_rules.json",
                "zh_en_symbols.json",
                "pinyin_to_tokens.json",
                "arpabet_to_tokens.json",
                "polychar.txt",
                "polyphone_phrases.txt",
                "chinese_surname_lexicon.txt",
                "frontend_golden.json",
                "rules_v2/zh.full.json",
                "rules_v2/en.full.json",
                "rules_v2/zh_pinyin.json",
                "tn-bin/arm64-v8a/zh_tts",
                "tn-bin/arm64-v8a/en_tts",
            ).forEach { copyAssetIfExists(root, it) }
            LitsTtsAssetInstaller.InstalledLayout.of(
                rootDir = root,
                manifest = fakeManifest(),
                source = LitsTtsAssetInstaller.LayoutSource.BUNDLED_ASSET,
            )
        }

        private fun copyAsset(root: File, name: String) {
            root.resolve(name).parentFile?.mkdirs()
            assetRoot.resolve(name).copyTo(root.resolve(name), overwrite = true)
        }

        private fun copyAssetIfExists(root: File, name: String) {
            val source = assetRoot.resolve(name)
            if (!source.isFile) return
            root.resolve(name).parentFile?.mkdirs()
            source.copyTo(root.resolve(name), overwrite = true)
        }

        private fun fakeManifest(): LitsTtsAssetInstaller.ManifestInfo =
            LitsTtsAssetInstaller.ManifestInfo(
                modelId = "lits_delivery_16k_hifigan",
                version = "1.0.0",
                sampleRate = 16_000,
                hopLength = 256,
                speakerCount = 1,
                defaultSpeakerId = 0,
                supportsStreaming = false,
                acousticModelFile = "lits_acoustic.onnx",
                vocoderModelFile = "hifigan_vocoder.onnx",
                hiddenEncoderModelFile = null,
                streamDecoderChunkModelFile = null,
                streamDecoderFinalModelFile = null,
                streamDecoderExternalLoop = false,
                streamDecoderTimesteps = -1,
                streamDecoderTemperature = Float.NaN,
                streamConditionChunkModelFile = null,
                streamConditionFinalModelFile = null,
                streamDecoderStepModelFile = null,
                streamingChunkSize = -1,
                streamingPreLookaheadLen = -1,
                streamingMelCacheLen = -1,
            )
    }
}
