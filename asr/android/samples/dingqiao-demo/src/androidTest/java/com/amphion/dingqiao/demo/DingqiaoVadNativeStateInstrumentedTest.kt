package com.amphion.dingqiao.demo

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.police.PoliceEngineConfig
import com.k2fsa.sherpa.onnx.*
import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Native regression: inspecting pending speech must preserve subsequent live decoding. */
@RunWith(AndroidJUnit4::class)
class DingqiaoVadNativeStateInstrumentedTest {
    @Test fun pendingSpeechVetoDoesNotChangeLiveStream() {
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
            decodingMethod = "modified_beam_search", maxActivePaths = 8, hotwordsScore = 3f,
            endpointConfig = EndpointConfig(rule2 = EndpointRule(true, 2f, 0f)),
        ))
        val hotwords = PoliceEngineConfig.effectiveHotwords(emptyList()).joinToString("\n")
        fun snapshot(stream: OnlineStream): String {
            val r = recognizer.getResult(stream)
            return "${r.text}|${r.tokens.toList()}|${r.timestamps.toList()}"
        }
        try {
            for ((asset, boundaryMs) in listOf("v6_1_1.wav" to 3300, "v6_2_1.wav" to 3760)) {
                val pcm = ByteBuffer.wrap(readAssetPcm(tc, asset)).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
                val audio = FloatArray(pcm.remaining()) { pcm.get() / 32768f }
                val traces = mutableListOf<List<String>>()
                for (probe in listOf(false, true)) {
                    val stream = recognizer.createStream(hotwords)
                    val trace = mutableListOf<String>()
                    var count = 0
                    var previous = ""
                    try {
                        val full = audio + FloatArray(20480)
                        var pos = 0
                        while (pos < full.size) {
                            val end = minOf(pos + 320, full.size)
                            stream.acceptWaveform(full.copyOfRange(pos, end), 16000)
                            var decoded = false
                            while (recognizer.isReady(stream)) {
                                recognizer.decode(stream); count++; decoded = true
                            }
                            pos = end
                            val before = snapshot(stream)
                            val boundary = pos == boundaryMs * 16
                            if (probe && (boundary || (pos > boundaryMs * 16 && decoded))) {
                                val start = System.nanoTime()
                                val wait = recognizer.getVadEndpointWaitSeconds(stream, .8f)
                                val elapsed = (System.nanoTime() - start) / 1e6
                                assertEquals("Probe mutated live public result", before, snapshot(stream))
                                DqReport.append(ctx, mapOf("case" to "pending_speech_probe", "asset" to asset,
                                    "sample" to pos, "realSamples" to audio.size, "decodeCount" to count,
                                    "boundary" to boundary, "waitSeconds" to wait,
                                    "probeMs" to elapsed, "liveResult" to before))
                                if (boundary) {
                                    assertTrue("Premature cut still allowed for $asset: $wait", wait > 0f)
                                    assertTrue("Short vadEnd discarded a pending token for $asset",
                                        recognizer.getVadEndpointWaitSeconds(stream, .2f) > 0f)
                                }
                            }
                            trace.add("$pos:$count:$before")
                            if (before != previous || boundary) {
                                DqReport.append(ctx, mapOf("case" to "pending_speech_live", "asset" to asset,
                                    "probe" to probe, "sample" to pos, "decodeCount" to count, "result" to before))
                                previous = before
                            }
                        }
                        if (probe) assertEquals("True silence cannot finalize", 0f,
                            recognizer.getVadEndpointWaitSeconds(stream, .8f), 0f)
                        traces.add(trace)
                    } finally { stream.release() }
                }
                assertEquals("Subsequent real decoding changed for $asset", traces[0], traces[1])
                DqReport.append(ctx, mapOf("case" to "pending_speech_equivalence", "asset" to asset,
                    "equalFrames" to traces[0].size, "passed" to true))
            }
        } finally { recognizer.release() }
    }
}
