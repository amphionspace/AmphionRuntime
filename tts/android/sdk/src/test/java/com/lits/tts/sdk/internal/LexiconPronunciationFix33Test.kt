package com.lits.tts.sdk.internal

import java.io.File
import kotlin.io.path.createTempDirectory
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 3.3 词典读音修复回归：用真实前端 + 本次交付的模型资源，核对客户反馈词的拼音。
 * 反馈：成都南站的"南"读 na；补充：缺词的"重做/重跑/重测/重拨"退回 zhong4。
 */
class LexiconPronunciationFix33Test {
    private fun layout(): LitsTtsAssetInstaller.InstalledLayout {
        val assetRoot = TtsTestAssets.root()
        val root = createTempDirectory("lits-tts-lexicon-fix-33").toFile()
        listOf(
            "manifest.json", "chinese_lexicon.txt", "cmudict.txt", "supplement_lexicon.json", "frontend_rules.json",
            "zh_en_symbols.json", "pinyin_to_tokens.json", "arpabet_to_tokens.json", "polychar.txt", "polyphone_phrases.txt",
            "chinese_surname_lexicon.txt", "frontend_golden.json", "rules_v2/zh.full.json", "rules_v2/en.full.json", "rules_v2/zh_pinyin.json",
            "chinese_lexicon.bin", "cmudict.bin", "polyphone_context.txt",
        ).forEach { name ->
            val src = assetRoot.resolve(name)
            if (src.isFile) { root.resolve(name).parentFile?.mkdirs(); src.copyTo(root.resolve(name), overwrite = true) }
        }
        return LitsTtsAssetInstaller.InstalledLayout.of(
            rootDir = root,
            manifest = LitsTtsAssetInstaller.parseAndValidateManifest(root.resolve("manifest.json")),
            source = LitsTtsAssetInstaller.LayoutSource.BUNDLED_ASSET,
        )
    }

    /** 把前端 token 串按 pinyin_to_tokens 反查回拼音；同音同调的 2/6 调号映射到同一 token，统一归一到首个登记键。 */
    private fun pinyinOf(layout: LitsTtsAssetInstaller.InstalledLayout, text: String): List<String> {
        val table = JSONObject(layout.rootDir.resolve("pinyin_to_tokens.json").readText()).getJSONObject("pinyin_to_tokens")
        val reverse = HashMap<String, String>()
        table.keys().forEach { py ->
            val arr = table.getJSONArray(py); val key = (0 until arr.length()).joinToString("|") { arr.getString(it) }
            val existing = reverse[key]
            if (existing == null || py < existing) reverse[key] = py
        }
        val tokens = LitsTtsFrontend.debugTokensForNormalizedForTest(layout, text, "zh-en", "zh-en")
        val out = ArrayList<String>(); var i = 0
        while (i < tokens.size) {
            var matched = false
            for (len in minOf(5, tokens.size - i) downTo 1) {
                val py = reverse[tokens.subList(i, i + len).joinToString("|")]
                if (py != null) { out += py; i += len; matched = true; break }
            }
            if (!matched) i += 1
        }
        return out
    }

    @Test
    fun southStationAndChongWordsReadCorrectly() {
        val layout = layout()
        val cases = mapOf(
            "成都南站" to listOf("cheng2", "du1", "nan2", "zhan4"),
            "广州南站" to listOf("guang3", "zhou1", "nan2", "zhan4"),
            "南昆线" to listOf("nan2", "kun1", "xian4"),
            "重试" to listOf("chong2", "shi4"),
            "重做" to listOf("chong2", "zuo4"),
            "重跑" to listOf("chong2", "pao3"),
            "重拨" to listOf("chong2", "bo1"),
            "重庆北站" to listOf("chong2", "qing4", "bei3", "zhan4"),
            "南无阿弥陀佛" to listOf("na1", "mo2", "e1", "mi2", "tuo2", "fo2"),
        )
        cases.forEach { (text, expected) ->
            assertEquals("pinyin of $text", expected, pinyinOf(layout, text))
        }
    }
}
