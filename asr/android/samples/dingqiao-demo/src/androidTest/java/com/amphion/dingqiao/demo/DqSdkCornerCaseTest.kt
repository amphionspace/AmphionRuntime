package com.amphion.dingqiao.demo

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.AudioInfo
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.DingqiaoErrorCode
import com.amphion.dingqiao.DingqiaoEventCode
import com.amphion.dingqiao.DingqiaoOnlineMode
import com.amphion.dingqiao.RecognitionListener
import com.amphion.dingqiao.SpeechRecognitionEngine
import com.amphion.dingqiao.SpeechRecognitionResult
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.StartParams
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
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
        assertTrue("no main wavs; pass -PdingqiaoEvalAudioDir=/path/to/audio", files.isNotEmpty())
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
            // 关键不变量：同一 PCM 的立即 finish 必须逐字等于充分尾上下文基线；只检查非空或长度比例
            // 会漏掉客户反馈的单个尾字丢失。
            if (padded.finalText.isNotEmpty()) {
                assertTrue("abrupt finish produced empty final for $wav (tail dropped)", abrupt.finalText.isNotEmpty())
                assertTrue("abrupt finish missing onComplete for $wav", abrupt.completed)
                assertTrue("abrupt finish last result not isLast for $wav", abrupt.lastIsLast)
                assertEquals(
                    "$wav abrupt finish must preserve the padded-reference tail",
                    padded.finalText,
                    abrupt.finalText,
                )
            }
            totalRatio += ratio
            counted++
        }
        val avg = totalRatio / counted
        DqReport.append(ctx, mapOf("case" to "a01_tailFrame_summary", "files" to counted, "avg_len_ratio" to avg))
        // 保留汇总指标用于报告，但逐文件逐字断言才是发布门禁。
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

    // ---------- a09: 正数 maxAudioDuration 原样生效，不再静默抬到 20 秒 ----------
    @Test
    fun a09_maxAudioDuration_explicitShortLimitAutoFinishes() {
        val engine = sharedEngine()
        awaitIdle(engine)
        val listener = CapturingListener().also { engine.setListener(it) }
        val sid = "maxshort-${System.currentTimeMillis()}"
        engine.startListening(
            StartParams(sid, AudioInfo(), mapOf("maxAudioDuration" to 5_000)),
        )
        assertTrue(listener.awaitStarted(10_000))
        feedSilence(engine, sid, 5_200)
        val completed = listener.awaitComplete(10_000)
        awaitIdle(engine)

        DqReport.append(ctx, mapOf("case" to "a09_maxDurationShort",
            "errorCodes" to listener.errorCodes().toString(), "completed" to completed,
            "completeCount" to listener.completes.size,
            "lastCount" to listener.finals.count { it.isLast }))
        assertFalse("MAX_AUDIO_DURATION must not be delivered anymore",
            listener.errorCodes().contains(DingqiaoErrorCode.MAX_AUDIO_DURATION))
        assertTrue("explicit 5000ms maxAudioDuration should auto-finish", completed)
        assertEquals("auto-finish must complete exactly once", 1, listener.completes.size)
        assertEquals("auto-finish must emit exactly one last result", 1,
            listener.finals.count { it.isLast })
    }

    // ---------- a09b: 非有限 maxAudioDuration 必须视为未配置 ----------
    @Test
    fun a09b_maxAudioDuration_nonFiniteValuesStayDisabled() {
        val engine = sharedEngine()
        val pcm = readAssetPcm(testCtx, mainWavs(testCtx).first())
        for ((label, value) in listOf("nan" to Double.NaN, "infinity" to Double.POSITIVE_INFINITY)) {
            awaitIdle(engine)
            val listener = CapturingListener().also { engine.setListener(it) }
            val sid = "max-$label-${System.currentTimeMillis()}"
            engine.startListening(
                StartParams(sid, AudioInfo(), mapOf("maxAudioDuration" to value)),
            )
            assertTrue("$label start failed", listener.awaitStarted(10_000))
            feedFrames(engine, sid, pcm.copyOfRange(0, minOf(pcm.size, DQ_SR * 4)), 0)
            Thread.sleep(300)
            assertTrue("$label must not auto-finish the session", engine.isBusy())
            assertTrue("$label must not emit complete before explicit finish",
                listener.completes.isEmpty())
            engine.finish(sid)
            assertTrue("$label explicit finish must complete", listener.awaitComplete(20_000))
            awaitIdle(engine)
            assertTrue("$label must not report errors", listener.errors.isEmpty())
        }
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
        engine.startListening(
            StartParams(sid, AudioInfo(), mapOf("maxAudioDuration" to 8_000)),
        )
        assertTrue(listener.awaitStarted(10_000))
        // 喂入越过 8s 上限；SDK 应在 8s 处自动结束，故喂到刚过上限或收到 onComplete 即停，
        // 避免继续向已结束的会话喂帧。
        var fedMs = 0L
        val targetMs = 9_000L
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
        engine.startListening(
            StartParams(sid, AudioInfo(), mapOf("maxAudioDuration" to 8_000)),
        )
        assertTrue(listener.awaitStarted(10_000))

        // 先快速喂到刚超过 8s，上限触发后继续补少量帧，模拟采集线程尚未停止的窗口。
        var fedMs = 0L
        while (fedMs < 8_400L) {
            var off = 0
            while (off < pcm.size && fedMs < 8_400L) {
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

    // ---------- a10d: 最终结果回调内用相同 sessionId 重启，旧会话仍须完整 complete ----------
    @Test
    fun a10d_terminalCallback_reentrantReplacementOwnsCompletion() {
        val engine = sharedEngine()
        awaitIdle(engine)
        val oldSid = "reentrant-old-${System.currentTimeMillis()}"
        val newSid = oldSid
        val oldStarted = CountDownLatch(1)
        val oldLast = CountDownLatch(1)
        val newStarted = CountDownLatch(1)
        val newCompleted = CountDownLatch(1)
        val oldCompleteCount = AtomicInteger(0)
        val oldLastCount = AtomicInteger(0)
        val newCompleteCount = AtomicInteger(0)
        val callbackErrors = mutableListOf<Int>()
        val timeline = mutableListOf<String>()

        val replacementListener = object : RecognitionListener {
            override fun onStart(sessionId: String, eventMessage: String) {
                if (sessionId == newSid) {
                    synchronized(timeline) { timeline += "new:start" }
                    newStarted.countDown()
                }
            }

            override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) = Unit
            override fun onResult(sessionId: String, result: SpeechRecognitionResult) = Unit
            override fun onComplete(sessionId: String, eventMessage: String) {
                newCompleteCount.incrementAndGet()
                newCompleted.countDown()
            }
            override fun onError(sessionId: String, errorCode: Int, errorMessage: String) {
                synchronized(callbackErrors) { callbackErrors += errorCode }
            }
        }
        val oldListener = object : RecognitionListener {
            override fun onStart(sessionId: String, eventMessage: String) {
                oldStarted.countDown()
                engine.finish(oldSid)
            }

            override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) = Unit

            override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
                if (!result.isLast) return
                oldLastCount.incrementAndGet()
                synchronized(timeline) { timeline += "old:last" }
                engine.cancel(oldSid)
                engine.setListener(replacementListener)
                engine.startListening(StartParams(newSid, AudioInfo()))
                engine.writeAudio(newSid, ByteArray(DQ_FRAME))
                engine.finish(newSid)
                oldLast.countDown()
            }

            override fun onComplete(sessionId: String, eventMessage: String) {
                oldCompleteCount.incrementAndGet()
                synchronized(timeline) { timeline += "old:complete" }
                engine.cancel(oldSid)
                engine.finish(oldSid)
                engine.setSpeakerVadEnabled(false)
            }

            override fun onError(sessionId: String, errorCode: Int, errorMessage: String) {
                synchronized(callbackErrors) { callbackErrors += errorCode }
            }
        }

        engine.setListener(oldListener)
        engine.startListening(StartParams(oldSid, AudioInfo()))
        assertTrue("old onStart not delivered", oldStarted.await(10_000, TimeUnit.MILLISECONDS))
        assertTrue("old terminal result not delivered", oldLast.await(10_000, TimeUnit.MILLISECONDS))
        assertTrue("replacement onStart not delivered", newStarted.await(10_000, TimeUnit.MILLISECONDS))
        assertTrue("replacement did not complete after same-stack write+finish",
            newCompleted.await(10_000, TimeUnit.MILLISECONDS))
        Thread.sleep(500)

        DqReport.append(ctx, mapOf("case" to "a10d_terminalReentry",
            "oldLastCount" to oldLastCount.get(), "oldCompleteCount" to oldCompleteCount.get(),
            "newCompleteCount" to newCompleteCount.get(),
            "timeline" to synchronized(timeline) { timeline.toString() },
            "callbackErrors" to synchronized(callbackErrors) { callbackErrors.toString() }))
        assertEquals("old session must emit exactly one last result", 1, oldLastCount.get())
        assertEquals("old last result must be followed by exactly one onComplete", 1, oldCompleteCount.get())
        assertEquals("replacement must complete after same-stack write+finish", 1,
            newCompleteCount.get())
        assertEquals(
            "old terminal callbacks must finish before replacement onStart",
            listOf("old:last", "old:complete", "new:start"),
            synchronized(timeline) { timeline.toList() },
        )
        assertTrue("reentrant replacement must not report callback errors",
            synchronized(callbackErrors) { callbackErrors.isEmpty() })
        awaitIdle(engine)
    }

    // ---------- a10e: onStart 调用栈内回放真实 PCM，返回后继续识别 ----------
    @Test
    fun a10e_onStartSynchronousWrite_thenContinue() {
        val engine = sharedEngine()
        awaitIdle(engine)
        val pcm = readAssetPcm(testCtx, mainWavs(testCtx).first())
        val split = minOf(pcm.size, DQ_SR * 2)
        val sid = "start-write-${System.currentTimeMillis()}"
        val listener = CapturingListener { callbackSid ->
            feedFrames(engine, callbackSid, pcm.copyOfRange(0, split), 0)
        }.also { engine.setListener(it) }

        engine.startListening(StartParams(sid, AudioInfo(), mapOf("vadEnd" to 800)))
        assertTrue("onStart stack write did not return", listener.awaitStarted(15_000))
        feedFrames(engine, sid, pcm.copyOfRange(split, pcm.size), 0)
        engine.finish(sid)
        val completed = listener.awaitComplete(25_000)
        awaitIdle(engine)

        DqReport.append(ctx, mapOf("case" to "a10e_startWriteContinue",
            "completed" to completed, "lastCount" to listener.finals.count { it.isLast },
            "errorCodes" to listener.errorCodes().toString()))
        assertTrue("start-write continuation must complete", completed)
        assertEquals("normal session must emit exactly one last", 1, listener.finals.count { it.isLast })
        assertFalse("onStart write must not observe NOT_LISTENING",
            listener.errorCodes().contains(DingqiaoErrorCode.NOT_LISTENING))
    }

    // ---------- a10f: onStart 调用栈内回放真实 PCM 后立即 finish ----------
    @Test
    fun a10f_onStartSynchronousWrite_thenImmediateFinish() {
        val engine = sharedEngine()
        awaitIdle(engine)
        val pcm = readAssetPcm(testCtx, mainWavs(testCtx).first())
        val cached = pcm.copyOfRange(0, minOf(pcm.size, DQ_SR * 3))
        val sid = "start-write-finish-${System.currentTimeMillis()}"
        val listener = CapturingListener { callbackSid ->
            feedFrames(engine, callbackSid, cached, 0)
            engine.finish(callbackSid)
        }.also { engine.setListener(it) }

        engine.startListening(StartParams(sid, AudioInfo(), mapOf("vadEnd" to 800)))
        assertTrue("onStart stack write+finish did not return", listener.awaitStarted(15_000))
        val completed = listener.awaitComplete(25_000)
        awaitIdle(engine)

        DqReport.append(ctx, mapOf("case" to "a10f_startWriteFinish",
            "completed" to completed, "completeCount" to listener.completes.size,
            "lastCount" to listener.finals.count { it.isLast },
            "errorCodes" to listener.errorCodes().toString()))
        assertTrue("onStart immediate finish must complete", completed)
        assertEquals("finish must complete exactly once", 1, listener.completes.size)
        assertEquals("finish must emit exactly one last", 1, listener.finals.count { it.isLast })
        assertFalse("onStart API calls must not observe NOT_LISTENING",
            listener.errorCodes().contains(DingqiaoErrorCode.NOT_LISTENING))
    }

    // ---------- a10g: shutdown 后重新冷建引擎，onStart 内同步写入仍可用 ----------
    @Test
    fun a10g_onStartSynchronousWrite_afterEngineReload() {
        val engine = reloadEngine()
        val pcm = readAssetPcm(testCtx, mainWavs(testCtx).first())
        val cached = pcm.copyOfRange(0, minOf(pcm.size, DQ_SR * 3))
        val sid = "start-write-reload-${System.currentTimeMillis()}"
        val listener = CapturingListener { callbackSid ->
            feedFrames(engine, callbackSid, cached, 0)
            engine.finish(callbackSid)
        }.also { engine.setListener(it) }

        engine.startListening(StartParams(sid, AudioInfo(), mapOf("vadEnd" to 800)))
        assertTrue("reloaded engine onStart write+finish did not return", listener.awaitStarted(20_000))
        val completed = listener.awaitComplete(30_000)
        awaitIdle(engine)

        DqReport.append(ctx, mapOf("case" to "a10g_startWriteReload",
            "completed" to completed, "completeCount" to listener.completes.size,
            "lastCount" to listener.finals.count { it.isLast },
            "errorCodes" to listener.errorCodes().toString()))
        assertTrue("reloaded engine session must complete", completed)
        assertEquals("reloaded engine must emit one complete", 1, listener.completes.size)
        assertEquals("reloaded engine must emit one last", 1, listener.finals.count { it.isLast })
        assertTrue("reloaded engine must not report errors", listener.errors.isEmpty())
    }

    // ---------- a10ga: onStart 内 cancel 并复用相同 ID，新会话不得收到旧回调 ----------
    @Test
    fun a10ga_onStartCancel_sameIdReplacementOwnsCallbacks() {
        val engine = sharedEngine()
        awaitIdle(engine)
        val sid = "start-cancel-${System.currentTimeMillis()}"
        val replacementStarted = CountDownLatch(1)
        val replacement = CapturingListener { replacementSid ->
            replacementStarted.countDown()
            engine.finish(replacementSid)
        }
        val oldErrors = mutableListOf<Int>()
        val oldListener = object : RecognitionListener {
            override fun onStart(sessionId: String, eventMessage: String) {
                engine.cancel(sessionId)
                engine.setListener(replacement)
                engine.startListening(StartParams(sessionId, AudioInfo()))
            }

            override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) = Unit
            override fun onResult(sessionId: String, result: SpeechRecognitionResult) = Unit
            override fun onComplete(sessionId: String, eventMessage: String) = Unit
            override fun onError(sessionId: String, errorCode: Int, errorMessage: String) {
                synchronized(oldErrors) { oldErrors += errorCode }
            }
        }

        engine.setListener(oldListener)
        engine.startListening(StartParams(sid, AudioInfo()))
        assertTrue("replacement onStart not delivered",
            replacementStarted.await(15_000, TimeUnit.MILLISECONDS))
        assertTrue("replacement did not complete", replacement.awaitComplete(15_000))
        awaitIdle(engine)

        DqReport.append(ctx, mapOf("case" to "a10ga_onStartCancelReplacement",
            "replacementCompleteCount" to replacement.completes.size,
            "replacementLastCount" to replacement.finals.count { it.isLast },
            "replacementErrors" to replacement.errorCodes().toString(),
            "oldErrors" to synchronized(oldErrors) { oldErrors.toString() }))
        assertEquals("replacement must complete once", 1, replacement.completes.size)
        assertEquals("replacement must emit one last", 1,
            replacement.finals.count { it.isLast })
        assertTrue("old session must not emit an error after cancel",
            synchronized(oldErrors) { oldErrors.isEmpty() })
        assertTrue("replacement must not report errors", replacement.errors.isEmpty())
    }

    // ---------- a10gb: 客户回调不得持有 engine monitor 阻塞其他录音线程 ----------
    @Test
    fun a10gb_onStartCanWaitForOtherThreadWriteAudio() {
        val engine = sharedEngine()
        val worker = Executors.newSingleThreadExecutor()
        try {
            repeat(2) { round ->
                awaitIdle(engine)
                val sid = "callback-worker-$round-${System.currentTimeMillis()}"
                val workerReturned = CountDownLatch(1)
                val listener = CapturingListener { callbackSid ->
                    worker.execute {
                        engine.writeAudio(callbackSid, ByteArray(DQ_FRAME))
                        engine.finish(callbackSid)
                        workerReturned.countDown()
                    }
                    assertTrue("recording worker was blocked by the customer callback",
                        workerReturned.await(2_000, TimeUnit.MILLISECONDS))
                }.also { engine.setListener(it) }

                engine.startListening(StartParams(sid, AudioInfo()))
                assertTrue("round $round onStart worker did not return",
                    listener.awaitStarted(10_000))
                assertTrue("round $round did not complete after worker write",
                    listener.awaitComplete(15_000))
                awaitIdle(engine)

                DqReport.append(ctx, mapOf("case" to "a10gb_callbackWorkerWrite",
                    "round" to round,
                    "completeCount" to listener.completes.size,
                    "lastCount" to listener.finals.count { it.isLast },
                    "errorCodes" to listener.errorCodes().toString()))
                assertEquals("round $round must complete once", 1, listener.completes.size)
                assertEquals("round $round must emit one last", 1,
                    listener.finals.count { it.isLast })
                assertTrue("round $round must not report errors", listener.errors.isEmpty())
            }
        } finally {
            worker.shutdownNow()
        }
    }

    @Test
    fun a10h_lateOldWrite_doesNotAffectReplacement() {
        assertLateOldCallDoesNotAffectReplacement("write") { engine, sid ->
            engine.writeAudio(sid, ByteArray(DQ_FRAME))
        }
    }

    @Test
    fun a10i_lateOldFinish_doesNotAffectReplacement() {
        assertLateOldCallDoesNotAffectReplacement("finish") { engine, sid ->
            engine.finish(sid)
        }
    }

    @Test
    fun a10j_lateOldCancel_doesNotAffectReplacement() {
        assertLateOldCallDoesNotAffectReplacement("cancel") { engine, sid ->
            engine.cancel(sid)
        }
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
        // Reuse the already licensed/prepared Runtime. Repeating setLicense here would correctly
        // invalidate the shared engine and make the following ordered stress case reuse a stale
        // test fixture rather than exercise a live SDK engine.
        sharedEngine()
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

    // ---------- a13: 真实调用方连续 cancel / finish / 立即替换 / 旧 session 迟到调用 ----------
    @Test
    fun a13_userSequenceStress_300Cycles() {
        val engine = sharedEngine()
        val source = readAssetPcm(testCtx, mainWavs(testCtx).first())
        val pcm = source.copyOfRange(0, minOf(source.size, DQ_SR * 3))
        var completedSessions = 0

        repeat(300) { cycle ->
            awaitIdle(engine)

            val cancelSid = "useq-c-$cycle-${System.currentTimeMillis()}"
            val cancelListener = CapturingListener().also { engine.setListener(it) }
            engine.startListening(StartParams(cancelSid, AudioInfo()))
            assertTrue("cycle=$cycle cancel session did not start",
                cancelListener.awaitStarted(10_000))
            feedFrames(engine, cancelSid, pcm.copyOfRange(0, minOf(pcm.size, DQ_SR)), 0)
            engine.cancel(cancelSid)
            awaitIdle(engine)
            assertFalse("cycle=$cycle cancel session remained busy", engine.isBusy())
            // Keep the cancel listener installed through a short quiescence window so callbacks
            // queued immediately before the state transition cannot escape the assertion.
            Thread.sleep(100)
            assertTrue("cycle=$cycle cancel must not emit final", cancelListener.finals.isEmpty())
            assertTrue("cycle=$cycle cancel must not emit complete",
                cancelListener.completes.isEmpty())

            val oldSid = "useq-old-$cycle-${System.currentTimeMillis()}"
            val oldListener = CapturingListener().also { engine.setListener(it) }
            engine.startListening(StartParams(oldSid, AudioInfo()))
            assertTrue("cycle=$cycle old session did not start", oldListener.awaitStarted(10_000))
            feedFrames(engine, oldSid, pcm, 0)
            assertEquals(
                "cycle=$cycle old session emitted isLast before finish",
                0,
                oldListener.finals.count { it.isLast },
            )
            engine.finish(oldSid)
            assertTrue("cycle=$cycle old session did not complete",
                oldListener.awaitComplete(20_000))
            assertEquals("cycle=$cycle old session last count", 1,
                oldListener.finals.count { it.isLast })
            assertEquals("cycle=$cycle old session complete count", 1,
                oldListener.completes.size)
            assertTrue("cycle=$cycle old session errors=${oldListener.errors}",
                oldListener.errors.isEmpty())
            awaitIdle(engine)
            completedSessions++

            val replacementSid = "useq-new-$cycle-${System.currentTimeMillis()}"
            val replacementStarted = CountDownLatch(1)
            val replacementComplete = CountDownLatch(1)
            val replacementLastCount = AtomicInteger(0)
            val replacementCompleteCount = AtomicInteger(0)
            val replacementErrors = mutableListOf<Int>()
            val unexpectedTerminalCallbacks = AtomicInteger(0)
            engine.setListener(object : RecognitionListener {
                override fun onStart(sessionId: String, eventMessage: String) {
                    if (sessionId == replacementSid) replacementStarted.countDown()
                }

                override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) = Unit

                override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
                    if (sessionId == replacementSid) {
                        if (result.isLast) replacementLastCount.incrementAndGet()
                    } else if (result.isLast) {
                        unexpectedTerminalCallbacks.incrementAndGet()
                    }
                }

                override fun onComplete(sessionId: String, eventMessage: String) {
                    if (sessionId == replacementSid) {
                        replacementCompleteCount.incrementAndGet()
                        replacementComplete.countDown()
                    } else {
                        unexpectedTerminalCallbacks.incrementAndGet()
                    }
                }

                override fun onError(sessionId: String, errorCode: Int, errorMessage: String) {
                    if (sessionId == replacementSid) {
                        synchronized(replacementErrors) { replacementErrors += errorCode }
                    }
                }
            })
            engine.startListening(StartParams(replacementSid, AudioInfo()))
            assertTrue("cycle=$cycle replacement did not start",
                replacementStarted.await(10_000, TimeUnit.MILLISECONDS))

            engine.writeAudio(oldSid, ByteArray(DQ_FRAME))
            engine.finish(oldSid)
            engine.cancel(oldSid)
            assertTrue("cycle=$cycle late old calls ended replacement", engine.isBusy())

            feedFrames(engine, replacementSid, pcm, 0)
            assertEquals(
                "cycle=$cycle replacement emitted isLast before finish",
                0,
                replacementLastCount.get(),
            )
            engine.finish(replacementSid)
            assertTrue("cycle=$cycle replacement did not complete",
                replacementComplete.await(20_000, TimeUnit.MILLISECONDS))
            assertEquals("cycle=$cycle replacement last count", 1,
                replacementLastCount.get())
            assertEquals("cycle=$cycle replacement complete count", 1,
                replacementCompleteCount.get())
            assertEquals("cycle=$cycle old terminal callback polluted replacement", 0,
                unexpectedTerminalCallbacks.get())
            assertTrue(
                "cycle=$cycle replacement errors=$replacementErrors",
                synchronized(replacementErrors) { replacementErrors.isEmpty() },
            )
            awaitIdle(engine)
            completedSessions++
        }

        DqReport.append(
            ctx,
            mapOf(
                "case" to "a13_userSequenceStress",
                "cycles" to 300,
                "completedSessions" to completedSessions,
            ),
        )
        assertEquals(600, completedSessions)
    }

    // ---------- a11: vadBegin 首段静音自动结束 ----------
    @Test
    fun a11_vadBegin_initialSilenceAutoFinish() {
        val engine = sharedEngine()
        awaitIdle(engine)
        val listener = CapturingListener().also { engine.setListener(it) }
        val sid = "vadbegin-${System.currentTimeMillis()}"
        engine.startListening(
            StartParams(
                sid,
                AudioInfo(),
                mapOf("vadBegin" to 500, "enablePartialResult" to false),
            ),
        )
        assertTrue(listener.awaitStarted(10_000))
        feedSilence(engine, sid, 700)
        val completed = listener.awaitComplete(10_000)
        awaitIdle(engine)

        assertTrue("vadBegin should complete a no-input session", completed)
        assertEquals("no-input final must be empty", "", listener.lastFinal()?.result)
        assertTrue("no-input final must close the session", listener.lastFinal()?.isLast == true)
        assertFalse(listener.events.any { it.first == DingqiaoEventCode.SPEECH_BEGIN })
        assertFalse(listener.events.any { it.first == DingqiaoEventCode.SPEECH_END })
        assertTrue(listener.errors.isEmpty())
        assertFalse(engine.isBusy())
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

    private fun assertLateOldCallDoesNotAffectReplacement(
        operationName: String,
        lateCall: (SpeechRecognitionEngine, String) -> Unit,
    ) {
        val engine = sharedEngine()
        awaitIdle(engine)
        val oldSid = "late-$operationName-old-${System.currentTimeMillis()}"
        val oldListener = CapturingListener().also { engine.setListener(it) }
        engine.startListening(StartParams(oldSid, AudioInfo()))
        assertTrue("old session did not start", oldListener.awaitStarted(10_000))
        engine.cancel(oldSid)
        awaitIdle(engine)

        val newSid = "late-$operationName-new-${System.currentTimeMillis()}"
        val newStarted = CountDownLatch(1)
        val newComplete = CountDownLatch(1)
        val newLastCount = AtomicInteger(0)
        val newCompleteCount = AtomicInteger(0)
        val newErrors = mutableListOf<Int>()
        engine.setListener(object : RecognitionListener {
            override fun onStart(sessionId: String, eventMessage: String) {
                if (sessionId == newSid) newStarted.countDown()
            }

            override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) = Unit

            override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
                if (sessionId == newSid && result.isLast) newLastCount.incrementAndGet()
            }

            override fun onComplete(sessionId: String, eventMessage: String) {
                if (sessionId == newSid) {
                    newCompleteCount.incrementAndGet()
                    newComplete.countDown()
                }
            }

            override fun onError(sessionId: String, errorCode: Int, errorMessage: String) {
                if (sessionId == newSid) synchronized(newErrors) { newErrors += errorCode }
            }
        })
        engine.startListening(StartParams(newSid, AudioInfo()))
        assertTrue("replacement session did not start", newStarted.await(10_000, TimeUnit.MILLISECONDS))

        lateCall(engine, oldSid)
        assertTrue("late old $operationName ended replacement", engine.isBusy())
        engine.finish(newSid)
        assertTrue("replacement did not complete", newComplete.await(20_000, TimeUnit.MILLISECONDS))
        awaitIdle(engine)

        assertEquals("replacement must emit one last", 1, newLastCount.get())
        assertEquals("replacement must emit one complete", 1, newCompleteCount.get())
        assertTrue("replacement must not receive old-call errors",
            synchronized(newErrors) { newErrors.isEmpty() })
    }

    companion object {
        @Volatile private var engine: SpeechRecognitionEngine? = null
        @Volatile private var seq = 0

        private fun ensureSdkReady() {
            val target = InstrumentationRegistry.getInstrumentation().targetContext
            val test = InstrumentationRegistry.getInstrumentation().context
            prepareSdkRuntime(
                test,
                target,
                File(target.getExternalFilesDir(null), "dq_corner_work"),
            )
        }

        @Synchronized
        fun sharedEngine(): SpeechRecognitionEngine {
            engine?.let { return it }
            ensureSdkReady()
            return SpeechRecognizeSdk.createEngine(
                CreateEngineParams(language = "zh-CN", online = DingqiaoOnlineMode.OFFLINE, extraParams = mapOf("vadEnd" to 800)),
            ).also { engine = it }
        }

        @Synchronized
        fun reloadEngine(): SpeechRecognitionEngine {
            engine?.shutdown()
            engine = null
            SpeechRecognizeSdk.unloadModel()
            return sharedEngine()
        }
    }
}
