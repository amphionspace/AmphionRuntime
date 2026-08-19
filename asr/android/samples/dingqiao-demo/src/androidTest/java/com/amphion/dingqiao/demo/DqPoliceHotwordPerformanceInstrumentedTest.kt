package com.amphion.dingqiao.demo

import android.content.Context
import android.os.Debug
import android.os.Process
import android.os.SystemClock
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.AudioInfo
import com.amphion.dingqiao.CreateEngineCallback
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.LicenseActivationCallback
import com.amphion.dingqiao.LicenseActivationResult
import com.amphion.dingqiao.PrepareRuntimeCallback
import com.amphion.dingqiao.RecognitionListener
import com.amphion.dingqiao.SpeechRecognitionEngine
import com.amphion.dingqiao.SpeechRecognitionResult
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.StartParams
import com.amphion.police.PoliceEngineConfig
import com.amphion.police.PoliceHotwordProfile
import java.io.File
import java.security.MessageDigest
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.json.JSONObject

/**
 * One repeatable performance probe for the profile compiled into the APK.
 *
 * It intentionally does not pass `__experimentalPoliceHotwordProfile`: prepareRuntime and the
 * public createEngine call therefore use the same build default. SDK-native timing/RTF metrics
 * remain available through logcat tag `AmphionMetrics`; this probe adds adapter wall time, process
 * CPU time and, for the `memory` lane only, PSS/VmRSS checkpoints to its dedicated
 * `files/police_hotword_perf/<lane>/report.jsonl`. Formal host runs execute this test through a plain
 * [android.app.Application], so the delivery demo cannot prepare the runtime before measurement.
 */
@RunWith(AndroidJUnit4::class)
class DqPoliceHotwordPerformanceInstrumentedTest {
    private val targetContext: Context
        get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val testContext: Context
        get() = InstrumentationRegistry.getInstrumentation().context

