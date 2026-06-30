package com.amphion.dingqiao.demo

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.AudioInfo
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.DingqiaoErrorCode
import com.amphion.dingqiao.DingqiaoOnlineMode
import com.amphion.dingqiao.SpeechRecognitionEngine
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.StartParams
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.FixMethodOrder
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.MethodSorters

/**
 * 鼎桥 SDK（交付 AAR）on-device corner-case 套件：
 * 尾帧 flush、帧大小、会话生命周期、错误码、maxAudioDuration、语言、shutdown 后语义。
 *
 * 全程复用一个 zh-CN 引擎以摊薄模型加载成本；每个用例结束把引擎恢复到 idle。
 */
@RunWith(AndroidJUnit4::class)
@FixMethodOrder(MethodSorters.NAME_ASCENDING)
class DqSdkCornerCaseTest {

    private val ctx: Context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val testCtx: Context get() = InstrumentationRegistry.getInstrumentation().context

    private data class DecodeOutcome(
        val started: Boolean,
        val completed: Boolean,
        val finalText: String,
        val finalCount: Int,
        val lastIsLast: Boolean,
        val errorCodes: List<Int>,
    )

    // ---------- a01: 尾帧 flush —— 突然结束 vs 充分补静音 ----------
    @Test
    fun a01_tailFrame_abruptFinish_keepsTail() {
        val engine = sharedEngine()
        val files = mainWavs(testCtx)
        assertTrue("no main wavs; pass -PdingqiaoEvalAudioDir=/Users/boxp/Downloads/audio", files.isNotEmpty())
        var totalRatio = 0.0
        var counted = 0
        for (wav in files) {
            val pcm = readAssetPcm(testCtx, wav)
            val padded = decode(engine, "pad-${idOf(wav)}", pcm, frameSleepMs = 0, tailSilenceMs = 2_000, drainMs = 300)
            val abrupt = decode(engine, "abr-${idOf(wav)}", pcm, frameSleepMs = 0, tailSilenceMs = 0, drainMs = 0)
            val ratio = if (padded.finalText.isEmpty()) 1.0 else abrupt.finalText.length.toDouble() / padded.finalText.length
            DqReport.append(
                ctx,
                mapOf(
                    "case" to "a01_tailFrame",
                    "file" to wav,
                    "padded_text" to padded.finalText,
                    "abrupt_text" to abrupt.finalText,
                    "padded_len" to padded.finalText.length,
                    "abrupt_len" to abrupt.finalText.length,
                    "len_ratio" to ratio,
                    "padded_finalCount" to padded.finalCount,
                    "abrupt_finalCount" to abrupt.finalCount,
                    "abrupt_completed" to abrupt.completed,
                    "abrupt_lastIsLast" to abrupt.lastIsLast,
                    "abrupt_errors" to abrupt.errorCodes.toString(),
                ),
            )
            // 关键不变量：充分补静音能出 final 的句子，突然结束也必须出非空 final（尾帧未被整段丢弃）。
            if (padded.finalText.isNotEmpty()) {
                assertTrue("abrupt finish produced empty final for $wav (tail dropped)", abrupt.finalText.isNotEmpty())
                assertTrue("abrupt finish missing onComplete for $wav", abrupt.completed)
                assertTrue("abrupt finish last result not isLast for $wav", abrupt.lastIsLast)
            }
            totalRatio += ratio
            counted++
        }
        val avg = totalRatio / counted
        DqReport.append(ctx, mapOf("case" to "a01_tailFrame_summary", "files" to counted, "avg_len_ratio" to avg))
        // 仅在明显塌缩时硬失败；细粒度差异留报告人工复核。
        assertTrue("avg abrupt/padded length ratio too low: $avg", avg >= 0.5)
    }

    // ---------- a02: 帧大小校验 ----------
    @Test
    fun a02_frameSize_nonStandardRejected() {
        val engine = sharedEngine()
        val listener = CapturingListener().also { engine.setListener(it) }
        val sid = "frame-${System.currentTimeMillis()}"
        engine.startListening(StartParams(sid, AudioInfo()))
        assertTrue("start failed", listener.awaitStarted(10_000))
        engine.writeAudio(sid, ByteArray(DQ_FRAME)) // 640 ok
        engine.writeAudio(sid, ByteArray(320)) // 320 -> error
        engine.writeAudio(sid, ByteArray(1280)) // 1280 (legacy 40ms) -> error
        Thread.sleep(400)
        val codes = listener.errorCodes()
        DqReport.append(ctx, mapOf("case" to "a02_frameSize", "errorCodes" to codes.toString(), "count" to codes.size))
        engine.cancel(sid)
        awaitIdle(engine)
        assertTrue("expected RECOGNITION_ERROR for 320/1280 byte frames, got $codes",
            codes.count { it == DingqiaoErrorCode.RECOGNITION_ERROR } >= 2)
    }

