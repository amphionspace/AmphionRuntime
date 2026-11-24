package com.lits.tts.sdk.internal

import java.io.File
import kotlin.io.path.createTempDirectory
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 3.3 号码读法回归：客户反馈播报号码时把 18912345678 读成"一百八十九亿一千二百三十四万五千六百七十八"。
 * 根因是 Kotlin 预处理的大数基数词规则抢在原生 TN 之前改写了号码。JVM 上无原生 TN，这里只断言预处理层输出。
 */
class PhoneNumberReadingFix33Test {
    private val layout: LitsTtsAssetInstaller.InstalledLayout by lazy {
        val assetRoot = TtsTestAssets.root()
        val root = createTempDirectory("lits-tts-phone-fix-34").toFile()
        assetRoot.walkTopDown().filter { it.isFile && !it.name.endsWith(".onnx") }.forEach { f ->
            val target = root.resolve(f.relativeTo(assetRoot).path); target.parentFile?.mkdirs(); f.copyTo(target, overwrite = true)
        }
        LitsTtsAssetInstaller.InstalledLayout.of(
            rootDir = root,
            manifest = LitsTtsAssetInstaller.parseAndValidateManifest(root.resolve("manifest.json")),
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
        assertEquals("金额一百三十八亿零一十三万八千元", tn("金额13800138000元"))
        assertEquals("人口一千四百万人", tn("人口14000000人"))
        assertEquals("共一千二百三十四万五千六百七十八", tn("共12345678"))
        // 前导零的长数字不再被当成基数词，原样交给原生 TN 逐位读。
        assertEquals("拨打02812345678", tn("拨打02812345678").let { if (it.startsWith("拨打零")) "拨打02812345678" else it })
    }
}
