package com.amphion.dingqiao.demo

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.AudioInfo
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.DingqiaoErrorCode
import com.amphion.dingqiao.DingqiaoEventCode
import com.amphion.dingqiao.DingqiaoOnlineMode
import com.amphion.dingqiao.SpeechRecognitionEngine
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.StartParams
import com.amphion.dingqiao.VoiceprintRegisterParams
import java.io.File
import org.junit.Assert.assertTrue
import org.junit.FixMethodOrder
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.MethodSorters

/**
 * 声纹注册 / 相似度回写 / 删除 / 目标说话人 VAD 的 corner-case。
 */
@RunWith(AndroidJUnit4::class)
@FixMethodOrder(MethodSorters.NAME_ASCENDING)
class DqVoiceprintTest {

    private val ctx: Context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val testCtx: Context get() = InstrumentationRegistry.getInstrumentation().context

    private fun errCodeOf(t: Throwable): Int? =
        runCatching { t.javaClass.getMethod("getErrorCode").invoke(t) as? Int }.getOrNull()

    private fun registerFromSample(sampleAsset: String): String {
        val path = stageAsset(testCtx, ctx, sampleAsset, "vp_samples/${File(sampleAsset).name}")
        val result = SpeechRecognizeSdk.registerVoiceprint(
            VoiceprintRegisterParams(samplePaths = listOf(path), audioInfo = AudioInfo()),
        )
        return result.voiceprintId.keys.first()
    }

    // ---------- v01: 用 _声纹 样本注册 ----------
    @Test
    fun v01_register_fromSample_ok() {
        ensureReady()
        val sample = testCtx.assets.list("").orEmpty().first { it.contains("声纹") }
        val id = registerFromSample(sample)
        val persisted = File(workDir(), "voiceprints/$id/embedding.bin").isFile
        DqReport.append(ctx, mapOf("case" to "v01_register", "sample" to sample, "voiceprintId" to id, "persisted" to persisted))
        assertTrue("voiceprint id should be returned", id.isNotBlank())
        assertTrue("embedding should be persisted", persisted)
    }

    // ---------- v02: 样本过长（>8s）被拒 ----------
    @Test
    fun v02_register_tooLong_rejected() {
        ensureReady()
        val longMain = mainWavs(testCtx).maxByOrNull { readAssetPcm(testCtx, it).size }!!
        val path = stageAsset(testCtx, ctx, longMain, "vp_samples/long.wav")
        var code: Int? = null
        try {
            SpeechRecognizeSdk.registerVoiceprint(VoiceprintRegisterParams(listOf(path), AudioInfo()))
        } catch (t: Throwable) {
            code = errCodeOf(t)
        }
        DqReport.append(ctx, mapOf("case" to "v02_tooLong", "file" to longMain, "errorCode" to code))
        assertTrue("expected VOICEPRINT_SAMPLE_DURATION", code == DingqiaoErrorCode.VOICEPRINT_SAMPLE_DURATION)
    }

    // ---------- v03: 样本路径不存在 ----------
    @Test
    fun v03_register_missingPath_rejected() {
        ensureReady()
        var code: Int? = null
        try {
            SpeechRecognizeSdk.registerVoiceprint(
                VoiceprintRegisterParams(listOf(File(ctx.filesDir, "nope.wav").absolutePath), AudioInfo()),
            )
        } catch (t: Throwable) {
            code = errCodeOf(t)
        }
        DqReport.append(ctx, mapOf("case" to "v03_missingPath", "errorCode" to code))
        assertTrue("expected VOICEPRINT_REGISTER_FAILED", code == DingqiaoErrorCode.VOICEPRINT_REGISTER_FAILED)
    }

    // ---------- v04: 启用声纹核验，final 回写 speakerSimilarity ----------
    @Test
    fun v04_verification_similarityReturned() {
        ensureReady()
        val main = mainWavs(testCtx).minByOrNull { readAssetPcm(testCtx, it).size }!!
        val sample = voiceprintSampleFor(testCtx, main) ?: main
        val id = registerFromSample(sample)
        val engine = engine()
        val listener = CapturingListener().also { engine.setListener(it) }
        val sid = "vp-verify-${System.currentTimeMillis()}"
        engine.startListening(
            StartParams(
                sid, AudioInfo(),
                extraParams = mapOf(
                    "enableVoiceprintVerification" to true,
                    "voiceprintIds" to listOf(id),
                    "vadEnd" to 800,
                ),
            ),
        )
        assertTrue("start failed: ${listener.errorCodes()}", listener.awaitStarted(15_000))
        feedFrames(engine, sid, readAssetPcm(testCtx, main), 0)
        feedSilence(engine, sid, 500)
        engine.finish(sid)
        listener.awaitComplete(25_000)
        Thread.sleep(300)
        awaitIdle(engine)
        val sims = listener.finals.mapNotNull { it.speakerSimilarity }
        DqReport.append(ctx, mapOf("case" to "v04_verification", "main" to main, "sample" to sample,
            "finalCount" to listener.finals.size, "similarities" to sims.toString(), "finalText" to listener.finalText()))
        assertTrue("expected at least one final with non-null speakerSimilarity", sims.isNotEmpty())
    }