    // ---------- a03: 未 start 就 writeAudio ----------
    @Test
    fun a03_writeBeforeStart_notListening() {
        val engine = sharedEngine()
        awaitIdle(engine)
        val listener = CapturingListener().also { engine.setListener(it) }
        engine.writeAudio("never-started", ByteArray(DQ_FRAME))
        assertTrue("expected an error", listener.awaitError(2_000))
        DqReport.append(ctx, mapOf("case" to "a03_writeBeforeStart", "errorCodes" to listener.errorCodes().toString()))
        assertTrue("expected NOT_LISTENING", listener.errorCodes().contains(DingqiaoErrorCode.NOT_LISTENING))
    }

    // ---------- a04: 重复 start 触发 BUSY ----------
    @Test
    fun a04_doubleStart_busy() {
        val engine = sharedEngine()
        awaitIdle(engine)
        val listener = CapturingListener().also { engine.setListener(it) }
        val sid1 = "busy-a-${System.currentTimeMillis()}"
        val sid2 = "busy-b-${System.currentTimeMillis()}"
        engine.startListening(StartParams(sid1, AudioInfo()))
        assertTrue(listener.awaitStarted(10_000))
        engine.startListening(StartParams(sid2, AudioInfo()))
        assertTrue("expected BUSY error", listener.awaitError(2_000))
        DqReport.append(ctx, mapOf("case" to "a04_doubleStart", "errorCodes" to listener.errorCodes().toString()))
        engine.cancel(sid1)
        awaitIdle(engine)
        assertTrue("expected ENGINE_BUSY", listener.errorCodes().contains(DingqiaoErrorCode.ENGINE_BUSY))
    }

    // ---------- a05: 空闲态 finish ----------
    @Test
    fun a05_finishWhenIdle_finishFailed() {
        val engine = sharedEngine()
        awaitIdle(engine)
        val listener = CapturingListener().also { engine.setListener(it) }
        engine.finish("idle-finish")
        assertTrue(listener.awaitError(2_000))
        DqReport.append(ctx, mapOf("case" to "a05_finishWhenIdle", "errorCodes" to listener.errorCodes().toString()))
        assertTrue("expected FINISH_FAILED", listener.errorCodes().contains(DingqiaoErrorCode.FINISH_FAILED))
    }

    // ---------- a06: cancel 不产生 final / complete ----------
    @Test
    fun a06_cancel_noFinalNoComplete() {
        val engine = sharedEngine()
        awaitIdle(engine)
        val listener = CapturingListener().also { engine.setListener(it) }
        val sid = "cancel-${System.currentTimeMillis()}"
        engine.startListening(StartParams(sid, AudioInfo()))
        assertTrue(listener.awaitStarted(10_000))
        val pcm = readAssetPcm(testCtx, mainWavs(testCtx).first())
        feedFrames(engine, sid, pcm.copyOfRange(0, minOf(pcm.size, DQ_SR * 2)), 0) // ~1s
        engine.cancel(sid)
        val gotComplete = listener.awaitComplete(2_000)
        DqReport.append(ctx, mapOf("case" to "a06_cancel", "gotComplete" to gotComplete, "finalCount" to listener.finals.size))
        awaitIdle(engine)
        assertFalse("cancel must not emit onComplete", gotComplete)
        assertTrue("cancel must not emit final", listener.finals.isEmpty())
    }

    // ---------- a07: 非法 sessionId ----------
    @Test
    fun a07_invalidSessionId_rejected() {
        val engine = sharedEngine()
        awaitIdle(engine)
        val l1 = CapturingListener().also { engine.setListener(it) }
        engine.startListening(StartParams("", AudioInfo()))
        assertTrue(l1.awaitError(2_000))
        awaitIdle(engine)
        val l2 = CapturingListener().also { engine.setListener(it) }
        engine.startListening(StartParams("bad id!#", AudioInfo()))
        assertTrue(l2.awaitError(2_000))
        DqReport.append(ctx, mapOf("case" to "a07_invalidSessionId",
            "emptyCodes" to l1.errorCodes().toString(), "badCodes" to l2.errorCodes().toString()))
        awaitIdle(engine)
        assertTrue("empty sid should fail start", l1.errorCodes().contains(DingqiaoErrorCode.START_LISTENING_FAILED))
        assertTrue("bad sid should fail start", l2.errorCodes().contains(DingqiaoErrorCode.START_LISTENING_FAILED))
    }

