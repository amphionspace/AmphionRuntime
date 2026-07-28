package com.amphion.dingqiao

import com.amphion.asr.AsrLanguage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

class RejectedFinalLifecycleTest {

    @Test
    fun nonLastRejectedFinal_doesNotCompleteSession() {
        assertFalse(RejectedFinalLifecycle.completesSession(false))
    }

    @Test
    fun lastRejectedFinal_completesSession() {
        assertTrue(RejectedFinalLifecycle.completesSession(true))
    }
}

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
    fun buildAsrConfig_matchesHarmonyDefaultThreadCount() {
        val config = DingqiaoEngineConfig.buildAsrConfig(
            CreateEngineParams(
                language = "zh-CN",
                online = DingqiaoOnlineMode.OFFLINE,
            ),
            speakerModelPath = null,
        )

        assertEquals(4, config.numThreads)
    }

    @Test
    fun buildAsrConfig_disablesPrepackByDefaultAndAllowsExplicitFallback() {
        val defaultConfig = DingqiaoEngineConfig.buildAsrConfig(
            CreateEngineParams(language = "zh-CN", online = DingqiaoOnlineMode.OFFLINE),
            speakerModelPath = null,
        )
        val fallbackConfig = DingqiaoEngineConfig.buildAsrConfig(
            CreateEngineParams(
                language = "zh-CN",
                online = DingqiaoOnlineMode.OFFLINE,
                extraParams = mapOf("disablePrepack" to false),
            ),
            speakerModelPath = null,
        )

        assertTrue(defaultConfig.disablePrepack)
        assertFalse(fallbackConfig.disablePrepack)
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
    fun buildAsrConfig_acceptsDocumentedRecognizerModes() {
        for (mode in listOf("short", "long")) {
            DingqiaoEngineConfig.buildAsrConfig(
                CreateEngineParams(
                    language = "zh-CN",
                    extraParams = mapOf("recognizerMode" to mode),
                ),
                speakerModelPath = null,
            )
        }

        val rejected = runCatching {
            DingqiaoEngineConfig.buildAsrConfig(
                CreateEngineParams(
                    language = "zh-CN",
                    extraParams = mapOf("recognizerMode" to "invalid"),
                ),
                speakerModelPath = null,
            )
        }
        assertTrue(rejected.isFailure)
    }

    @Test
    fun buildAsrConfig_usesValueEqualityForReuse() {
        val createParams = CreateEngineParams(
            language = "zh-CN",
            online = DingqiaoOnlineMode.OFFLINE,
            extraParams = mapOf("sysGeneralLexicon" to listOf("盘查")),
        )
        val startParams = StartParams(
            sessionId = "s1",
            audioInfo = AudioInfo(),
            extraParams = mapOf("vadEnd" to 800),
        )

        val first = DingqiaoEngineConfig.buildAsrConfig(createParams, speakerModelPath = null, startParams)
        val second = DingqiaoEngineConfig.buildAsrConfig(createParams, speakerModelPath = null, startParams)
        val changed = DingqiaoEngineConfig.buildAsrConfig(
            createParams,
            speakerModelPath = null,
            startParams = startParams.copy(extraParams = mapOf("vadEnd" to 1500)),
        )

        assertEquals(first, second)
        assertEquals(first.hashCode(), second.hashCode())
        assertTrue(first != changed)
    }

    @Test
    fun buildSessionConfig_readsVadEndAndSpeakerVad() {
        val sc = DingqiaoEngineConfig.buildSessionConfig(
            StartParams(
                sessionId = "s1",
                audioInfo = AudioInfo(),
                extraParams = mapOf(
                    "vadEnd" to 1500,
                    "speakerVadWindowMs" to 1200,
                    "speakerVadHopMs" to 400,
                    "speakerVadThreshold" to 0.5,
                    "speakerVadConsecutiveBelow" to 3,
                ),
            ),
            speakerModelPath = "/tmp/eres2net.onnx",
        )
        assertEquals(1500, sc.endpointSilenceMs)
        val sv = sc.speakerVad!!
        assertEquals(1.2f, sv.winSec, 1e-6f)
        assertEquals(0.4f, sv.hopSec, 1e-6f)
        assertEquals(0.5f, sv.threshold, 1e-6f)
        assertEquals(3, sv.consecutiveBelow)
    }

    @Test
    fun buildSessionConfig_noSpeakerModelDropsSpeakerVad() {
        val sc = DingqiaoEngineConfig.buildSessionConfig(
            StartParams("s1", AudioInfo(), mapOf("vadEnd" to 800)),
            speakerModelPath = null,
        )
        assertEquals(800, sc.endpointSilenceMs)
        assertEquals(null, sc.speakerVad)
    }

    @Test
    fun buildSessionConfig_usesDefaultsWhenAbsent() {
        val sc = DingqiaoEngineConfig.buildSessionConfig(
            StartParams("s1", AudioInfo(), emptyMap()),
            speakerModelPath = "/tmp/eres2net.onnx",
        )
        assertEquals(800, sc.endpointSilenceMs)
        assertEquals(0.40f, sc.speakerVad!!.threshold, 1e-6f)
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
    fun vadBeginMs_isOptInAndClampsToDocumentRange() {
        assertNull(DingqiaoEngineConfig.vadBeginMs(StartParams("s1", AudioInfo())))
        assertNull(
            DingqiaoEngineConfig.vadBeginMs(
                StartParams("s1", AudioInfo(), mapOf("vadBegin" to "invalid")),
            ),
        )
        assertEquals(
            500,
            DingqiaoEngineConfig.vadBeginMs(
                StartParams("s1", AudioInfo(), mapOf("vadBegin" to 100)),
            ),
        )
        assertEquals(
            10_000,
            DingqiaoEngineConfig.vadBeginMs(
                StartParams("s1", AudioInfo(), mapOf("vadBegin" to "20000")),
            ),
        )
    }

    @Test
    fun buildSessionConfig_carriesVadBeginWithoutRebuildingEngine() {
        val sc = DingqiaoEngineConfig.buildSessionConfig(
            StartParams("s1", AudioInfo(), mapOf("vadBegin" to 2_000, "vadEnd" to 900)),
            speakerModelPath = null,
        )

        assertEquals(2_000, sc.initialSilenceTimeoutMs)
        assertEquals(900, sc.endpointSilenceMs)
    }

    @Test
    fun buildSessionConfig_voiceprintKeepsVadBeginAndAddsBoundedConfirmationGrace() {
        val sc = DingqiaoEngineConfig.buildSessionConfig(
            StartParams(
                "s1",
                AudioInfo(),
                mapOf(
                    "vadBegin" to 1_000,
                    "enableVoiceprintVerification" to true,
                    "voiceprintIds" to listOf("vp-1"),
                ),
            ),
            speakerModelPath = "/tmp/eres2net.onnx",
        )
        assertEquals(1_000, sc.initialSilenceTimeoutMs)
        assertEquals(1_500, sc.initialSilenceConfirmationGraceMs)
    }

    @Test
    fun buildSessionConfig_plainAsrKeepsRequestedVadBegin() {
        val sc = DingqiaoEngineConfig.buildSessionConfig(
            StartParams("s1", AudioInfo(), mapOf("vadBegin" to 1_000)),
            speakerModelPath = "/tmp/eres2net.onnx",
        )

        assertEquals(1_000, sc.initialSilenceTimeoutMs)
        assertNull(sc.initialSilenceConfirmationGraceMs)
    }

    @Test
    fun buildSessionConfig_withoutSpeakerCapabilityDropsConfirmationGrace() {
        val sc = DingqiaoEngineConfig.buildSessionConfig(
            StartParams(
                "s1",
                AudioInfo(),
                mapOf("vadBegin" to 1_000, "enableVoiceprintVerification" to true),
            ),
            speakerModelPath = null,
        )

        assertEquals(1_000, sc.initialSilenceTimeoutMs)
        assertNull(sc.initialSilenceConfirmationGraceMs)
    }

    @Test
    fun buildSessionConfig_voiceprintIdsReserveConfirmationGraceForOnStartEnablement() {
        val sc = DingqiaoEngineConfig.buildSessionConfig(
            StartParams(
                "s1",
                AudioInfo(),
                mapOf(
                    "vadBegin" to 1_000,
                    "voiceprintIds" to listOf("vp-1"),
                ),
            ),
            speakerModelPath = "/tmp/eres2net.onnx",
            voiceprintCapabilityProvisioned = true,
        )

        assertEquals(1_000, sc.initialSilenceTimeoutMs)
        assertEquals(1_500, sc.initialSilenceConfirmationGraceMs)
    }

    @Test
    fun buildSessionConfig_unvalidatedVoiceprintIdsDoNotReserveConfirmationGrace() {
        val sc = DingqiaoEngineConfig.buildSessionConfig(
            StartParams(
                "s1",
                AudioInfo(),
                mapOf("vadBegin" to 1_000, "voiceprintIds" to listOf("missing")),
            ),
            speakerModelPath = "/tmp/eres2net.onnx",
        )

        assertNull(sc.initialSilenceConfirmationGraceMs)
    }

    @Test
    fun audioFrameBytes_acceptsDocumentedFrameSizeOnly() {
        assertTrue(DingqiaoEngineConfig.isSupportedAudioFrameBytes(640))
        assertTrue(!DingqiaoEngineConfig.isSupportedAudioFrameBytes(1280))
        assertTrue(!DingqiaoEngineConfig.isSupportedAudioFrameBytes(960))
    }

    @Test
    fun maxAudioDuration_isOptInFiniteAndCapped() {
        assertEquals(
            0L,
            DingqiaoEngineConfig.maxAudioDurationMs(StartParams("s1", AudioInfo())),
        )
        assertEquals(
            0L,
            DingqiaoEngineConfig.maxAudioDurationMs(StartParams("s1", AudioInfo(), mapOf("maxAudioDuration" to 0))),
        )
        assertEquals(
            5_000L,
            DingqiaoEngineConfig.maxAudioDurationMs(StartParams("s1", AudioInfo(), mapOf("maxAudioDuration" to "5000"))),
        )
        assertEquals(
            60_000L,
            DingqiaoEngineConfig.maxAudioDurationMs(StartParams("s1", AudioInfo(), mapOf("maxAudioDuration" to 60_000))),
        )
        assertEquals(
            0L,
            DingqiaoEngineConfig.maxAudioDurationMs(
                StartParams("s1", AudioInfo(), mapOf("maxAudioDuration" to Double.POSITIVE_INFINITY)),
            ),
        )
        assertEquals(
            0L,
            DingqiaoEngineConfig.maxAudioDurationMs(
                StartParams("s1", AudioInfo(), mapOf("maxAudioDuration" to Double.NaN)),
            ),
        )
        assertEquals(
            28_800_000L,
            DingqiaoEngineConfig.maxAudioDurationMs(
                StartParams("s1", AudioInfo(), mapOf("maxAudioDuration" to 99_999_999)),
            ),
        )
    }

    @Test
    fun nonFiniteSessionNumbersFallBackToDocumentedDefaults() {
        val config = DingqiaoEngineConfig.buildSessionConfig(
            StartParams(
                "s1",
                AudioInfo(),
                mapOf(
                    "vadEnd" to Double.NaN,
                    "speakerVadThreshold" to Float.NaN,
                    "speakerVadWindowMs" to Double.POSITIVE_INFINITY,
                    "speakerVadHopMs" to "NaN",
                    "speakerVadConsecutiveBelow" to Double.NEGATIVE_INFINITY,
                ),
            ),
            speakerModelPath = "/tmp/eres2net.onnx",
        )

        assertEquals(800, config.endpointSilenceMs)
        assertEquals(0.40f, config.speakerVad?.threshold)
        assertEquals(1.0f, config.speakerVad?.winSec)
        assertEquals(0.3f, config.speakerVad?.hopSec)
        assertEquals(2, config.speakerVad?.consecutiveBelow)
    }

    @Test
    fun recognitionMode_acceptsExternalStreamOnly() {
        DingqiaoEngineConfig.validateRecognitionMode(StartParams("s1", AudioInfo()))
        DingqiaoEngineConfig.validateRecognitionMode(
            StartParams("s1", AudioInfo(), mapOf("recognitionMode" to "1")),
        )

        val rejected = runCatching {
            DingqiaoEngineConfig.validateRecognitionMode(
                StartParams("s1", AudioInfo(), mapOf("recognitionMode" to DingqiaoRecognitionMode.RECORD)),
            )
        }
        assertTrue(rejected.isFailure)
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

class CallbackEpochTest {

    @Test
    fun replacementInvalidatesEveryQueuedCallbackFromTheOldSession() {
        val gate = CallbackEpoch()
        val old = gate.beginSession()
        assertTrue(gate.isCurrent(old))

        val replacement = gate.beginSession()

        assertFalse(gate.isCurrent(old))
        assertTrue(gate.isCurrent(replacement))
    }

    @Test
    fun shutdownInvalidatesQueuedEngineErrors() {
        val gate = CallbackEpoch()
        val queuedError = gate.current()

        gate.invalidate()

        assertFalse(gate.isCurrent(queuedError))
    }

    @Test
    fun staleTerminalClaimCannotBlockReplacementSession() {
        val gate = CallbackEpoch()
        val old = gate.beginSession()
        assertTrue(gate.claimTerminal(old))

        val replacement = gate.beginSession()

        assertFalse(gate.claimTerminal(old))
        assertTrue(gate.claimTerminal(replacement))
        assertFalse(gate.claimTerminal(replacement))
    }
}

class CallbackInvocationContextTest {
    @Test
    fun replacementCanBeAdoptedWithinResultButOldCompletionIsRestored() {
        val context = CallbackInvocationContext()

        context.withEpoch(7L) {
            context.adopt(8L)
            assertFalse(context.isStaleForActiveSession(activeEpoch = 8L, listening = true))
        }
        context.withEpoch(7L) {
            assertTrue(context.isStaleForActiveSession(activeEpoch = 8L, listening = true))
        }
    }

    @Test
    fun longLivedAudioThreadDoesNotInheritOneSessionsCallbackEpoch() {
        val context = CallbackInvocationContext()
        val stale = java.util.concurrent.atomic.AtomicBoolean(false)

        context.withEpoch(7L) {
            val worker = Thread {
                stale.set(context.isStaleForActiveSession(activeEpoch = 8L, listening = true))
            }
            worker.start()
            worker.join()
        }

        assertFalse(stale.get())
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