    // ---------- v04b: voiceprint + vadBegin，前置静音后真实语音不得提前结束 ----------
    @Test
    fun v04b_verificationWithVadBegin_frontSilenceDoesNotEndEarly() {
        ensureReady()
        val main = mainWavs(testCtx).minByOrNull { readAssetPcm(testCtx, it).size }!!
        val sample = voiceprintSampleFor(testCtx, main) ?: main
        val id = registerFromSample(sample)
        val engine = engine()
        awaitIdle(engine)
        val listener = CapturingListener().also { engine.setListener(it) }
        val sid = "vp-vadbegin-${System.currentTimeMillis()}"
        engine.startListening(
            StartParams(
                sid,
                AudioInfo(),
                extraParams = mapOf(
                    "enableVoiceprintVerification" to true,
                    "voiceprintIds" to listOf(id),
                    "vadBegin" to 1_000,
                    "vadEnd" to 800,
                ),
            ),
        )
        assertTrue("start failed: ${listener.errorCodes()}", listener.awaitStarted(15_000))
        feedSilence(engine, sid, 300)
        feedFrames(engine, sid, readAssetPcm(testCtx, main), 20)
        assertTrue("voiceprint vadBegin must not auto-finish real speech",
            listener.finals.none { it.isLast } && listener.completes.isEmpty())
        engine.finish(sid)
        val completed = listener.awaitComplete(25_000)
        awaitIdle(engine)
        val eligible = listener.finals.filter { it.result.isNotBlank() }

        DqReport.append(ctx, mapOf("case" to "v04b_voiceprintVadBegin",
            "main" to main, "completed" to completed,
            "lastCount" to listener.finals.count { it.isLast },
            "scoredFinalCount" to eligible.count { it.speakerSimilarity != null },
            "errorCodes" to listener.errorCodes().toString()))
        assertTrue("voiceprint vadBegin session must complete after explicit finish", completed)
        assertTrue("expected a non-empty final", eligible.isNotEmpty())
        assertTrue("voiceprint vadBegin speech must produce a scored non-empty final",
            eligible.any { it.speakerSimilarity != null })
    }

    // ---------- v04c: 500 ms 短句有 ASR 证据时，退化到本句真实 PCM ----------
    @Test
    fun v04c_shortEffectiveSpeech_fallsBackToRealUtterancePcm() {
        ensureReady()
        val registrationAsset = "000_enroll.wav"
        val recognitionAsset = "001_recognize.wav"
        val full = readAssetPcm(testCtx, recognitionAsset)
        val id = registerFromSample(registrationAsset)
        val engine = freshEngine()
        awaitIdle(engine)
        val speechBytes = minOf(full.size, (DQ_SR * 2 * 0.5).toInt())
        repeat(2) { round ->
            val listener = CapturingListener().also { engine.setListener(it) }
            val sid = "vp-fallback-$round-${System.currentTimeMillis()}"
            engine.startListening(
                StartParams(
                    sid,
                    AudioInfo(),
                    extraParams = mapOf(
                        "enableVoiceprintVerification" to true,
                        "voiceprintIds" to listOf(id),
                        "vadEnd" to 800,
                    ),
                ),
            )
            assertTrue("round=$round start failed: ${listener.errorCodes()}",
                listener.awaitStarted(15_000))
            feedSilence(engine, sid, 350)
            feedFrames(engine, sid, full.copyOfRange(0, speechBytes), 20)
            engine.finish(sid)
            val completed = listener.awaitComplete(25_000)
            awaitIdle(engine)
            val firstNonEmpty = listener.finals.firstOrNull { it.result.isNotBlank() }

            DqReport.append(ctx, mapOf("case" to "v04c_voiceprintFallback",
                "round" to round, "registrationAsset" to registrationAsset,
                "recognitionAsset" to recognitionAsset, "completed" to completed,
                "finalText" to firstNonEmpty?.result,
                "speakerSimilarity" to firstNonEmpty?.speakerSimilarity,
                "errorCodes" to listener.errorCodes().toString()))
            assertTrue("round=$round voiceprint fallback session must complete", completed)
            assertTrue("round=$round fallback corpus must produce a non-empty final",
                firstNonEmpty != null)
            assertTrue("round=$round real utterance PCM fallback must produce speakerSimilarity",
                firstNonEmpty?.speakerSimilarity != null)
        }
    }