    // ---------- a08: writeAudio sessionId 不匹配 ----------
    @Test
    fun a08_writeWrongSessionId_mismatch() {
        val engine = sharedEngine()
        awaitIdle(engine)
        val listener = CapturingListener().also { engine.setListener(it) }
        val sid = "real-${System.currentTimeMillis()}"
        engine.startListening(StartParams(sid, AudioInfo()))
        assertTrue(listener.awaitStarted(10_000))
        engine.writeAudio("other-sid", ByteArray(DQ_FRAME))
        assertTrue(listener.awaitError(2_000))
        DqReport.append(ctx, mapOf("case" to "a08_wrongSessionId", "errorCodes" to listener.errorCodes().toString()))
        engine.cancel(sid)
        awaitIdle(engine)
        assertTrue("expected RECOGNITION_ERROR", listener.errorCodes().contains(DingqiaoErrorCode.RECOGNITION_ERROR))
    }

    // ---------- a09: maxAudioDuration 低于下限被静默抬到 20000 ----------
    @Test
    fun a09_maxAudioDuration_coercedBelowMin() {
        val engine = sharedEngine()
        awaitIdle(engine)
        // 选最长的主场景（~11.8s）：5000 应被 coerce 到 20000。若未 coerce（5000 当真），会在 5s
        // 自动结束，decode 后续帧会落到已结束会话而报 NOT_LISTENING，且只识别前 5s。
        val longest = mainWavs(testCtx).maxByOrNull { readAssetPcm(testCtx, it).size } ?: mainWavs(testCtx).first()
        val outcome = decode(engine, "maxcoerce-${idOf(longest)}", readAssetPcm(testCtx, longest),
            frameSleepMs = 0, tailSilenceMs = 300, drainMs = 200, maxAudioDuration = 5_000)
        DqReport.append(ctx, mapOf("case" to "a09_maxDurationCoercion", "file" to longest,
            "errorCodes" to outcome.errorCodes.toString(), "finalText" to outcome.finalText, "completed" to outcome.completed))
        assertFalse("MAX_AUDIO_DURATION must not be delivered anymore",
            outcome.errorCodes.contains(DingqiaoErrorCode.MAX_AUDIO_DURATION))
        assertFalse("session must not auto-finish at 5s (would cause NOT_LISTENING on later frames)",
            outcome.errorCodes.contains(DingqiaoErrorCode.NOT_LISTENING))
        assertTrue("~12s audio should be fully recognized when 5000 is coerced to 20000",
            outcome.completed && outcome.finalText.isNotEmpty())
    }

    // ---------- a10: 达到 maxAudioDuration 自动结束（出最终 onResult/onComplete，且可重新 start）----------
    @Test
    fun a10_maxAudioDuration_autoFinish() {
        val engine = sharedEngine()
        awaitIdle(engine)
        val longest = mainWavs(testCtx).maxByOrNull { readAssetPcm(testCtx, it).size } ?: mainWavs(testCtx).first()
        val pcm = readAssetPcm(testCtx, longest)
        val listener = CapturingListener().also { engine.setListener(it) }
        val sid = "maxexceed-${System.currentTimeMillis()}"
        engine.startListening(StartParams(sid, AudioInfo())) // default cap 20000
        assertTrue(listener.awaitStarted(10_000))
        // 喂入越过 20s 上限的音频；SDK 应在 20s 处自动结束，故喂到刚过上限或收到 onComplete 即停，
        // 避免继续向已结束的会话喂帧。
        var fedMs = 0L
        val targetMs = 22_000L
        outer@ while (fedMs < targetMs) {
            var off = 0
            while (off < pcm.size) {
                val n = minOf(DQ_FRAME, pcm.size - off)
                val f = ByteArray(DQ_FRAME)
                System.arraycopy(pcm, off, f, 0, n)
                engine.writeAudio(sid, f)
                off += n
                fedMs += DQ_FRAME_MS
                if (fedMs >= targetMs || listener.awaitComplete(0)) break@outer
            }
        }
        val completed = listener.awaitComplete(25_000)
        Thread.sleep(300)
        awaitIdle(engine)
        DqReport.append(ctx, mapOf("case" to "a10_maxDurationAutoFinish",
            "errorCodes" to listener.errorCodes().toString(), "completed" to completed,
            "lastIsLast" to (listener.lastFinal()?.isLast == true), "finalText" to listener.finalText()))
        // 达到上限是正常结束：不再出现 MAX_AUDIO_DURATION，应收到最终 onResult(isLast) 与 onComplete。
        assertFalse("MAX_AUDIO_DURATION must not be delivered anymore",
            listener.errorCodes().contains(DingqiaoErrorCode.MAX_AUDIO_DURATION))
        assertTrue("auto-finish should deliver onComplete", completed)
        assertTrue("final result should be marked isLast", listener.lastFinal()?.isLast == true)
        assertFalse("engine must be idle after auto-finish", engine.isBusy())
        // 关键回归：自动结束后可再次 startListening，不再 ENGINE_BUSY（覆盖原 engine is busy 现象）。
        val listener2 = CapturingListener().also { engine.setListener(it) }
        val sid2 = "maxexceed2-${System.currentTimeMillis()}"
        engine.startListening(StartParams(sid2, AudioInfo()))
        val restarted = listener2.awaitStarted(10_000)
        DqReport.append(ctx, mapOf("case" to "a10_restartAfterAutoFinish",
            "restarted" to restarted, "errorCodes" to listener2.errorCodes().toString()))
        assertTrue("should be able to startListening again after auto-finish", restarted)
        assertFalse("second start must not report ENGINE_BUSY",
            listener2.errorCodes().contains(DingqiaoErrorCode.ENGINE_BUSY))
        engine.cancel(sid2)
        awaitIdle(engine)
    }

