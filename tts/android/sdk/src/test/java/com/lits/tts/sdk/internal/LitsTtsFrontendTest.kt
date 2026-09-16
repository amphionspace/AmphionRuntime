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
    @Test fun ordinalYiKeepsContextAcrossWhitespace() {
        val layout = realAssetLayout()
        for (text in listOf("第一百轮。", "第 一百 轮。", "第\t一百轮。")) {
            assertNormalizedTokenSequence(layout, text, "ㄉ ㄧ ˋ ㄧ ˉ ㄅ ㄞ ˇ")
        }
        assertNormalizedTokenSequence(layout, "第一百一十轮。", "ㄧ ˉ ㄕ ˊ")
        // A cardinal quantity must still take 一 sandhi; punctuation breaks ordinal context.
        assertNormalizedTokenSequence(layout, "一百轮。", "ㄧ ˋ ㄅ ㄞ ˇ")
        assertNormalizedTokenSequence(layout, "第，一百轮。", "ㄧ ˋ ㄅ ㄞ ˇ")
    }

    @Test fun pcmExtensionIsProtectedFromNativeUnitExpansion() {
        val normalized = LitsTnNormalizer.normalize(testLayout(), "文件 audio.pcm 已生成。", "zh-en", "zh-en")
        assertTrue(normalized, normalized.contains("P C M"))
        assertFalse(normalized, normalized.contains("pcm"))
    }

    @Test fun yiSandhiUsesCitationToneBeforeNeutralSyllablesAndKeepsDecimals() {
        val layout = testLayout()
        assertNormalizedTokenSequence(layout, "稍等一下。", "ㄧ ˊ ㄒ ㄧㄚ ˙")
        assertNormalizedTokenSequence(layout, "百分之一点二三。", "ㄧ ˉ ㄉ ㄧㄢ ˇ ㄦ ˋ ㄙ ㄢ ˉ")
        assertNormalizedTokenSequence(layout, "买一点水果。", "ㄧ ˋ ㄉ ㄧㄢ ˇ")
    }

    @Test fun orderIdsKeepDigitSequences() {
        val normalized = LitsTnNormalizer.normalize(testLayout(), "订单 ID 是 A12B11。", "zh-en", "zh-en")
        assertTrue(normalized, normalized.contains("A一二B一一"))
    }

    @Test fun numericPathKeepsEverySeparatorBeforeNativeTn() {
        val layout = testLayout()
        for (path in listOf("/sdcard/test/6/audio.wav", "/sdcard/test/18/audio.wav", "C:/Users/test/3/audio.pcm")) {
            val prepared = LitsTnNormalizer.normalize(layout, "路径 $path 已生成。", "zh-en", "zh-en")
            assertFalse(prepared, prepared.contains('/'))
            assertEquals(prepared, path.count { it == '/' }, Regex("斜杠").findAll(prepared).count())
        }
    }

    @Test fun spacedClocksPreserveLeadingZeroMinutes() {
        val layout = testLayout()
        for (raw in listOf("闹钟设为 5 点 05 分。", "闹钟设为5点05分。", "闹钟设为五点05分。")) {
            assertTrue(raw, LitsTnNormalizer.normalize(layout, raw, "zh-en", "zh-en").contains("五点零五分"))
        }
        assertTrue(LitsTnNormalizer.normalize(layout, "下午3:05开会。", "zh-en", "zh-en").contains("三点零五分"))
    }

    @Test fun percentCardinalsKeepInternalTensAndSupportThousands() {
        val layout = testLayout()
        for ((raw, spoken) in listOf("12%" to "百分之十二", "112%" to "百分之一百一十二",
            "1012%" to "百分之一千零一十二", "100010%" to "百分之十万零一十")) {
            assertEquals(raw, spoken, LitsTnNormalizer.normalize(layout, raw, "zh-en", "zh-en"))
            assertArrayEquals(raw, LitsTtsFrontend.encodeNormalized(layout, spoken, "zh-en", "zh-en"),
                LitsTtsFrontend.encodeNormalized(layout, raw, "zh-en", "zh-en"))
        }
    }

    @Test fun buildIdentifiersUseDigitsButQuantitiesUseCardinals() {
        val layout = testLayout()
        assertTrue(LitsTnNormalizer.normalize(layout, "build 20260702 已完成。", "zh-en", "zh-en").contains("二零二六零七零二"))
        assertTrue(LitsTnNormalizer.normalize(layout, "数量20260702个。", "zh-en", "zh-en").contains("二千零二十六万零七百零二"))
    }

    @Test fun volumeAndSerialContextResolvePolyphones() {
        val layout = testLayout()
        assertNormalizedTokenSequence(layout, "请把音量调到合适的大小。", "ㄊ ㄧㄠ ˊ ㄉ ㄠ ˋ")
        assertNormalizedTokenSequence(layout, "请求应该串行完成。", "ㄔ ㄨㄢ ˋ ㄒ ㄧㄥ ˊ")
        assertNormalizedTokenSequence(layout, "每个请求只终止一次。", "ㄓ ˇ ㄓ ㄨㄥ ˉ ㄓ ˇ")
        // Transfer uses diao: do not globally replace the ambiguous word 调到.
        assertNormalizedTokenSequence(layout, "他被调到北京。", "ㄉ ㄧㄠ ˋ ㄉ ㄠ ˋ")
    }

    @Test fun commonTechnicalWordsDoNotFallBackToLetterSpelling() {
        val layout = testLayout()
        assertNormalizedTokenSequence(layout, "SDK callback 已完成。", "K AO1 L B AE2 K")
        assertNormalizedTokenSequence(layout, "emoji 作为输入。", "IH0 M OW1 JH IY0")
        assertNormalizedTokenSequence(layout, "每个 requestId 都不同。", "R IH0 K W EH1 S T AY1 D IY1")
    }

    @Test
    fun sentenceColonBeforeEnglishRemainsPunctuation() {
        val layout = testLayout()
        for (colon in listOf(":", "：")) {
            for (suffix in listOf("Hello", "Room 204 is ready.", "The meeting starts at nine thirty.")) {
                val raw = "提示${colon}${suffix}"
                val spaced = "提示${colon} ${suffix}"
                val normalized = LitsTnNormalizer.normalize(layout, raw, "zh-en", "zh-en")
                assertFalse("$raw -> $normalized", normalized.contains("冒号"))
                assertArrayEquals(raw,
                    LitsTtsFrontend.encode(layout, spaced, "zh-en", "zh-en"),
                    LitsTtsFrontend.encode(layout, raw, "zh-en", "zh-en"))
                // Also cover callers that enter after native TN.
                assertArrayEquals(raw,
                    LitsTtsFrontend.encodeNormalized(layout, spaced, "zh-en", "zh-en"),
                    LitsTtsFrontend.encodeNormalized(layout, raw, "zh-en", "zh-en"))
            }
        }
        val english = LitsTnNormalizer.normalize(layout, ":Hello", "en-US", "en-US")
        assertFalse(english, english.contains("colon", ignoreCase = true))
    }

    @Test
    fun sentenceColonFixPreservesTimeAndUrlReadings() {
        val layout = testLayout()
        val time = LitsTnNormalizer.normalize(layout, "会议时间：9:30", "zh-en", "zh-en")
        assertEquals("会议时间:九点三十分", time)
        val url = LitsTnNormalizer.normalize(layout, "请访问https://example.com", "zh-en", "zh-en")
        assertEquals("请访问https冒号斜杠斜杠example点com", url)
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "提示：你好", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "提示:你好", "zh-en", "zh-en"))
    }

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
        // Technical tokens intentionally spell LITS as an acronym; the ordinary
        // lowercase word outside a technical token retains its lexicon reading.
        assertArrayEquals(
            LitsTtsFrontend.encodeNormalized(layout, "包名是com点LITS点tts点sample", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "包名是com.lits.tts.sample", "zh-en", "zh-en"),
        )
        assertFalse(
            LitsTtsFrontend.encode(layout, "包名是com点lits点tts点sample", "zh-en", "zh-en").contentEquals(
                LitsTtsFrontend.encode(layout, "包名是com.lits.tts.sample", "zh-en", "zh-en"),
            ),
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

        assertNormalizedTokenSequence(layout, "今天是 2026 年 7 月 2 日,下午 3:05 开会.", "ㄦ ˋ ㄌ ㄧㄥ ˊ ㄦ ˋ ㄌ ㄧㄡ ˋ ㄋ ㄧㄢ ˊ")
        assertNormalizedTokenSequence(layout, "今天是 2026 年 7 月 2 日,下午 3:05 开会.", "ㄙ ㄢ ˉ ㄉ ㄧㄢ ˇ ㄌ ㄧㄥ ˊ ㄨ ˇ")
        assertNormalizedTokenSequence(layout, "股票 600519 今日上涨 5.23百分号.", "ㄌ ㄧㄡ ˋ ㄌ ㄧㄥ ˊ ㄌ ㄧㄥ ˊ ㄨ ˇ ㄧ ˉ ㄐ ㄧㄡ ˇ")
        assertNormalizedTokenSequence(layout, "股票 600519 今日上涨 5.23百分号.", "ㄅ ㄞ ˇ ㄈ ㄣ ˉ ㄓ ˉ ㄨ ˊ ㄉ ㄧㄢ ˇ ㄦ ˋ ㄙ ㄢ ˉ")
        assertNormalizedTokenSequence(layout, "编号 1 的房间是 204,温度 -24.5 度.", "ㄦ ˋ ㄌ ㄧㄥ ˊ ㄙ ˋ")
        assertNormalizedTokenSequence(layout, "车牌号粤 B00009 已经入场.", "B IY1 _ ㄌ ㄧㄥ ˊ ㄌ ㄧㄥ ˊ ㄌ ㄧㄥ ˊ ㄌ ㄧㄥ ˊ ㄐ ㄧㄡ ˇ")
        assertNormalizedTokenSequence(layout, "身份证尾号 010X,请核对.", "ㄌ ㄧㄥ ˊ ㄧ ˉ ㄌ ㄧㄥ ˊ _ EH1 K S")
        assertNormalizedTokenSequence(layout, "版本 v3.0.7 与 build 20260702 对齐.", "V IY1 _ ㄙ ㄢ ˉ ㄉ ㄧㄢ ˇ ㄌ ㄧㄥ ˊ ㄉ ㄧㄢ ˇ ㄑ ㄧ ˉ")
        assertNormalizedTokenSequence(layout, "路径 斜杠sdcard斜杠test斜杠18斜杠audio.wav 已生成.", "ㄧ ˉ ㄅ ㄚ ˉ")
        assertNormalizedTokenSequence(layout, "坐标 N22.12 E113.11,导航继续.", "ㄅ ㄟ ˊ ㄨㄟ ˇ ㄦ ˋ ㄕ ˊ ㄦ ˋ ㄉ ㄧㄢ ˇ ㄧ ˉ ㄦ ˋ")
        assertNormalizedTokenSequence(layout, "速度 80km斜杠h,距离目的地 11.5 公里.", "ㄅ ㄚ ˉ ㄕ ˊ ㄑ ㄧㄢ ˉ ㄇ ㄧ ˊ ㄇ ㄟ ˊ ㄒ ㄧㄠ ˇ ㄕ ˊ")
    }

    @Test
    fun stockCodeLabelProtectsDigitsBeforeNativeTn() {
        val layout = testLayout()
        listOf(
            "股票代码 600519" to "股票代码 六零零五一九",
            "股票代码600519" to "股票代码六零零五一九",
            "股票 代码 000001" to "股票 代码 零零零零零一",
            "股票 600519" to "股票 六零零五一九",
        ).forEach { (raw, spoken) ->
            assertEquals(raw, spoken, LitsTnNormalizer.normalize(layout, raw, "zh-en", "zh-en"))
            val expected = LitsTtsFrontend.encodeNormalized(layout, spoken, "zh-en", "zh-en")
            assertArrayEquals("raw: $raw", expected, LitsTtsFrontend.encode(layout, raw, "zh-en", "zh-en"))
            assertArrayEquals("prepared: $raw", expected, LitsTtsFrontend.encodeNormalized(layout, raw, "zh-en", "zh-en"))
        }
    }

    @Test
    fun stockCodeProtectionKeepsOtherNumericContexts() {
        val layout = testLayout()
        listOf("数值600519", "代码600519", "股票代码12345").forEach { raw ->
            assertEquals(raw, raw, LitsTnNormalizer.normalize(layout, raw, "zh-en", "zh-en"))
        }
        assertEquals("股票代码六百万五千一百九十", LitsTnNormalizer.normalize(layout, "股票代码6005190", "zh-en", "zh-en"))
        assertEquals("Stock code 600519", LitsTnNormalizer.normalize(layout, "Stock code 600519", "en-US", "en-US"))
        listOf(Triple("数值600519", "数值", "六零零五一九"), Triple("股票代码6005190", "股票代码", "六零零五一九零")).forEach { (raw, prefix, digits) ->
            assertArrayEquals(raw,
                LitsTtsFrontend.encodeNormalized(layout, prefix + digits, "zh-en", "zh-en"),
                LitsTtsFrontend.encodeNormalized(layout, raw, "zh-en", "zh-en"))
        }
    }

    @Test
    fun zhEnTechnicalTnContextsUseCodeAndSymbolReadings() {
        val layout = testLayout()

        assertNormalizedTokenSequence(layout, "请访问 https:斜杠斜杠example.com斜杠help斜杠1?q等于lits-v3.", "ㄧ ˉ _ , _ ㄨㄣ ˋ ㄏ ㄠ ˋ")
        assertNormalizedTokenSequence(layout, "请访问 https:斜杠斜杠example.com斜杠help斜杠1?q等于lits-v3.", "EH1 L AY1 T IY1 EH1 S")
        assertNormalizedTokenSequence(layout, "A斜杠B 测试组 16 的 F1-score 是 0.16.", "EH1 F _ ㄧ ˉ _ , _ ㄍ ㄤ ˋ _ S K AO1 R")
        assertNormalizedTokenSequence(layout, "错误码 TTS_8_TIMEOUT 只作为普通文本.", "T IY1 T IY1 EH1 S _ AH2 N D ER0 S K AO1 R _ ㄅ ㄚ ˉ _ , _ AH2 N D ER0 S K AO1 R _ T AY1 M AW1 T")
        assertNormalizedTokenSequence(layout, "包名 com.lits.tts.sample9 应按规则处理.", "K AA1 M _ ㄉ ㄧㄢ ˇ _ EH1 L AY1 T IY1 EH1 S")
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
    fun zhEnNumericReadingsMatchSpokenForms() {
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
            LitsTtsFrontend.encode(layout, "出生日期1998年二月九日", "zh-en", "zh-en"),
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
    }

    @Test
    fun zhEnVersionSuffixKeepsTechnicalDigitReadings() {
        val layout = testLayout()
        // The technical-token contract added in 75e48aee reads each digit and
        // retains its separator pauses; it is not the older macOS cardinal rule.
        assertArrayEquals(
            LitsTtsFrontend.encodeNormalized(layout, "firmware 二,点零,点一零,杠beta需要灰度", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "firmware 2.0.10-beta需要灰度", "zh-en", "zh-en"),
        )
    }

    @Test
    fun zhEnPathKeepsTechnicalUnderscoreReading() {
        val layout = testLayout()
        // As for TTS_8_TIMEOUT above, '_' in a technical token is spoken in
        // English. A lowercase prose "underscore" is a different input contract.
        assertArrayEquals(
            LitsTtsFrontend.encodeNormalized(layout, "路径是斜杠home斜杠user斜杠report UNDERSCORE 二零二六,点csv", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "路径是/home/user/report_2026.csv", "zh-en", "zh-en"),
        )
    }

    @Test
    fun zhEnUrlQueryValueMatchesSpokenDigits() {
        val layout = testLayout()
        // Do not run a partly expanded reference containing "123" through TN:
        // it no longer has the technical-token context of the raw URL.
        assertArrayEquals(
            LitsTtsFrontend.encodeNormalized(layout, "URL是www点example点com斜杠test问号id等于一二三", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "URL是www.example.com/test?id=123", "zh-en", "zh-en"),
        )
    }

    @Test
    fun zhEnCalendarPaddingMatchesNativeCardinalReading() {
        val layout = testLayout()
        // The real native TN emits 二月九日, as does the separator-date path.
        val expected = LitsTtsFrontend.encodeNormalized(layout, "出生日期一九九八年二月九日", "zh-en", "zh-en")
        listOf("出生日期1998年02月09日", "出生日期1998年2月09日", "出生日期1998-02-09").forEach { raw ->
            assertArrayEquals(raw, expected, LitsTtsFrontend.encode(layout, raw, "zh-en", "zh-en"))
        }
        assertArrayEquals(expected,
            LitsTtsFrontend.encodeNormalized(layout, "出生日期1998年02月09日", "zh-en", "zh-en"))
        val explicitZero = "出生日期一九九八年零二月零九日"
        val explicitTokens = LitsTtsFrontend.encodeNormalized(layout, explicitZero, "zh-en", "zh-en")
        assertFalse("Explicit Hanzi zero must remain spoken", expected.contentEquals(explicitTokens))
        assertArrayEquals(explicitTokens, LitsTtsFrontend.encode(layout, explicitZero, "zh-en", "zh-en"))
    }

    @Test
    fun zhEnCalendarMonthsStillNormalizeAfterYearExpansion() {
        val layout = testLayout()
        listOf(
            "出生日期1998年2月09日" to "出生日期一九九八年二月九日",
            "出生日期一九九八年2月09日" to "出生日期一九九八年二月九日",
            "出生日期1998年02月09日" to "出生日期一九九八年二月九日",
            "日期2026年12月31日" to "日期二零二六年十二月三十一日",
        ).forEach { (raw, spoken) ->
            val expected = LitsTtsFrontend.encodeNormalized(layout, spoken, "zh-en", "zh-en")
            assertArrayEquals("raw: $raw", expected, LitsTtsFrontend.encode(layout, raw, "zh-en", "zh-en"))
            assertArrayEquals("prepared: $raw", expected, LitsTtsFrontend.encodeNormalized(layout, raw, "zh-en", "zh-en"))
        }
    }

    @Test
    fun negativeTemperatureReadingsAreIndependentOfWhitespace() {
        val layout = testLayout()
        listOf(
            "气温-24.5度" to "气温零下二十四点五度",
            "气温 -24.5 度" to "气温零下二十四点五度",
            "温度  -  5 度" to "温度零下五度",
            "体温-0.5度" to "体温零下零点五度",
            "温度范围是-5到10度" to "温度范围是零下五到十度",
            "温度范围是 -5 到 10 度" to "温度范围是零下五到十度",
            "温度范围是  -  5  到  10  度" to "温度范围是零下五到十度",
        ).forEach { (raw, spoken) ->
            // Assert the pre-native text as well as tokens: a downstream repair must
            // not conceal a native TN input that already lost the temperature context.
            assertEquals(raw, spoken, LitsTnNormalizer.normalize(layout, raw, "zh-en", "zh-en"))
            assertArrayEquals(
                raw,
                LitsTtsFrontend.encodeNormalized(layout, spoken, "zh-en", "zh-en"),
                LitsTtsFrontend.encode(layout, raw, "zh-en", "zh-en"),
            )
        }
    }

    @Test
    fun temperatureProtectionDoesNotChangeOtherNumericContexts() {
        val layout = testLayout()
        listOf(
            "气温24.5度" to "气温24.5度",
            "温度范围是5到10度" to "温度范围是5到10度",
            "数值 -24.5" to "数值 负24.5",
            "比分1-2" to "比分1-2",
        ).forEach { (raw, prepared) ->
            assertEquals(raw, prepared, LitsTnNormalizer.normalize(layout, raw, "zh-en", "zh-en"))
        }
        assertEquals(
            "Temperature -24.5 degrees",
            LitsTnNormalizer.normalize(layout, "Temperature -24.5 degrees", "en-US", "en-US"),
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

        assertTokenSequence(layout, "一辆车。", "ㄧ ˊ ㄌ ㄧㄤ ˋ")
        assertTokenSequence(layout, "一条鱼。", "ㄧ ˋ ㄊ ㄧㄠ ˊ")
        assertTokenSequence(layout, "一个城市。", "ㄧ ˊ ㄍ ㄜ ˋ")
        assertTokenSequence(layout, "不对。", "ㄅ ㄨ ˊ ㄉ ㄨㄟ ˋ")
        assertTokenSequence(layout, "看一看。", "ㄎ ㄢ ˋ ㄧ ˙ ㄎ ㄢ ˋ")
        assertTokenSequence(layout, "花儿。", "ㄏ ㄨㄚ ˉ ㄦ ˙")
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

        assertTrue("expected 已为你 with 为 as fourth tone, actual=$actual", actual.contains("ㄧ ˇ ㄨㄟ ˋ ㄋ ㄧ ˇ ㄕ ㄜ ˋ"))
    }

    @Test
    fun splitRawForStreamingUsesStrongChinesePunctuation() {
        val segments = LitsTtsFrontend.splitRawForStreaming("你好。欢迎使用语音合成系统！请稍等。")

        assertArrayEquals(
            arrayOf("你好。", "欢迎使用语音合成系统！", "请稍等。"),
            segments.toTypedArray(),
        )
    }

    @Test
    fun splitRawForStreamingAvoidsEnglishPunctuationFalseBreaks() {
        val segments = LitsTtsFrontend.splitRawForStreaming(
            "Hello world. Dr. Smith paid 3.14 dollars at 10:30 a.m. Visit example.com/test. Done.",
            // Isolate punctuation decisions from the independently tested length target.
            targetCharsPerSegment = 100,
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
    fun splitRawForStreamingPreservesEnglishInputForEncoding() {
        val layout = testLayout()

        val segments = LitsTtsFrontend.splitRawForStreaming(
            text = "Welcome to the Lits delivery TTS sample. Room 204 is ready.",
        )

        assertArrayEquals(
            arrayOf(
                "Welcome to the Lits delivery TTS sample.",
                "Room 204 is ready.",
            ),
            segments.toTypedArray(),
        )
        assertTrue(
            LitsTtsFrontend.encode(layout, segments[1], "en-US", "en-US").isNotEmpty(),
        )
    }

    @Test
    fun splitRawForStreamingCapsLongChineseSegmentsWithoutDroppingText() {
        val text = "这是一段没有标点的测试文本".repeat(8)
        val segments = LitsTtsFrontend.splitRawForStreaming(text)
        assertTrue(segments.size > 1)
        assertEquals(text, segments.joinToString(""))
        assertTrue(segments.all { it.length <= 50 })
        assertTrue(segments.dropLast(1).all { it.length == 50 })
    }

    @Test
    fun splitRawForStreamingPreservesAsciiTokensAcrossLengthBoundary() {
        val prefix = "前".repeat(49)
        listOf(
            "recognition", "example.com/test", "https://api.example.com/v1?id=123",
            "USB-C", "don't", "3.14", "10:30", "1,000,000.00", "file_name.ext",
            "support-team@example.com", "v10.20.003",
        ).forEach { token ->
            assertArrayEquals(token, arrayOf("$prefix$token。", "下一句。"),
                LitsTtsFrontend.splitRawForStreaming("$prefix$token。下一句。").toTypedArray())
        }
    }

    @Test
    fun splitRawForStreamingKeepsOversizedTechnicalTokenIntact() {
        val url = "https://example.com/" + "long-path/".repeat(12) + "?id=123"
        assertArrayEquals(arrayOf("$url.", "Done."),
            LitsTtsFrontend.splitRawForStreaming("$url. Done.").toTypedArray())
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

        assertTokenSequence(layout, "听音乐。", "ㄧㄣ ˉ ㄩㄝ ˋ")
        assertTokenSequence(layout, "成都是一个美食之都。", "ㄕ ˋ ㄧ ˊ ㄍ ㄜ ˋ ㄇ ㄟ ˇ")
        assertTokenSequence(layout, "成都是一个美食之都。", "ㄇ ㄟ ˇ ㄕ ˊ ㄓ ˉ ㄉ ㄨ ˉ")
        assertTokenSequence(layout, "重庆市人民医院的曾医生今天接诊。", "ㄗ ㄥ ˉ ㄧ ˉ ㄕ ㄥ ˉ")
        assertTokenSequence(layout, "单县来的单老师重新核对名单。", "ㄕ ㄢ ˋ ㄌ ㄠ ˇ ㄕ ˉ")
        assertTokenSequence(layout, "解律师在解放路口说明合同。", "ㄒ ㄧㄝ ˋ ㄌ ㄩ ˋ ㄕ ˉ")
        assertTokenSequence(layout, "仇工程师并不记仇。", "ㄑ ㄧㄡ ˊ ㄍ ㄨㄥ ˉ ㄔ ㄥ ˊ ㄕ ˉ")
        assertTokenSequence(layout, "朴顾问建议保持朴素风格。", "ㄆ ㄧㄠ ˊ ㄍ ㄨ ˋ ㄨㄣ ˋ")
        assertTokenSequence(layout, "区记者从南海区发回报道。", "ㄡ ˉ ㄐ ㄧ ˋ ㄓ ㄜ ˇ")
        assertTokenSequence(layout, "华教授研究华山碑刻。", "ㄏ ㄨㄚ ˋ ㄐ ㄧㄠ ˋ ㄕ ㄡ ˋ")
        assertTokenSequence(layout, "燕法官出生在燕郊。", "ㄧㄢ ˉ ㄈ ㄚ ˇ ㄍ ㄨㄢ ˉ")
        assertTokenSequence(layout, "曾宁从重庆飞到长沙。", "ㄘ ㄨㄥ ˊ ㄔ ㄨㄥ ˊ ㄑ ㄧㄥ ˋ")
    }

    @Test
    fun zhEnJingzangExpresswayUsesTibetanReading() {
        val layout = testLayout()
        assertTokenSequence(layout, "京藏高速。", "ㄐ ㄧㄥ ˉ ㄗ ㄤ ˋ ㄍ ㄠ ˉ ㄙ ㄨ ˋ")
        assertTokenSequence(layout, "京藏（zang）高速", "ㄐ ㄧㄥ ˉ ㄗ ㄤ ˋ")
    }

    @Test
    fun zhEnPoliceCaseIdInChineseBracketsDoesNotEmitUnsupportedBracketTokens() {
        val layout = testLayout()

        assertTrue(
            LitsTtsFrontend.encode(
                layout,
                "已存在【C10194368】警单待处置，请继续完成处置操作。",
                "zh-en",
                "zh-en",
            ).isNotEmpty(),
        )
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
        assertTrue("expected user_dict 曾医生 entry, actual=$polyphoneTokens", polyphoneTokens.contains("ㄗ ㄥ ˉ ㄧ ˉ ㄕ ㄥ ˉ"))
        assertTrue("expected user_dict 从重庆 entry, actual=$polyphoneTokens", polyphoneTokens.contains("ㄘ ㄨㄥ ˊ ㄔ ㄨㄥ ˊ ㄑ ㄧㄥ ˋ"))
    }

    @Test
    fun realAssetLayoutUsesSyncedPolyphonePhraseOverrides() {
        val layout = realAssetLayout()
        assertTrue(
            "expected copied polyphone overrides to contain 圈养了",
            layout.rootDir.resolve(LitsTtsAssetRegistry.POLYPHONE_PHRASES).readText().contains("圈养了\tjuan4 yang3 le5"),
        )

        assertNormalizedTokenSequence(layout, "朝阳越过山脊照亮小村", "ㄓ ㄠ ˉ ㄧㄤ ˊ")
        assertNormalizedTokenSequence(layout, "医生在处方上写下用药说明", "ㄔ ㄨ ˇ ㄈ ㄤ ˉ")
        assertNormalizedTokenSequence(layout, "盖姓同学在名册里排在前面", "ㄍ ㄜ ˇ ㄒ ㄧㄥ ˋ")
        assertNormalizedTokenSequence(layout, "吴堡县名出现在这册旧志里", "ㄨ ˊ ㄅ ㄨ ˇ ㄒ ㄧㄢ ˋ")
        assertNormalizedTokenSequence(layout, "棋盘上那枚车守住了边线", "ㄋ ㄚ ˋ ㄇ ㄟ ˊ ㄐ ㄩ ˉ")
        assertNormalizedTokenSequence(layout, "区老师住在区庄附近", "ㄡ ˉ ㄌ ㄠ ˇ ㄕ ˉ")
        assertNormalizedTokenSequence(layout, "曾参和曾老师都在名单里", "ㄗ ㄥ ˉ ㄕ ㄣ ˉ ㄏ ㄜ ˊ ㄗ ㄥ ˉ ㄌ ㄠ ˇ ㄕ ˉ")
        assertNormalizedTokenSequence(layout, "解经理正在解释合同", "ㄒ ㄧㄝ ˋ ㄐ ㄧㄥ ˉ ㄌ ㄧ ˇ")
        assertNormalizedTokenSequence(layout, "薄荷味很淡，薄书记也在现场", "ㄅ ㄛ ˋ ㄏ ㄜ ˙")
        assertNormalizedTokenSequence(layout, "薄荷味很淡，薄书记也在现场", "ㄅ ㄛ ˊ ㄕ ㄨ ˉ ㄐ ㄧ ˋ")
        assertNormalizedTokenSequence(layout, "任先生负责本次任务", "ㄖ ㄣ ˊ ㄒ ㄧㄢ ˉ ㄕ ㄥ ˉ")
        assertNormalizedTokenSequence(layout, "朴老师介绍朴素的设计", "ㄆ ㄧㄠ ˊ ㄌ ㄠ ˇ ㄕ ˉ")
        assertNormalizedTokenSequence(layout, "区先生和区主任都到了", "ㄡ ˉ ㄒ ㄧㄢ ˉ ㄕ ㄥ ˉ")
        assertNormalizedTokenSequence(layout, "区先生和区主任都到了", "ㄡ ˉ ㄓ ㄨ ˇ ㄖ ㄣ ˋ")
        assertNormalizedTokenSequence(layout, "区域里的任务需要解释清楚", "ㄑ ㄩ ˉ ㄩ ˋ")
        assertNormalizedTokenSequence(layout, "区域里的任务需要解释清楚", "ㄖ ㄣ ˋ ㄨ ˋ")
        assertNormalizedTokenSequence(layout, "区域里的任务需要解释清楚", "ㄐ ㄧㄝ ˇ ㄕ ˋ")
    }

    @Test
    fun splitRawForStreamingDoesNotCreateShortPlateFragments() {
        val segments = LitsTtsFrontend.splitRawForStreaming("车牌冀R65438，请核查。下一条。")

        assertArrayEquals(
            arrayOf("车牌冀R65438，请核查。", "下一条。"),
            segments.toTypedArray(),
        )
    }

    @Test
    fun splitRawForStreamingAvoidsTechnicalPunctuationFalseBreaks() {
        val segments = LitsTtsFrontend.splitRawForStreaming(
            "URL为https://api.example.com/v1/order?id=10086。版本号v10.20.003发布。用时1小时05分钟。下一句。",
        )

        assertArrayEquals(
            arrayOf(
                "URL为https://api.example.com/v1/order?id=10086。",
                "版本号v10.20.003发布。",
                "用时1小时05分钟。",
                "下一句。",
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
        private val assetRoot = TtsTestAssets.root()
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
