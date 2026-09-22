package com.amphion.dingqiao.demo

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.asr.AmphionLogLevel
import com.amphion.dingqiao.*
import com.k2fsa.sherpa.onnx.SileroVadModelConfig
import com.k2fsa.sherpa.onnx.Vad
import com.k2fsa.sherpa.onnx.VadModelConfig
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Temporary diagnostic: retained in the evidence archive, not a release gate. */
@RunWith(AndroidJUnit4::class)
class Pr218VadOnsetDiagnosticTest {
    @Test
    fun samePcmAcrossInitialDeadline() {
        val ctx = InstrumentationRegistry.getInstrumentation().targetContext
        val testCtx = InstrumentationRegistry.getInstrumentation().context
        val pcm = readAssetPcm(testCtx, "01_target.wav")
        SpeechRecognizeSdk.setLogLevel(AmphionLogLevel.DEBUG)
        prepareSdkRuntime(ctx, File(ctx.getExternalFilesDir(null), "dq_vp_work"))
        val sample = stageAsset(testCtx, ctx, "01_声纹.wav", "vp_samples/onset_enroll.wav")
        val id = SpeechRecognizeSdk.registerVoiceprint(
            VoiceprintRegisterParams(listOf(sample), AudioInfo()),
        ).voiceprintId.keys.single()
        val engine = SpeechRecognizeSdk.createEngine(CreateEngineParams(
            language = "zh-CN", online = DingqiaoOnlineMode.OFFLINE,
            extraParams = mapOf("vadEnd" to 800),
        ))
        try {
            for (prefixMs in listOf(300, 0)) {
                val input = ByteArray(prefixMs * 32) + pcm
                val samples = ByteBuffer.wrap(input).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
                val floats = FloatArray(samples.remaining()) { samples.get() / 32768f }
                val vad = Vad(ctx.assets, VadModelConfig(sileroVadModelConfig = SileroVadModelConfig(
                    model = "amphion-models/vad/v1/silero_vad.onnx",
                )))
                var confirmedMs: Int? = null
                try {
                    for (i in 0..floats.size - 512 step 512) {
                        vad.acceptWaveform(floats.copyOfRange(i, i + 512))
                        if (vad.isSpeechDetected()) { confirmedMs = (i + 512) / 16; break }
                    }
                } finally { vad.release() }
                awaitIdle(engine)
                val listener = CapturingListener { engine.setSpeakerVadEnabled(true) }
                engine.setListener(listener)
                val sid = "onset-$prefixMs-${System.currentTimeMillis()}"
                DqReport.append(ctx, mapOf("case" to "onset_diagnostic", "phase" to "start",
                    "sessionId" to sid, "prefixMs" to prefixMs, "nativeConfirmedMs" to confirmedMs,
                    "vadBeginMs" to 1000, "minSegSec" to 0, "voiceprintIdCount" to 1))
                engine.startListening(StartParams(sid, AudioInfo(), extraParams = mapOf(
                    "voiceprintIds" to listOf(id), "vadBegin" to 1000, "vadEnd" to 800,
                )))
                assertTrue(listener.awaitStarted(15000))
                var fedBytes = 0
                // Match the original burst prefix followed by real-time PCM.
                feedSilence(engine, sid, prefixMs)
                while (fedBytes < pcm.size && listener.completes.isEmpty()) {
                    val count = minOf(DQ_FRAME, pcm.size - fedBytes)
                    val frame = ByteArray(DQ_FRAME)
                    System.arraycopy(pcm, fedBytes, frame, 0, count)
                    engine.writeAudio(sid, frame)
                    fedBytes += count
                    Thread.sleep(20)
                }
                val lastBeforeFinish = listener.finals.count { it.isLast }
                DqReport.append(ctx, mapOf("case" to "onset_diagnostic", "phase" to "before_finish",
                    "sessionId" to sid, "prefixMs" to prefixMs, "fedAudioMs" to prefixMs + fedBytes / 32,
                    "lastBeforeFinish" to lastBeforeFinish, "events" to listener.events.toString(),
                    "partials" to listener.partials.toString()))
                if (listener.completes.isEmpty()) engine.finish(sid)
                assertTrue(listener.awaitComplete(25000))
                awaitIdle(engine)
                DqReport.append(ctx, mapOf("case" to "onset_diagnostic", "phase" to "complete",
                    "sessionId" to sid, "prefixMs" to prefixMs, "errors" to listener.errors.toString(),
                    "text" to listener.finalText(), "lastCount" to listener.finals.count { it.isLast },
                    "completeCount" to listener.completes.size,
                    "scores" to listener.finals.map { it.speakerSimilarity }.toString()))
                assertTrue("native onset contradicts the hypothesis", if (prefixMs == 0)
                    confirmedMs != null && confirmedMs <= 1000 else confirmedMs != null && confirmedMs > 1000)
                assertTrue("SDK timeout contradicts native onset", lastBeforeFinish == if (prefixMs == 0) 0 else 1)
                assertTrue(listener.errors.isEmpty())
                assertTrue(listener.callbackTrace.filter { it.isLast || it.kind == CapturedCallbackKind.COMPLETE }
                    .map { it.kind } == listOf(CapturedCallbackKind.FINAL, CapturedCallbackKind.COMPLETE))
                if (prefixMs == 0) {
                    val nonEmpty = listener.finals.filter { it.result.isNotBlank() }
                    assertTrue(nonEmpty.isNotEmpty() && nonEmpty.all { it.speakerSimilarity != null })
                }
            }
        } finally { engine.shutdown(); SpeechRecognizeSdk.unloadRuntime() }
    }
}