    // ---------- a10b: 自动结束窗口内续喂帧不应报错 / 不应重复 complete ----------
    @Test
    fun a10b_autoFinishWindow_ignoresLateFrames() {
        val engine = sharedEngine()
        awaitIdle(engine)
        val pcm = readAssetPcm(testCtx, mainWavs(testCtx).first())
        val listener = CapturingListener().also { engine.setListener(it) }
        val sid = "maxlate-${System.currentTimeMillis()}"
        engine.startListening(StartParams(sid, AudioInfo()))
        assertTrue(listener.awaitStarted(10_000))

        // 先快速喂到刚超过 20s，上限触发后继续补少量帧，模拟采集线程尚未停止的窗口。
        var fedMs = 0L
        while (fedMs < 21_000L) {
            var off = 0
            while (off < pcm.size && fedMs < 21_000L) {
                val n = minOf(DQ_FRAME, pcm.size - off)
                val f = ByteArray(DQ_FRAME)
                System.arraycopy(pcm, off, f, 0, n)
                engine.writeAudio(sid, f)
                off += n
                fedMs += DQ_FRAME_MS
            }
        }
        repeat(80) { engine.writeAudio(sid, ByteArray(DQ_FRAME)) }

        val completed = listener.awaitComplete(25_000)
        Thread.sleep(1_800)
        awaitIdle(engine)
        DqReport.append(ctx, mapOf("case" to "a10b_autoFinishLateFrames",
            "completed" to completed, "completeCount" to listener.completes.size,
            "finalCount" to listener.finals.size, "errorCodes" to listener.errorCodes().toString()))
        assertTrue("auto-finish should complete despite late frames", completed)
        assertEquals("auto-finish must complete exactly once", 1, listener.completes.size)
        assertFalse("late frames must not surface MAX_AUDIO_DURATION",
            listener.errorCodes().contains(DingqiaoErrorCode.MAX_AUDIO_DURATION))
        assertFalse("late frames before complete must not surface NOT_LISTENING",
            listener.errorCodes().contains(DingqiaoErrorCode.NOT_LISTENING))
        assertFalse("engine must be idle after auto-finish late-frame window", engine.isBusy())
    }

    // ---------- a10c: 重复 finish 幂等，不重复 complete，不 busy 卡死 ----------
    @Test
    fun a10c_finishIdempotent_singleComplete() {
        val engine = sharedEngine()
        awaitIdle(engine)
        val listener = CapturingListener().also { engine.setListener(it) }
        val sid = "finish2-${System.currentTimeMillis()}"
        engine.startListening(StartParams(sid, AudioInfo(), extraParams = mapOf("vadEnd" to 800)))
        assertTrue(listener.awaitStarted(10_000))
        val pcm = readAssetPcm(testCtx, mainWavs(testCtx).first())
        feedFrames(engine, sid, pcm.copyOfRange(0, minOf(pcm.size, DQ_SR * 2)), 0)
        engine.finish(sid)
        engine.finish(sid)
        val completed = listener.awaitComplete(25_000)
        Thread.sleep(1_800)
        awaitIdle(engine)
        DqReport.append(ctx, mapOf("case" to "a10c_finishIdempotent",
            "completed" to completed, "completeCount" to listener.completes.size,
            "finalCount" to listener.finals.size, "errorCodes" to listener.errorCodes().toString()))
        assertTrue("finish should complete", completed)
        assertEquals("duplicate finish must not duplicate onComplete", 1, listener.completes.size)
        assertFalse("engine must be idle after duplicate finish", engine.isBusy())
    }

