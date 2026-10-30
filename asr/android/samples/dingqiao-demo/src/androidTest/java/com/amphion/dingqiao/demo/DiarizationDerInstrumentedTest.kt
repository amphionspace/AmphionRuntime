package com.amphion.dingqiao.demo

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.AudioInfo
import com.amphion.dingqiao.RecognitionListener
import com.amphion.dingqiao.SpeakerDiarizationConfig
import com.amphion.dingqiao.SpeakerDiarizationResult
import com.amphion.dingqiao.SpeakerDiarizationUpdate
import com.amphion.dingqiao.SpeechRecognitionResult
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.StartParams
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * 把一条会议录音按实时速率喂给产品链路，把回传的 `speakerTurns` 落成 JSON，供主机用
 * openbench-der-v1 评分。与鸿蒙 `diarization-windows` 那轮取的是同一口径：评的是设备回传的
 * 公开结果，不是内部中间量。
 *
 * 用 `-e derAsset <测试包内资产路径>` 指定录音，音频经 `-PdingqiaoEvalAudioDir` 外挂进测试包。
 */
@RunWith(AndroidJUnit4::class)
class DiarizationDerInstrumentedTest {
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private val targetContext: Context get() = instrumentation.targetContext
    private val testContext: Context get() = instrumentation.context

    @Test
    fun speakerTurnsForOneMeetingRecording() {
        val args = InstrumentationRegistry.getArguments()
        val asset = args.getString("derAsset")
        assumeTrue("Pass -e derAsset <asset path> to score one recording", asset != null)
        val paceMs = args.getString("derFrameSleepMs")?.toLongOrNull() ?: 20L
        val maxSpeakers = args.getString("derMaxSpeakers")?.toIntOrNull() ?: 4

        // Android 16 会冻结后台进程：没有前台 Activity 时整个会话一动不动（实测 37 分钟只用掉
        // 4.9 秒 CPU）。与其他真机用例一致，先拉起保活 Activity 并保持屏幕常亮。
        targetContext.startActivity(
            android.content.Intent(targetContext, DeviceTestKeepAliveActivity::class.java)
                .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK),
        )
        android.os.SystemClock.sleep(1_000)

        val app = targetContext.applicationContext as DingqiaoApp
        val ready = CountDownLatch(1)
        var runtimeError = ""
        app.whenRuntimeReady { if (!it.isReady) runtimeError = it.errorMessage; ready.countDown() }
        assertTrue("runtime ready", ready.await(60, TimeUnit.SECONDS))
        assertEquals("", runtimeError)

        val pcm = DqWav.read16kMonoPcm(asset!!, testContext.assets.open(asset).use { it.readBytes() })
        val output = File(targetContext.filesDir, "diarization-der/${File(asset).name}.json")
        output.parentFile?.mkdirs()

        val finished = CountDownLatch(1)
        val windows = JSONArray()
        var finalResult: SpeakerDiarizationResult? = null
        var degradedReason = ""
        var degradedMessage = ""
        var errors = 0
        var windowTurnCount = 0
        var coveredMs = 0L
        var lastInferenceMs = 0L
        var lastRtf = 0f
        val engine = SpeechRecognizeSdk.createEngine(com.amphion.dingqiao.CreateEngineParams())
        val sessionId = "der"
        try {
            val params = StartParams(
                sessionId = sessionId,
                audioInfo = AudioInfo(),
                extraParams = mapOf(
                    "recognizerMode" to "long",
                    "enablePartialResult" to true,
                    "maxAudioDuration" to 7_200_000,
                ),
                speakerDiarization = SpeakerDiarizationConfig(maxSpeakers = maxSpeakers),
            )
            engine.setListener(object : RecognitionListener {
                override fun onStart(sessionId: String, eventMessage: String) = Unit
                override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) = Unit
                override fun onResult(sessionId: String, result: SpeechRecognitionResult) = Unit
                override fun onSpeakerDiarizationUpdate(sessionId: String, update: SpeakerDiarizationUpdate) = Unit

                override fun onSpeakerDiarizationResult(sessionId: String, result: SpeakerDiarizationResult) {
                    windows.put(encode(result))
                    windowTurnCount += result.speakerTurns.size
                    coveredMs += result.speakerTurns.sumOf { (it.endTime - it.beginTime).toLong() }
                    lastInferenceMs = result.inferenceMs
                    lastRtf = result.rtf
                    if (result.isSessionFinal) {
                        finalResult = result
                        if (result.degradedReason.name != "NONE") degradedReason = result.degradedReason.name
                    }
                }

                override fun onComplete(sessionId: String, eventMessage: String) {
                    finished.countDown()
                }

                override fun onError(sessionId: String, errorCode: Int, errorMessage: String) {
                    errors += 1
                    finished.countDown()
                }
            })
            engine.startListening(params)
            var offset = 0
            while (offset < pcm.size) {
                val size = minOf(DQ_FRAME, pcm.size - offset)
                val frame = ByteArray(DQ_FRAME)
                System.arraycopy(pcm, offset, frame, 0, size)
                engine.writeAudio(sessionId, frame)
                offset += size
                if (paceMs > 0) Thread.sleep(paceMs)
            }
            engine.finish(sessionId)
            assertTrue("session completed", finished.await(900, TimeUnit.SECONDS))
        } finally {
            engine.shutdown()
        }

        val root = JSONObject()
            .put("asset", asset)
            .put("maxSpeakers", maxSpeakers)
            .put("frameSleepMs", paceMs)
            .put("audioMs", pcm.size / 32)
            .put("errors", errors)
            .put("degradedReason", degradedReason)
            .put("degradedMessage", degradedMessage)
            .put("turnsAcrossWindows", windowTurnCount)
            .put("turnCoveredMs", coveredMs)
            .put("inferenceMs", lastInferenceMs)
            .put("rtf", lastRtf.toDouble())
            .put("windows", windows)
            .put("final", finalResult?.let { encode(it) } ?: JSONObject())
        output.writeText(root.toString(), Charsets.UTF_8)

        assertEquals("no recognizer error", 0, errors)
        assertEquals("not degraded: $degradedMessage", "", degradedReason)
        assertTrue("a session-final diarization result arrived", finalResult != null)
        // 会话按窗口增量发布，每个窗口只覆盖自己那一段：整场时间线是全部窗口的并集，
        // 只看最后一个结果会把除末窗以外的内容全漏掉。
        val allTurns = windowTurnCount
        assertTrue("the session published speaker turns across its windows", allTurns > 0)
    }

    private fun encode(result: SpeakerDiarizationResult): JSONObject {
        val turns = JSONArray()
        result.speakerTurns.forEach {
            turns.put(
                JSONObject()
                    .put("beginTime", it.beginTime)
                    .put("endTime", it.endTime)
                    .put("speakerIndex", it.speakerIndex)
                    .put("secondarySpeakerIndexes", JSONArray(it.secondarySpeakerIndexes))
                    .put("overlap", it.overlap),
            )
        }
        return JSONObject()
            .put("windowIndex", result.windowIndex)
            .put("windowBeginTime", result.windowBeginTime)
            .put("windowEndTime", result.windowEndTime)
            .put("speakerCount", result.speakerCount)
            .put("isSessionFinal", result.isSessionFinal)
            .put("utterances", result.utterances.size)
            .put("speakerTurns", turns)
    }
}
