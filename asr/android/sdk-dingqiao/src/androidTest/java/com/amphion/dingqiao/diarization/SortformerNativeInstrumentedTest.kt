package com.amphion.dingqiao.diarization

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.DingqiaoSpeakerModelAssets
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * 裸开 Sortformer 引擎：资产安装、原生加载、一次喂入。这里不经会话层，所以失败时异常原样
 * 抛出，不会被降级路径吞成一个没有消息的 `INFERENCE_UNAVAILABLE`。
 */
@RunWith(AndroidJUnit4::class)
class SortformerNativeInstrumentedTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun assetsInstallAndTheEngineLoadsAndFeeds() {
        val workPath = File(context.filesDir, "sortformer-native-test").apply { mkdirs() }
        val dir = DingqiaoSpeakerModelAssets.ensureSortformerInstalled(context, workPath)
        assertTrue("model directory exists: ${dir.absolutePath}", dir.isDirectory)
        val names = dir.listFiles()?.map { it.name }?.sorted() ?: emptyList()
        val expected = listOf(
            "encoder_layers.int8.onnx", "learnable_sil_emb.npy",
            "mel_filterbank_128x257_slaney.npy", "mel_window_hann400_periodic_false.npy",
            "pre_encode.onnx", "speaker_head.onnx", "spkcache_update.onnx",
        )
        assertTrue("installed $names, expected to contain $expected", names.containsAll(expected))
        // 被取代的 .ort 应被安装器清掉，不该留在工作目录里
        assertTrue("stale .ort left behind: $names", names.none { it.endsWith(".ort") })
        assertTrue("installed: $names", DingqiaoSpeakerModelAssets.isSortformerReady(workPath))

        SortformerDiarizationInference(modelDir = dir.absolutePath, threads = 2, previewMs = 0).use { engine ->
            // 10 s 静音：足够跨过一个 9.92 s 块，拿到一次 final 事件。
            val samples = FloatArray(16_000 * 10)
            val result = engine.feed(samples, flush = true)
            assertEquals(160_000L, result.samples)
            assertTrue("the engine reported at least one event", result.events.isNotEmpty())
            val finals = result.events.filter { !it.preview }
            assertTrue("a chunk became final: ${result.events.map { it.kind }}", finals.isNotEmpty())
            // 纯静音不应判出任何人声
            assertTrue("silence has no speech runs", finals.all { event -> event.runs.all { it.isEmpty() } })
        }
    }
}
