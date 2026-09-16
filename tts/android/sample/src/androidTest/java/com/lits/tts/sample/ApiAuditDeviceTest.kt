package com.lits.tts.sample

import android.content.Context
import android.media.AudioManager
import android.os.Looper
import androidx.test.core.app.ApplicationProvider
import com.lits.tts.sdk.*
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

/** Audits public APIs with the installed, licensed model; records PCM and callbacks. */
class ApiAuditDeviceTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val engines = mutableListOf<TextToSpeechEngine>()
    private val records = CopyOnWriteArrayList<Record>()
    private val output = File(context.filesDir, "api-audit").apply { mkdirs() }
    private val phrase = "你好，欢迎使用语音合成。今天阳光明媚，我们一起出发。"

    @Before fun prepare() {
        TextToSpeechSdk.setWorkPath(File(context.filesDir, "lits-tts-work").absolutePath)
        TextToSpeechSdk.init(context, TtsLicenseOptions(
            license = File(context.filesDir, "tts-provisioning/amphion-license.lic").readText(),
            licenseAssetName = null,
            deviceIdProvider = TtsDeviceIdProvider { File(context.filesDir, "tts-provisioning/device-sn.txt").readText().trim() },
        ))
        assertTrue(TextToSpeechSdk.licenseStatus().valid)
    }

    @After fun finish() {
        engines.forEach { runCatching { it.shutdown() } }
        for (r in records) {
            File(output, "${r.artifactName}.pcm").writeBytes(r.pcm.toByteArray())
            File(output, "${r.artifactName}.json").writeText(JSONObject()
                .put("id", r.id).put("events", JSONArray(r.events)).put("error", r.error)
                .put("pcmBytes", r.pcm.size()).put("chunkCount", r.sequence)
                .put("sampleRate", r.start?.sampleRate).put("isStreaming", r.start?.isStreaming)
                .put("dataPath", r.start?.dataPath).put("pcmQueueCapacity", r.start?.pcmQueueCapacity)
                .put("audioDurationMs", r.complete?.audioDurationMs)
                .put("synthesisMs", r.complete?.synthesisMs).put("firstPacketMs", r.complete?.firstPacketMs)
                .toString(2))
        }
    }

    @Test fun discoveryCreationAndValidation() {
        val voices = TextToSpeechSdk.listVoices(VoiceQuery("sync-list", RunMode.OFFLINE))
        assertEquals(2, voices.size)
        assertEquals(setOf("lits-female-02"), voices.map { it.voiceId }.toSet())
        val listed = CountDownLatch(1)
        var asyncVoices: List<VoiceInfo>? = null
        var mainThread = false
        TextToSpeechSdk.listVoices(VoiceQuery("async-list", RunMode.OFFLINE, "en-US"), object : Callback<List<VoiceInfo>> {
            override fun onSuccess(result: List<VoiceInfo>) { asyncVoices = result; mainThread = Looper.myLooper() == Looper.getMainLooper(); listed.countDown() }
            override fun onError(errorCode: Int, errorMessage: String) { listed.countDown() }
        })
        assertTrue(listed.await(10, TimeUnit.SECONDS)); assertTrue(mainThread)
        assertEquals(listOf("lits-female-02"), asyncVoices?.map { it.voiceId })
        val created = CountDownLatch(1)
        var engine: TextToSpeechEngine? = null
        TextToSpeechSdk.createEngine(CreateEngineParams("en-US", RunMode.OFFLINE, "lits-female-02"), object : Callback<TextToSpeechEngine> {
            override fun onSuccess(result: TextToSpeechEngine) { engine = result; created.countDown() }
            override fun onError(errorCode: Int, errorMessage: String) { created.countDown() }
        })
        assertTrue(created.await(30, TimeUnit.SECONDS)); assertNotNull(engine)
        engines += engine!!
        assertFalse(engine!!.isBusy())
        assertEquals(TtsErrorCode.INTERNAL_SERVICE_ERROR, assertThrows(TextToSpeechException::class.java) {
            TextToSpeechSdk.setWorkPath(File(context.filesDir, "other-work").absolutePath)
        }.errorCode)
        val recorder = Recorder(); engine!!.setListener(recorder)
        for ((id, text, params, code) in listOf(
            Invalid("empty", " ", SpeakParams("empty"), TtsErrorCode.TEXT_LENGTH_INVALID),
            Invalid("format", "Hello.", SpeakParams("format", audioType = "wav"), TtsErrorCode.RUNTIME_EXCEPTION),
            Invalid("volume-invalid", "Hello.", SpeakParams("volume-invalid", volume = -1f), TtsErrorCode.RUNTIME_EXCEPTION),
        )) {
            val r = recorder.add(id); engine!!.speak(text, params); r.await(); assertEquals(code, r.errorCode)
            assertEquals(listOf("error"), r.events.toList())
        }
        val good = recorder.add("english-recovery")
        engine!!.speak("Hello. The meeting will begin at nine o'clock.", only(good.id).copy(languageContext = "en-US"))
        good.await(); good.assertSynthesis()
        val duplicate = recorder.add(good.id)
        engine!!.speak("Hello.", only(good.id)); duplicate.await()
        assertEquals(TtsErrorCode.RUNTIME_EXCEPTION, duplicate.errorCode)
        val alive = engine!!; alive.shutdown(); engines.remove(alive)
        assertEquals(TtsErrorCode.ENGINE_DESTROYED, assertThrows(TextToSpeechException::class.java) { alive.isBusy() }.errorCode)
        val destroyed = recorder.add("destroyed")
        alive.speak("Hello.", only(destroyed.id)); destroyed.await()
        assertEquals(TtsErrorCode.ENGINE_DESTROYED, destroyed.errorCode)
    }

    @Test fun synthesisParametersAffectRealPcm() {
        val engine = engine(); val recorder = Recorder(); engine.setListener(recorder)
        val outputs = mutableMapOf<String, Record>()
        for (params in listOf(only("baseline"), only("slow").copy(speed = .8f), only("fast").copy(speed = 1.2f),
            only("half-volume").copy(volume = .5f), only("mute").copy(volume = 0f), only("pitch-up").copy(pitch = 1.2f))) {
            val r = recorder.add(params.requestId); outputs[r.id] = r
            engine.speak(phrase, params); r.await(); r.assertSynthesis()
        }
        val base = outputs.getValue("baseline")
        assertTrue(outputs.getValue("slow").pcm.size() > base.pcm.size())
        assertTrue(outputs.getValue("fast").pcm.size() < base.pcm.size())
        val reference = base.pcm.toByteArray(); val half = outputs.getValue("half-volume").pcm.toByteArray()
        assertEquals(reference.size, half.size)
        for (i in reference.indices step 2) {
            val x = ((reference[i].toInt() and 255) or (reference[i+1].toInt() shl 8)).toShort().toInt()
            val y = ((half[i].toInt() and 255) or (half[i+1].toInt() shl 8)).toShort().toInt()
            assertTrue("volume scaling at $i", kotlin.math.abs(y - x * .5) <= 1.0)
        }
        assertTrue(outputs.getValue("mute").pcm.toByteArray().all { it == 0.toByte() })
        // Pitch is recorded for spectral/listening analysis; a changed byte array
        // alone is deliberately not treated as proof that pitch shifted correctly.
    }

    @Test fun queuePreemptStopAndRecovery() {
        val engine = engine(); val recorder = Recorder(); engine.setListener(recorder)
        val a = recorder.add("queue-a"); val b = recorder.add("queue-b")
        engine.speak(phrase, only(a.id)); engine.speak("第二条排队请求。", only(b.id))
        assertTrue(engine.isBusy()); a.await(); b.await(); a.assertSynthesis(); b.assertSynthesis()
        assertTrue(recorder.timeline.indexOf("queue-a:complete:SYNTHESIS_COMPLETE") < recorder.timeline.indexOf("queue-b:start"))
        val old = recorder.add("preempt-old"); val next = recorder.add("preempt-new")
        val preempted = AtomicBoolean(false)
        recorder.afterData = { id -> if (id == old.id && preempted.compareAndSet(false, true)) {
            engine.speak("新的请求。", only(next.id).copy(queueMode = QueueMode.PREEMPT))
        } }
        engine.speak(phrase.repeat(5), only(old.id)); old.await(); next.await(); next.assertSynthesis()
        assertEquals(1, old.events.count { it == "stop" }); assertFalse(old.events.any { it.startsWith("complete") || it == "error" })
        val stopA = recorder.add("stop-active"); val stopB = recorder.add("stop-queued")
        val stopped = AtomicBoolean(false)
        recorder.afterData = { id -> if (id == stopA.id && stopped.compareAndSet(false, true)) {
            engine.speak("等待中的请求。", only(stopB.id)); engine.stop()
        } }
        engine.speak(phrase.repeat(5), only(stopA.id)); stopA.await(); stopB.await()
        recorder.afterData = null
        val recovery = recorder.add("stop-recovery"); engine.speak("停止之后恢复正常。", only(recovery.id)); recovery.await(); recovery.assertSynthesis()
        for (r in listOf(stopA, stopB)) {
            assertEquals(1, r.events.count { it == "stop" }); assertFalse(r.events.any { it.startsWith("complete") || it == "error" })
        }
    }

    @Test fun internalPlaybackWithSmallAndLargePcmQueues() {
        val engine = engine(); val recorder = Recorder(); engine.setListener(recorder)
        for (capacity in listOf(1, 32)) {
            val r = recorder.add("play-queue-$capacity", playback = true)
            engine.speak("播放测试。Hello, welcome.", SpeakParams(r.id, soundChannel = AudioManager.STREAM_MUSIC,
                streamingConfig = TtsStreamingConfig(pcmQueueCapacity = capacity)))
            r.await(); assertNull(r.error); assertEquals(0, r.pcm.size())
            assertEquals(capacity, r.start?.pcmQueueCapacity)
            assertEquals(listOf("start", "playback-start", "complete:SYNTHESIS_COMPLETE", "complete:PLAYBACK_COMPLETE"), r.events.toList())
        }
    }

    private fun engine() = TextToSpeechSdk.createEngine(CreateEngineParams("zh-en", RunMode.OFFLINE, "lits-female-02")).also { engines += it }
    private fun only(id: String) = SpeakParams(id, playType = PlayType.SYNTHESIZE_ONLY)
    private data class Invalid(val id: String, val text: String, val params: SpeakParams, val code: Int)
    private inner class Recorder : SpeakListener {
        val requests = ConcurrentHashMap<String, Record>()
        val timeline = CopyOnWriteArrayList<String>()
        var afterData: ((String) -> Unit)? = null
        fun add(id: String, playback: Boolean = false): Record {
            val occurrence = records.count { it.id == id }
            val artifactName = if (occurrence == 0) id else "$id-repeat-$occurrence"
            return Record(id, playback, artifactName).also { requests[id] = it; records += it }
        }
        private fun event(id: String, value: String) { requests.getValue(id).events += value; timeline += "$id:$value" }
        override fun onStart(requestId: String, response: StartResponse) { requests.getValue(requestId).start = response; event(requestId, "start") }
        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {
            val r = requests.getValue(requestId)
            if (response.sequence != r.sequence || !response.isStreaming) r.error = "invalid chunk sequence/streaming flag"
            r.sequence++; r.pcm.write(audio); event(requestId, "data"); afterData?.invoke(requestId)
        }
        override fun onPlaybackStart(requestId: String, elapsedMs: Long) { event(requestId, "playback-start") }
        override fun onComplete(requestId: String, response: CompleteResponse) {
            val r = requests.getValue(requestId); event(requestId, "complete:${response.type}")
            if (response.type == CompleteType.SYNTHESIS_COMPLETE) r.complete = response
            if (!r.playback || response.type == CompleteType.PLAYBACK_COMPLETE) r.done.countDown()
        }
        override fun onStop(requestId: String, response: StopResponse) { event(requestId, "stop"); requests.getValue(requestId).done.countDown() }
        override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
            val r = requests.getValue(requestId); r.error = errorMessage; r.errorCode = errorCode; event(requestId, "error"); r.done.countDown()
        }
    }
    private class Record(val id: String, val playback: Boolean, val artifactName: String) {
        val events = CopyOnWriteArrayList<String>(); val pcm = ByteArrayOutputStream(); val done = CountDownLatch(1)
        var start: StartResponse? = null; var complete: CompleteResponse? = null; var error: String? = null; var errorCode: Int? = null; var sequence = 0
        fun await() { assertTrue("$id timeout: $events", done.await(60, TimeUnit.SECONDS)) }
        fun assertSynthesis() {
            assertNull("$id: $events", error); assertEquals("start", events.first())
            assertEquals(1, events.count { it == "complete:SYNTHESIS_COMPLETE" }); assertFalse(events.contains("stop"))
            assertEquals("complete:SYNTHESIS_COMPLETE", events.last()); assertTrue(pcm.size() > 0)
            assertEquals(24000, start?.sampleRate); assertEquals(16, start?.sampleBit); assertEquals(1, start?.audioChannel)
        }
    }
}
