package com.amphion.asr.internal

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import android.content.ContextWrapper
import com.amphion.asr.BuildConfig
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class InternalWeitnEngineInstrumentedTest {
    @Test
    fun upgradeReplacesLegacyItnCacheAndPreservesInterjections() {
        val base = InstrumentationRegistry.getInstrumentation().targetContext
        val files = File(base.cacheDir, "itn-upgrade-test").apply { mkdirs() }
        val context = object : ContextWrapper(base) {
            override fun getFilesDir(): File = files
        }
        val root = File(files, AssetRegistry.INSTALL_ROOT)
        val bundle = AssetRegistry.itnBundle()
        val itnDir = File(root, bundle.installSubDir).apply { mkdirs() }
        // A same-SDK-version install used to accept this marker and keep both stale files.
        File(root, AssetRegistry.INSTALL_FLAG).writeText("${BuildConfig.SDK_VERSION}:itn-only-v1")
        bundle.files.forEach { File(itnDir, it).writeText("legacy graph") }
        try {
            assertTrue(AssetInstaller.preInstallAllSync(context).installBytes > 0)
            InternalWeitnEngine(
                File(itnDir, "zh_itn_tagger.fst"),
                File(itnDir, "zh_itn_verbalizer.fst"),
            ).use { itn ->
                listOf("今天天气很好啊", "啊今天天气很好", "今天啊天气很好", "啊", "呃")
                    .forEach { assertEquals(it, itn.normalize(it)) }
                assertEquals("2026/05/15啊", itn.normalize("二零二六年五月十五日啊"))
            }
            assertEquals(0L, AssetInstaller.preInstallAllSync(context).installBytes)
        } finally {
            files.deleteRecursively()
        }
    }

    @Test
    fun spokenIdentityNumberWithYiYaoAndMeiIsFullyNormalized() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val modelDir = File(context.cacheDir, "itn-identity-number-test").apply { mkdirs() }
        val tagger = stageAsset(
            "amphion-models/itn-zh/v1/zh_itn_tagger.fst",
            File(modelDir, "zh_itn_tagger.fst"),
        )
        val verbalizer = stageAsset(
            "amphion-models/itn-zh/v1/zh_itn_verbalizer.fst",
            File(modelDir, "zh_itn_verbalizer.fst"),
        )

        InternalWeitnEngine(tagger, verbalizer).use { itn ->
            val expected = "130421199211011854"
            val inputs = listOf(
                "查询身份证一三零四二一一九九二一一零一一八五四，身份证对应的手机号码。",
                "查询身份证幺三零四二幺幺九九二幺幺零幺幺八五四，身份证对应的手机号码。",
                "查询身份证么三零四二么么九九二么么零么么八五四，身份证对应的手机号码。",
                "查询身份证号码：么三零四二么么九九二么么零么么八五四。",
            )
            val outputs = inputs.map(itn::normalize)

            assertTrue(
                "identity number must be a contiguous Arabic digit sequence: $outputs",
                outputs.all { expected in it },
            )
            val ordinaryTexts = mapOf(
                "你这么说是什么意思" to "你这么说是什么意思",
                "这么1234" to "这么1234",
                "这么12345678901234567" to "这么12345678901234567",
                "身份证为什么1234" to "身份证为什么1234",
                // Unambiguous following digits may still normalize; only grammatical 么 is protected.
                "什么两三四五" to "什么2345",
            )
            ordinaryTexts.forEach { (ordinaryText, expectedText) ->
                assertEquals(
                    "grammatical 么 outside a numeric field must remain text",
                    expectedText,
                    itn.normalize(ordinaryText),
                )
            }
        }
    }

    private fun stageAsset(assetPath: String, destination: File): File {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        context.assets.open(assetPath).use { input ->
            destination.outputStream().use(input::copyTo)
        }
        return destination
    }
}
