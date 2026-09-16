package com.amphion.dingqiao.demo

import android.content.Intent
import android.os.SystemClock
import android.widget.Button
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class DiarizationDemoInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()

    private fun activity(): MainActivity = instrumentation.startActivitySync(
        Intent(instrumentation.targetContext, MainActivity::class.java)
            .putExtra("demoFileInput", true).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
    ) as MainActivity

    @Test
    fun textFinalDoesNotFreezeRoleButWindowResultDoes() {
        val activity = activity()
        try {
            instrumentation.runOnMainSync {
                MainActivity::class.java.getDeclaredField("capturedScenario").apply { isAccessible = true }
                    .set(activity, CustomerScenario.MEETING_MINUTES)
                val listener = MainActivity::class.java.getDeclaredMethod("createListener")
                    .apply { isAccessible = true }.invoke(activity) as RecognitionListener
                val view = activity.findViewById<TextView>(R.id.tv_final)
                listener.onResult("s", SpeechRecognitionResult(isFinal = true, isLast = true,
                    result = "你好", utteranceId = "u", speakerIndex = 3))
                assertTrue(view.text.toString().contains("说话人 1（中间结果）"))
                listener.onResult("s", SpeechRecognitionResult(isFinal = true, result = "再见",
                    utteranceId = "u2", speakerIndex = 0, beginTime = 2000))
                assertTrue(view.text.toString().contains("说话人 1（中间结果）] 你好"))
                assertTrue(view.text.toString().contains("说话人 2（中间结果）] 再见"))
                listener.onSpeakerDiarizationResult("s", SpeakerDiarizationResult(
                    utterances = listOf(DiarizedUtterance(utteranceId = "u-final", sourceUtteranceId = "u",
                        text = "你好", speakerIndex = -1),
                        DiarizedUtterance(utteranceId = "u2-final", sourceUtteranceId = "u2",
                            text = "再见", speakerIndex = 0, beginTime = 2000)), windowIndex = 0))
                val frozen = view.text.toString()
                assertTrue(frozen.contains("未能区分说话人（最终结果）"))
                assertFalse(frozen.contains("中间结果"))
                listener.onSpeakerDiarizationUpdate("s", SpeakerDiarizationUpdate(utteranceId = "u-final", speakerIndex = 1))
                assertEquals(frozen, view.text.toString())
            }
        } finally {
            instrumentation.runOnMainSync { activity.finish() }
        }
    }

    /** Explicit device experiment: same PCM and 20ms clock; only vadEnd changes. */
    @Test
    fun compareMeetingPauseOnRealSdk() {
        val args = InstrumentationRegistry.getArguments()
        val vadEnd = args.getString("diarizationVadEndMs")?.toIntOrNull()
        assumeTrue("Pass diarizationVadEndMs=800/600/400 to run the audio experiment", vadEnd != null)
        require(vadEnd in listOf(800, 600, 400))
        val app = instrumentation.targetContext.applicationContext as DingqiaoApp
        val ready = CountDownLatch(1)
        var runtimeError = ""
        app.whenRuntimeReady { if (!it.isReady) runtimeError = it.errorMessage; ready.countDown() }
        assertTrue(ready.await(30, TimeUnit.SECONDS))
        assertEquals("", runtimeError)
        val pcm = WavIo.readDemoInput(File(app.workDir, "demo-test-input.wav"))
        val output = File(app.filesDir, "diarization-vad-$vadEnd-${System.currentTimeMillis()}.jsonl")
        val done = CountDownLatch(1)
        var feedStart = 0L
        var last = 0
        var completes = 0
        var errors = 0
        var windows = 0
        val finalResults = mutableListOf<SpeechRecognitionResult>()
        val windowTexts = mutableListOf<String>()
        val trace = mutableListOf<String>()
        fun record(kind: String, value: JSONObject = JSONObject()) = synchronized(trace) {
            trace.add(kind)
            output.appendText(value.put("kind", kind).put("atMs", SystemClock.elapsedRealtime())
                .put("feedStartedAtMs", feedStart).put("vadEndMs", vadEnd).toString() + "\n")
        }
        val engine = SpeechRecognizeSdk.createEngine(CreateEngineParams())
        val sid = "vad-$vadEnd"
        try {
            engine.setListener(object : RecognitionListener {
                override fun onStart(sessionId: String, eventMessage: String) { record("start") }
                override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) {
                    record("event", JSONObject().put("eventCode", eventCode))
                }
                override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
                    if (!result.isFinal) return
                    synchronized(trace) { if (result.isLast) last++; finalResults.add(result) }
                    record(if (result.isLast) "last" else "final", JSONObject()
                        .put("result", result.result).put("beginTime", result.beginTime).put("endTime", result.endTime)
                        .put("speakerIndex", result.speakerIndex).put("utteranceId", result.utteranceId))
                }
                override fun onSpeakerDiarizationResult(sessionId: String, result: SpeakerDiarizationResult) {
                    synchronized(trace) { windows++; windowTexts.add(result.utterances.joinToString("") { it.text }) }
                    val turns = JSONArray()
                    result.speakerTurns.forEach { turns.put(JSONObject().put("beginTime", it.beginTime)
                        .put("endTime", it.endTime).put("speakerIndex", it.speakerIndex)
                        .put("secondarySpeakerIndexes", JSONArray(it.secondarySpeakerIndexes)).put("overlap", it.overlap)) }
                    val utterances = JSONArray()
                    result.utterances.forEach { utterances.put(JSONObject().put("text", it.text).put("beginTime", it.beginTime)
                        .put("endTime", it.endTime).put("speakerIndex", it.speakerIndex)) }
                    record("window", JSONObject().put("speakerTurns", turns).put("utterances", utterances)
                        .put("windowIndex", result.windowIndex).put("isSessionFinal", result.isSessionFinal)
                        .put("degraded", result.degraded).put("inferenceMs", result.inferenceMs))
                }
                override fun onComplete(sessionId: String, eventMessage: String) {
                    synchronized(trace) { completes++ }; record("complete"); done.countDown()
                }
                override fun onError(sessionId: String, errorCode: Int, errorMessage: String) {
                    synchronized(trace) { errors++ }; record("error", JSONObject().put("message", errorMessage)); done.countDown()
                }
            })
            engine.startListening(StartParams(sid, extraParams = mapOf("vadEnd" to requireNotNull(vadEnd),
                "recognizerMode" to "long", "endpointMaxUtteranceMs" to 60_000,
                "maxAudioDuration" to 7_200_000, "enablePartialResult" to true,
                "enablePoliceEnhancement" to false, "enableContinuousRecognition" to false),
                speakerDiarization = SpeakerDiarizationConfig(maxSpeakers = 4)))
            feedStart = SystemClock.elapsedRealtime()
            for (offset in pcm.indices step 640) {
                engine.writeAudio(sid, pcm.copyOfRange(offset, offset + 640))
                val delay = feedStart + (offset + 640) / 32 - SystemClock.elapsedRealtime()
                if (delay > 0) Thread.sleep(delay)
            }
            synchronized(trace) { assertEquals("last before explicit finish", 0, last) }
            record("finish")
            engine.finish(sid)
            assertTrue("Completion timeout; evidence: $output", done.await(90, TimeUnit.SECONDS))
            synchronized(trace) {
                assertEquals(0, errors); assertEquals(1, last); assertEquals(1, completes)
                assertTrue(windows >= 1)
                assertTrue(trace.indexOf("last") < trace.indexOf("complete"))
                val nonEmpty = finalResults.filter { it.result.isNotEmpty() }
                assertTrue("token time must not restart at an endpoint", nonEmpty.zipWithNext().all { (a, b) ->
                    val begin = b.beginTime
                    val end = a.endTime
                    begin != null && end != null && begin >= end
                })
                assertEquals("role windows must preserve every final exactly once",
                    finalResults.joinToString("") { it.result }, windowTexts.joinToString(""))
            }
        } finally {
            if (engine.isBusy()) engine.cancel(sid)
            engine.shutdown()
        }
    }

    @Test
    fun fileInputShowsIntermediateThenFinalRoles() {
        assumeTrue(InstrumentationRegistry.getArguments().getString("demoFileRun") == "true")
        val activity = activity()
        var intermediate = false
        var final = false
        var clicked = false
        try {
            val deadline = SystemClock.elapsedRealtime() + 300_000
            while (SystemClock.elapsedRealtime() < deadline && !final) {
                instrumentation.runOnMainSync {
                    val button = activity.findViewById<Button>(R.id.btn_talk)
                    if (!clicked && button.isEnabled) { button.performClick(); clicked = true }
                    val text = activity.findViewById<TextView>(R.id.tv_final).text.toString()
                    intermediate = intermediate || text.contains("（中间结果）")
                    final = text.contains("（最终结果）") && !text.contains("（中间结果）") &&
                        MainActivity::class.java.getDeclaredField("liveHasCompleted").apply { isAccessible = true }.getBoolean(activity)
                }
                Thread.sleep(100)
            }
            assertTrue("file path must render provisional roles", intermediate)
            assertTrue("window callback must finalize visible roles", final)
        } finally {
            instrumentation.runOnMainSync { activity.finish() }
        }
    }
}