    // ---------- a11: 不支持的语言 ----------
    @Test
    fun a11_unsupportedLanguage_createFails() {
        var code: Int? = null
        var thrown: String? = null
        try {
            SpeechRecognizeSdk.createEngine(CreateEngineParams(language = "en-US", online = DingqiaoOnlineMode.OFFLINE))
        } catch (t: Throwable) {
            thrown = t.javaClass.simpleName
            code = runCatching { t.javaClass.getMethod("getErrorCode").invoke(t) as? Int }.getOrNull()
        }
        DqReport.append(ctx, mapOf("case" to "a11_unsupportedLanguage", "thrown" to thrown, "errorCode" to code))
        assertNotNull("createEngine with en-US should throw", thrown)
        assertTrue("expected CREATE_ENGINE_FAILED", code == DingqiaoErrorCode.CREATE_ENGINE_FAILED || code == null)
    }

    // ---------- a12: shutdown 后调用抛异常而非回调 onError ----------
    @Test
    fun a12_postShutdown_throwsInsteadOfCallback() {
        ensureSdkReady()
        val throwaway = SpeechRecognizeSdk.createEngine(
            CreateEngineParams(language = "zh-CN", online = DingqiaoOnlineMode.OFFLINE),
        )
        val listener = CapturingListener().also { throwaway.setListener(it) }
        throwaway.shutdown()
        var thrown: String? = null
        var thrownMsg: String? = null
        try {
            throwaway.writeAudio("x", ByteArray(DQ_FRAME))
        } catch (t: Throwable) {
            thrown = t.javaClass.simpleName
            thrownMsg = t.message
        }
        Thread.sleep(300)
        DqReport.append(ctx, mapOf("case" to "a12_postShutdown",
            "thrown" to thrown, "thrownMsg" to thrownMsg, "callbackErrors" to listener.errorCodes().toString()))
        assertNotNull("post-shutdown writeAudio should throw (not deliver onError)", thrown)
        assertTrue("post-shutdown should NOT deliver onError callback", listener.errors.isEmpty())
    }

    // ---------- helpers ----------
    private fun decode(
        engine: SpeechRecognitionEngine,
        sid: String,
        pcm: ByteArray,
        frameSleepMs: Long,
        tailSilenceMs: Int,
        drainMs: Long,
        maxAudioDuration: Int = 60_000,
    ): DecodeOutcome {
        val listener = CapturingListener().also { engine.setListener(it) }
        engine.startListening(
            StartParams(
                sessionId = sid,
                audioInfo = AudioInfo(),
                extraParams = mapOf(
                    "enablePartialResult" to true,
                    "maxAudioDuration" to maxAudioDuration,
                    "vadEnd" to 800,
                ),
            ),
        )
        if (!listener.awaitStarted(10_000)) {
            return DecodeOutcome(false, false, "", 0, false, listener.errorCodes())
        }
        feedFrames(engine, sid, pcm, frameSleepMs)
        feedSilence(engine, sid, tailSilenceMs)
        if (drainMs > 0) Thread.sleep(drainMs)
        engine.finish(sid)
        val completed = listener.awaitComplete(25_000)
        Thread.sleep(300)
        awaitIdle(engine)
        return DecodeOutcome(
            started = true,
            completed = completed,
            finalText = listener.finalText(),
            finalCount = listener.finals.size,
            lastIsLast = listener.lastFinal()?.isLast == true,
            errorCodes = listener.errorCodes(),
        )
    }

    private fun idOf(wav: String): String = Integer.toHexString(wav.hashCode()) + "-" + (seq++)

    companion object {
        @Volatile private var engine: SpeechRecognitionEngine? = null
        @Volatile private var seq = 0

        private fun ensureSdkReady() {
            val target = InstrumentationRegistry.getInstrumentation().targetContext
            SpeechRecognizeSdk.init(target)
            SpeechRecognizeSdk.setWorkPath(File(target.getExternalFilesDir(null), "dq_corner_work").absolutePath)
        }

        @Synchronized
        fun sharedEngine(): SpeechRecognitionEngine {
            engine?.let { return it }
            ensureSdkReady()
            return SpeechRecognizeSdk.createEngine(
                CreateEngineParams(language = "zh-CN", online = DingqiaoOnlineMode.OFFLINE, extraParams = mapOf("vadEnd" to 800)),
            ).also { engine = it }
        }
    }
}