    @Test
    fun measureCompiledDefaultProfile() {
        val arguments = InstrumentationRegistry.getArguments()
        val runId = arguments.getString("runId")?.takeIf { it.isNotBlank() }
            ?: "perf-${System.currentTimeMillis()}"
        require(runId.matches(Regex("[A-Za-z0-9._-]+"))) {
            "runId may contain only letters, digits, dot, underscore and dash"
        }
        val perfLane = PerfLane.fromWireValue(
            arguments.getString("perfLane")?.takeIf { it.isNotBlank() }
                ?: PerfLane.CPU_LATENCY.wireValue,
        )
        val requirePlainApplicationRaw =
            arguments.getString("requirePlainApplication")?.takeIf { it.isNotBlank() } ?: "false"
        require(requirePlainApplicationRaw == "true" || requirePlainApplicationRaw == "false") {
            "requirePlainApplication must be true or false"
        }
        val requirePlainApplication = requirePlainApplicationRaw.toBoolean()
        val applicationClass = targetContext.applicationContext.javaClass.name
        val demoBootstrapSuppressed = applicationClass == android.app.Application::class.java.name
        val evidenceBindings = if (requirePlainApplication) {
            EvidenceBindings(
                expectedCount = requireArgument(arguments.getString("expectedCount"), "expectedCount")
                    .toInt(),
                targetApkSha256 = requireSha256Argument(arguments.getString("targetApkSha256")),
                testApkSha256 = requireSha256Argument(arguments.getString("testApkSha256")),
                modelManifestSha256 = requireSha256Argument(
                    arguments.getString("modelManifestSha256"),
                ),
                modelPayloadSha256 = requireSha256Argument(
                    arguments.getString("modelPayloadSha256"),
                ),
                audioSha256 = requireSha256Argument(arguments.getString("audioSha256")),
            )
        } else {
            null
        }
        if (requirePlainApplication) {
            assertTrue(
                "formal performance runner must suppress DingqiaoApp bootstrap",
                demoBootstrapSuppressed,
            )
        }
        val profile = PoliceHotwordProfile.defaultProfile()
        val expectedProfile = arguments.getString("expectedProfile")?.takeIf { it.isNotBlank() }
        if (expectedProfile != null) assertEquals(expectedProfile, profile.wireValue)
        val hotwords = PoliceEngineConfig.effectiveHotwordsForProfile(
            userHotwords = emptyList(),
            profile = profile,
        )
        val expectedCount = when (profile) {
            PoliceHotwordProfile.FULL -> FULL_HOTWORD_COUNT
            PoliceHotwordProfile.PRUNE_UI28 -> PRUNE_UI28_HOTWORD_COUNT
            PoliceHotwordProfile.NONE -> error("none is not a supported performance build default")
        }
        assertEquals(expectedCount, hotwords.size)
        evidenceBindings?.let { assertEquals(it.expectedCount, hotwords.size) }
        val effectiveHotwordSha256 = sha256(hotwords.joinToString("\n").toByteArray(Charsets.UTF_8))

        val availableAudio = mainWavs(testContext)
        val requestedAudio = arguments.getString("audioAsset")?.takeIf { it.isNotBlank() }
        val audioAsset = requestedAudio ?: availableAudio.firstOrNull()
        assertTrue(
            "requested audio '$audioAsset' is unavailable; found=$availableAudio",
            audioAsset != null && audioAsset in availableAudio,
        )
        val pcm = readAssetPcm(testContext, checkNotNull(audioAsset))

        val sampler = if (perfLane == PerfLane.MEMORY) ResourceSampler() else null
        var engine: SpeechRecognitionEngine? = null
        var prepareCallCount = 0
        var createCallCount = 0
        try {
            SpeechRecognizeSdk.init(targetContext)
            val perfRoot = File(targetContext.filesDir, "$PERF_ROOT/${perfLane.wireValue}")
            SpeechRecognizeSdk.setWorkPath(
                File(perfRoot, "work/$runId").absolutePath,
            )
            activateValidLicense("$PERF_ROOT/${perfLane.wireValue}/license/valid.lic")

            val prepareCpuStartMs = Process.getElapsedCpuTime()
            val prepareStartMs = SystemClock.elapsedRealtime()
            prepareCallCount += 1
            logPhase(runId, "prepare_start")
            prepareRuntime()
            logPhase(runId, "prepare_end")
            val prepareMs = SystemClock.elapsedRealtime() - prepareStartMs
            val prepareCpuMs = Process.getElapsedCpuTime() - prepareCpuStartMs
            val pssAfterPrepareKb = memoryPssKb(perfLane)
            val rssAfterPrepareKb = memoryRssKb(perfLane)

            val createCpuStartMs = Process.getElapsedCpuTime()
            val createStartMs = SystemClock.elapsedRealtime()
            createCallCount += 1
            logPhase(runId, "create_start")
            engine = createEngine()
            logPhase(runId, "create_end")
            val measuredEngine = checkNotNull(engine)
            val createMs = SystemClock.elapsedRealtime() - createStartMs
            val createCpuMs = Process.getElapsedCpuTime() - createCpuStartMs
            val pssAfterCreateKb = memoryPssKb(perfLane)
            val rssAfterCreateKb = memoryRssKb(perfLane)

            val started = CountDownLatch(1)
            val completed = CountDownLatch(1)
            val onStartElapsedMs = AtomicLong(-1L)
            val firstPartialElapsedMs = AtomicLong(-1L)
            val firstFinalElapsedMs = AtomicLong(-1L)
            val framesWrittenAtFirstPartial = AtomicInteger(-1)
            val framesWritten = AtomicInteger(0)
            val finalCount = AtomicInteger(0)
            val lastCount = AtomicInteger(0)
            val finalTexts = Collections.synchronizedList(mutableListOf<String>())
            val errors = Collections.synchronizedList(mutableListOf<String>())

            measuredEngine.setListener(object : RecognitionListener {
                override fun onStart(sessionId: String, eventMessage: String) {
                    onStartElapsedMs.compareAndSet(-1L, SystemClock.elapsedRealtime())
                    started.countDown()
                }

                override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) = Unit

                override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
                    val now = SystemClock.elapsedRealtime()
                    if (!result.isFinal && result.result.isNotBlank()) {
                        if (firstPartialElapsedMs.compareAndSet(-1L, now)) {
                            framesWrittenAtFirstPartial.set(framesWritten.get())
                        }
                    }
                    if (result.isFinal) {
                        firstFinalElapsedMs.compareAndSet(-1L, now)
                        finalCount.incrementAndGet()
                        if (result.isLast) lastCount.incrementAndGet()
                        if (result.result.isNotBlank()) finalTexts.add(result.result)
                    }
                }

                override fun onComplete(sessionId: String, eventMessage: String) {
                    completed.countDown()
                }

                override fun onError(sessionId: String, errorCode: Int, errorMessage: String) {
                    errors.add("$errorCode:$errorMessage")
                    completed.countDown()
                }
            })

