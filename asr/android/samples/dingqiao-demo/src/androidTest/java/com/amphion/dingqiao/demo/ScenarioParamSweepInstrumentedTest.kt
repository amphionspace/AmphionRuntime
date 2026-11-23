package com.amphion.dingqiao.demo

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.AudioInfo
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.DingqiaoOnlineMode
import com.amphion.dingqiao.RecognitionListener
import com.amphion.dingqiao.SpeakerDiarizationConfig
import com.amphion.dingqiao.SpeakerDiarizationResult
import com.amphion.dingqiao.SpeakerDiarizationUpdate
import com.amphion.dingqiao.SpeechRecognitionEngine
import com.amphion.dingqiao.SpeechRecognitionResult
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.StartParams
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assume.assumeTrue
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * 《语音识别场景划分方案》真机参数交叉验证载体。两个入口：
 *
 * 1. [recordFromMicrophone]：按指定 Android AudioSource 用 AudioRecord 录 16 kHz 单声道 N 毫秒，写成 WAV。
 *    Mac 外放同一份拼接语料，分别用 MIC / VOICE_RECOGNITION / VOICE_COMMUNICATION / UNPROCESSED 录回，
 *    这样采集链前处理（NS/AGC/AEC）的影响可以和识别参数分开看。
 *    `-e sweepAudioSource VOICE_RECOGNITION -e sweepRecordMs 370000 -e sweepRecordOut src-vr.wav`
 *
 * 2. [replayWavList]：把一组 WAV（应用私有目录下的绝对路径清单）按 20 ms 实时节奏喂给 SDK，
 *    会话参数全部可从 instrumentation 参数覆盖，逐条落 JSONL（finals/partials/角色更新/耗时）。
 *    `-e sweepList /data/user/0/<pkg>/files/param-sweep/list.txt -e sweepVadEnd 1200
 *     -e sweepRecognizerMode short -e sweepHotwordsFile <path> -e sweepMaxSpeakers 2
 *     -e sweepIdentityMode voiceprint -e sweepDiarization true -e sweepTag vad1200`
 *
 * 结果在 `getExternalFilesDir/param-sweep/out/<tag>.jsonl`（正式签名包不可 run-as，用 adb pull 拉取）。
 */
@RunWith(AndroidJUnit4::class)
class ScenarioParamSweepInstrumentedTest {
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private val targetContext: Context get() = instrumentation.targetContext

    private fun outDir(): File = File(targetContext.getExternalFilesDir(null), "param-sweep/out").apply { mkdirs() }

