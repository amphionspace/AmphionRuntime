package com.lits.tts.sdk.internal

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class StockCodeDeviceTest {
    @Test
    fun stockCodeDigitsSurviveNativeTnAndFrontend() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val workPath = requireNotNull(InstrumentationRegistry.getArguments().getString("workPath"))
        val layout = LitsTtsAssetInstaller.ensureInstalled(context, workPath)
        val rows = JSONArray()
        val reportFile = File(context.filesDir, "stock-code-${System.currentTimeMillis()}.json")
        var passed = false
        try {
            listOf(
                "股票代码 600519" to "股票代码 六零零五一九",
                "股票代码600519" to "股票代码六零零五一九",
                "股票 代码 000001" to "股票 代码 零零零零零一",
                "股票 600519" to "股票 六零零五一九",
                "数值600519" to "数值六十万零五百一十九",
                "股票代码6005190" to "股票代码六百万五千一百九十",
                "股票代码 600519 今日上涨 1.23%，请播报完整。" to
                    "股票代码 六零零五一九 今日上涨 百分之一点二三，请播报完整。",
            ).forEach { (raw, spoken) ->
                val normalized = LitsTnNormalizer.normalize(layout, raw, "zh-en", "zh-en")
                val profile = LitsTnNormalizer.lastProfileSummary().orEmpty()
                val expected = LitsTtsFrontend.encodeNormalized(layout, spoken, "zh-en", "zh-en")
                val actual = LitsTtsFrontend.encode(layout, raw, "zh-en", "zh-en")
                // The normalized-input entry bypasses native cardinal expansion.
                // Preserve its existing digit-by-digit reading for these controls.
                val preparedSpoken = when (raw) {
                    "数值600519" -> "数值六零零五一九"
                    "股票代码6005190" -> "股票代码六零零五一九零"
                    else -> spoken
                }
                // A raw digit run is a separate chunk without a leading boundary;
                // unlike a single hanzi chunk, it does not add '_' after its prefix.
                val preparedExpected = when (raw) {
                    "数值600519" -> LitsTtsFrontend.encodeNormalized(layout, "数值", "zh-en", "zh-en") +
                        LitsTtsFrontend.encodeNormalized(layout, "六零零五一九", "zh-en", "zh-en")
                    "股票代码6005190" -> LitsTtsFrontend.encodeNormalized(layout, "股票代码", "zh-en", "zh-en") +
                        LitsTtsFrontend.encodeNormalized(layout, "六零零五一九零", "zh-en", "zh-en")
                    else -> LitsTtsFrontend.encodeNormalized(layout, preparedSpoken, "zh-en", "zh-en")
                }
                val preparedActual = LitsTtsFrontend.encodeNormalized(layout, raw, "zh-en", "zh-en")
                val row = JSONObject().put("raw", raw).put("spoken", spoken).put("normalized", normalized)
                    .put("profile", profile).put("expected_tokens", JSONArray(expected.toList()))
                    .put("actual_tokens", JSONArray(actual.toList()))
                    .put("prepared_spoken", preparedSpoken)
                    .put("prepared_expected_tokens", JSONArray(preparedExpected.toList()))
                    .put("prepared_actual_tokens", JSONArray(preparedActual.toList()))
                rows.put(row)
                assertTrue("Native TN must run: $profile", profile.contains("nativeCalls=zh:"))
                assertArrayEquals(raw, expected, actual)
                assertArrayEquals("prepared: $raw", preparedExpected, preparedActual)
                row.put("pass", true)
            }
            assertEquals(7, rows.length())
            passed = true
        } finally {
            reportFile.writeText(JSONObject().put("pass", passed).put("cases", rows).toString(2))
            println("STOCK_CODE_REPORT=${reportFile.absolutePath}")
        }
    }
}