    // ---------- v04d: 仅预置 voiceprintIds，在 onStart 内开启 Speaker VAD ----------
    @Test
    fun v04d_voiceprintIdsReserveVadBeginGrace_forOnStartSpeakerVad() {
        ensureReady()
        val main = mainWavs(testCtx).minByOrNull { readAssetPcm(testCtx, it).size }!!
        val sample = voiceprintSampleFor(testCtx, main) ?: main
        val id = registerFromSample(sample)
        val engine = engine()
        awaitIdle(engine)
        val sid = "vp-onstart-svad-${System.currentTimeMillis()}"
        val listener = CapturingListener {
            engine.setSpeakerVadEnabled(true)
        }.also { engine.setListener(it) }
        engine.startListening(
            StartParams(
                sid,
                AudioInfo(),
                extraParams = mapOf(
                    "voiceprintIds" to listOf(id),
                    "vadBegin" to 1_000,
                    "vadEnd" to 800,
                ),
            ),
        )
        assertTrue("onStart Speaker VAD enable failed: ${listener.errorCodes()}",
            listener.awaitStarted(15_000))
        feedSilence(engine, sid, 300)
        feedFrames(engine, sid, readAssetPcm(testCtx, main), 20)
        assertTrue("runtime Speaker VAD must not let vadBegin end real speech",
            listener.finals.none { it.isLast } && listener.completes.isEmpty())
        engine.finish(sid)
        val completed = listener.awaitComplete(25_000)
        awaitIdle(engine)
        val eligible = listener.finals.filter { it.result.isNotBlank() }

        DqReport.append(ctx, mapOf("case" to "v04d_onStartSpeakerVad",
            "main" to main, "completed" to completed,
            "lastCount" to listener.finals.count { it.isLast },
            "scoredFinalCount" to eligible.count { it.speakerSimilarity != null },
            "errorCodes" to listener.errorCodes().toString()))
        assertTrue("runtime Speaker VAD session must complete after explicit finish", completed)
        assertTrue("runtime Speaker VAD must not report errors", listener.errors.isEmpty())
        assertTrue("runtime Speaker VAD corpus must produce a non-empty final", eligible.isNotEmpty())
        assertTrue("runtime Speaker VAD must produce a scored non-empty final",
            eligible.any { it.speakerSimilarity != null })
        assertTrue("normal finish must emit exactly one last",
            listener.finals.count { it.isLast } == 1)
    }

    // ---------- v04e: 声纹确认窗有界，纯静音最终仍按 vadBegin 自动结束 ----------
    @Test
    fun v04e_voiceprintVadBegin_pureSilenceEndsOnce() {
        ensureReady()
        val sample = mainWavs(testCtx).minByOrNull { readAssetPcm(testCtx, it).size }!!
        val id = registerFromSample(sample)
        val engine = engine()
        awaitIdle(engine)
        val listener = CapturingListener().also { engine.setListener(it) }
        val sid = "vp-vadbegin-silence-${System.currentTimeMillis()}"
        engine.startListening(
            StartParams(
                sid,
                AudioInfo(),
                extraParams = mapOf(
                    "enableVoiceprintVerification" to true,
                    "voiceprintIds" to listOf(id),
                    "vadBegin" to 1_000,
                ),
            ),
        )
        assertTrue("start failed: ${listener.errorCodes()}", listener.awaitStarted(15_000))
        feedSilence(engine, sid, 2_700)
        val completed = listener.awaitComplete(15_000)
        awaitIdle(engine)

        DqReport.append(ctx, mapOf("case" to "v04e_voiceprintVadBeginSilence",
            "completed" to completed, "completeCount" to listener.completes.size,
            "lastCount" to listener.finals.count { it.isLast },
            "errorCodes" to listener.errorCodes().toString()))
        assertTrue("voiceprint confirmation window must remain bounded", completed)
        assertTrue("pure silence must emit one empty last",
            listener.finals.count { it.isLast && it.result.isEmpty() } == 1)
        assertTrue("pure silence must not produce speakerSimilarity",
            listener.finals.all { it.speakerSimilarity == null })
        assertTrue("pure silence must complete exactly once", listener.completes.size == 1)
        assertTrue("pure silence must not report errors", listener.errors.isEmpty())
    }

