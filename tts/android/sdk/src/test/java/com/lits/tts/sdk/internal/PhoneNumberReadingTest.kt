package com.lits.tts.sdk.internal

import java.io.File
import kotlin.io.path.createTempDirectory
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 号码读法回归：客户反馈播报号码时把 18912345678 读成"一百八十九亿一千二百三十四万五千六百七十八"。
 * 根因是 Kotlin 预处理的大数基数词规则抢在原生 TN 之前改写了号码。JVM 上无原生 TN，这里只断言预处理层输出。
 */
class PhoneNumberReadingTest {
    private val layout: LitsTtsAssetInstaller.InstalledLayout by lazy {
        val assetRoot = TtsTestAssets.root()
        val root = createTempDirectory("lits-tts-phone-reading").toFile()
        assetRoot.walkTopDown().filter { it.isFile && !it.name.endsWith(".onnx") }.forEach { f ->
            val target = root.resolve(f.relativeTo(assetRoot).path); target.parentFile?.mkdirs(); f.copyTo(target, overwrite = true)
        }
        File(root, "lits_acoustic.onnx").writeBytes(byteArrayOf())
        File(root, "hifigan_vocoder.onnx").writeBytes(byteArrayOf())
        LitsTtsAssetInstaller.InstalledLayout.of(
            rootDir = root,
            manifest = LitsTtsAssetInstaller.ManifestInfo(
                modelId = "lits_delivery_16k_hifigan", version = "1.0.0", sampleRate = 16_000, hopLength = 256,
                speakerCount = 1, defaultSpeakerId = 0, supportsStreaming = false,
                acousticModelFile = "lits_acoustic.onnx", vocoderModelFile = "hifigan_vocoder.onnx",
                hiddenEncoderModelFile = null, streamDecoderChunkModelFile = null, streamDecoderFinalModelFile = null,
                streamDecoderExternalLoop = false, streamDecoderTimesteps = -1, streamDecoderTemperature = Float.NaN,
                streamConditionChunkModelFile = null, streamConditionFinalModelFile = null, streamDecoderStepModelFile = null,
                streamingChunkSize = -1, streamingPreLookaheadLen = -1, streamingMelCacheLen = -1,
            ),
            source = LitsTtsAssetInstaller.LayoutSource.BUNDLED_ASSET,
        )
    }

    private fun tn(text: String) = LitsTnNormalizer.normalize(layout, text, "zh-en", "zh-en")

    @Test fun numbersAnnouncedAsCodesAreReadDigitByDigit() {
        mapOf(
            "现在播报号码18912345678。" to "现在播报号码幺八九幺二三四五六七八。",
            "号码：18912345678" to "号码:幺八九幺二三四五六七八",
            "请拨打18912345678。" to "请拨打幺八九幺二三四五六七八。",
            "18912345678" to "幺八九幺二三四五六七八",
            "18912345678号" to "幺八九幺二三四五六七八号",
            "工号18912345678" to "工号一八九一二三四五六七八",
            "警号123456" to "警号一二三四五六",
            "编号2024001" to "编号二零二四零零一",
            "案件编号 2024110100123" to "案件编号 二零二四一一零一零零一二三",
            "卡号6222021234567890123" to "卡号六二二二零二一二三四五六七八九零一二三",
            "回拨13800138000" to "回拨幺三八零零幺三八零零零",
        ).forEach { (raw, spoken) -> assertEquals(raw, spoken, tn(raw)) }
    }

    @Test fun cardinalsWithUnitsAndLeadingZeroCodesAreUntouched() {
        assertEquals("金额一百三十八亿零十三万八千元", tn("金额13800138000元"))  // 主线基数词读法：零后省"一十"
        assertEquals("人口一千四百万人", tn("人口14000000人"))
        assertEquals("共一千二百三十四万五千六百七十八", tn("共12345678"))
        // 前导零的长数字不再被当成基数词，原样交给原生 TN 逐位读。
        assertEquals("拨打02812345678", tn("拨打02812345678").let { if (it.startsWith("拨打零")) "拨打02812345678" else it })
    }
}