            val sessionCpuStartMs = Process.getElapsedCpuTime()
            val startCallElapsedMs = SystemClock.elapsedRealtime()
            val sessionId = "$runId-${System.currentTimeMillis()}"
            logPhase(runId, "recognition_start")
            measuredEngine.startListening(
                StartParams(
                    sessionId = sessionId,
                    audioInfo = AudioInfo(),
                    extraParams = mapOf(
                        "enablePartialResult" to true,
                        "enablePoliceEnhancement" to true,
                        "vadEnd" to 800,
                    ),
                ),
            )
            assertTrue("onStart timed out", started.await(20, TimeUnit.SECONDS))
            val startToOnStartMs = onStartElapsedMs.get() - startCallElapsedMs

            val firstPcmElapsedMs = SystemClock.elapsedRealtime()
            feedPaced(measuredEngine, sessionId, pcm, framesWritten)
            val tailSilence = ByteArray(DQ_SR * 2 * TAIL_SILENCE_MS / 1_000)
            feedPaced(measuredEngine, sessionId, tailSilence, framesWritten)
            measuredEngine.finish(sessionId)
            assertTrue("session did not complete: $errors", completed.await(30, TimeUnit.SECONDS))
            awaitIdle(measuredEngine)
            logPhase(runId, "recognition_end")
            val sessionCpuMs = Process.getElapsedCpuTime() - sessionCpuStartMs
            val completedElapsedMs = SystemClock.elapsedRealtime()

            val sourceDurationMs = pcm.size * 1_000L / (DQ_SR * 2L)
            val acceptedDurationMs = (pcm.size + tailSilence.size) * 1_000L / (DQ_SR * 2L)
            val firstPartialMs = firstPartialElapsedMs.get().takeIf { it >= 0L }
                ?.minus(firstPcmElapsedMs) ?: -1L
            val audioFedAtFirstPartialMs = framesWrittenAtFirstPartial.get().takeIf { it >= 0 }
                ?.times(DQ_FRAME_MS) ?: -1L
            val firstPartialOverheadMs = if (firstPartialMs >= 0L) {
                firstPartialMs - audioFedAtFirstPartialMs
            } else {
                -1L
            }
            val finalE2eWallMs = firstFinalElapsedMs.get().takeIf { it >= 0L }
                ?.minus(firstPcmElapsedMs) ?: -1L
            val completeE2eWallMs = completedElapsedMs - firstPcmElapsedMs
            val cpuRtf = if (acceptedDurationMs > 0L) {
                sessionCpuMs.toDouble() / acceptedDurationMs.toDouble()
            } else {
                -1.0
            }
            val pssBeforeShutdownKb = memoryPssKb(perfLane)
            val rssBeforeShutdownKb = memoryRssKb(perfLane)

            measuredEngine.shutdown()
            engine = null
            SystemClock.sleep(200)
            val pssAfterShutdownKb = memoryPssKb(perfLane)
            val rssAfterShutdownKb = memoryRssKb(perfLane)
            SpeechRecognizeSdk.unloadModel()
            SystemClock.sleep(400)
            val pssAfterUnloadKb = memoryPssKb(perfLane)
            val rssAfterUnloadKb = memoryRssKb(perfLane)
            sampler?.sampleNow()
            sampler?.close()

