package com.amphion.dingqiao.diarization

import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.DingqiaoSpeakerModelAssets
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.json.JSONObject
import org.json.JSONArray

class CommunityNativeInstrumentedTest {
    @Test fun bundledOfflineModelsProcessAndClusterRealWindow() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val directory = File(context.filesDir,"community-parity").apply { mkdirs() }
        val assets = DingqiaoSpeakerModelAssets.ensureCommunityInstalled(context,directory)
        val input = File(directory,"input.f32")
        assertTrue("Push a 10-second PCM float32 fixture to ${input.absolutePath}",input.isFile)
        val bytes = input.readBytes()
        assertEquals(160000*4,bytes.size)
        val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
        val pcm = FloatArray(160000).also { buffer.get(it) }
        CommunityDiarizationInference(assets).use { model ->
            val window = model.process(pcm)
            assertEquals(589*3,window.segments.size)
            assertEquals(3*256,window.embeddings.size)
            assertTrue(window.segments.any { it > 0 })
            fun save(name: String, values: FloatArray) {
                val data = ByteBuffer.allocate(values.size*4).order(ByteOrder.LITTLE_ENDIAN)
                values.forEach { data.putFloat(it) }
                File(directory,name).writeBytes(data.array())
            }
            save("segments.f32",window.segments);save("embeddings.f32",window.embeddings)
            val result = model.cluster(window.segments,window.embeddings,4,doubleArrayOf(32000.0),32000.0)
            assertTrue(result.speakerCount in 1..4)
            assertTrue(result.turns.isNotEmpty())
            assertTrue(result.turns.all { it[0] >= 2000 && it[1] <= 12100 })
            File(directory,"result.json").writeText(JSONObject().put("speakerCount",result.speakerCount)
                .put("hard",JSONArray(result.hard.toList())).put("turns",JSONArray(result.turns.map { it.toList() }))
                .put("segmentationMs",window.segmentationMs).put("embeddingMs",window.embeddingMs).toString())
        }
        // Loading again proves the first session released its native handle.
        CommunityDiarizationInference(assets).use { model ->
            assertEquals(589*3,model.process(FloatArray(160000)).segments.size)
        }
    }
}