    // ---------- v05: enableSpeakerVad 但无 voiceprintIds ----------
    @Test
    fun v05_speakerVad_requiresVoiceprintIds() {
        ensureReady()
        val engine = engine()
        awaitIdle(engine)
        val listener = CapturingListener().also { engine.setListener(it) }
        engine.startListening(
            StartParams("svad-noid-${System.currentTimeMillis()}", AudioInfo(),
                extraParams = mapOf("enableSpeakerVad" to true)),
        )
        assertTrue(listener.awaitError(3_000))
        DqReport.append(ctx, mapOf("case" to "v05_speakerVadNoId", "errorCodes" to listener.errorCodes().toString()))
        awaitIdle(engine)
        assertTrue("expected START_LISTENING_FAILED",
            listener.errorCodes().contains(DingqiaoErrorCode.START_LISTENING_FAILED))
    }

    // ---------- v06: enableSpeakerVad + 声纹，重叠音频跑通并采集事件 ----------
    @Test
    fun v06_speakerVad_overlapRuns() {
        ensureReady()
        val main = mainWavs(testCtx).first { it.contains("重叠") }
        val sample = voiceprintSampleFor(testCtx, main) ?: testCtx.assets.list("").orEmpty().first { it.contains("声纹") }
        val id = registerFromSample(sample)
        val engine = engine()
        awaitIdle(engine)
        val listener = CapturingListener().also { engine.setListener(it) }
        val sid = "svad-${System.currentTimeMillis()}"
        engine.startListening(
            StartParams(sid, AudioInfo(),
                extraParams = mapOf(
                    "enableSpeakerVad" to true,
                    "voiceprintIds" to listOf(id),
                    "speakerVadThreshold" to 0.40,
                    "vadEnd" to 800,
                )),
        )
        assertTrue("start failed: ${listener.errorCodes()}", listener.awaitStarted(15_000))
        feedFrames(engine, sid, readAssetPcm(testCtx, main), 0)
        feedSilence(engine, sid, 500)
        engine.finish(sid)
        val completed = listener.awaitComplete(25_000)
        Thread.sleep(300)
        awaitIdle(engine)
        val vadEvents = listener.events.filter {
            it.first == DingqiaoEventCode.SPEAKER_VAD_CHANGED ||
                it.first == DingqiaoEventCode.SPEAKER_VAD_DEBUG ||
                it.first == DingqiaoEventCode.SPEAKER_VAD_REJECTED
        }
        DqReport.append(ctx, mapOf("case" to "v06_speakerVadOverlap", "main" to main, "completed" to completed,
            "finalText" to listener.finalText(), "vadEventCount" to vadEvents.size,
            "errorCodes" to listener.errorCodes().toString()))
        assertTrue("speaker VAD session should complete without recognition error",
            !listener.errorCodes().contains(DingqiaoErrorCode.RECOGNITION_ERROR))
    }

    // ---------- v07: 删除后再用 -> NOT_FOUND ----------
    @Test
    fun v07_delete_thenNotFound() {
        ensureReady()
        val sample = testCtx.assets.list("").orEmpty().first { it.contains("声纹") }
        val id = registerFromSample(sample)
        SpeechRecognizeSdk.deleteVoiceprint(id)
        var deleteAgain: Int? = null
        try {
            SpeechRecognizeSdk.deleteVoiceprint(id)
        } catch (t: Throwable) {
            deleteAgain = errCodeOf(t)
        }
        val engine = engine()
        awaitIdle(engine)
        val listener = CapturingListener().also { engine.setListener(it) }
        engine.startListening(
            StartParams("vp-del-${System.currentTimeMillis()}", AudioInfo(),
                extraParams = mapOf("enableVoiceprintVerification" to true, "voiceprintIds" to listOf(id))),
        )
        listener.awaitError(3_000)
        DqReport.append(ctx, mapOf("case" to "v07_deleteNotFound", "deleteAgainCode" to deleteAgain,
            "startErrorCodes" to listener.errorCodes().toString()))
        awaitIdle(engine)
        assertTrue("delete missing -> VOICEPRINT_NOT_FOUND", deleteAgain == DingqiaoErrorCode.VOICEPRINT_NOT_FOUND)
        assertTrue("start with deleted id -> VOICEPRINT_NOT_FOUND",
            listener.errorCodes().contains(DingqiaoErrorCode.VOICEPRINT_NOT_FOUND))
    }