            val pssBaselineKb = sampler?.baselinePssKb ?: -1L
            val pssPeakKb = sampler?.peakPssKb() ?: -1L
            val rssBaselineKb = sampler?.baselineRssKb ?: -1L
            val rssPeakKb = sampler?.peakRssKb() ?: -1L
            val resourceSampleCount = sampler?.sampleCount() ?: 0L

            val report = linkedMapOf<String, Any?>(
                "schemaVersion" to 2,
                "case" to "police-hotword-performance",
                "runId" to runId,
                "perfLane" to perfLane.wireValue,
                "applicationClass" to applicationClass,
                "plainApplicationRequired" to requirePlainApplication,
                "demoBootstrapSuppressed" to demoBootstrapSuppressed,
                "prepareCallCount" to prepareCallCount,
                "createCallCount" to createCallCount,
                "compiledDefaultProfile" to profile.wireValue,
                "effectiveHotwordCount" to hotwords.size,
                "effectiveHotwordSha256" to effectiveHotwordSha256,
                "audioAsset" to audioAsset,
                "sourceDurationMs" to sourceDurationMs,
                "acceptedDurationMs" to acceptedDurationMs,
                "acceptedPcmBytes" to (pcm.size + tailSilence.size),
                "prepareMs" to prepareMs,
                "prepareCpuMs" to prepareCpuMs,
                "createMs" to createMs,
                "createCpuMs" to createCpuMs,
                "startToOnStartMs" to startToOnStartMs,
                "firstPartialMs" to firstPartialMs,
                "audioFedAtFirstPartialMs" to audioFedAtFirstPartialMs,
                "firstPartialOverheadMs" to firstPartialOverheadMs,
                "finalE2eWallMs" to finalE2eWallMs,
                "completeE2eWallMs" to completeE2eWallMs,
                "sessionCpuMs" to sessionCpuMs,
                "cpuRtf" to cpuRtf,
                "pssBaselineKb" to pssBaselineKb,
                "pssAfterPrepareKb" to pssAfterPrepareKb,
                "pssAfterCreateKb" to pssAfterCreateKb,
                "pssPeakKb" to pssPeakKb,
                "pssPeakDeltaKb" to availableDelta(pssBaselineKb, pssPeakKb),
                "pssBeforeShutdownKb" to pssBeforeShutdownKb,
                "pssAfterShutdownKb" to pssAfterShutdownKb,
                "pssAfterUnloadKb" to pssAfterUnloadKb,
                "rssBaselineKb" to rssBaselineKb,
                "rssAfterPrepareKb" to rssAfterPrepareKb,
                "rssAfterCreateKb" to rssAfterCreateKb,
                "rssPeakKb" to rssPeakKb,
                "rssPeakDeltaKb" to availableDelta(rssBaselineKb, rssPeakKb),
                "rssAvailable" to (rssBaselineKb >= 0L && rssPeakKb >= 0L),
                "rssBeforeShutdownKb" to rssBeforeShutdownKb,
                "rssAfterShutdownKb" to rssAfterShutdownKb,
                "rssAfterUnloadKb" to rssAfterUnloadKb,
                "finalCount" to finalCount.get(),
                "lastCount" to lastCount.get(),
                "finalText" to finalTexts.joinToString(""),
                "errors" to errors.joinToString(" | "),
                "resourceSamplerEnabled" to (sampler != null),
                "cpuIncludesResourceSampler" to (sampler != null),
                "resourceSampleIntervalMs" to if (sampler != null) RESOURCE_SAMPLE_MS else -1L,
                "resourceSampleCount" to resourceSampleCount,
                "resourceBackgroundSampleCount" to (sampler?.backgroundSampleCount() ?: 0L),
                "resourceSamplingDurationMs" to (sampler?.samplingDurationMs() ?: -1L),
                "resourceSamplingStoppedBeforeReport" to true,
                "targetApkSha256" to evidenceBindings?.targetApkSha256,
                "testApkSha256" to evidenceBindings?.testApkSha256,
                "modelManifestSha256" to evidenceBindings?.modelManifestSha256,
                "modelPayloadSha256" to evidenceBindings?.modelPayloadSha256,
                "audioSha256" to evidenceBindings?.audioSha256,
            )
            appendPerfReport(perfLane, report)
            Log.i(TAG, report.toString())

