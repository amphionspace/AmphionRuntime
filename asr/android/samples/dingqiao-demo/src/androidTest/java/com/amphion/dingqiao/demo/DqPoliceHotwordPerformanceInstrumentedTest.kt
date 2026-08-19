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
 * CPU time, PSS and VmRSS checkpoints to its dedicated
 * `files/police_hotword_perf/report.jsonl`.
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
        val effectiveHotwordSha256 = sha256(hotwords.joinToString("\n").toByteArray(Charsets.UTF_8))

        val availableAudio = mainWavs(testContext)
        val requestedAudio = arguments.getString("audioAsset")?.takeIf { it.isNotBlank() }
        val audioAsset = requestedAudio ?: availableAudio.firstOrNull()
        assertTrue(
            "requested audio '$audioAsset' is unavailable; found=$availableAudio",
            audioAsset != null && audioAsset in availableAudio,
        )
        val pcm = readAssetPcm(testContext, checkNotNull(audioAsset))

        val sampler = ResourceSampler()
        var engine: SpeechRecognitionEngine? = null
        try {
            SpeechRecognizeSdk.init(targetContext)
            val perfRoot = File(targetContext.filesDir, PERF_ROOT)
            SpeechRecognizeSdk.setWorkPath(
                File(perfRoot, "work/$runId").absolutePath,
            )
            activateValidLicense("$PERF_ROOT/license/valid.lic")

            val prepareCpuStartMs = Process.getElapsedCpuTime()
            val prepareStartMs = SystemClock.elapsedRealtime()
            prepareRuntime()
            val prepareMs = SystemClock.elapsedRealtime() - prepareStartMs
            val prepareCpuMs = Process.getElapsedCpuTime() - prepareCpuStartMs
            val pssAfterPrepareKb = Debug.getPss().toLong()
            val rssAfterPrepareKb = readVmRssKb()

            val createCpuStartMs = Process.getElapsedCpuTime()
            val createStartMs = SystemClock.elapsedRealtime()
            engine = createEngine()
            val measuredEngine = checkNotNull(engine)
            val createMs = SystemClock.elapsedRealtime() - createStartMs
            val createCpuMs = Process.getElapsedCpuTime() - createCpuStartMs
            val pssAfterCreateKb = Debug.getPss().toLong()
            val rssAfterCreateKb = readVmRssKb()

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
            val pssBeforeShutdownKb = Debug.getPss().toLong()
            val rssBeforeShutdownKb = readVmRssKb()

            measuredEngine.shutdown()
            engine = null
            SystemClock.sleep(200)
            val pssAfterShutdownKb = Debug.getPss().toLong()
            val rssAfterShutdownKb = readVmRssKb()
            SpeechRecognizeSdk.unloadModel()
            SystemClock.sleep(400)
            val pssAfterUnloadKb = Debug.getPss().toLong()
            val rssAfterUnloadKb = readVmRssKb()
            sampler.sampleNow()

            val report = linkedMapOf<String, Any?>(
                "case" to "police-hotword-performance",
                "runId" to runId,
                "compiledDefaultProfile" to profile.wireValue,
                "effectiveHotwordCount" to hotwords.size,
                "effectiveHotwordSha256" to effectiveHotwordSha256,
                "audioAsset" to audioAsset,
                "sourceDurationMs" to sourceDurationMs,
                "acceptedDurationMs" to acceptedDurationMs,
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
                "pssBaselineKb" to sampler.baselinePssKb,
                "pssAfterPrepareKb" to pssAfterPrepareKb,
                "pssAfterCreateKb" to pssAfterCreateKb,
                "pssPeakKb" to sampler.peakPssKb(),
                "pssPeakDeltaKb" to availableDelta(sampler.baselinePssKb, sampler.peakPssKb()),
                "pssBeforeShutdownKb" to pssBeforeShutdownKb,
                "pssAfterShutdownKb" to pssAfterShutdownKb,
                "pssAfterUnloadKb" to pssAfterUnloadKb,
                "rssBaselineKb" to sampler.baselineRssKb,
                "rssAfterPrepareKb" to rssAfterPrepareKb,
                "rssAfterCreateKb" to rssAfterCreateKb,
                "rssPeakKb" to sampler.peakRssKb(),
                "rssPeakDeltaKb" to availableDelta(sampler.baselineRssKb, sampler.peakRssKb()),
                "rssAvailable" to (sampler.baselineRssKb >= 0L && sampler.peakRssKb() >= 0L),
                "rssBeforeShutdownKb" to rssBeforeShutdownKb,
                "rssAfterShutdownKb" to rssAfterShutdownKb,
                "rssAfterUnloadKb" to rssAfterUnloadKb,
                "finalCount" to finalCount.get(),
                "lastCount" to lastCount.get(),
                "finalText" to finalTexts.joinToString(""),
                "errors" to errors.joinToString(" | "),
                "cpuIncludesResourceSampler" to true,
            )
            appendPerfReport(report)
            Log.i(TAG, report.toString())

            assertTrue("compiled profile must have real hotwords", hotwords.isNotEmpty())
            assertTrue("createEngine should hit prepared pool: createMs=$createMs", createMs <= 500L)
            assertTrue("first non-empty partial missing", firstPartialMs >= 0L)
            assertTrue("first final missing", finalCount.get() > 0)
            assertEquals("normal finish must produce one last", 1, lastCount.get())
            assertTrue("recognition errors: $errors", errors.isEmpty())
        } finally {
            try {
                engine?.shutdown()
            } catch (_: Throwable) {
            }
            sampler.close()
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

    private fun appendPerfReport(fields: Map<String, Any?>) {
        val dir = File(targetContext.filesDir, PERF_ROOT).apply { mkdirs() }
        val obj = JSONObject()
        obj.put("ts", System.currentTimeMillis())
        for ((key, value) in fields) obj.put(key, value ?: JSONObject.NULL)
        File(dir, "report.jsonl").appendText(obj.toString() + "\n", Charsets.UTF_8)
    }

    private class ResourceSampler : AutoCloseable {
        val baselinePssKb: Long = Debug.getPss().toLong()
        val baselineRssKb: Long = readVmRssKb()
        private val peakPss = AtomicLong(baselinePssKb)
        private val peakRss = AtomicLong(baselineRssKb)
        private val running = AtomicBoolean(true)
        private val thread = Thread({
            while (running.get()) {
                sampleNow()
                SystemClock.sleep(RESOURCE_SAMPLE_MS)
            }
        }, "police-hotword-perf-sampler").apply { start() }

        fun sampleNow() {
            peakPss.getAndUpdate { previous -> maxOf(previous, Debug.getPss().toLong()) }
            val rss = readVmRssKb()
            if (rss >= 0L) peakRss.getAndUpdate { previous -> maxOf(previous, rss) }
        }

        fun peakPssKb(): Long = peakPss.get()

        fun peakRssKb(): Long = peakRss.get()

        override fun close() {
            running.set(false)
            thread.join(1_000)
            sampleNow()
        }
    }

    companion object {
        private const val TAG = "DqPoliceHotwordPerf"
        private const val PERF_ROOT = "police_hotword_perf"
        private const val FULL_HOTWORD_COUNT = 370
        private const val PRUNE_UI28_HOTWORD_COUNT = 342
        private const val TAIL_SILENCE_MS = 1_000
        private const val RESOURCE_SAMPLE_MS = 50L

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