    // ---------- v08: 运行时 setSpeakerVadEnabled 但无声纹 ----------
    @Test
    fun v08_setSpeakerVadEnabled_noVoiceprint_error() {
        ensureReady()
        val engine = engine()
        awaitIdle(engine)
        val listener = CapturingListener().also { engine.setListener(it) }
        val sid = "rt-svad-${System.currentTimeMillis()}"
        engine.startListening(StartParams(sid, AudioInfo(), extraParams = mapOf("vadEnd" to 800)))
        assertTrue(listener.awaitStarted(15_000))
        feedFrames(engine, sid, readAssetPcm(testCtx, mainWavs(testCtx).first()).copyOfRange(0, DQ_SR), 0)
        engine.setSpeakerVadEnabled(true) // 无 voiceprintIds -> loadMergedEmbedding(empty)=null -> error
        Thread.sleep(500)
        DqReport.append(ctx, mapOf("case" to "v08_runtimeSpeakerVadNoVp",
            "errorCodes" to listener.errorCodes().toString(), "events" to listener.events.map { it.first }.toString()))
        engine.cancel(sid)
        awaitIdle(engine)
        // 记录行为即可：期望出现 VOICEPRINT_NOT_FOUND 或 RECOGNITION_ERROR。
        assertTrue("expected an error toggling speaker VAD without voiceprint",
            listener.errors.isNotEmpty())
    }

    // ---------- v09: 异步 registerVoiceprint —— 回调成功且跑在后台线程(engineExecutor),不阻塞调用线程 ----------
    // 同时覆盖 setWorkPath 后台预装 eres2net 与异步注册的 @Synchronized 并发安全:紧跟 ensureReady() 就注册。
    @Test
    fun v09_register_async_offCallerThread_ok() {
        ensureReady()
        val sample = testCtx.assets.list("").orEmpty().first { it.contains("声纹") }
        val path = stageAsset(testCtx, ctx, sample, "vp_samples/${File(sample).name}")
        val callerThread = Thread.currentThread().name
        val latch = java.util.concurrent.CountDownLatch(1)
        val cbThread = java.util.concurrent.atomic.AtomicReference("")
        val id = java.util.concurrent.atomic.AtomicReference("")
        val err = java.util.concurrent.atomic.AtomicReference("")
        SpeechRecognizeSdk.registerVoiceprint(
            VoiceprintRegisterParams(samplePaths = listOf(path), audioInfo = AudioInfo()),
            object : com.amphion.dingqiao.VoiceprintRegisterCallback {
                override fun onResult(result: com.amphion.dingqiao.VoiceprintRegisterResult) {
                    cbThread.set(Thread.currentThread().name)
                    id.set(result.voiceprintId.keys.firstOrNull() ?: "")
                    latch.countDown()
                }
                override fun onError(errorCode: Int, errorMessage: String) {
                    cbThread.set(Thread.currentThread().name)
                    err.set("$errorCode $errorMessage")
                    latch.countDown()
                }
            },
        )
        val fired = latch.await(30, java.util.concurrent.TimeUnit.SECONDS)
        DqReport.append(ctx, mapOf("case" to "v09_register_async", "callerThread" to callerThread,
            "callbackThread" to cbThread.get(), "voiceprintId" to id.get(), "err" to err.get()))
        assertTrue("async callback must fire within 30s", fired)
        assertTrue("no error: ${err.get()}", err.get().isEmpty())
        assertTrue("voiceprint id should be returned", id.get().isNotBlank())
        assertTrue("callback must run OFF the caller thread (cb='${cbThread.get()}' caller='$callerThread')",
            cbThread.get() != callerThread)
        assertTrue("callback should run on the SDK engine executor 'dingqiao-engine', got '${cbThread.get()}'",
            cbThread.get().contains("dingqiao-engine"))
    }

    companion object {
        @Volatile private var engine: SpeechRecognitionEngine? = null
        @Volatile private var runtimePrepared: Boolean = false

        private fun workDir(): File {
            val target = InstrumentationRegistry.getInstrumentation().targetContext
            return File(target.getExternalFilesDir(null), "dq_vp_work")
        }

        @Synchronized
        private fun ensureReady() {
            if (runtimePrepared) return
            val target = InstrumentationRegistry.getInstrumentation().targetContext
            prepareSdkRuntime(target, workDir())
            runtimePrepared = true
        }

        @Synchronized
        private fun engine(): SpeechRecognitionEngine {
            engine?.let { return it }
            ensureReady()
            return SpeechRecognizeSdk.createEngine(
                CreateEngineParams(language = "zh-CN", online = DingqiaoOnlineMode.OFFLINE, extraParams = mapOf("vadEnd" to 800)),
            ).also { engine = it }
        }

        @Synchronized
        private fun freshEngine(): SpeechRecognitionEngine {
            engine?.shutdown()
            engine = null
            return engine()
        }
    }
}