            assertTrue("compiled profile must have real hotwords", hotwords.isNotEmpty())
            assertEquals("test must issue exactly one prepareRuntime call", 1, prepareCallCount)
            assertEquals("test must issue exactly one createEngineAsync call", 1, createCallCount)
            assertTrue("first non-empty partial missing", firstPartialMs >= 0L)
            assertTrue("first final missing", finalCount.get() > 0)
            assertEquals("normal finish must produce one last", 1, lastCount.get())
            assertTrue("recognition errors: $errors", errors.isEmpty())
        } finally {
            try {
                engine?.shutdown()
            } catch (_: Throwable) {
            }
            sampler?.close()
        }
    }

    private fun activateValidLicense(outName: String) {
        val path = stageAsset(
            testContext,
            targetContext,
            "licenses/valid.lic",
            outName,
        )
        val done = CountDownLatch(1)
        var resultCode: Int? = null
        SpeechRecognizeSdk.setLicense(path, object : LicenseActivationCallback {
            override fun onResult(result: LicenseActivationResult) {
                resultCode = result.errorCode
                done.countDown()
            }

            override fun onError(errorCode: Int, errorMessage: String) {
                resultCode = errorCode
                done.countDown()
            }
        })
        assertTrue("setLicense callback timed out", done.await(20, TimeUnit.SECONDS))
        assertEquals("valid license must activate", 0, resultCode)
    }

    private fun prepareRuntime() {
        val done = CountDownLatch(1)
        var error: String? = null
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() {
                done.countDown()
            }

            override fun onError(errorCode: Int, errorMessage: String) {
                error = "$errorCode:$errorMessage"
                done.countDown()
            }
        })
        assertTrue("prepareRuntime callback timed out", done.await(30, TimeUnit.SECONDS))
        assertEquals("prepareRuntime failed", null, error)
    }

    private fun createEngine(): SpeechRecognitionEngine {
        val done = CountDownLatch(1)
        var createdEngine: SpeechRecognitionEngine? = null
        var error: String? = null
        SpeechRecognizeSdk.createEngineAsync(
            CreateEngineParams(language = "zh-CN"),
            object : CreateEngineCallback {
                override fun onSuccess(engine: SpeechRecognitionEngine) {
                    createdEngine = engine
                    done.countDown()
                }

                override fun onError(errorCode: Int, errorMessage: String) {
                    error = "$errorCode:$errorMessage"
                    done.countDown()
                }
            },
        )
        assertTrue("createEngineAsync callback timed out", done.await(120, TimeUnit.SECONDS))
        assertEquals("createEngineAsync failed", null, error)
        return checkNotNull(createdEngine)
    }

    private fun feedPaced(
        engine: SpeechRecognitionEngine,
        sessionId: String,
        pcm: ByteArray,
        framesWritten: AtomicInteger,
    ) {
        var offset = 0
        while (offset < pcm.size) {
            val frame = ByteArray(DQ_FRAME)
            val size = minOf(DQ_FRAME, pcm.size - offset)
            System.arraycopy(pcm, offset, frame, 0, size)
            engine.writeAudio(sessionId, frame)
            framesWritten.incrementAndGet()
            offset += size
            SystemClock.sleep(DQ_FRAME_MS)
        }
    }

    private fun appendPerfReport(lane: PerfLane, fields: Map<String, Any?>) {
        val dir = File(targetContext.filesDir, "$PERF_ROOT/${lane.wireValue}").apply { mkdirs() }
        val obj = JSONObject()
        obj.put("ts", System.currentTimeMillis())
        for ((key, value) in fields) obj.put(key, value ?: JSONObject.NULL)
        File(dir, "report.jsonl").appendText(obj.toString() + "\n", Charsets.UTF_8)
    }

    private fun logPhase(runId: String, phase: String) {
        Log.i(TAG, "runId=$runId pid=${Process.myPid()} phase=$phase")
    }

    private fun requireSha256Argument(value: String?): String {
        val normalized = requireArgument(value, "SHA-256 binding")
        require(normalized.matches(Regex("[0-9a-f]{64}"))) {
            "invalid SHA-256 binding"
        }
        return normalized
    }

    private fun requireArgument(value: String?, name: String): String =
        value?.takeIf { it.isNotBlank() } ?: error("missing instrumentation argument: $name")

    private data class EvidenceBindings(
        val expectedCount: Int,
        val targetApkSha256: String,
        val testApkSha256: String,
        val modelManifestSha256: String,
        val modelPayloadSha256: String,
        val audioSha256: String,
    )

    private class ResourceSampler : AutoCloseable {
        val baselinePssKb: Long = Debug.getPss().toLong()
        val baselineRssKb: Long = readVmRssKb()
        private val peakPss = AtomicLong(baselinePssKb)
        private val peakRss = AtomicLong(baselineRssKb)
        private val samples = AtomicLong(0L)
        private val backgroundSamples = AtomicLong(0L)
        private val startedElapsedMs = SystemClock.elapsedRealtime()
        private val stoppedElapsedMs = AtomicLong(-1L)
        private val running = AtomicBoolean(true)
        private val thread = Thread({
            while (running.get()) {
                sample(background = true)
                SystemClock.sleep(RESOURCE_SAMPLE_MS)
            }
        }, "police-hotword-perf-sampler").apply { start() }

        private fun sample(background: Boolean) {
            peakPss.getAndUpdate { previous -> maxOf(previous, Debug.getPss().toLong()) }
            val rss = readVmRssKb()
            if (rss >= 0L) peakRss.getAndUpdate { previous -> maxOf(previous, rss) }
            samples.incrementAndGet()
            if (background) backgroundSamples.incrementAndGet()
        }

        fun sampleNow() = sample(background = false)

        fun peakPssKb(): Long = peakPss.get()

        fun peakRssKb(): Long = peakRss.get()

        fun sampleCount(): Long = samples.get()

        fun backgroundSampleCount(): Long = backgroundSamples.get()

        fun samplingDurationMs(): Long = stoppedElapsedMs.get().takeIf { it >= 0L }
            ?.minus(startedElapsedMs) ?: -1L

        override fun close() {
            if (running.getAndSet(false)) {
                thread.join(1_000)
                sampleNow()
                stoppedElapsedMs.compareAndSet(-1L, SystemClock.elapsedRealtime())
            }
        }
    }

    companion object {
        private const val TAG = "DqPoliceHotwordPerf"
        private const val PERF_ROOT = "police_hotword_perf"
        private const val FULL_HOTWORD_COUNT = 370
        private const val PRUNE_UI28_HOTWORD_COUNT = 342
        private const val TAIL_SILENCE_MS = 1_000
        private const val RESOURCE_SAMPLE_MS = 50L

        private enum class PerfLane(val wireValue: String) {
            CPU_LATENCY("cpu_latency"),
            MEMORY("memory");

            companion object {
                fun fromWireValue(value: String): PerfLane = entries.firstOrNull {
                    it.wireValue == value
                } ?: throw IllegalArgumentException(
                    "perfLane must be cpu_latency or memory, got '$value'",
                )
            }
        }

        private fun memoryPssKb(lane: PerfLane): Long =
            if (lane == PerfLane.MEMORY) Debug.getPss().toLong() else -1L

        private fun memoryRssKb(lane: PerfLane): Long =
            if (lane == PerfLane.MEMORY) readVmRssKb() else -1L

        private fun availableDelta(baseline: Long, peak: Long): Long =
            if (baseline >= 0L && peak >= 0L) peak - baseline else -1L

        private fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
            .digest(bytes)
            .joinToString("") { byte -> "%02x".format(byte.toInt() and 0xff) }

        private fun readVmRssKb(): Long = try {
            File("/proc/self/status").useLines { lines ->
                lines.firstOrNull { it.startsWith("VmRSS:") }
                    ?.substringAfter("VmRSS:")
                    ?.trim()
                    ?.substringBefore(' ')
                    ?.toLongOrNull()
                    ?: -1L
            }
        } catch (_: Throwable) {
            -1L
        }
    }
}
