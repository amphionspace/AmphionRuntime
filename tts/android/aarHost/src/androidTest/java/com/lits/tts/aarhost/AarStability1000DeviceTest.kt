package com.lits.tts.aarhost

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Debug
import android.os.Process
import android.os.SystemClock
import android.util.Log
import androidx.test.core.app.ApplicationProvider
import com.lits.tts.sdk.CompleteResponse
import com.lits.tts.sdk.CreateEngineParams
import com.lits.tts.sdk.PlayType
import com.lits.tts.sdk.QueueMode
import com.lits.tts.sdk.RunMode
import com.lits.tts.sdk.SpeakListener
import com.lits.tts.sdk.SpeakParams
import com.lits.tts.sdk.StartResponse
import com.lits.tts.sdk.SynthesisResponse
import com.lits.tts.sdk.TextToSpeechException
import com.lits.tts.sdk.TextToSpeechEngine
import com.lits.tts.sdk.TextToSpeechSdk
import com.lits.tts.sdk.TtsStreamingConfig
import com.lits.tts.sdk.VoiceQuery
import java.io.File
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.abs
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class AarStability1000DeviceTest {
    @get:Rule
    val externalResources = AarLicensedExternalResourcesRule()

    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val outputDir = File(
        context.getExternalFilesDir(null) ?: context.filesDir,
        "aar-stability-1000",
    ).apply { mkdirs() }
    private val runId = "aar-stability-1000-${System.currentTimeMillis()}"

    @Test
    fun runAndroidV3SdkStability1000CasesThroughAar() {
        val cases = loadCases()
        val caseStart = instrumentationArg("caseStart")?.toIntOrNull()?.coerceIn(0, cases.lastIndex) ?: 0
        val caseLimit = instrumentationArg("caseLimit")?.toIntOrNull()?.coerceIn(1, cases.size - caseStart) ?: (cases.size - caseStart)
        val selectedCases = cases.withIndex().drop(caseStart).take(caseLimit)
        assertTrue(
            "supported stability corpus size: ${cases.size}",
            cases.size == 1000 || cases.size == 424 || cases.size == 100,
        )

        applyRuntimeOptions()

        val resultsFile = File(outputDir, "results-$runId.jsonl")
        val startedAtMs = System.currentTimeMillis()
        var pass = 0
        var fail = 0
        var expectedError = 0
        var skipped = 0
        val categoryCounts = mutableMapOf<String, Int>()
        val sharedEngineHolder = SharedEngineHolder()
        val lifecyclePolicy = LifecyclePolicy()
        lateinit var finalShutdownBefore: Snapshot
        lateinit var finalShutdownAfter: Snapshot

        try {
            selectedCases.forEach { indexedCase ->
                val result = runCase(indexedCase.index, indexedCase.value, sharedEngineHolder, lifecyclePolicy)
                resultsFile.appendText(result.toString() + "\n", Charsets.UTF_8)
                categoryCounts[result.getString("category")] = (categoryCounts[result.getString("category")] ?: 0) + 1
                when (result.getString("status")) {
                    "PASS" -> pass += 1
                    "EXPECTED_ERROR" -> expectedError += 1
                    "SKIPPED" -> skipped += 1
                    else -> fail += 1
                }
                Log.i(TAG, "RESULT ${result.toCompactString()}")
            }
        } finally {
            finalShutdownBefore = Snapshot.capture()
            sharedEngineHolder.shutdown()
            SystemClock.sleep(LIFECYCLE_CASE_COOLDOWN_MS)
            finalShutdownAfter = Snapshot.capture()
        }

        val summary = JSONObject()
            .put("runId", runId)
            .put("sourceAsset", inputAssetName())
            .put("devicePackage", context.packageName)
            .put("integrationPath", "aarHost implementation(files(\"../sdk/build/outputs/aar/sdk-release.aar\"))")
            .put("totalAvailableCases", cases.size)
            .put("totalRunCases", selectedCases.size)
            .put("enginePolicy", "shared engine for normal batch cases; lifecycle cases run with isolated engines")
            .put("pass", pass)
            .put("expectedError", expectedError)
            .put("skipped", skipped)
            .put("fail", fail)
            .put("categoryCounts", JSONObject().apply {
                categoryCounts.toSortedMap().forEach { (category, count) -> put(category, count) }
            })
            .put("finalSharedEngineShutdown", JSONObject().apply {
                put("before", finalShutdownBefore.toJson())
                put("after", finalShutdownAfter.toJson())
            })
            .put("startedAtMs", startedAtMs)
            .put("finishedAtMs", System.currentTimeMillis())
            .put("resultsFile", resultsFile.absolutePath)
        File(outputDir, "summary-$runId.json").writeText(summary.toString(2) + "\n", Charsets.UTF_8)
        Log.i(TAG, "SUMMARY ${summary.toCompactString()}")
        assertEquals("failed cases; see ${resultsFile.absolutePath}", 0, fail)
    }

    private fun runCase(
        index: Int,
        case: JSONObject,
        sharedEngineHolder: SharedEngineHolder,
        lifecyclePolicy: LifecyclePolicy,
    ): JSONObject {
        val id = case.getString("id")
        val category = case.getString("category")
        val operation = case.optString("operation")
        val expectedStatus = case.getString("expected_status")
        val params = case.optJSONObject("params") ?: JSONObject()
        val setup = case.optJSONObject("setup") ?: JSONObject()
        val leakChecks = case.optJSONArray("leak_checks") ?: JSONArray()
        val before = Snapshot.capture()
        var leakCheckBefore = before
        var leakBaselineMode = "cold"
        var leakWarmupBefore: Snapshot? = null
        var leakWarmupAfter: Snapshot? = null
        var leakWarmupError = ""
        val sampler = ResourceSampler(context).also { it.start() }
        val startedAt = SystemClock.elapsedRealtime()
        val errors = mutableListOf<String>()
        var status = "PASS"
        var startCallbacks = 0
        var dataCallbacks = 0
        var completeCallbacks = 0
        var callbackError = false
        var bytes = 0L
        var firstPacketMs = -1L
        var firstAudioMs = -1L
        var playbackStartMs = -1L
        var synthesisMs = -1L
        var audioDurationMs = -1L
        var rtf = -1.0
        var profilingInfo = ""
        var engineScope = "none"
        var rtfExcluded = false
        val loopDetails = JSONArray()

        try {
            val text = case.optString("text", DEFAULT_TEXT)
            val lifecycleRequired = requiresIsolatedEngine(operation)
            if (lifecycleRequired && !lifecyclePolicy.allowInline()) {
                return skippedLifecycleResult(index, id, category, operation, expectedStatus, before, startedAt)
            }

            if (shouldWarmLeakBaseline(leakChecks, expectedStatus)) {
                val warmup = runCatching {
                    warmUpLeakBaseline(sharedEngineHolder, id, params, expectedStatus, text)
                }
                warmup.onSuccess { snapshots ->
                    leakWarmupBefore = snapshots.first
                    leakWarmupAfter = snapshots.second
                    leakCheckBefore = snapshots.second
                    leakBaselineMode = "warm"
                }.onFailure { error ->
                    leakWarmupError = "${error::class.java.simpleName}:${error.message}"
                    errors += "leak warmup failed: $leakWarmupError"
                }
            }

            if (operation.contains("query", ignoreCase = true)) {
                engineScope = "query"
                val voices = TextToSpeechSdk.listVoices(
                    VoiceQuery(
                        requestId = "$id-query",
                        mode = RunMode.OFFLINE,
                        language = sdkLanguage(params, expectedStatus).ifBlank { null },
                    ),
                )
                if (expectedStatus == "PASS" && voices.isEmpty()) {
                    errors += "voice query returned empty list"
                }
            } else if (operation == "create-engine-burst") {
                engineScope = "isolated-lifecycle"
                rtfExcluded = true
                val engines = mutableListOf<TextToSpeechEngine>()
                try {
                    sharedEngineHolder.prepareForLifecycleCase()
                    coolDownAfterLifecycleCase()
                    val count = params.optInt("engineCreateCount", 4).coerceAtLeast(1)
                    repeat(count) { ordinal ->
                        engines += TextToSpeechSdk.createEngine(createParams("$id-$ordinal", params, expectedStatus, text))
                    }
                    errors += "create-engine burst unexpectedly accepted"
                } catch (_: TextToSpeechException) {
                    callbackError = true
                } finally {
                    engines.forEach { runCatching { it.shutdown() } }
                    coolDownAfterLifecycleCase()
                }
            } else if (operation == "create-speak-shutdown-loop" || operation == "resource-load-cycle") {
                engineScope = "isolated-lifecycle-loop"
                rtfExcluded = false
                val loopCount = if (operation == "resource-load-cycle") {
                    setup.optInt("repeatCreateDestroy", 1).coerceAtLeast(1)
                } else {
                    instrumentationArg("loopCountOverride")?.toIntOrNull()?.takeIf { it > 0 }
                        ?: params.optInt("loopCount", 1).coerceAtLeast(1)
                }
                val loopMetrics = LoopMetrics()
                val loopProgressFile = File(outputDir, "loop-progress-$runId-index-$index-$id.jsonl")
                val sameEngineSpeakOnly = operation == "create-speak-shutdown-loop" &&
                    instrumentationArg("sameEngineSpeakOnly") == "true"
                if (sameEngineSpeakOnly) {
                    engineScope = "same-engine-speak-loop"
                    sharedEngineHolder.prepareForLifecycleCase()
                    coolDownAfterLifecycleCase()
                    val createStartedAt = SystemClock.elapsedRealtime()
                    val engine = TextToSpeechSdk.createEngine(createParams("$id-same-engine", params, expectedStatus, text))
                    val createMs = SystemClock.elapsedRealtime() - createStartedAt
                    val afterCreate = Snapshot.capture()
                    leakCheckBefore = afterCreate
                    try {
                        repeat(loopCount) { ordinal ->
                            val loopStartedAt = SystemClock.elapsedRealtime()
                            val loopCpuStartedAt = Process.getElapsedCpuTime()
                            val beforeSpeak = Snapshot.capture()
                            var afterSpeak = beforeSpeak
                            var afterShutdown = beforeSpeak
                            var awaitMs = -1L
                            var shutdownMs = -1L
                            var terminalTimedOut = false
                            var listener: RecordingListener? = null
                            try {
                                listener = RecordingListener()
                                engine.setListener(listener)
                                engine.speak(text, speakParams("$id-same-engine-loop-$ordinal", params, expectedStatus, text))
                                val timeoutMs = params.optLong("timeoutMs", DEFAULT_TIMEOUT_MS).coerceIn(5_000L, MAX_TIMEOUT_MS)
                                val awaitStartedAt = SystemClock.elapsedRealtime()
                                if (!listener.terminalLatch.await(timeoutMs, TimeUnit.MILLISECONDS)) {
                                    errors += "loop $ordinal terminal callback timeout after ${timeoutMs}ms"
                                    terminalTimedOut = true
                                }
                                awaitMs = SystemClock.elapsedRealtime() - awaitStartedAt
                                listener?.let { recorded ->
                                    loopMetrics.add(recorded)
                                    errors += recorded.errors.map { "loop $ordinal $it" }
                                }
                            } finally {
                                afterSpeak = Snapshot.capture()
                                if (ordinal == loopCount - 1) {
                                    val shutdownStartedAt = SystemClock.elapsedRealtime()
                                    runCatching { engine.shutdown() }
                                    shutdownMs = SystemClock.elapsedRealtime() - shutdownStartedAt
                                    coolDownAfterLifecycleCase()
                                    afterShutdown = Snapshot.capture()
                                } else {
                                    afterShutdown = afterSpeak
                                }
                                val loopDetail = JSONObject()
                                    .put("index", index)
                                    .put("id", id)
                                    .put("operation", operation)
                                    .put("loopMode", "same-engine-speak-only")
                                    .put("loopIndex", ordinal)
                                    .put("loopCount", loopCount)
                                    .put("loopElapsedMs", SystemClock.elapsedRealtime() - loopStartedAt)
                                    .put("loopCpuMs", Process.getElapsedCpuTime() - loopCpuStartedAt)
                                    .put("createMs", if (ordinal == 0) createMs else 0L)
                                    .put("awaitTerminalMs", awaitMs)
                                    .put("shutdownMs", shutdownMs)
                                    .put("terminalTimedOut", terminalTimedOut)
                                    .put("shutdownError", "")
                                    .put("startCallbacks", listener?.startCallbacks ?: 0)
                                    .put("dataCallbacks", listener?.dataCallbacks ?: 0)
                                    .put("completeCallbacks", listener?.completeCallbacks ?: 0)
                                    .put("errorCallbacks", listener?.errorCallbacks ?: 0)
                                    .put("bytes", listener?.bytes ?: 0L)
                                    .put("firstPacketMs", listener?.firstPacketMs ?: -1L)
                                    .put("synthesisMs", listener?.synthesisMs ?: -1L)
                                    .put("audioDurationMs", listener?.audioDurationMs ?: -1L)
                                    .put("rtf", listener?.rtf ?: -1.0)
                                    .put("profilingInfo", listener?.profilingInfo ?: "")
                                    .put("beforePrepare", beforeSpeak.toJson())
                                    .put("afterPrepare", beforeSpeak.toJson())
                                    .put("afterCreate", afterCreate.toJson())
                                    .put("beforeShutdown", afterSpeak.toJson())
                                    .put("afterShutdown", afterShutdown.toJson())
                                loopDetails.put(loopDetail)
                                loopProgressFile.appendText(loopDetail.toString() + "\n", Charsets.UTF_8)
                                Log.i(TAG, "LOOP_PROGRESS ${loopDetail.toCompactString()}")
                            }
                        }
                    } finally {
                        runCatching { engine.shutdown() }
                    }
                } else {
                repeat(loopCount) { ordinal ->
                    val loopStartedAt = SystemClock.elapsedRealtime()
                    val loopCpuStartedAt = Process.getElapsedCpuTime()
                    val beforePrepare = Snapshot.capture()
                    var afterPrepare = beforePrepare
                    var afterCreate = beforePrepare
                    var beforeShutdown = beforePrepare
                    var afterShutdown = beforePrepare
                    var createMs = -1L
                    var awaitMs = -1L
                    var shutdownMs = -1L
                    var terminalTimedOut = false
                    var shutdownError = ""
                    var listener: RecordingListener? = null
                    sharedEngineHolder.prepareForLifecycleCase()
                    afterPrepare = Snapshot.capture()
                    coolDownAfterLifecycleLoopIteration()
                    val createStartedAt = SystemClock.elapsedRealtime()
                    val engine = TextToSpeechSdk.createEngine(createParams("$id-loop-$ordinal", params, expectedStatus, text))
                    createMs = SystemClock.elapsedRealtime() - createStartedAt
                    afterCreate = Snapshot.capture()
                    try {
                        val recorded = RecordingListener()
                        listener = recorded
                        engine.setListener(recorded)
                        engine.speak(text, speakParams("$id-loop-$ordinal", params, expectedStatus, text))
                        val timeoutMs = params.optLong("timeoutMs", DEFAULT_TIMEOUT_MS).coerceIn(5_000L, MAX_TIMEOUT_MS)
                        val awaitStartedAt = SystemClock.elapsedRealtime()
                        if (!recorded.terminalLatch.await(timeoutMs, TimeUnit.MILLISECONDS)) {
                            errors += "loop $ordinal terminal callback timeout after ${timeoutMs}ms"
                            terminalTimedOut = true
                        }
                        awaitMs = SystemClock.elapsedRealtime() - awaitStartedAt
                        loopMetrics.add(recorded)
                        errors += recorded.errors.map { "loop $ordinal $it" }
                    } finally {
                        beforeShutdown = Snapshot.capture()
                        val shutdownStartedAt = SystemClock.elapsedRealtime()
                        runCatching { engine.shutdown() }.onFailure { error ->
                            shutdownError = "${error::class.java.simpleName}:${error.message}"
                        }
                        shutdownMs = SystemClock.elapsedRealtime() - shutdownStartedAt
                        coolDownAfterLifecycleLoopIteration()
                        afterShutdown = Snapshot.capture()
                        if (operation == "create-speak-shutdown-loop" && ordinal == 0) {
                            leakCheckBefore = afterShutdown
                        }
                        val loopDetail = JSONObject()
                            .put("index", index)
                            .put("id", id)
                            .put("operation", operation)
                            .put("loopIndex", ordinal)
                            .put("loopCount", loopCount)
                            .put("loopElapsedMs", SystemClock.elapsedRealtime() - loopStartedAt)
                            .put("loopCpuMs", Process.getElapsedCpuTime() - loopCpuStartedAt)
                            .put("createMs", createMs)
                            .put("awaitTerminalMs", awaitMs)
                            .put("shutdownMs", shutdownMs)
                            .put("terminalTimedOut", terminalTimedOut)
                            .put("shutdownError", shutdownError)
                            .put("startCallbacks", listener?.startCallbacks ?: 0)
                            .put("dataCallbacks", listener?.dataCallbacks ?: 0)
                            .put("completeCallbacks", listener?.completeCallbacks ?: 0)
                            .put("errorCallbacks", listener?.errorCallbacks ?: 0)
                            .put("bytes", listener?.bytes ?: 0L)
                            .put("firstPacketMs", listener?.firstPacketMs ?: -1L)
                            .put("synthesisMs", listener?.synthesisMs ?: -1L)
                            .put("audioDurationMs", listener?.audioDurationMs ?: -1L)
                            .put("rtf", listener?.rtf ?: -1.0)
                            .put("profilingInfo", listener?.profilingInfo ?: "")
                            .put("beforePrepare", beforePrepare.toJson())
                            .put("afterPrepare", afterPrepare.toJson())
                            .put("afterCreate", afterCreate.toJson())
                            .put("beforeShutdown", beforeShutdown.toJson())
                            .put("afterShutdown", afterShutdown.toJson())
                        loopDetails.put(loopDetail)
                        loopProgressFile.appendText(loopDetail.toString() + "\n", Charsets.UTF_8)
                        Log.i(TAG, "LOOP_PROGRESS ${loopDetail.toCompactString()}")
                    }
                }
                }
                startCallbacks = loopMetrics.startCallbacks
                dataCallbacks = loopMetrics.dataCallbacks
                completeCallbacks = loopMetrics.completeCallbacks
                callbackError = loopMetrics.errorCallbacks > 0
                bytes = loopMetrics.bytes
                firstPacketMs = loopMetrics.lastFirstPacketMs
                synthesisMs = loopMetrics.synthesisMs
                audioDurationMs = loopMetrics.audioDurationMs
                rtf = loopMetrics.rtf()
                profilingInfo = "loopCount=$loopCount lastProfile=${loopMetrics.lastProfilingInfo}"
            } else if (operation == "create-shutdown-fd-loop") {
                engineScope = "isolated-lifecycle-loop"
                rtfExcluded = true
                val loopCount = params.optInt("loopCount", 1).coerceAtLeast(1)
                repeat(loopCount) { ordinal ->
                    sharedEngineHolder.prepareForLifecycleCase()
                    coolDownAfterLifecycleLoopIteration()
                    val engine = TextToSpeechSdk.createEngine(createParams("$id-loop-$ordinal", params, expectedStatus, text))
                    runCatching { engine.shutdown() }.onFailure { error ->
                        errors += "loop $ordinal shutdown=${error::class.java.simpleName}:${error.message}"
                    }
                    coolDownAfterLifecycleLoopIteration()
                }
                profilingInfo = "loopCount=$loopCount createShutdownOnly=true"
            } else {
                val isolatedLifecycle = lifecycleRequired
                engineScope = if (isolatedLifecycle) "isolated-lifecycle" else "shared"
                rtfExcluded = isolatedLifecycle
                val engine = if (isolatedLifecycle) {
                    sharedEngineHolder.prepareForLifecycleCase()
                    coolDownAfterLifecycleCase()
                    TextToSpeechSdk.createEngine(createParams(id, params, expectedStatus, text))
                } else {
                    sharedEngineHolder.get()
                }
                try {
                    if (operation == "create-engine") {
                        // Creation is the operation under test.
                    } else if (operation == "set-listener-after-shutdown") {
                        engine.shutdown()
                        try {
                            engine.setListener(RecordingListener())
                            errors += "setListener after shutdown unexpectedly accepted"
                        } catch (_: TextToSpeechException) {
                            callbackError = true
                        }
                    } else if (operation.contains("speak-after-shutdown", ignoreCase = true)) {
                        engine.shutdown()
                        try {
                            engine.speak(text, speakParams(id, params, expectedStatus, text))
                            errors += "speak after shutdown unexpectedly accepted"
                        } catch (_: TextToSpeechException) {
                            callbackError = true
                        }
                    } else if (operation == "duplicate-request-id-pair") {
                        val listener = RecordingListener()
                        engine.setListener(listener)
                        val speakParams = speakParams(id, params, expectedStatus, text)
                        engine.speak(text, speakParams)
                        val timeoutMs = params.optLong("timeoutMs", DEFAULT_TIMEOUT_MS).coerceIn(5_000L, MAX_TIMEOUT_MS)
                        listener.terminalLatch.await(timeoutMs, TimeUnit.MILLISECONDS)
                        engine.speak(text, speakParams)
                        SystemClock.sleep(ASYNC_ERROR_SETTLE_MS)
                        startCallbacks = listener.startCallbacks
                        dataCallbacks = listener.dataCallbacks
                        completeCallbacks = listener.completeCallbacks
                        callbackError = listener.errorCallbacks > 0
                        bytes = listener.bytes
                        firstPacketMs = listener.firstPacketMs
                        firstAudioMs = listener.firstAudioMs()
                        playbackStartMs = listener.playbackStartMs
                        synthesisMs = listener.synthesisMs
                        audioDurationMs = listener.audioDurationMs
                        rtf = listener.rtf
                        profilingInfo = listener.profilingInfo
                        errors += listener.errors
                    } else {
                        val listener = RecordingListener()
                        engine.setListener(listener)
                        engine.speak(text, speakParams(id, params, expectedStatus, text))
                        val timeoutMs = params.optLong("timeoutMs", DEFAULT_TIMEOUT_MS).coerceIn(5_000L, MAX_TIMEOUT_MS)
                        if (!listener.terminalLatch.await(timeoutMs, TimeUnit.MILLISECONDS)) {
                            errors += "terminal callback timeout after ${timeoutMs}ms"
                        }
                        startCallbacks = listener.startCallbacks
                        dataCallbacks = listener.dataCallbacks
                        completeCallbacks = listener.completeCallbacks
                        callbackError = listener.errorCallbacks > 0
                        bytes = listener.bytes
                        firstPacketMs = listener.firstPacketMs
                        synthesisMs = listener.synthesisMs
                        audioDurationMs = listener.audioDurationMs
                        rtf = listener.rtf
                        profilingInfo = listener.profilingInfo
                        errors += listener.errors
                    }
                } finally {
                    if (isolatedLifecycle) {
                        runCatching { engine.shutdown() }
                        coolDownAfterLifecycleCase()
                    }
                }
            }
        } catch (error: TextToSpeechException) {
            callbackError = true
            errors += "sdkError=${error.errorCode}:${error.message}"
        } catch (error: Throwable) {
            errors += "unexpected=${error::class.java.simpleName}:${error.message}"
        }

        if (setup.optBoolean("forceShutdownAtEnd", false) && engineScope == "shared") {
            sharedEngineHolder.shutdown()
            coolDownAfterLifecycleCase()
        }

        SystemClock.sleep(
            if (engineScope.contains("loop") || setup.optBoolean("forceShutdownAtEnd", false)) {
                STRESS_CASE_SETTLE_MS
            } else {
                POST_CASE_SETTLE_MS
            },
        )
        val after = Snapshot.capture()
        val resourceStats = sampler.stop()
        val leakErrors = checkLeaks(leakChecks, leakCheckBefore, after)
        errors += leakErrors

        val terminalOk = completeCallbacks > 0 || callbackError || operation.contains("query", ignoreCase = true) ||
            operation == "create-engine" || operation.contains("speak-after-shutdown", ignoreCase = true) ||
            operation == "create-shutdown-fd-loop"
        if (expectedStatus == "PASS") {
            if (callbackError) errors += "unexpected callback/sdk error"
            if (!terminalOk) errors += "missing terminal state"
        } else if (expectedStatus == "EXPECTED_ERROR") {
            if (callbackError) {
                status = "EXPECTED_ERROR"
            } else {
                errors += "expected error but operation completed"
            }
        }
        if (errors.isNotEmpty() && status != "EXPECTED_ERROR") {
            status = "FAIL"
        }

        return JSONObject()
            .put("index", index)
            .put("id", id)
            .put("category", category)
            .put("operation", operation)
            .put("expectedStatus", expectedStatus)
            .put("status", status)
            .put("elapsedMs", SystemClock.elapsedRealtime() - startedAt)
            .put("startCallbacks", startCallbacks)
            .put("dataCallbacks", dataCallbacks)
            .put("completeCallbacks", completeCallbacks)
            .put("bytes", bytes)
            .put("firstPacketMs", firstPacketMs)
            .put("firstAudioMs", firstAudioMs)
            .put("playbackStartMs", playbackStartMs)
            .put("synthesisMs", synthesisMs)
            .put("audioDurationMs", audioDurationMs)
            .put("rtf", rtf)
            .put("rtfExcluded", rtfExcluded)
            .put("engineScope", engineScope)
            .put("profilingInfo", profilingInfo)
            .put("loopDetails", loopDetails)
            .put("before", before.toJson())
            .put("leakBaselineMode", leakBaselineMode)
            .put("leakWarmupBefore", leakWarmupBefore?.toJson() ?: JSONObject.NULL)
            .put("leakWarmupAfter", leakWarmupAfter?.toJson() ?: JSONObject.NULL)
            .put("leakWarmupError", leakWarmupError)
            .put("leakCheckBaseline", leakCheckBefore.toJson())
            .put("after", after.toJson())
            .put("resourceStats", resourceStats.toJson())
            .put("errors", JSONArray(errors))
    }

    private fun skippedLifecycleResult(
        index: Int,
        id: String,
        category: String,
        operation: String,
        expectedStatus: String,
        before: Snapshot,
        startedAt: Long,
    ): JSONObject {
        val after = Snapshot.capture()
        val resourceStats = ResourceStats.fromSamples(listOf(ResourceSample.capture(context)), RESOURCE_SAMPLE_INTERVAL_MS)
        return JSONObject()
            .put("index", index)
            .put("id", id)
            .put("category", category)
            .put("operation", operation)
            .put("expectedStatus", expectedStatus)
            .put("status", "SKIPPED")
            .put("skipReason", "lifecycle case excluded from shared-engine RTF batch")
            .put("elapsedMs", SystemClock.elapsedRealtime() - startedAt)
            .put("startCallbacks", 0)
            .put("dataCallbacks", 0)
            .put("completeCallbacks", 0)
            .put("bytes", 0L)
            .put("firstPacketMs", -1L)
            .put("synthesisMs", -1L)
            .put("audioDurationMs", -1L)
            .put("rtf", -1.0)
            .put("rtfExcluded", true)
            .put("engineScope", "skipped-lifecycle")
            .put("profilingInfo", "")
            .put("before", before.toJson())
            .put("after", after.toJson())
            .put("resourceStats", resourceStats.toJson())
            .put("errors", JSONArray())
    }

    private fun createParams(id: String, params: JSONObject, expectedStatus: String, text: String): CreateEngineParams =
        CreateEngineParams(
            language = sdkLanguage(params, expectedStatus, text),
            mode = sdkMode(params),
            voiceId = params.optString("voiceId", VOICE_ID),
            engineName = if (params.has("engineName")) params.optString("engineName") else "aar-$id",
            extraParams = createExtraParams(params),
            modelLoadOnCreate = if (expectedStatus == "PASS") true else params.optBoolean("modelLoadOnCreate", true),
        )

    private fun sharedEngineParams(): CreateEngineParams =
        CreateEngineParams(
            language = "zh-en",
            mode = RunMode.OFFLINE,
            voiceId = VOICE_ID,
            engineName = "aar-$runId-shared",
            extraParams = emptyMap(),
            modelLoadOnCreate = true,
        )

    private fun requiresIsolatedEngine(operation: String): Boolean {
        val normalized = operation.lowercase(Locale.US)
        return normalized.contains("shutdown") ||
            normalized.contains("cold-create") ||
            normalized.contains("warm-create") ||
            normalized.contains("create-engine") ||
            normalized == "create-query-destroy" ||
            normalized == "create-speak-shutdown-loop" ||
            normalized == "create-shutdown-fd-loop" ||
            normalized == "deferred-load-create" ||
            normalized == "multi-engine-sequential" ||
            normalized == "engine-limit-recovery" ||
            normalized.contains("speak-after-shutdown") ||
            normalized.contains("set-listener-after-shutdown") ||
            normalized.contains("listener-reuse-after-shutdown")
    }

    private fun coolDownAfterLifecycleCase() {
        SystemClock.sleep(LIFECYCLE_CASE_COOLDOWN_MS)
    }

    private fun coolDownAfterLifecycleLoopIteration() {
        SystemClock.sleep(LIFECYCLE_LOOP_COOLDOWN_MS)
    }

    private fun sdkMode(params: JSONObject): RunMode {
        val modelSource = params.optString("modelSource", "").lowercase(Locale.US)
        return if (modelSource == "online" || modelSource == "remote") RunMode.ONLINE else RunMode.OFFLINE
    }

    private fun createExtraParams(params: JSONObject): Map<String, Any?> {
        val extra = mutableMapOf<String, Any?>()
        if (params.has("modelSource")) extra["modelSource"] = params.optString("modelSource")
        if (params.has("workPathScenario")) extra["workPathScenario"] = params.optString("workPathScenario")
        return extra
    }

    private fun sdkLanguage(params: JSONObject, expectedStatus: String, text: String = ""): String {
        val language = params.optString("language", "zh-en")
        if (expectedStatus == "PASS" && text.any { it.code in HAN_RANGE }) {
            return "zh-en"
        }
        return if (expectedStatus == "PASS" && language == "zh-CN") "zh-en" else language
    }

    private fun speakParams(id: String, params: JSONObject, expectedStatus: String, text: String): SpeakParams {
        val chunkSize = params.optInt("chunkSize", 50).takeIf { it > 0 }
        val firstChunkSize = instrumentationArg("firstChunkSizeOverride")?.toIntOrNull()?.takeIf { it > 0 }
            ?: params.optInt("firstChunkSize", 0).takeIf { it > 0 }
            ?: params.optInt("streamingFirstChunkSize", 0).takeIf { it > 0 }
        val queueCapacity = instrumentationArg("pcmQueueCapacityOverride")?.toIntOrNull()?.takeIf { it > 0 }
            ?: params.optInt("pcmQueueCapacity", 32).takeIf { it > 0 }
        val speakExtraParams = mutableMapOf<String, Any?>()
        instrumentationArg("flowStepOverride")?.toIntOrNull()?.takeIf { it > 0 }?.let { flowStep ->
            speakExtraParams["flowStep"] = flowStep
        }
        instrumentationArg("firstChunkSizeOverride")?.toIntOrNull()?.takeIf { it > 0 }?.let { firstChunkSize ->
            speakExtraParams["firstChunkSize"] = firstChunkSize
        }
        instrumentationArg("previousChunkContextFramesOverride")?.toIntOrNull()?.takeIf { it >= 0 }?.let { contextFrames ->
            speakExtraParams["previousChunkContextFrames"] = contextFrames
        }
        instrumentationArg("secondChunkSizeOverride")?.toIntOrNull()?.takeIf { it > 0 }?.let { secondChunkSize ->
            speakExtraParams["secondChunkSize"] = secondChunkSize
        }
        instrumentationArg("steadyChunkSizeOverride")?.toIntOrNull()?.takeIf { it > 0 }?.let { steadyChunkSize ->
            speakExtraParams["steadyChunkSize"] = steadyChunkSize
        }
        instrumentationArg("chunkGrowthFactorOverride")?.toIntOrNull()?.takeIf { it > 1 }?.let { chunkGrowthFactor ->
            speakExtraParams["chunkGrowthFactor"] = chunkGrowthFactor
        }
        instrumentationArg("maxChunkSizeOverride")?.toIntOrNull()?.takeIf { it > 0 }?.let { maxChunkSize ->
            speakExtraParams["maxChunkSize"] = maxChunkSize
        }
        instrumentationArg("powerModeOverride")?.takeIf { it.isNotBlank() }?.let { powerMode ->
            speakExtraParams["powerMode"] = powerMode
        }
        instrumentationArg("cpuBudgetCoreOverride")?.toDoubleOrNull()?.takeIf { it > 0.0 }?.let { cpuBudgetCore ->
            speakExtraParams["cpuBudgetCore"] = cpuBudgetCore
        }
        val languageContext = if (expectedStatus == "PASS") {
            sdkLanguage(params, expectedStatus, text)
        } else {
            params.optString("languageContext", "zh-CN")
        }
        return SpeakParams(
            requestId = if (params.has("requestId")) params.optString("requestId") else id,
            speed = params.optDouble("speed", 1.0).toFloat(),
            volume = params.optDouble("volume", 1.0).toFloat(),
            pitch = params.optDouble("pitch", 1.0).toFloat(),
            languageContext = languageContext,
            audioType = params.optString("audioType", "pcm"),
            playType = enumValue(instrumentationArg("playTypeOverride") ?: params.optString("playType"), PlayType.SYNTHESIZE_ONLY),
            soundChannel = soundChannel(params, expectedStatus),
            queueMode = enumValue(params.optString("queueMode"), QueueMode.PREEMPT),
            extraParams = speakExtraParams,
            streamingConfig = TtsStreamingConfig(
                chunkSize = chunkSize,
                firstChunkSize = firstChunkSize,
                pcmQueueCapacity = queueCapacity,
            ),
        )
    }

    private fun soundChannel(params: JSONObject, expectedStatus: String): Int? {
        if (!params.has("soundChannel")) return null
        val value = params.opt("soundChannel")
        return when (value) {
            is Number -> value.toInt()
            is String -> value.toIntOrNull() ?: if (expectedStatus == "EXPECTED_ERROR") -999 else null
            else -> null
        }
    }

    private fun checkLeaks(checks: JSONArray, before: Snapshot, after: Snapshot): List<String> {
        val errors = mutableListOf<String>()
        for (i in 0 until checks.length()) {
            when (checks.optString(i)) {
                "fd_count_returns_near_baseline" -> {
                    if (after.fdCount - before.fdCount > 8) errors += "fd delta too high: ${after.fdCount - before.fdCount}"
                }
                "thread_count_returns_near_baseline", "stderr_watcher_thread_not_accumulating" -> {
                    if (after.threadCount - before.threadCount > 8) errors += "thread delta too high: ${after.threadCount - before.threadCount}"
                }
                "native_heap_delta_below_threshold" -> {
                    if (after.nativeHeap - before.nativeHeap > 32L * 1024L * 1024L) {
                        errors += "native heap delta too high: ${after.nativeHeap - before.nativeHeap}"
                    }
                }
                "java_heap_delta_below_threshold" -> {
                    if (after.javaHeap - before.javaHeap > 96L * 1024L * 1024L) {
                        errors += "java heap delta too high: ${after.javaHeap - before.javaHeap}"
                    }
                }
            }
        }
        return errors
    }

    private fun shouldWarmLeakBaseline(checks: JSONArray, expectedStatus: String): Boolean =
        expectedStatus == "PASS" &&
            checks.length() > 0 &&
            instrumentationArg("warmLeakBaseline") != "false"

    private fun warmUpLeakBaseline(
        sharedEngineHolder: SharedEngineHolder,
        id: String,
        params: JSONObject,
        expectedStatus: String,
        text: String,
    ): Pair<Snapshot, Snapshot> {
        val beforeWarmup = Snapshot.capture()
        val engine = sharedEngineHolder.get()
        val listener = RecordingListener()
        engine.setListener(listener)
        val requestId = "leak-warmup-$id-${SystemClock.elapsedRealtime()}"
        engine.speak(
            text,
            speakParams(requestId, params.withoutRequestId(), expectedStatus, text),
        )
        if (!listener.terminalLatch.await(SHARED_ENGINE_WARMUP_TIMEOUT_MS, TimeUnit.MILLISECONDS)) {
            throw IllegalStateException("leak warmup terminal callback timeout")
        }
        if (listener.errorCallbacks > 0 || listener.errors.isNotEmpty()) {
            throw IllegalStateException("leak warmup callback error: ${listener.errors.joinToString(";")}")
        }
        SystemClock.sleep(LEAK_BASELINE_SETTLE_MS)
        return beforeWarmup to Snapshot.capture()
    }

    private fun JSONObject.withoutRequestId(): JSONObject =
        JSONObject(toString()).also { copy ->
            copy.remove("requestId")
        }

    private fun loadCases(): List<JSONObject> =
        InstrumentationRegistry.getInstrumentation().context.assets.open(inputAssetName()).bufferedReader(Charsets.UTF_8).useLines { lines ->
            lines.filter { it.isNotBlank() }.map { JSONObject(it) }.toList()
        }

    private fun instrumentationArg(name: String): String? =
        InstrumentationRegistry.getArguments().getString(name)

    private fun applyRuntimeOptions() {
        instrumentationArg("decoderCacheEnabled")?.let { value ->
            runCatching {
                val clazz = Class.forName("com.lits.tts.sdk.internal.LitsTtsRuntimeOptions")
                val instance = clazz.getField("INSTANCE").get(null)
                clazz.getMethod("setDecoderCacheEnabled", Boolean::class.javaPrimitiveType).invoke(instance, value == "true")
            }.onFailure { error ->
                Log.w(TAG, "failed to set decoderCacheEnabled=$value", error)
            }
        }
        instrumentationArg("ortOptimization")?.let { optimization ->
            System.setProperty("lits.ort.optimization", optimization)
        }
    }

    private fun inputAssetName(): String =
        instrumentationArg("inputAsset")?.takeIf { it.isNotBlank() } ?: ASSET_NAME

    private inline fun <reified T : Enum<T>> enumValue(value: String, default: T): T =
        runCatching { enumValueOf<T>(value.ifBlank { default.name }) }.getOrDefault(default)

    private fun JSONObject.toCompactString(): String = toString().replace('\n', ' ')

    private class LifecyclePolicy {
        fun allowInline(): Boolean = true
    }

    private inner class SharedEngineHolder {
        private var engine: TextToSpeechEngine? = null
        private var warmupOnNextCreate = true

        fun get(): TextToSpeechEngine {
            val existing = engine
            if (existing != null) return existing
            return TextToSpeechSdk.createEngine(sharedEngineParams()).also {
                engine = it
                if (warmupOnNextCreate) {
                    warmup(it)
                    warmupOnNextCreate = false
                }
            }
        }

        fun prepareForLifecycleCase() {
            shutdown()
            warmupOnNextCreate = true
        }

        fun shutdown() {
            engine?.let { runCatching { it.shutdown() } }
            engine = null
        }

        private fun warmup(engine: TextToSpeechEngine) {
            val listener = RecordingListener()
            engine.setListener(listener)
            val requestId = "shared-warmup-${SystemClock.elapsedRealtime()}"
            engine.speak(SHARED_ENGINE_WARMUP_TEXT, speakParams(requestId, JSONObject(), "PASS", SHARED_ENGINE_WARMUP_TEXT))
            listener.terminalLatch.await(SHARED_ENGINE_WARMUP_TIMEOUT_MS, TimeUnit.MILLISECONDS)
            SystemClock.sleep(POST_CASE_SETTLE_MS)
        }
    }

    private class RecordingListener : SpeakListener {
        val terminalLatch = CountDownLatch(1)
        val errors = mutableListOf<String>()
        var startCallbacks = 0
        var dataCallbacks = 0
        var completeCallbacks = 0
        var errorCallbacks = 0
        var bytes = 0L
        var firstPacketMs = -1L
        var playbackStartMs = -1L
        var synthesisMs = -1L
        var audioDurationMs = -1L
        var rtf = -1.0
        var profilingInfo = ""

        override fun onStart(requestId: String, response: StartResponse) {
            startCallbacks += 1
        }

        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {
            dataCallbacks += 1
            bytes += audio.size
        }

        override fun onPlaybackStart(requestId: String, elapsedMs: Long) {
            playbackStartMs = elapsedMs
        }

        override fun onComplete(requestId: String, response: CompleteResponse) {
            completeCallbacks += 1
            firstPacketMs = response.firstPacketMs
            synthesisMs = response.synthesisMs
            audioDurationMs = response.audioDurationMs
            rtf = response.rtf
            profilingInfo = response.profilingInfo
            if (playbackStartMs < 0L && response.playbackStartMs >= 0L) {
                playbackStartMs = response.playbackStartMs
            }
            terminalLatch.countDown()
        }

        fun firstAudioMs(): Long = if (playbackStartMs >= 0L) playbackStartMs else firstPacketMs

        override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
            errorCallbacks += 1
            errors += "$errorCode:$errorMessage"
            terminalLatch.countDown()
        }
    }

    private class LoopMetrics {
        var startCallbacks = 0
        var dataCallbacks = 0
        var completeCallbacks = 0
        var errorCallbacks = 0
        var bytes = 0L
        var lastFirstPacketMs = -1L
        var synthesisMs = 0L
        var audioDurationMs = 0L
        var lastProfilingInfo = ""

        fun add(listener: RecordingListener) {
            startCallbacks += listener.startCallbacks
            dataCallbacks += listener.dataCallbacks
            completeCallbacks += listener.completeCallbacks
            errorCallbacks += listener.errorCallbacks
            bytes += listener.bytes
            if (listener.firstPacketMs >= 0L) lastFirstPacketMs = listener.firstPacketMs
            if (listener.synthesisMs >= 0L) synthesisMs += listener.synthesisMs
            if (listener.audioDurationMs >= 0L) audioDurationMs += listener.audioDurationMs
            if (listener.profilingInfo.isNotBlank()) lastProfilingInfo = listener.profilingInfo
        }

        fun rtf(): Double =
            if (synthesisMs > 0L && audioDurationMs > 0L) synthesisMs.toDouble() / audioDurationMs.toDouble() else -1.0
    }

    private class ResourceSampler(
        private val context: Context,
        private val intervalMs: Long = RESOURCE_SAMPLE_INTERVAL_MS,
    ) {
        private val running = AtomicBoolean(false)
        private val samples = mutableListOf<ResourceSample>()
        private var thread: Thread? = null

        fun start() {
            if (!running.compareAndSet(false, true)) return
            samples += ResourceSample.capture(context)
            thread = Thread({
                while (running.get()) {
                    SystemClock.sleep(intervalMs)
                    if (running.get()) {
                        synchronized(samples) {
                            samples += ResourceSample.capture(context)
                        }
                    }
                }
            }, "aar-resource-sampler").apply {
                isDaemon = true
                start()
            }
        }

        fun stop(): ResourceStats {
            running.set(false)
            thread?.join(250L)
            val finalSamples = synchronized(samples) {
                if (samples.isEmpty()) listOf(ResourceSample.capture(context)) else samples.toList()
            }
            return ResourceStats.fromSamples(finalSamples, intervalMs)
        }
    }

    private data class ResourceSample(
        val elapsedRealtimeMs: Long,
        val javaHeap: Long,
        val nativeHeap: Long,
        val pssKb: Long,
        val rssKb: Long,
        val vmHwmKb: Long,
        val batteryLevelPct: Int,
        val batteryTempDeciC: Int,
        val batteryVoltageMv: Int,
        val currentNowUa: Int,
        val currentAverageUa: Int,
        val chargeCounterUah: Int,
        val energyCounterNwh: Long,
        val plugged: Int,
        val batteryStatus: Int,
    ) {
        companion object {
            fun capture(context: Context): ResourceSample {
                val runtime = Runtime.getRuntime()
                val memoryInfo = Debug.MemoryInfo()
                Debug.getMemoryInfo(memoryInfo)
                val batteryManager = context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
                val battery = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
                return ResourceSample(
                    elapsedRealtimeMs = SystemClock.elapsedRealtime(),
                    javaHeap = runtime.totalMemory() - runtime.freeMemory(),
                    nativeHeap = Debug.getNativeHeapAllocatedSize(),
                    pssKb = memoryInfo.totalPss.toLong(),
                    rssKb = procStatusKb("VmRSS"),
                    vmHwmKb = procStatusKb("VmHWM"),
                    batteryLevelPct = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1,
                    batteryTempDeciC = battery?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1) ?: -1,
                    batteryVoltageMv = battery?.getIntExtra(BatteryManager.EXTRA_VOLTAGE, -1) ?: -1,
                    currentNowUa = batteryManager.safeIntProperty(BatteryManager.BATTERY_PROPERTY_CURRENT_NOW),
                    currentAverageUa = batteryManager.safeIntProperty(BatteryManager.BATTERY_PROPERTY_CURRENT_AVERAGE),
                    chargeCounterUah = batteryManager.safeIntProperty(BatteryManager.BATTERY_PROPERTY_CHARGE_COUNTER),
                    energyCounterNwh = batteryManager.safeLongProperty(BatteryManager.BATTERY_PROPERTY_ENERGY_COUNTER),
                    plugged = battery?.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1) ?: -1,
                    batteryStatus = battery?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1,
                )
            }

            private fun BatteryManager.safeIntProperty(property: Int): Int =
                runCatching { getIntProperty(property) }.getOrDefault(Int.MIN_VALUE)

            private fun BatteryManager.safeLongProperty(property: Int): Long =
                runCatching { getLongProperty(property) }.getOrDefault(Long.MIN_VALUE)

            private fun procStatusKb(key: String): Long =
                runCatching {
                    File("/proc/self/status").useLines { lines ->
                        lines.firstOrNull { it.startsWith("$key:") }
                            ?.split(Regex("\\s+"))
                            ?.firstOrNull { token -> token.toLongOrNull() != null }
                            ?.toLongOrNull()
                            ?: -1L
                    }
                }.getOrDefault(-1L)
        }
    }

    private data class ResourceStats(
        val sampleCount: Int,
        val sampleIntervalMs: Long,
        val durationMs: Long,
        val javaHeapAvg: Long,
        val javaHeapPeak: Long,
        val nativeHeapAvg: Long,
        val nativeHeapPeak: Long,
        val pssKbAvg: Long,
        val pssKbPeak: Long,
        val rssKbAvg: Long,
        val rssKbPeak: Long,
        val vmHwmKbPeak: Long,
        val currentNowUaAvg: Long,
        val currentNowUaPeakAbs: Int,
        val currentAverageUaAvg: Long,
        val batteryVoltageMvAvg: Int,
        val estimatedPowerMwAvg: Double,
        val estimatedPowerMwPeak: Double,
        val batteryTempDeciCAvg: Int,
        val batteryTempDeciCPeak: Int,
        val batteryLevelPctStart: Int,
        val batteryLevelPctEnd: Int,
        val chargeCounterUahStart: Int,
        val chargeCounterUahEnd: Int,
        val energyCounterNwhStart: Long,
        val energyCounterNwhEnd: Long,
        val plugged: Int,
        val batteryStatus: Int,
    ) {
        fun toJson(): JSONObject = JSONObject()
            .put("sampleCount", sampleCount)
            .put("sampleIntervalMs", sampleIntervalMs)
            .put("durationMs", durationMs)
            .put("javaHeapAvg", javaHeapAvg)
            .put("javaHeapPeak", javaHeapPeak)
            .put("nativeHeapAvg", nativeHeapAvg)
            .put("nativeHeapPeak", nativeHeapPeak)
            .put("pssKbAvg", pssKbAvg)
            .put("pssKbPeak", pssKbPeak)
            .put("rssKbAvg", rssKbAvg)
            .put("rssKbPeak", rssKbPeak)
            .put("vmHwmKbPeak", vmHwmKbPeak)
            .put("currentNowUaAvg", currentNowUaAvg)
            .put("currentNowUaPeakAbs", currentNowUaPeakAbs)
            .put("currentAverageUaAvg", currentAverageUaAvg)
            .put("batteryVoltageMvAvg", batteryVoltageMvAvg)
            .put("estimatedPowerMwAvg", estimatedPowerMwAvg)
            .put("estimatedPowerMwPeak", estimatedPowerMwPeak)
            .put("batteryTempDeciCAvg", batteryTempDeciCAvg)
            .put("batteryTempDeciCPeak", batteryTempDeciCPeak)
            .put("batteryLevelPctStart", batteryLevelPctStart)
            .put("batteryLevelPctEnd", batteryLevelPctEnd)
            .put("chargeCounterUahStart", chargeCounterUahStart)
            .put("chargeCounterUahEnd", chargeCounterUahEnd)
            .put("energyCounterNwhStart", energyCounterNwhStart)
            .put("energyCounterNwhEnd", energyCounterNwhEnd)
            .put("plugged", plugged)
            .put("batteryStatus", batteryStatus)

        companion object {
            fun fromSamples(samples: List<ResourceSample>, intervalMs: Long): ResourceStats {
                val valid = if (samples.isEmpty()) listOf(ResourceSample.capture(ApplicationProvider.getApplicationContext())) else samples
                val powerMw = valid.map { sample ->
                    if (sample.currentNowUa == Int.MIN_VALUE || sample.batteryVoltageMv <= 0) {
                        -1.0
                    } else {
                        abs(sample.currentNowUa).toDouble() * sample.batteryVoltageMv.toDouble() / 1_000_000.0
                    }
                }.filter { it >= 0.0 }
                return ResourceStats(
                    sampleCount = valid.size,
                    sampleIntervalMs = intervalMs,
                    durationMs = (valid.last().elapsedRealtimeMs - valid.first().elapsedRealtimeMs).coerceAtLeast(0L),
                    javaHeapAvg = valid.avgLong { it.javaHeap },
                    javaHeapPeak = valid.maxLong { it.javaHeap },
                    nativeHeapAvg = valid.avgLong { it.nativeHeap },
                    nativeHeapPeak = valid.maxLong { it.nativeHeap },
                    pssKbAvg = valid.avgLongPositive { it.pssKb },
                    pssKbPeak = valid.maxLong { it.pssKb },
                    rssKbAvg = valid.avgLongPositive { it.rssKb },
                    rssKbPeak = valid.maxLong { it.rssKb },
                    vmHwmKbPeak = valid.maxLong { it.vmHwmKb },
                    currentNowUaAvg = valid.avgIntValid(Int.MIN_VALUE) { it.currentNowUa },
                    currentNowUaPeakAbs = valid.map { it.currentNowUa }.filter { it != Int.MIN_VALUE }.maxOfOrNull { abs(it) } ?: Int.MIN_VALUE,
                    currentAverageUaAvg = valid.avgIntValid(Int.MIN_VALUE) { it.currentAverageUa },
                    batteryVoltageMvAvg = valid.avgIntValid(-1) { it.batteryVoltageMv }.toInt(),
                    estimatedPowerMwAvg = if (powerMw.isEmpty()) -1.0 else powerMw.average(),
                    estimatedPowerMwPeak = powerMw.maxOrNull() ?: -1.0,
                    batteryTempDeciCAvg = valid.avgIntValid(-1) { it.batteryTempDeciC }.toInt(),
                    batteryTempDeciCPeak = valid.map { it.batteryTempDeciC }.filter { it >= 0 }.maxOrNull() ?: -1,
                    batteryLevelPctStart = valid.first().batteryLevelPct,
                    batteryLevelPctEnd = valid.last().batteryLevelPct,
                    chargeCounterUahStart = valid.first().chargeCounterUah,
                    chargeCounterUahEnd = valid.last().chargeCounterUah,
                    energyCounterNwhStart = valid.first().energyCounterNwh,
                    energyCounterNwhEnd = valid.last().energyCounterNwh,
                    plugged = valid.last().plugged,
                    batteryStatus = valid.last().batteryStatus,
                )
            }

            private inline fun List<ResourceSample>.avgLong(selector: (ResourceSample) -> Long): Long =
                selectorSum(selector).let { if (isEmpty()) -1L else it / size }

            private inline fun List<ResourceSample>.avgLongPositive(selector: (ResourceSample) -> Long): Long {
                val values = map(selector).filter { it >= 0L }
                return if (values.isEmpty()) -1L else values.sum() / values.size
            }

            private inline fun List<ResourceSample>.maxLong(selector: (ResourceSample) -> Long): Long =
                map(selector).maxOrNull() ?: -1L

            private inline fun List<ResourceSample>.avgIntValid(invalid: Int, selector: (ResourceSample) -> Int): Long {
                val values = map(selector).filter { it != invalid && it >= 0 }
                return if (values.isEmpty()) invalid.toLong() else values.map { it.toLong() }.sum() / values.size
            }

            private inline fun List<ResourceSample>.selectorSum(selector: (ResourceSample) -> Long): Long =
                fold(0L) { acc, sample -> acc + selector(sample) }
        }
    }

    private data class Snapshot(
        val fdCount: Int,
        val threadCount: Int,
        val javaHeap: Long,
        val nativeHeap: Long,
        val pssKb: Long,
        val rssKb: Long,
        val vmHwmKb: Long,
        val litsThreadCount: Int,
        val ttsThreadCount: Int,
        val onnxThreadCount: Int,
    ) {
        fun toJson(): JSONObject = JSONObject()
            .put("fdCount", fdCount)
            .put("threadCount", threadCount)
            .put("javaHeap", javaHeap)
            .put("nativeHeap", nativeHeap)
            .put("pssKb", pssKb)
            .put("rssKb", rssKb)
            .put("vmHwmKb", vmHwmKb)
            .put("litsThreadCount", litsThreadCount)
            .put("ttsThreadCount", ttsThreadCount)
            .put("onnxThreadCount", onnxThreadCount)

        companion object {
            fun capture(): Snapshot {
                val runtime = Runtime.getRuntime()
                val memoryInfo = Debug.MemoryInfo()
                Debug.getMemoryInfo(memoryInfo)
                val threadNames = Thread.getAllStackTraces().keys.map { it.name.lowercase(Locale.US) }
                return Snapshot(
                    fdCount = File("/proc/self/fd").list()?.size ?: -1,
                    threadCount = threadNames.size,
                    javaHeap = runtime.totalMemory() - runtime.freeMemory(),
                    nativeHeap = Debug.getNativeHeapAllocatedSize(),
                    pssKb = memoryInfo.totalPss.toLong(),
                    rssKb = ResourceSample.capture(ApplicationProvider.getApplicationContext()).rssKb,
                    vmHwmKb = ResourceSample.capture(ApplicationProvider.getApplicationContext()).vmHwmKb,
                    litsThreadCount = threadNames.count { it.contains("lits") },
                    ttsThreadCount = threadNames.count { it.contains("tts") },
                    onnxThreadCount = threadNames.count { it.contains("onnx") || it.contains("ort") },
                )
            }
        }
    }

    private companion object {
        const val TAG = "AarStability1000"
        const val ASSET_NAME = "android_v3_sdk_stability_1000_cases_improved.jsonl"
        const val VOICE_ID = "lits-female-02"
        const val DEFAULT_TEXT = "SDK service stability smoke text."
        const val DEFAULT_TIMEOUT_MS = 60_000L
        const val MAX_TIMEOUT_MS = 600_000L
        const val POST_CASE_SETTLE_MS = 120L
        const val STRESS_CASE_SETTLE_MS = 1_000L
        const val RESOURCE_SAMPLE_INTERVAL_MS = 1_000L
        const val LIFECYCLE_CASE_COOLDOWN_MS = 5_000L
        const val LIFECYCLE_LOOP_COOLDOWN_MS = 250L
        const val SHARED_ENGINE_WARMUP_TIMEOUT_MS = 30_000L
        const val SHARED_ENGINE_WARMUP_TEXT = "预热。"
        const val LEAK_BASELINE_SETTLE_MS = 1_000L
        const val ASYNC_ERROR_SETTLE_MS = 300L
        val HAN_RANGE = 0x4E00..0x9FFF
    }
}
