package com.amphion.dingqiao

import com.amphion.asr.AsrLanguage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

class DingqiaoEngineConfigTest {

    @Test
    fun mapLanguage_zhCn() {
        assertEquals(AsrLanguage.ZH_EN, DingqiaoEngineConfig.mapLanguage("zh-CN"))
    }

    @Test
    fun buildAsrConfig_includesPoliceHotwords() {
        val config = DingqiaoEngineConfig.buildAsrConfig(
            CreateEngineParams(
                language = "zh-CN",
                online = DingqiaoOnlineMode.OFFLINE,
                extraParams = mapOf("sysGeneralLexicon" to listOf("盘查")),
            ),
            speakerModelPath = null,
        )
        assertTrue(config.hotwords.isNotEmpty())
        assertTrue(config.hotwords.contains("盘查"))
    }

    @Test
    fun buildAsrConfig_readsVadEndFromStartParams() {
        val config = DingqiaoEngineConfig.buildAsrConfig(
            CreateEngineParams(
                language = "zh-CN",
                online = DingqiaoOnlineMode.OFFLINE,
            ),
            speakerModelPath = null,
            startParams = StartParams(
                sessionId = "s1",
                audioInfo = AudioInfo(),
                extraParams = mapOf("vadEnd" to 1500),
            ),
        )

        assertEquals(1500, config.vadConfig.activeEndpointSilenceMs)
    }

    @Test
    fun buildAsrConfig_ignoresCreateEngineVadEnd() {
        val config = DingqiaoEngineConfig.buildAsrConfig(
            CreateEngineParams(
                language = "zh-CN",
                online = DingqiaoOnlineMode.OFFLINE,
                extraParams = mapOf("vadEnd" to 1500),
            ),
            speakerModelPath = null,
        )

        assertEquals(800, config.vadConfig.activeEndpointSilenceMs)
    }

    @Test
    fun vadEndMs_clampsToDocumentRange() {
        val low = DingqiaoEngineConfig.vadEndMs(
            StartParams("s1", AudioInfo(), mapOf("vadEnd" to 100)),
        )
        val high = DingqiaoEngineConfig.vadEndMs(
            StartParams("s1", AudioInfo(), mapOf("vadEnd" to 20_000)),
        )

        assertEquals(500, low)
        assertEquals(10_000, high)
    }

    @Test
    fun audioFrameBytes_acceptsDocumentedFrameSizes() {
        assertTrue(DingqiaoEngineConfig.isSupportedAudioFrameBytes(640))
        assertTrue(DingqiaoEngineConfig.isSupportedAudioFrameBytes(1280))
        assertTrue(!DingqiaoEngineConfig.isSupportedAudioFrameBytes(960))
    }

    @Test
    fun voiceprintIds_fromStartParams() {
        val ids = DingqiaoEngineConfig.voiceprintIds(
            StartParams(
                sessionId = "s1",
                audioInfo = AudioInfo(),
                extraParams = mapOf(
                    "enableVoiceprintVerification" to true,
                    "voiceprintIds" to listOf("vp-1", "vp-2"),
                ),
            ),
        )
        assertEquals(listOf("vp-1", "vp-2"), ids)
    }
}

class VoiceprintStoreTest {

    @Test
    fun saveLoadDelete_roundTrip() {
        val dir = File.createTempFile("dingqiao-vp", "").apply { delete(); mkdirs() }
        val store = VoiceprintStore(dir)
        val emb = floatArrayOf(0.6f, 0.8f)

        val result = store.saveVoiceprint(listOf("/tmp/sample1.pcm"), emb)
        val id = result.voiceprintId.keys.first()
        assertEquals(DingqiaoVoiceprintStatus.SUCCESS, result.status)
        assertEquals("sample1.pcm", result.voiceprintId[id])
        assertTrue(store.exists(id))

        val loaded = store.loadEmbedding(id)!!
        assertEquals(emb.size, loaded.size)
        assertEquals(emb[0], loaded[0], 1e-5f)
        assertEquals(emb[1], loaded[1], 1e-5f)

        assertTrue(store.deleteVoiceprint(id))
        assertTrue(!store.exists(id))
    }

    @Test
    fun loadMergedEmbedding_averagesMultiple() {
        val dir = File.createTempFile("dingqiao-vp-merge", "").apply { delete(); mkdirs() }
        val store = VoiceprintStore(dir)
        writeEmbeddingFile(dir, "vp-a", floatArrayOf(1f, 0f))
        writeEmbeddingFile(dir, "vp-b", floatArrayOf(0f, 1f))
        val merged = store.loadMergedEmbedding(listOf("vp-a", "vp-b"))!!
        assertEquals(2, merged.size)
        assertEquals(0.7071f, merged[0], 0.01f)
        assertEquals(0.7071f, merged[1], 0.01f)
    }

    private fun writeEmbeddingFile(workPath: File, id: String, emb: FloatArray) {
        val file = File(workPath, "voiceprints/$id/embedding.bin")
        file.parentFile?.mkdirs()
        val buf = ByteBuffer.allocate(4 + emb.size * 4).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(emb.size)
        for (v in emb) buf.putFloat(v)
        file.writeBytes(buf.array())
    }
}

class PcmIoTest {

    @Test
    fun bytesToShortsLE_roundTrip() {
        val shorts = shortArrayOf(100, -200, 300)
        val bytes = ByteArray(6)
        ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).apply {
            for (s in shorts) putShort(s)
        }
        val out = PcmIo.bytesToShortsLE(bytes)
        assertEquals(shorts.size, out.size)
        for (i in shorts.indices) {
            assertEquals(shorts[i], out[i])
        }
    }
}