    private fun keepAlive() {
        targetContext.startActivity(
            Intent(targetContext, DeviceTestKeepAliveActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
        SystemClock.sleep(500)
    }

    // ---------------------------------------------------------------- 1. 采集源录音

    @SuppressLint("MissingPermission")
    @Test
    fun recordFromMicrophone() {
        val args = InstrumentationRegistry.getArguments()
        val sourceName = args.getString("sweepAudioSource")
        assumeTrue("Pass -e sweepAudioSource <MIC|VOICE_RECOGNITION|VOICE_COMMUNICATION|UNPROCESSED|CAMCORDER>", sourceName != null)
        val durationMs = args.getString("sweepRecordMs")?.toLongOrNull() ?: 60_000L
        val outName = args.getString("sweepRecordOut") ?: "record-${sourceName!!.lowercase()}.wav"
        val source = when (sourceName!!.uppercase()) {
            "MIC" -> MediaRecorder.AudioSource.MIC
            "VOICE_RECOGNITION" -> MediaRecorder.AudioSource.VOICE_RECOGNITION
            "VOICE_COMMUNICATION" -> MediaRecorder.AudioSource.VOICE_COMMUNICATION
            "UNPROCESSED" -> MediaRecorder.AudioSource.UNPROCESSED
            "CAMCORDER" -> MediaRecorder.AudioSource.CAMCORDER
            "VOICE_PERFORMANCE" -> MediaRecorder.AudioSource.VOICE_PERFORMANCE
            else -> error("unknown AudioSource $sourceName")
        }
        keepAlive()
        val sampleRate = 16_000
        val minBuf = AudioRecord.getMinBufferSize(sampleRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val record = AudioRecord(source, sampleRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(minBuf * 4, sampleRate * 2))
        assertTrue("AudioRecord init failed for $sourceName", record.state == AudioRecord.STATE_INITIALIZED)
        val out = File(outDir(), outName)
        val raf = RandomAccessFile(out, "rw")
        raf.setLength(0)
        raf.write(ByteArray(44))
        val buf = ByteArray(sampleRate / 10 * 2)
        var total = 0L
        var overruns = 0
        val startedAt = SystemClock.elapsedRealtime()
        record.startRecording()
        assertTrue("AudioRecord not recording for $sourceName", record.recordingState == AudioRecord.RECORDSTATE_RECORDING)
        try {
            while (SystemClock.elapsedRealtime() - startedAt < durationMs) {
                val n = record.read(buf, 0, buf.size)
                if (n < 0) { overruns += 1; continue }
                raf.write(buf, 0, n)
                total += n
            }
        } finally {
            record.stop()
            record.release()
        }
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
        header.put("RIFF".toByteArray()).putInt((36 + total).toInt()).put("WAVE".toByteArray())
        header.put("fmt ".toByteArray()).putInt(16).putShort(1).putShort(1).putInt(sampleRate).putInt(sampleRate * 2).putShort(2).putShort(16)
        header.put("data".toByteArray()).putInt(total.toInt())
        raf.seek(0); raf.write(header.array()); raf.close()
        val meta = JSONObject()
            .put("type", "record").put("audioSource", sourceName).put("audioSourceId", source)
            .put("durationMs", durationMs).put("bytes", total).put("readErrors", overruns)
            .put("audioSessionId", record.audioSessionId)
            .put("model", Build.MODEL).put("android", Build.VERSION.RELEASE).put("file", out.absolutePath)
        File(outDir(), "$outName.json").writeText(meta.toString(2))
        assertTrue("recorded too little audio: $total bytes", total > sampleRate * 2 * (durationMs / 1000) / 2)
    }

    // ---------------------------------------------------------------- 2. 参数回放

    private class SweepListener : RecognitionListener {
        val started = CountDownLatch(1)
        val complete = CountDownLatch(1)
        val finals: MutableList<JSONObject> = Collections.synchronizedList(mutableListOf())
        val partials: MutableList<JSONObject> = Collections.synchronizedList(mutableListOf())
        val updates: MutableList<JSONObject> = Collections.synchronizedList(mutableListOf())
        val events: MutableList<JSONObject> = Collections.synchronizedList(mutableListOf())
        val errors: MutableList<JSONObject> = Collections.synchronizedList(mutableListOf())
        @Volatile var firstPartialAt = -1L
        @Volatile var firstFinalAt = -1L
        @Volatile var speakerCount = 0
        val t0 = SystemClock.elapsedRealtime()
        private fun now() = SystemClock.elapsedRealtime() - t0

        override fun onStart(sessionId: String, eventMessage: String) { started.countDown() }
        override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) {
            events += JSONObject().put("t", now()).put("code", eventCode).put("msg", eventMessage)
        }
        override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
            val o = JSONObject().put("t", now()).put("text", result.result).put("isFinal", result.isFinal).put("isLast", result.isLast)
                .put("beginTime", result.beginTime ?: JSONObject.NULL).put("endTime", result.endTime ?: JSONObject.NULL)
                .put("speakerIndex", result.speakerIndex).put("secondary", JSONArray(result.secondarySpeakerIndexes))
                .put("speakerConfidence", result.speakerConfidence.toDouble()).put("utteranceId", result.utteranceId ?: JSONObject.NULL)
            if (result.isFinal) { if (firstFinalAt < 0) firstFinalAt = now(); finals += o } else { if (firstPartialAt < 0) firstPartialAt = now(); partials += o }
        }
        override fun onSpeakerDiarizationUpdate(sessionId: String, update: SpeakerDiarizationUpdate) {
            updates += JSONObject().put("t", now()).put("utteranceId", update.utteranceId).put("revision", update.revision)
                .put("speakerIndex", update.speakerIndex).put("secondary", JSONArray(update.secondarySpeakerIndexes))
                .put("beginTime", update.beginTime).put("endTime", update.endTime).put("confidence", update.confidence.toDouble())
        }
        /** 与鸿蒙载体同口径：累计每个窗口的 speakerTurns（公开 speakerIndex 时间轴），用于 DER。 */
        val turns: MutableList<JSONObject> = Collections.synchronizedList(mutableListOf())
        val windows: MutableList<JSONObject> = Collections.synchronizedList(mutableListOf())
        override fun onSpeakerDiarizationResult(sessionId: String, result: SpeakerDiarizationResult) {
            speakerCount = result.speakerCount
            result.speakerTurns.forEach { t ->
                turns += JSONObject().put("beginTime", t.beginTime).put("endTime", t.endTime).put("speakerIndex", t.speakerIndex)
                    .put("modelSpeakerIndex", t.modelSpeakerIndex).put("secondary", JSONArray(t.secondarySpeakerIndexes)).put("overlap", t.overlap)
            }
            windows += JSONObject().put("t", now()).put("windowIndex", result.windowIndex).put("windowBeginTime", result.windowBeginTime)
                .put("speakerCount", result.speakerCount).put("degraded", result.degraded).put("utterances", result.utterances.size)
                .put("turns", result.speakerTurns.size).put("inferenceMs", result.inferenceMs).put("rtf", result.rtf.toDouble())
        }
        override fun onComplete(sessionId: String, eventMessage: String) { complete.countDown() }
        override fun onError(sessionId: String, errorCode: Int, errorMessage: String) {
            errors += JSONObject().put("t", now()).put("code", errorCode).put("msg", errorMessage); complete.countDown()
        }
    }

    @Test
    fun replayWavList() {
        val args = InstrumentationRegistry.getArguments()
        val listPath = args.getString("sweepList")
        assumeTrue("Pass -e sweepList <file with one wav path per line>", listPath != null)
        val wavs = File(listPath!!).readLines().map { it.trim() }.filter { it.isNotEmpty() }
        assumeTrue("sweepList is empty", wavs.isNotEmpty())
        val tag = args.getString("sweepTag") ?: "sweep"
        val vadEnd = args.getString("sweepVadEnd")?.toIntOrNull()
        val vadBegin = args.getString("sweepVadBegin")?.toIntOrNull()
        val recognizerMode = args.getString("sweepRecognizerMode")?.takeIf { it.isNotBlank() }
        val endpointMax = args.getString("sweepEndpointMaxUtteranceMs")?.toIntOrNull()
        val policeEnhancement = args.getString("sweepPoliceEnhancement")?.toBooleanStrictOrNull()
        val diarization = args.getString("sweepDiarization")?.toBooleanStrictOrNull() ?: false
        val maxSpeakers = args.getString("sweepMaxSpeakers")?.toIntOrNull() ?: 4
        val identityMode = args.getString("sweepIdentityMode")?.takeIf { it.isNotBlank() }
        val frameSleepMs = args.getString("sweepFrameSleepMs")?.toLongOrNull() ?: 20L
        val tailSilenceMs = args.getString("sweepTailSilenceMs")?.toIntOrNull() ?: 800
        val hotwords = args.getString("sweepHotwordsFile")?.let { File(it).readLines().map(String::trim).filter(String::isNotEmpty) } ?: emptyList()
        val completeTimeoutS = args.getString("sweepCompleteTimeoutS")?.toLongOrNull() ?: 120L

        keepAlive()
        prepareSdkRuntime(targetContext, File(targetContext.getExternalFilesDir(null), "customer_bug_work"))
        val out = File(outDir(), "$tag.jsonl").apply { writeText("") }
        fun append(o: JSONObject) = out.appendText(o.toString() + "\n")

        val extra = mutableMapOf<String, Any>("disablePrepack" to true)
        if (hotwords.isNotEmpty()) extra["sysGeneralLexicon"] = hotwords
        val engine = SpeechRecognizeSdk.createEngine(CreateEngineParams("zh-CN", DingqiaoOnlineMode.OFFLINE, extra))
        val startExtra = mutableMapOf<String, Any>("enablePartialResult" to true)
        vadEnd?.let { startExtra["vadEnd"] = it }
        vadBegin?.let { startExtra["vadBegin"] = it }
        recognizerMode?.let { startExtra["recognizerMode"] = it }
        endpointMax?.let { startExtra["endpointMaxUtteranceMs"] = it }
        policeEnhancement?.let { startExtra["enablePoliceEnhancement"] = it }
        val diarizationConfig = if (!diarization) null
            else if (identityMode == null) SpeakerDiarizationConfig(maxSpeakers = maxSpeakers)
            else SpeakerDiarizationConfig(maxSpeakers = maxSpeakers, speakerIdentityMode = identityMode)
        append(JSONObject().put("type", "config").put("tag", tag).put("model", Build.MODEL).put("android", Build.VERSION.RELEASE)
            .put("startExtra", JSONObject(startExtra as Map<*, *>)).put("hotwords", hotwords.size)
            .put("diarization", diarization).put("maxSpeakers", maxSpeakers).put("identityMode", identityMode ?: "default")
            .put("frameSleepMs", frameSleepMs).put("tailSilenceMs", tailSilenceMs).put("files", wavs.size))
        try {
            wavs.forEachIndexed { index, path ->
                awaitIdle(engine, 60_000)
                val bytes = File(path).readBytes()
                val pcm = DqWav.read16kMonoPcm(path, bytes)
                val listener = SweepListener()
                engine.setListener(listener)
                val sessionId = "sweep-$tag-$index"
                val wall0 = SystemClock.elapsedRealtime()
                engine.startListening(StartParams(sessionId, AudioInfo(), startExtra, diarizationConfig))
                val started = listener.started.await(30, TimeUnit.SECONDS)
                var completed = false
                if (started) {
                    feedFrames(engine, sessionId, pcm, frameSleepMs)
                    feedSilence(engine, sessionId, tailSilenceMs)
                    val fedAt = SystemClock.elapsedRealtime() - wall0
                    engine.finish(sessionId)
                    completed = listener.complete.await(completeTimeoutS, TimeUnit.SECONDS)
                    if (!completed) runCatching { engine.cancel(sessionId) }
                    awaitIdle(engine, 60_000)
                    append(JSONObject().put("type", "file").put("index", index).put("path", path).put("audioMs", pcm.size / 32)
                        .put("started", true).put("completed", completed).put("wallMs", SystemClock.elapsedRealtime() - wall0).put("fedMs", fedAt)
                        .put("firstPartialMs", listener.firstPartialAt).put("firstFinalMs", listener.firstFinalAt)
                        .put("finals", JSONArray(listener.finals)).put("partialCount", listener.partials.size)
                        .put("lastPartial", listener.partials.lastOrNull()?.optString("text") ?: "")
                        .put("diarizationUpdates", JSONArray(listener.updates)).put("diarizationTurns", JSONArray(listener.turns)).put("diarizationWindows", JSONArray(listener.windows))
                        .put("speakerCount", listener.speakerCount).put("events", JSONArray(listener.events)).put("errors", JSONArray(listener.errors)))
                } else {
                    runCatching { engine.cancel(sessionId) }
                    append(JSONObject().put("type", "file").put("index", index).put("path", path).put("started", false).put("errors", JSONArray(listener.errors)))
                }
            }
        } finally {
            engine.shutdown()
        }
        append(JSONObject().put("type", "done").put("files", wavs.size))
    }
}
