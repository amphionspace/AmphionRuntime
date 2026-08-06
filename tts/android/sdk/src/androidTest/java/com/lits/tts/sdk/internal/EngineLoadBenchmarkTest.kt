package com.lits.tts.sdk.internal

import android.os.Debug
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.lits.tts.sdk.CompleteResponse
import com.lits.tts.sdk.CompleteType
import com.lits.tts.sdk.CreateEngineParams
import com.lits.tts.sdk.PlayType
import com.lits.tts.sdk.QueueMode
import com.lits.tts.sdk.RunMode
import com.lits.tts.sdk.SpeakListener
import com.lits.tts.sdk.SpeakParams
import com.lits.tts.sdk.StartResponse
import com.lits.tts.sdk.TextToSpeechSdk
import com.lits.tts.sdk.TtsStreamingConfig
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Test

class EngineLoadBenchmarkTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()

    @Test
    fun measureColdZhEngineLoad() {
        val outputDir = File(context.getExternalFilesDir(null) ?: context.filesDir, "engine-load-benchmark").apply { mkdirs() }
        val workDir = File(
            instrumentationArg("workPath") ?: File(context.filesDir, "engine-load-benchmark-work").absolutePath,
        ).apply {
            if (instrumentationArg("preserveWorkPath") != "true") {
                deleteRecursively()
            }
            mkdirs()
        }
        TextToSpeechSdk.setWorkPath(workDir.absolutePath)
        instrumentationArg("parallelOrtCreate")?.let {
            LitsTtsRuntimeOptions.parallelOrtCreate = it == "true"
        }
        instrumentationArg("ortWarmup")?.let {
            LitsTtsRuntimeOptions.ortWarmupOnCreate = it == "true"
        }
        instrumentationArg("hiddenThreads")?.toIntOrNull()?.let {
            LitsTtsRuntimeOptions.hiddenEncoderThreads = it
        }
        instrumentationArg("conditionThreads")?.toIntOrNull()?.let {
            LitsTtsRuntimeOptions.conditionEncoderThreads = it
        }
        instrumentationArg("decoderThreads")?.toIntOrNull()?.let {
            LitsTtsRuntimeOptions.decoderStepThreads = it
        }
        instrumentationArg("vocoderThreads")?.toIntOrNull()?.let {
            LitsTtsRuntimeOptions.vocoderThreads = it
        }
        instrumentationArg("firstChunkSize")?.toIntOrNull()?.let {
            LitsTtsRuntimeOptions.streamingFirstChunkSize = it
        }
        instrumentationArg("decoderCacheEnabled")?.let {
            LitsTtsRuntimeOptions.decoderCacheEnabled = it == "true"
        }
        instrumentationArg("ortOptimization")?.let { optimization ->
            System.setProperty("lits.ort.optimization", optimization)
        }
        val layout = if (
            instrumentationArg("preloadLargeBinaryLexicons") == "true" ||
            instrumentationArg("preloadFrontendResources") == "true"
        ) {
            LitsTtsAssetInstaller.ensureInstalled(context, workDir.absolutePath)
        } else {
            null
        }
        val preloadLargeBinaryLexicons = instrumentationArg("preloadLargeBinaryLexicons") == "true"
        val largeBinaryPreload = if (preloadLargeBinaryLexicons) {
            LitsTtsFrontend.preloadLargeBinaryLexicons(layout ?: error("layout unavailable"))
        } else {
            null
        }
        val preloadFrontendResources = instrumentationArg("preloadFrontendResources") == "true"
        val frontendResourcePreload = if (preloadFrontendResources) {
            val memoryBefore = stableMemorySnapshot()
            val startedAt = System.nanoTime()
            LitsTtsFrontend.preload(layout ?: error("layout unavailable"))
            val elapsedMs = elapsedMs(startedAt)
            val memoryAfter = stableMemorySnapshot()
            FrontendResourcePreloadResult(
                elapsedMs = elapsedMs,
                memoryBefore = memoryBefore,
                memoryAfter = memoryAfter,
            )
        } else {
            null
        }
        val preloadNativeTn = instrumentationArg("preloadNativeTn") == "true"
        val expectBatchNativeTn = instrumentationArg("batchNativeTn") == "true"
        LitsTnNormalizer.batchNativeEnabled = expectBatchNativeTn
        val nativeTnPreload = if (preloadNativeTn) {
            val activeLayout = layout ?: LitsTtsAssetInstaller.ensureInstalled(context, workDir.absolutePath)
            val memoryBefore = stableMemorySnapshot()
            val startedAt = System.nanoTime()
            val zh = LitsTnNormalizer.normalize(
                layout = activeLayout,
                text = "今天是2026年7月14日，温度是-24.5度，room 204 is ready.",
                language = "zh-en",
                languageContext = "zh-en",
            )
            val en = LitsTnNormalizer.normalize(
                layout = activeLayout,
                text = "Room 204 is ready at 09:15.",
                language = "en-US",
                languageContext = "en-US",
            )
            val elapsedMs = elapsedMs(startedAt)
            val memoryAfter = stableMemorySnapshot()
            NativeTnPreloadResult(
                elapsedMs = elapsedMs,
                zhOutput = zh,
                enOutput = en,
                memoryBefore = memoryBefore,
                memoryAfter = memoryAfter,
            )
        } else {
            null
        }

        val createStartedAt = System.currentTimeMillis()
        val engine = TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = "zh-en",
                mode = RunMode.OFFLINE,
                voiceId = "lits-female-02",
                engineName = "engine-load-${System.nanoTime()}",
            ),
        )
        val createEngineMs = System.currentTimeMillis() - createStartedAt

        val playType = instrumentationArg("playType")?.let { PlayType.valueOf(it) } ?: PlayType.SYNTHESIZE_ONLY
        val done = CountDownLatch(1)
        var startResponse: StartResponse? = null
        var completeResponse: CompleteResponse? = null
        var errorMessage: String? = null
        var bytes = 0L
        var playbackStartMs = -1L
        var coldToPlaybackStartMs = -1L
        var speakSubmitGapMs = -1L
        engine.setListener(
            object : SpeakListener {
                override fun onStart(requestId: String, response: StartResponse) {
                    startResponse = response
                }

                override fun onData(requestId: String, audio: ByteArray, response: com.lits.tts.sdk.SynthesisResponse) {
                    bytes += audio.size
                }

                override fun onPlaybackStart(requestId: String, elapsedMs: Long) {
                    playbackStartMs = elapsedMs
                    coldToPlaybackStartMs = System.currentTimeMillis() - createStartedAt
                    if (playType == PlayType.SYNTHESIZE_AND_PLAY) {
                        done.countDown()
                    }
                }

                override fun onComplete(requestId: String, response: CompleteResponse) {
                    if (response.type == CompleteType.SYNTHESIS_COMPLETE) {
                        completeResponse = response
                        if (playType == PlayType.SYNTHESIZE_ONLY) {
                            done.countDown()
                        }
                    }
                    if (playbackStartMs < 0L && response.playbackStartMs >= 0L) {
                        playbackStartMs = response.playbackStartMs
                        coldToPlaybackStartMs = System.currentTimeMillis() - createStartedAt
                        if (playType == PlayType.SYNTHESIZE_AND_PLAY) {
                            done.countDown()
                        }
                    }
                }

                override fun onError(requestId: String, errorCode: Int, errorMessageText: String) {
                    errorMessage = "$errorCode:$errorMessageText"
                    done.countDown()
                }
            },
        )
        val speakSubmitStartedAt = System.currentTimeMillis()
        speakSubmitGapMs = speakSubmitStartedAt - createStartedAt
        val text = instrumentationArg("text") ?: when (instrumentationArg("textPreset")) {
            "long" -> LONG_STREAMING_BENCHMARK_TEXT
            else -> "引擎加载速度测试，room 204 is ready."
        }
        engine.speak(
            text,
            SpeakParams(
                requestId = "engine-load-${System.nanoTime()}",
                playType = playType,
                queueMode = QueueMode.PREEMPT,
                languageContext = "zh-en",
                streamingConfig = TtsStreamingConfig(chunkSize = 50, pcmQueueCapacity = 128),
            ),
        )
        assertTrue(errorMessage ?: "timeout", done.await(90, TimeUnit.SECONDS))
        if (expectBatchNativeTn) {
            assertTrue(
                "expected batch TN profile, profilingInfo=${completeResponse?.profilingInfo}",
                completeResponse?.profilingInfo?.contains("nativeBatch=true") == true,
            )
        }
        engine.shutdown()
        LitsTnNormalizer.batchNativeEnabled = false

        val result = JSONObject()
            .put("createEngineMs", createEngineMs)
            .put("bytes", bytes)
            .put("error", errorMessage ?: JSONObject.NULL)
            .put("playType", playType.name)
            .put("modelInfo", startResponse?.modelInfo ?: JSONObject.NULL)
            .put("loadProfileInfo", startResponse?.loadProfileInfo ?: JSONObject.NULL)
            .put("firstPacketMs", completeResponse?.firstPacketMs ?: JSONObject.NULL)
            .put("playbackStartMs", playbackStartMs.takeIf { it >= 0 } ?: JSONObject.NULL)
            .put("coldToPlaybackStartMs", coldToPlaybackStartMs.takeIf { it >= 0 } ?: JSONObject.NULL)
            .put("speakSubmitGapMs", speakSubmitGapMs)
            .put("synthesisMs", completeResponse?.synthesisMs ?: JSONObject.NULL)
            .put("audioDurationMs", completeResponse?.audioDurationMs ?: JSONObject.NULL)
            .put("rtf", completeResponse?.rtf ?: JSONObject.NULL)
            .put("profilingInfo", completeResponse?.profilingInfo ?: JSONObject.NULL)
            .put("workPath", workDir.absolutePath)
            .put("preloadLargeBinaryLexicons", preloadLargeBinaryLexicons)
            .put("largeBinaryPreload", largeBinaryPreload?.toJson() ?: JSONObject.NULL)
            .put("preloadFrontendResources", preloadFrontendResources)
            .put("frontendResourcePreload", frontendResourcePreload?.toJson() ?: JSONObject.NULL)
            .put("preloadNativeTn", preloadNativeTn)
            .put("batchNativeTn", expectBatchNativeTn)
            .put("nativeTnPreload", nativeTnPreload?.toJson() ?: JSONObject.NULL)
            .put("parallelOrtCreate", LitsTtsRuntimeOptions.parallelOrtCreate)
            .put("decoderCacheEnabled", LitsTtsRuntimeOptions.decoderCacheEnabled)
            .put("ortWarmup", LitsTtsRuntimeOptions.ortWarmupOnCreate)
            .put("hiddenThreads", LitsTtsRuntimeOptions.hiddenEncoderThreads)
            .put("conditionThreads", LitsTtsRuntimeOptions.conditionEncoderThreads)
            .put("decoderThreads", LitsTtsRuntimeOptions.decoderStepThreads)
            .put("vocoderThreads", LitsTtsRuntimeOptions.vocoderThreads)
            .put("firstChunkSizeOption", LitsTtsRuntimeOptions.streamingFirstChunkSize)
            .put("textLength", text.length)
        File(outputDir, "engine-load-benchmark-summary.json").writeText(result.toString(2) + "\n")
        if (playType == PlayType.SYNTHESIZE_AND_PLAY) {
            assertTrue("expected playback start, result=$result", playbackStartMs >= 0L)
        } else {
            assertTrue("expected synthesized bytes, result=$result", bytes > 0)
        }
    }

    private fun instrumentationArg(name: String): String? =
        InstrumentationRegistry.getArguments().getString(name)

    companion object {
        private const val LONG_STREAMING_BENCHMARK_TEXT =
            "今天我们测试安卓端流式语音合成的长文本性能。第一段包含中文数字二零二六年七月二十一日，也包含room 204 is ready。第二段用于观察首包时延和整体RTF，看看decoder cache对后续chunk是否有收益。第三段继续增加长度，让模型至少产生多个流式分块，这样缓存才有发挥空间。Finally we add a short English sentence to keep the mixed frontend path active."
    }

    private fun LitsTtsFrontend.LargeBinaryLexiconPreloadResult.toJson(): JSONObject =
        JSONObject()
            .put("totalMs", totalMs)
            .put("wordPinyinMs", wordPinyinMs)
            .put("wordPinyinEntries", wordPinyinEntries)
            .put("cmudictMs", cmudictMs)
            .put("cmudictEntries", cmudictEntries)

    private fun FrontendResourcePreloadResult.toJson(): JSONObject =
        JSONObject()
            .put("elapsedMs", elapsedMs)
            .put("memoryBefore", memoryBefore.toJson())
            .put("memoryAfter", memoryAfter.toJson())
            .put("memoryDelta", memoryAfter.minus(memoryBefore).toJson())

    private fun NativeTnPreloadResult.toJson(): JSONObject =
        JSONObject()
            .put("elapsedMs", elapsedMs)
            .put("zhOutput", zhOutput)
            .put("enOutput", enOutput)
            .put("memoryBefore", memoryBefore.toJson())
            .put("memoryAfter", memoryAfter.toJson())
            .put("memoryDelta", memoryAfter.minus(memoryBefore).toJson())

    private fun MemorySnapshot.toJson(): JSONObject =
        JSONObject()
            .put("javaHeapBytes", javaHeapBytes)
            .put("nativeHeapAllocatedBytes", nativeHeapAllocatedBytes)
            .put("pssKb", pssKb)
            .put("rssKb", rssKb)

    private fun stableMemorySnapshot(): MemorySnapshot {
        repeat(2) {
            System.gc()
            System.runFinalization()
            Thread.sleep(80)
        }
        val info = Debug.MemoryInfo()
        Debug.getMemoryInfo(info)
        val runtime = Runtime.getRuntime()
        return MemorySnapshot(
            javaHeapBytes = runtime.totalMemory() - runtime.freeMemory(),
            nativeHeapAllocatedBytes = Debug.getNativeHeapAllocatedSize(),
            pssKb = info.totalPss,
            rssKb = readRssKb(),
        )
    }

    private fun readRssKb(): Long {
        val status = File("/proc/self/status")
        if (!status.isFile) return -1L
        for (line in status.readLines()) {
            if (line.startsWith("VmRSS:")) {
                return line.split(Regex("\\s+")).firstNotNullOfOrNull { it.toLongOrNull() } ?: -1L
            }
        }
        return -1L
    }

    private fun elapsedMs(startedAt: Long): Long = (System.nanoTime() - startedAt) / 1_000_000L

    private data class FrontendResourcePreloadResult(
        val elapsedMs: Long,
        val memoryBefore: MemorySnapshot,
        val memoryAfter: MemorySnapshot,
    )

    private data class NativeTnPreloadResult(
        val elapsedMs: Long,
        val zhOutput: String,
        val enOutput: String,
        val memoryBefore: MemorySnapshot,
        val memoryAfter: MemorySnapshot,
    )

    private data class MemorySnapshot(
        val javaHeapBytes: Long,
        val nativeHeapAllocatedBytes: Long,
        val pssKb: Int,
        val rssKb: Long,
    ) {
        fun minus(other: MemorySnapshot): MemorySnapshot =
            MemorySnapshot(
                javaHeapBytes = javaHeapBytes - other.javaHeapBytes,
                nativeHeapAllocatedBytes = nativeHeapAllocatedBytes - other.nativeHeapAllocatedBytes,
                pssKb = pssKb - other.pssKb,
                rssKb = rssKb - other.rssKb,
            )
    }
}
