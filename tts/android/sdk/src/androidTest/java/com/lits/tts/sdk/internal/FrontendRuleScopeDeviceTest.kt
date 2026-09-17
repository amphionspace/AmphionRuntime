package com.lits.tts.sdk.internal

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FrontendRuleScopeDeviceTest {
    @Test fun mainlandNumberReadingsSurviveNativeTnAndG2p() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val workPath = requireNotNull(InstrumentationRegistry.getArguments().getString("workPath"))
        val layout = LitsTtsAssetInstaller.ensureInstalled(context, workPath)
        val rows = JSONArray()
        try {
            for ((text, spoken) in listOf(
                "手机号：13800138000。" to "幺三八零零幺三八零零零",
                "电话是 138-0013-8000。" to "幺三八零零幺三八零零零",
                "手机号码 138 0013 8000。" to "幺三八零零幺三八零零零",
                "身份证号：11010119900101123X。" to "一一零一零一一九九零零一零一一二三",
                "身份证号码 110101 19900101 123x。" to "一一零一零一一九九零零一零一一二三",
                "身份证 110101900101123。" to "一一零一零一九零零一零一一二三",
                "金额13800138000元。" to "一百三十八亿",
                "订单号13800138000。" to "一百三十八亿",
            )) {
                val tn = LitsTnNormalizer.normalize(layout, text, "zh-en", "zh-en")
                val tokens = LitsTtsFrontend.debugTokensForNormalizedForTest(layout, tn, "zh-en", "zh-en").joinToString(" ")
                rows.put(JSONObject().put("text", text).put("tn", tn).put("tokens", tokens))
                assertTrue("$text -> $tn", tn.contains(spoken))
                if (text.startsWith("手机") || text.startsWith("电话")) {
                    assertTrue(tokens, tokens.contains("ㄧㄠ ˉ ㄙ ㄢ ˉ ㄅ ㄚ ˉ"))
                }
                if (text.startsWith("身份证")) {
                    assertTrue(tokens, tokens.contains("ㄧ ˉ ㄧ ˉ ㄌ ㄧㄥ ˊ"))
                    if (text.contains('X') || text.contains('x')) assertTrue(tokens, tokens.contains("EH1 K S"))
                }
            }
        } finally {
            File(context.getExternalFilesDir(null), "mainland-number-readings.json").writeText(rows.toString(2))
        }
    }

    @Test fun nativeTnAndFrontendPreserveUnrelatedReadings() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val workPath = requireNotNull(InstrumentationRegistry.getArguments().getString("workPath"))
        val layout = LitsTtsAssetInstaller.ensureInstalled(context, workPath)
        val rows = JSONArray()
        try {
            for ((text, expected) in listOf(
                "We will build 12 houses." to "T W EH1 L V",
                "买一点三文鱼。" to "ㄧ ˋ ㄉ ㄧㄢ",
                "买一点五花肉。" to "ㄧ ˋ ㄉ ㄧㄢ",
                "打印一串行号。" to "ㄏ ㄤ ˊ",
                "一只终止鸣叫的蝉。" to "ㄓ ˉ ㄓ ㄨㄥ",
                "请求应该串行完成。" to "ㄔ ㄨㄢ ˋ ㄒ ㄧㄥ ˊ",
                "每个请求只终止一次。" to "ㄓ ˇ ㄓ ㄨㄥ",
                "百分之一点二三。" to "ㄧ ˉ ㄉ ㄧㄢ",
                "版本 v3.0.19 与 build 20260702 对齐。" to "B IH1 L D",
            )) {
                val tn = LitsTnNormalizer.normalize(layout, text, "zh-en", "zh-en")
                val tokens = LitsTtsFrontend.debugTokensForNormalizedForTest(layout, tn, "zh-en", "zh-en").joinToString(" ")
                rows.put(JSONObject().put("text", text).put("tn", tn).put("tokens", tokens).put("expected", expected))
                assertTrue("$text -> $tn -> $tokens", tokens.contains(expected))
                if (text.startsWith("We")) assertFalse(tn, tn.any { it in '\u4e00'..'\u9fff' })
                if (text.startsWith("版本")) assertTrue(tn, tn.contains("二零二六零七零二"))
            }
        } finally {
            File(context.getExternalFilesDir(null), "frontend-rule-scope.json").writeText(rows.toString(2))
        }
    }
}
