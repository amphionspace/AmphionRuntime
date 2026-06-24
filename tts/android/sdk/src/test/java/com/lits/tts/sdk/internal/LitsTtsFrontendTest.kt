package com.lits.tts.sdk.internal

import java.io.File
import kotlin.io.path.createTempDirectory
import org.junit.Assert.assertArrayEquals
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
            LitsTtsFrontend.encode(layout, "温度范围是零下五到十度", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "温度范围是-5到10度", "zh-en", "zh-en"),
        )
        assertArrayEquals(
            LitsTtsFrontend.encode(layout, "闹钟设为七点零五分", "zh-en", "zh-en"),
            LitsTtsFrontend.encode(layout, "闹钟设为7点05分", "zh-en", "zh-en"),
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
            TranssionTnNormalizer.preserveSegmentWhitespace(" 204 ", "二百零四") == " 二百零四 ",
        )
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

    private fun assertTokenSequence(
        layout: LitsTtsAssetInstaller.InstalledLayout,
        text: String,
        expected: String,
    ) {
        val actual = LitsTtsFrontend.debugTokensForTest(layout, text, "zh-en", "zh-en").joinToString(" ")
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
            copyAsset(root, "zh_en_symbols.json")
            copyAsset(root, "pinyin_to_tokens.json")
            copyAsset(root, "arpabet_to_tokens.json")
            copyAsset(root, "polychar.txt")
            copyAsset(root, "frontend_golden.json")
            File(root, "lits_acoustic.onnx").writeBytes(byteArrayOf())
            File(root, "hifigan_vocoder.onnx").writeBytes(byteArrayOf())
            LitsTtsAssetInstaller.InstalledLayout.of(
                rootDir = root,
                manifest = LitsTtsAssetInstaller.ManifestInfo(
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
                ),
                source = LitsTtsAssetInstaller.LayoutSource.BUNDLED_ASSET,
            )
        }

        private fun copyAsset(root: File, name: String) {
            assetRoot.resolve(name).copyTo(root.resolve(name), overwrite = true)
        }
    }
}
