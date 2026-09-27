package com.amphion.dingqiao.demo

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.police.PoliceEngineConfig
import com.k2fsa.sherpa.onnx.*
import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Test
import org.junit.runner.RunWith

/** Temporary native state fork; never a product acceptance result. */
@RunWith(AndroidJUnit4::class)
class Pr218NativeBoundaryDiagnosticTest {
    @Test
    fun compareKeepSoftAndFreshAtObservedBoundary() {
        val ctx = InstrumentationRegistry.getInstrumentation().targetContext
        val tc = InstrumentationRegistry.getInstrumentation().context
        val base = "amphion-models/zh-en/v1/"
        val recognizer = OnlineRecognizer(ctx.assets, OnlineRecognizerConfig(
            modelConfig = OnlineModelConfig(
                transducer = OnlineTransducerModelConfig(base + "encoder.int8.ort.mp3",
                    base + "decoder.ort.mp3", base + "joiner.int8.ort.mp3"),
                tokens = base + "tokens.txt", bpeVocab = base + "bbpe.vocab",
                modelingUnit = "bbpe", modelType = "zipformer2",
                numThreads = 4, provider = "cpu;DisablePrepacking=1",
            ),
            decodingMethod = "modified_beam_search", maxActivePaths = 8,
            hotwordsScore = 3f,
            endpointConfig = EndpointConfig(rule2 = EndpointRule(true, 2f, 0f)),
        ))
        val hotwords = PoliceEngineConfig.effectiveHotwords(emptyList()).joinToString("\n")
        try {
            for ((asset, boundaryMs) in listOf("v6_1_1.wav" to 3300, "v6_2_1.wav" to 3760)) {
                val pcm = ByteBuffer.wrap(readAssetPcm(tc, asset)).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
                val audio = FloatArray(pcm.remaining()) { pcm.get() / 32768f }
                for (branch in listOf("keep", "soft", "fresh")) {
                    var stream = recognizer.createStream(hotwords)
                    var decodes = 0
                    var previousTokens = ""
                    var generation = 0
                    fun capture(phase: String, position: Int, force: Boolean = false) {
                        val r = recognizer.getResult(stream)
                        val key = r.tokens.joinToString("|")
                        if (force || key != previousTokens) {
                            DqReport.append(ctx, mapOf("case" to "native_boundary", "asset" to asset,
                                "branch" to branch, "phase" to phase, "sample" to position,
                                "generation" to generation, "decodeCount" to decodes,
                                "ready" to recognizer.isReady(stream),
                                "nativeEndpoint" to recognizer.getEndpointReason(stream).toString(),
                                "text" to r.text, "tokens" to r.tokens.toList().toString(),
                                "timestamps" to r.timestamps.toList().toString()))
                            previousTokens = key
                        }
                    }
                    fun drain() { while (recognizer.isReady(stream)) { recognizer.decode(stream); decodes++ } }
                    try {
                        var position = 0
                        val boundary = boundaryMs * 16
                        while (position < audio.size) {
                            val end = minOf(position + 320, audio.size)
                            stream.acceptWaveform(audio.copyOfRange(position, end), 16000)
                            drain()
                            position = end
                            capture("real", position)
                            if (position == boundary) {
                                capture("before_boundary", position, true)
                                when (branch) {
                                    "soft" -> { recognizer.reset(stream); generation++ }
                                    "fresh" -> {
                                        stream.inputFinished(); drain(); capture("input_finished", position, true)
                                        stream.release(); stream = recognizer.createStream(hotwords); generation++
                                        stream.acceptWaveform(FloatArray(12800), 16000); drain(); recognizer.reset(stream)
                                    }
                                }
                                capture("after_boundary", position, true)
                            }
                        }
                        // Fixed diagnostic tail, separately labeled from real input.
                        repeat(64) {
                            stream.acceptWaveform(FloatArray(320), 16000); drain()
                            capture("synthetic_tail", audio.size + (it + 1) * 320)
                        }
                        stream.inputFinished(); drain(); capture("end", audio.size, true)
                    } finally { stream.release() }
                }
            }
        } finally { recognizer.release() }
    }
}
