package com.amphion.dingqiao.demo

import android.app.KeyguardManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Handler
import android.os.PowerManager
import android.os.Process
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.asr.AmphionRuntime
import com.amphion.asr.AsrCallback
import com.amphion.asr.AsrConfig
import com.amphion.asr.AsrError
import com.amphion.asr.AsrLanguage
import com.amphion.asr.AsrResult
import com.amphion.asr.AsrSession
import com.amphion.asr.EndpointRules
import com.amphion.asr.VadConfig
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.DingqiaoEventCode
import com.amphion.dingqiao.DingqiaoOnlineMode
import com.amphion.dingqiao.RecognitionListener
import com.amphion.dingqiao.SpeechRecognitionEngine
import com.amphion.dingqiao.SpeechRecognitionResult
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.StartParams
import com.k2fsa.sherpa.onnx.OnlineRecognizer
import java.io.File
import java.io.RandomAccessFile
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference
import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Explicit, streaming, real-time PCM qualification. A pass is not thermal or recognition acceptance. */
@RunWith(AndroidJUnit4::class)
class EncoderIdleGateThermalInstrumentedTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext

    @Test fun pacedPrivatePcmQualification() {
        val args = InstrumentationRegistry.getArguments()
        assumeTrue("thermalPcmPath is required", args.containsKey("thermalPcmPath"))
        fun number(name: String, default: Long) = args.getString(name)?.toLong() ?: default
        fun flag(name: String, default: Boolean) = when (args.getString(name) ?: default.toString()) {
            "true" -> true
            "false" -> false
            else -> error("invalid boolean argument")
        }
        val pcm = File(requireNotNull(args.getString("thermalPcmPath"))).canonicalFile
        require(pcm.path.startsWith(context.filesDir.canonicalPath + File.separator)) {
            "PCM must be inside the target app's private files directory"
        }
        val startSample = number("thermalStartSample", 0)
        val sampleCount = requireNotNull(args.getString("thermalSampleCount")).toLong()
        val mode = args.getString("thermalMode") ?: "qualification"
        require(mode == "qualification" || mode == "measurement")
        val maxSamples = SR * if (mode == "qualification") 300L else 3600L
        require(startSample >= 0 && sampleCount in 1..maxSamples)
        require(pcm.isFile && pcm.length() % 2 == 0L)
        require(startSample <= pcm.length() / 2 && sampleCount <= pcm.length() / 2 - startSample)
        val gate = when (args.getString("thermalGate") ?: "on") {
            "on" -> true
            "off" -> false
            else -> error("thermalGate must be on or off")
        }
        val backend = args.getString("thermalBackend") ?: "sdk"
        require(backend == "sdk" || backend == "dingqiao")
        // Non-default thread counts are only for explicit diagnostic arms; the product
        // configuration keeps the 2-thread Dingqiao default.
        val allowNonDefaultThreads = flag("thermalAllowNonDefaultThreads", false)
        val threads = number("thermalThreads", 2).also { require(it in 1..4) }.toInt()
        if (backend == "dingqiao") {
            require(threads == 2 || allowNonDefaultThreads) {
                "dingqiao requires its default 2 threads unless thermalAllowNonDefaultThreads=true"
            }
            require(sampleCount % FRAME == 0L) { "dingqiao requires complete 320-sample frames" }
        }
        val expectedUsb = number("thermalExpectedUsb", 0).also { require(it in 0..1) }.toInt()
        val requireLocked = flag("thermalRequireLocked", true)
        val requireSpeech = flag("thermalRequireSpeech", true)
        val readySeconds = number("thermalReadyDelaySeconds", 30).also { require(it in 0..120) }
        val maxLagMs = number("thermalMaxLagMs", 10_000).also { require(it in 1_000..30_000) }
        val maxFeedLagMs = number("thermalMaxFeedLagMs", 1_000).also { require(it in 100..5_000) }
        val expectedHash = args.getString("thermalExpectedPcmSha256")?.lowercase()?.also {
            require(it.matches(Regex("[0-9a-f]{64}")))
        }
        val runId = args.getString("thermalRunId") ?: "${System.currentTimeMillis()}-${UUID.randomUUID()}"
        require(runId.matches(Regex("[A-Za-z0-9][A-Za-z0-9._-]{0,95}")))
        val root = File(requireNotNull(context.getExternalFilesDir(null)), "thermal_qualification")
        val dir = File(root, runId)
        check(!dir.exists() && dir.mkdirs()) { "run output exists or cannot be created" }
        val report = Report(dir, runId, backend)
        val capture = Capture()
        var lease: ThermalQualificationService.Lease? = null
        var monitor: Monitor? = null
        var success = false
        var stage = "preparing"
        var failureClass = ""
        var failureStage = ""
        var knownFailureReason = ""
        val cleanupFailures = mutableListOf<String>()
        var inputHash = ""
        var drainMs = -1L
        var wasInterrupted = false
        val targetNs = sampleCount * 1_000_000_000L / SR
        try {
            report.emit("preparing", mapOf("mode" to mode, "gate" to gate, "threads" to threads,
                "startSample" to startSample, "sampleCount" to sampleCount,
                "sampleRate" to SR, "pcmEncoding" to "s16le_mono", "frameSamples" to FRAME,
                "expectedUsb" to expectedUsb, "requireScreenOff" to requireLocked,
                "requireSpeech" to requireSpeech, "readyDelaySeconds" to readySeconds,
                "maxLagMs" to maxLagMs, "maxFeedLagMs" to maxFeedLagMs,
                "diarization" to false, "targetSpeaker" to false, "punctuation" to (backend == "dingqiao"),
                "itn" to (backend == "dingqiao"), "vadEndMs" to 800, "rule3Seconds" to -1,
                "recognizerMode" to "long", "hotwordsSource" to if (backend == "dingqiao") "public_defaults" else "none",
                "pid" to Process.myPid(), "cpuPercentOneCore" to 100,
                "processedMeaning" to "source_samples_observed_on_decoder_or_after_decoder_join_including_idle",
                "maxDecodeDurationAvailable" to false))
            val activeLease = ThermalQualificationService.acquire(context, targetNs / 1_000_000 + 480_000)
            lease = activeLease
            stage = "runtime_prepare"
            val runtimeWork = File(context.filesDir, "encoder_idle_thermal_runtime" +
                if (backend == "dingqiao") "/$runId" else "")
            if (backend == "dingqiao") check(!runtimeWork.exists())
            prepareSdkRuntime(context, runtimeWork)
            stage = "engine_and_session_create"
            openBackend(backend, threads, capture).use { inputBackend ->
                inputBackend.session.let { session ->
                    activeLease.setCancellationAction { inputBackend.cancel() }
                    stage = "probe_setup"
                    val probe = DecoderProbe(session)
                    probe.initialize(gate)
                    report.emit("effective_configuration", probe.configuration(backend, threads))
                    stage = "session_start"
                    check(capture.started.await(10, TimeUnit.SECONDS) && capture.errorCount.get() == 0L)
                    stage = "readiness"
                    report.emit("ready", emptyMap())
                    File(dir, "READY").writeText("${SystemClock.elapsedRealtime()}\n")
                    waitReady(activeLease, expectedUsb, requireLocked, readySeconds * 1000, report)
                    val t0 = SystemClock.elapsedRealtimeNanos()
                    val cpu0 = Process.getElapsedCpuTime()
                    File(dir, "STARTED").writeText("${t0 / 1_000_000}\n")
                    val running = Monitor(context, inputBackend::cancel, probe, capture, activeLease, report,
                        sampleCount, t0, cpu0, expectedUsb, requireLocked, maxLagMs)
                    monitor = running
                    try {
                        stage = "feeding"
                        running.start()
                        val digest = MessageDigest.getInstance("SHA-256")
                        val bytes = ByteArray(FRAME * 2)
                        val fullFrame = ShortArray(FRAME)
                        RandomAccessFile(pcm, "r").use { input ->
                            input.seek(startSample * 2)
                            while (running.submitted.get() < sampleCount) {
                                running.checkHealthy()
                                val sent = running.submitted.get()
                                val dueNs = t0 + sent * 1_000_000_000L / SR
                                waitUntil(dueNs, running::checkHealthy)
                                val lateMs = ((SystemClock.elapsedRealtimeNanos() - dueNs) / 1_000_000)
                                    .coerceAtLeast(0)
                                running.maxFeedLag.updateAndGet { maxOf(it, lateMs) }
                                if (lateMs > maxFeedLagMs) running.fail("feed_clock_late")
                                running.checkHealthy()
                                val n = minOf(FRAME.toLong(), sampleCount - sent).toInt()
                                input.readFully(bytes, 0, n * 2)
                                digest.update(bytes, 0, n * 2)
                                val samples = if (n == FRAME) fullFrame else ShortArray(n)
                                if (backend == "sdk") for (i in 0 until n) {
                                    samples[i] = ((bytes[i * 2].toInt() and 255) or
                                        ((bytes[i * 2 + 1].toInt() and 255) shl 8)).toShort()
                                }
                                val before = SystemClock.elapsedRealtimeNanos()
                                inputBackend.write(bytes, samples)
                                running.maxAcceptCall.updateAndGet {
                                    maxOf(it, (SystemClock.elapsedRealtimeNanos() - before) / 1_000_000)
                                }
                                running.submitted.addAndGet(n.toLong())
                                running.checkHealthy()
                            }
                        }
                        // Preserve the exact duration of the final partial frame; no padding or loop.
                        waitUntil(t0 + targetNs, running::checkHealthy)
                        val finishLateMs = ((SystemClock.elapsedRealtimeNanos() - t0 - targetNs) / 1_000_000)
                            .coerceAtLeast(0)
                        running.maxFeedLag.updateAndGet { maxOf(it, finishLateMs) }
                        if (finishLateMs > maxFeedLagMs) running.fail("feed_window_late")
                        running.checkHealthy()
                        inputHash = hex(digest.digest())
                        check(expectedHash == null || inputHash == expectedHash) { "input_hash_mismatch" }
                        stage = "draining"
                        running.markDraining()
                        val stopAt = SystemClock.elapsedRealtime()
                        if (backend == "dingqiao") probe.pausePeriodic()
                        capture.finishRequested.set(true)
                        inputBackend.finish()
                        while (!capture.stopped.await(100, TimeUnit.MILLISECONDS)) {
                            running.checkHealthy()
                            check(SystemClock.elapsedRealtime() - stopAt <= 30_000) { "terminal_timeout" }
                        }
                        drainMs = SystemClock.elapsedRealtime() - stopAt
                        if (backend == "dingqiao") probe.afterDecoderClosed(10_000)
                        else probe.synchronize(10_000)
                        running.checkHealthy()
                        running.emitProgress("input_complete")
                        check(running.submitted.get() == sampleCount)
                        check(probe.acceptedSamples() == sampleCount)
                        check(probe.latest.get().processedSamples == sampleCount)
                        capture.assertTerminal(requireSpeech)
                    } finally {
                        // Kotlin use still closes session/engine even if monitor cleanup fails.
                        running.close()
                    }
                }
            }
            stage = "sdk_closed"
            capture.assertTerminal(requireSpeech)
            success = true
        } catch (failure: Throwable) {
            // No exception messages/causes, SDK output text, license contents, or customer text.
            failureClass = failure.javaClass.simpleName
            failureStage = stage
            knownFailureReason = failure.message?.takeIf { it in setOf("input_hash_mismatch",
                "terminal_timeout", "speech_not_observed", "ready_conditions_timeout",
                "monitor_cleanup_timeout", "decoder_join_timeout") } ?: ""
            wasInterrupted = failure is InterruptedException || Thread.currentThread().isInterrupted
        } finally {
            wasInterrupted = Thread.interrupted() || wasInterrupted
            fun cleanup(action: () -> Unit) {
                try { action() } catch (failure: Throwable) {
                    success = false
                    cleanupFailures += failure.javaClass.simpleName
                    if (failureClass.isEmpty()) {
                        failureClass = failure.javaClass.simpleName
                        failureStage = "cleanup"
                    }
                    wasInterrupted = Thread.interrupted() || failure is InterruptedException || wasInterrupted
                }
            }
            cleanup { monitor?.close() }
            cleanup { lease?.close() }
            if (lease?.cancellation != null || monitor?.failure?.get() != null) success = false
            try {
                report.emit("result", capture.summary() + mapOf(
                    "status" to if (success) "PASS_PROCESSING_ONLY" else "FAIL",
                    "failureClass" to failureClass, "failureStage" to failureStage,
                    "failureReason" to (monitor?.failure?.get() ?: lease?.cancellation ?: knownFailureReason),
                    "cleanupFailures" to cleanupFailures.joinToString(","),
                    "serviceCancellation" to lease?.cancellation,
                    "inputPcmSha256" to inputHash, "finalTextSha256" to capture.finalTextHash(),
                    "drainMs" to drainMs, "thermalAcceptance" to false,
                    "serviceReleased" to (lease?.isReleased == true),
                    "serviceCleanupFailure" to lease?.cleanupFailure,
                    "monitorTerminated" to (monitor?.isTerminated ?: true)))
                File(dir, "DONE").writeText(if (success) "PASS_PROCESSING_ONLY\n" else "FAIL\n")
            } finally {
                if (wasInterrupted) Thread.currentThread().interrupt()
            }
        }
        assertTrue("processing qualification failed; inspect this run's sanitized report", success)
    }

    private fun openBackend(backend: String, threads: Int, capture: Capture): InputBackend {
        if (backend == "sdk") {
            val config = AsrConfig.Builder().numThreads(threads).punctuation(false).itn(false)
                .targetSpeaker(null).vad(true).endpoint(true)
                .vadConfig(VadConfig(activeEndpointSilenceMs = 800))
                .endpointRules(EndpointRules(rule3MinUtteranceLengthSec = -1f)).build()
            val engine = AmphionRuntime.create(context, AsrLanguage.ZH_EN, config)
            try {
                return InputBackend(engine.newSession(capture), null, "", engine::close)
            } catch (failure: Throwable) {
                try { engine.close() } catch (cleanup: Throwable) { failure.addSuppressed(cleanup) }
                throw failure
            }
        }
        // Keep the public defaults: full preset hotwords/beam, punctuation, ITN, and two threads.
        val engine = SpeechRecognizeSdk.createEngine(CreateEngineParams(
            language = "zh-CN", online = DingqiaoOnlineMode.OFFLINE,
            extraParams = mapOf("recognizerMode" to "long")))
        val sessionId = "thermal-${UUID.randomUUID()}"
        try {
            engine.setListener(capture.dingqiaoListener(sessionId))
            engine.startListening(StartParams(sessionId = sessionId, extraParams = mapOf(
                "recognizerMode" to "long", "vadEnd" to 800,
                "enableVoiceprintVerification" to false, "enableSpeakerVad" to false)))
            // Retain this exact session: the wrapper clears its field before public terminal callbacks.
            val session = field(engine, "session") as AsrSession
            return InputBackend(session, engine, sessionId, engine::shutdown)
        } catch (failure: Throwable) {
            try {
                if (engine.isBusy()) engine.cancel(sessionId)
            } catch (cleanup: Throwable) { failure.addSuppressed(cleanup) }
            try { engine.shutdown() } catch (cleanup: Throwable) { failure.addSuppressed(cleanup) }
            throw failure
        }
    }

    private class InputBackend(val session: AsrSession, private val publicEngine: SpeechRecognitionEngine?,
        private val sessionId: String, private val releaseEngine: () -> Unit) : AutoCloseable {
        private val cancelling = AtomicBoolean(false)
        private val writing = AtomicBoolean(false)
        fun write(bytes: ByteArray, samples: ShortArray) {
            writing.set(true)
            try {
                check(!cancelling.get())
                if (publicEngine == null) session.acceptPcmShort(samples)
                else publicEngine.writeAudio(sessionId, bytes)
            } finally { writing.set(false) }
        }
        fun finish() {
            check(!cancelling.get())
            if (publicEngine == null) session.stop() else publicEngine.finish(sessionId)
        }
        fun cancel() {
            if (!cancelling.compareAndSet(false, true)) return
            if (publicEngine == null) {
                session.close()
            } else {
                // writeAudio holds the wrapper monitor while reserving PCM. A blocked writer
                // must be released before public cancel can acquire that monitor. Publishing
                // cancelling before reading writing also prevents a later writer entering.
                try { if (writing.get()) session.close() }
                finally { if (publicEngine.isBusy()) publicEngine.cancel(sessionId) }
            }
        }
        override fun close() {
            try {
                if (publicEngine == null) session.close()
                else if (publicEngine.isBusy()) cancel()
            } finally { releaseEngine() }
        }
    }

    private fun waitReady(lease: ThermalQualificationService.Lease, usb: Int, locked: Boolean,
        delayMs: Long, report: Report) {
        val start = SystemClock.elapsedRealtime()
        var matches = 0
        var nextReport = start
        while (SystemClock.elapsedRealtime() - start <= delayMs + 120_000) {
            check(lease.cancellation == null && !File(report.dir, "ABORT").exists())
            val state = deviceState(context)
            val now = SystemClock.elapsedRealtime()
            if (now >= nextReport) {
                report.emit("ready_wait", state)
                nextReport = now + 10_000
            }
            val eligible = now - start >= delayMs && powerMatches(state, usb) &&
                (!locked || state["interactive"] == false) &&
                (usb != 0 || state["batteryPlugged"] == 0) && state["batteryTemperatureValid"] == true
            matches = if (eligible) matches + 1 else 0
            if (matches >= 3) {
                // Re-check after the binder/sysfs reads and report write so a slow sample cannot
                // turn a lapsed window into a pass; the window itself is unchanged.
                check(SystemClock.elapsedRealtime() - start <= delayMs + 120_000) {
                    "ready_conditions_timeout"
                }
                return
            }
            Thread.sleep(1000)
        }
        error("ready_conditions_timeout")
    }

    private class Report(val dir: File, private val runId: String, private val backend: String) {
        @Synchronized fun emit(event: String, fields: Map<String, Any?>) {
            val json = JSONObject().put("event", event).put("runId", runId).put("backend", backend)
                .put("elapsedRealtimeMs", SystemClock.elapsedRealtime()).put("epochMs", System.currentTimeMillis())
                // elapsedRealtime includes suspend while uptimeMillis does not; the gap separates
                // system suspend from an application-side stall without changing any condition.
                .put("uptimeMillis", SystemClock.uptimeMillis())
            fields.forEach { (key, value) -> json.put(key, value ?: JSONObject.NULL) }
            File(dir, "report.jsonl").appendText(json.toString() + "\n")
        }
    }

    private data class Snapshot(val processedSamples: Long = 0, val observedMs: Long = 0,
        val barrierDelayMs: Long = 0, val idleSamples: Long = 0, val idleEntries: Long = 0,
        val resumes: Long = 0, val source: String = "none")

    /** Non-atomic fields are read on the decoder, or after joining its terminated thread. */
    private class DecoderProbe(session: AsrSession) {
        private val impl = field(session, "impl")!!
        private val handler = field(impl, "decoderHandler") as Handler
        private val acceptedBytes = field(field(impl, "metrics")!!, "totalPcmBytes") as AtomicLong
        private val periodicPending = AtomicBoolean(false)
        private var periodicPaused = false
        val latest = AtomicReference(Snapshot())
        val failure = AtomicReference<String?>(null)
        val maxBarrierDelay = AtomicLong()
        val decoderJoinMs = AtomicLong(-1)
        fun acceptedSamples() = acceptedBytes.get() / 2
        fun configuration(backend: String, threads: Int): Map<String, Any?> {
            val config = field(field(impl, "engineImpl")!!, "config") as AsrConfig
            val native = (field(impl, "recognizer") as OnlineRecognizer).config
            check(config.numThreads == threads && native.modelConfig.numThreads == threads)
            check(config.targetSpeaker == null && config.vad && config.endpoint)
            check(config.punctuation == (backend == "dingqiao") && config.itn == (backend == "dingqiao"))
            check(config.vadConfig.activeEndpointSilenceMs == 800 && config.endpointRules.rule3MinUtteranceLengthSec < 0f)
            check(backend != "dingqiao" || config.hotwords.isNotEmpty())
            return mapOf("threads" to config.numThreads, "nativeThreads" to native.modelConfig.numThreads,
                "punctuation" to config.punctuation, "itn" to config.itn, "targetSpeaker" to false,
                "diarization" to false, "vadEndMs" to config.vadConfig.activeEndpointSilenceMs,
                "rule3Seconds" to config.endpointRules.rule3MinUtteranceLengthSec,
                "disablePrepack" to config.disablePrepack, "hotwordsCount" to config.hotwords.size,
                "hotwordsSha256" to hex(MessageDigest.getInstance("SHA-256")
                    .digest(config.hotwords.joinToString("\n").toByteArray(Charsets.UTF_8))),
                "hotwordsScore" to config.hotwordsScore, "decodingMethod" to native.decodingMethod,
                "maxActivePaths" to native.maxActivePaths)
        }
        fun initialize(gateEnabled: Boolean) {
            val done = CountDownLatch(1)
            check(handler.post {
                try {
                    check(field(impl, "publicSamplesFed") == 0L)
                    check(field(impl, "encoderIdleGate") != null)
                    if (!gateEnabled) impl.javaClass.getDeclaredField("encoderIdleGate")
                        .apply { isAccessible = true }.set(impl, null)
                } catch (_: Throwable) { failure.set("probe_setup_failed") }
                finally { done.countDown() }
            })
            check(done.await(10, TimeUnit.SECONDS) && failure.get() == null)
            synchronize(10_000)
        }
        private fun snapshot(delayMs: Long, source: String): Snapshot {
            val gate = field(impl, "encoderIdleGate")
            fun metric(name: String): Long = if (gate == null) 0 else
                (gate.javaClass.getMethod("get$name").invoke(gate) as Number).toLong()
            return Snapshot(field(impl, "publicSamplesFed") as Long, SystemClock.elapsedRealtime(), delayMs,
                metric("IdleSamples"), metric("IdleEntries"), metric("Resumes"), source)
        }
        @Synchronized fun pausePeriodic() { periodicPaused = true }
        @Synchronized fun request(done: CountDownLatch? = null) {
            // At most one periodic probe plus one explicit setup/final synchronization barrier.
            val periodic = done == null
            if (periodic && (periodicPaused || !periodicPending.compareAndSet(false, true))) return
            val requested = SystemClock.elapsedRealtime()
            if (!handler.post {
                try {
                    val delay = SystemClock.elapsedRealtime() - requested
                    latest.set(snapshot(delay, "decoder_queue_barrier"))
                    maxBarrierDelay.updateAndGet { maxOf(it, delay) }
                } catch (_: Throwable) { failure.compareAndSet(null, "probe_read_failed") }
                finally {
                    if (periodic) periodicPending.set(false)
                    done?.countDown()
                }
            }) {
                if (periodic) periodicPending.set(false)
                failure.compareAndSet(null, "probe_queue_closed")
                done?.countDown()
            }
        }
        fun synchronize(timeoutMs: Long) {
            val done = CountDownLatch(1)
            request(done)
            check(done.await(timeoutMs, TimeUnit.MILLISECONDS) && failure.get() == null)
        }
        fun afterDecoderClosed(timeoutMs: Long) {
            // Dingqiao closes the session before public last/complete. join establishes visibility
            // of all decoder writes, including AGC's stop flush, without posting to a closed queue.
            val start = SystemClock.elapsedRealtime()
            val thread = handler.looper.thread
            thread.join(timeoutMs)
            decoderJoinMs.set(SystemClock.elapsedRealtime() - start)
            check(!thread.isAlive) { "decoder_join_timeout" }
            check(failure.get() == null)
            latest.set(snapshot(0, "decoder_thread_join"))
        }
    }

    private class Monitor(
        private val context: Context, private val cancelInput: () -> Unit, private val probe: DecoderProbe,
        private val capture: Capture, private val lease: ThermalQualificationService.Lease,
        private val report: Report, private val targetSamples: Long, private val t0Ns: Long,
        private val cpu0: Long, private val expectedUsb: Int, private val requireLocked: Boolean,
        private val maxLagMs: Long,
    ) : AutoCloseable {
        val submitted = AtomicLong()
        val maxFeedLag = AtomicLong()
        val maxAcceptCall = AtomicLong()
        val failure = AtomicReference<String?>(null)
        private val executor = Executors.newSingleThreadScheduledExecutor { work ->
            Thread(work, "thermal-qualification-monitor").apply { isDaemon = true }
        }
        private val closed = AtomicBoolean(false)
        private val maxProgressLag = AtomicLong()
        private val maxBacklog = AtomicLong()
        private val maxMonitorGap = AtomicLong()
        private val t0Ms = t0Ns / 1_000_000
        private var previousTick = t0Ms
        private var nextReport = t0Ms
        private var previousReportMs = t0Ms
        private var previousReportCpu = cpu0
        @Volatile private var tailBacklogUpperBound = -1L
        @Volatile private var tailSnapshotAgeMs = -1L
        @Volatile private var phase = "feeding"
        val isTerminated: Boolean get() = executor.isTerminated
        fun start() { executor.scheduleAtFixedRate({ tick() }, 0, 1, TimeUnit.SECONDS) }
        fun markDraining() {
            val snapshot = probe.latest.get()
            tailBacklogUpperBound = (probe.acceptedSamples() - snapshot.processedSamples).coerceAtLeast(0)
            tailSnapshotAgeMs = SystemClock.elapsedRealtime() - snapshot.observedMs
            phase = "draining"
        }
        private fun tick() {
            if (closed.get() || failure.get() != null) return
            try {
                val now = SystemClock.elapsedRealtime()
                val gapMs = now - previousTick
                maxMonitorGap.updateAndGet { maxOf(it, gapMs) }
                previousTick = now
                probe.request()
                val snapshot = probe.latest.get()
                val expected = minOf(targetSamples, (now - t0Ms).coerceAtLeast(0) * SR / 1000)
                val lagMs = (expected - snapshot.processedSamples).coerceAtLeast(0) * 1000 / SR
                maxProgressLag.updateAndGet { maxOf(it, lagMs) }
                maxBacklog.updateAndGet { maxOf(it, (probe.acceptedSamples() - snapshot.processedSamples).coerceAtLeast(0)) }
                val device = deviceState(context)
                when {
                    lease.cancellation != null -> fail("service_cancelled")
                    File(report.dir, "ABORT").exists() -> fail("collector_abort")
                    capture.errorCount.get() > 0 -> fail("sdk_error")
                    capture.contractFailure.get() != null -> fail(capture.contractFailure.get()!!)
                    probe.failure.get() != null -> fail(probe.failure.get()!!)
                    !powerMatches(device, expectedUsb) -> fail("usb_condition_mismatch_or_unreadable")
                    expectedUsb == 0 && device["batteryPlugged"] != 0 -> fail("external_power_present")
                    requireLocked && device["interactive"] != false -> fail("screen_became_interactive")
                    device["batteryTemperatureValid"] != true -> fail("invalid_battery_temperature")
                    gapMs > maxLagMs -> fail("monitor_observation_gap")
                    lagMs > maxLagMs -> fail("processed_progress_lag")
                    now - t0Ms > targetSamples * 1000 / SR + 30_000 -> fail("run_deadline")
                }
                if (now >= nextReport) {
                    emitProgress("progress")
                    nextReport = now + 10_000
                }
            } catch (_: Throwable) { fail("monitor_failed") }
        }
        fun fail(reason: String) {
            if (failure.compareAndSet(null, reason)) {
                // The backend releases blocked PCM reservation before public cancellation.
                try { cancelInput() } catch (_: Throwable) { /* Main use/finally retries cleanup. */ }
                try { report.emit("abort", mapOf("reason" to reason)) } catch (_: Throwable) { }
            }
        }
        fun checkHealthy() {
            check(failure.get() == null && lease.cancellation == null && !Thread.currentThread().isInterrupted)
        }
        @Synchronized fun emitProgress(event: String) {
            val now = SystemClock.elapsedRealtime()
            val cpu = Process.getElapsedCpuTime()
            val snapshot = probe.latest.get()
            val expected = minOf(targetSamples, (now - t0Ms).coerceAtLeast(0) * SR / 1000)
            val deltaWall = (now - previousReportMs).coerceAtLeast(1)
            report.emit(event, capture.summary() + deviceState(context) + mapOf(
                "phase" to phase, "wallMs" to now - t0Ms, "cpuMs" to cpu - cpu0,
                "cpuPercentSincePreviousReport" to (100.0 * (cpu - previousReportCpu) / deltaWall),
                "expectedSamples" to expected, "submittedSamples" to submitted.get(),
                "acceptedSamples" to probe.acceptedSamples(), "processedSamples" to snapshot.processedSamples,
                "processedObservedMs" to snapshot.observedMs, "processedSnapshotAgeMs" to now - snapshot.observedMs,
                "progressLagUpperBoundMs" to ((expected - snapshot.processedSamples).coerceAtLeast(0) * 1000 / SR),
                "backlogUpperBoundSamples" to (probe.acceptedSamples() - snapshot.processedSamples).coerceAtLeast(0),
                "maxProgressLagUpperBoundMs" to maxProgressLag.get(), "maxBacklogUpperBoundSamples" to maxBacklog.get(),
                "barrierDelayMs" to snapshot.barrierDelayMs, "maxBarrierDelayMs" to probe.maxBarrierDelay.get(),
                "processedSnapshotSource" to snapshot.source, "decoderJoinMs" to probe.decoderJoinMs.get(),
                "maxFeedLagMs" to maxFeedLag.get(), "maxAcceptCallMs" to maxAcceptCall.get(),
                "maxMonitorGapMs" to maxMonitorGap.get(),
                "tailBacklogUpperBoundSamples" to tailBacklogUpperBound, "tailSnapshotAgeMs" to tailSnapshotAgeMs,
                "idleSamplesGross" to snapshot.idleSamples, "idleEntries" to snapshot.idleEntries,
                "resumes" to snapshot.resumes,
                "gateTransitionsCovered" to (snapshot.idleEntries > 0 && snapshot.resumes > 0),
                "failureReason" to (failure.get() ?: "")))
            previousReportMs = now
            previousReportCpu = cpu
        }
        override fun close() {
            if (closed.compareAndSet(false, true)) {
                executor.shutdownNow()
                if (!executor.awaitTermination(5, TimeUnit.SECONDS)) {
                    failure.compareAndSet(null, "monitor_cleanup_timeout")
                    error("monitor_cleanup_timeout")
                }
            }
        }
    }

    private class Capture : AsrCallback {
        val started = CountDownLatch(1)
        val stopped = CountDownLatch(1)
        val errorCount = AtomicLong()
        val finishRequested = AtomicBoolean(false)
        val contractFailure = AtomicReference<String?>(null)
        private val partials = AtomicLong()
        private val endpoints = AtomicLong()
        private val lastCallbackMs = AtomicLong()
        private val digest = MessageDigest.getInstance("SHA-256")
        private var starts = 0
        private var finals = 0
        private var lasts = 0
        private var stops = 0
        private var textChars = 0L
        private var ordered = true
        private var lastFinalHash = ""
        private var lastErrorCode = 0
        private var completedHash: String? = null
        fun dingqiaoListener(expectedSessionId: String): RecognitionListener = object : RecognitionListener {
            private fun owns(sessionId: String): Boolean {
                if (sessionId == expectedSessionId) return true
                contractFailure.compareAndSet(null, "callback_session_mismatch")
                return false
            }
            override fun onStart(sessionId: String, eventMessage: String) {
                if (owns(sessionId)) onSessionStarted()
            }
            override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) {
                if (owns(sessionId) && eventCode == DingqiaoEventCode.SPEECH_END) onEndpoint()
            }
            override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
                if (!owns(sessionId)) return
                if (result.isFinal) recordFinal(result.result, result.isLast)
                else {
                    if (result.isLast) contractFailure.compareAndSet(null, "non_final_last")
                    onPartial(result.result)
                }
            }
            override fun onComplete(sessionId: String, eventMessage: String) {
                if (owns(sessionId)) onSessionStopped()
            }
            override fun onError(sessionId: String, errorCode: Int, errorMessage: String) {
                if (owns(sessionId)) recordError(errorCode)
            }
        }
        @Synchronized override fun onSessionStarted() {
            starts++
            lastCallbackMs.set(SystemClock.elapsedRealtime())
            started.countDown()
        }
        override fun onPartial(text: String) {
            partials.incrementAndGet()
            lastCallbackMs.set(SystemClock.elapsedRealtime())
        }
        override fun onEndpoint() {
            endpoints.incrementAndGet()
            lastCallbackMs.set(SystemClock.elapsedRealtime())
        }
        override fun onFinal(result: AsrResult) { recordFinal(result.text, result.isLast) }
        @Synchronized private fun recordFinal(text: String, isLast: Boolean) {
            if (lasts != 0 || stops != 0 || completedHash != null) ordered = false
            if (isLast && !finishRequested.get()) contractFailure.compareAndSet(null, "last_before_finish")
            finals++
            if (isLast) lasts++
            val bytes = text.toByteArray(Charsets.UTF_8)
            digest.update(bytes)
            textChars += text.length
            lastFinalHash = hex(MessageDigest.getInstance("SHA-256").digest(bytes))
            lastCallbackMs.set(SystemClock.elapsedRealtime())
        }
        override fun onError(error: AsrError) { recordError(error.code) }
        @Synchronized private fun recordError(code: Int) {
            errorCount.incrementAndGet()
            lastErrorCode = code
            lastCallbackMs.set(SystemClock.elapsedRealtime())
        }
        @Synchronized override fun onSessionStopped() {
            if (lasts != 1 || stops != 0) ordered = false
            if (!finishRequested.get()) contractFailure.compareAndSet(null, "complete_before_finish")
            stops++
            lastCallbackMs.set(SystemClock.elapsedRealtime())
            stopped.countDown()
        }
        @Synchronized fun assertTerminal(requireSpeech: Boolean) {
            check(starts == 1 && lasts == 1 && stops == 1 && ordered && errorCount.get() == 0L && contractFailure.get() == null)
            check(!requireSpeech || textChars > 0) { "speech_not_observed" }
        }
        @Synchronized fun summary(): Map<String, Any?> = mapOf(
            "starts" to starts, "partials" to partials.get(), "endpoints" to endpoints.get(),
            "finals" to finals, "lasts" to lasts, "stops" to stops,
            "errors" to errorCount.get(), "lastErrorCode" to lastErrorCode,
            "callbackOrderValid" to (ordered && contractFailure.get() == null),
            "callbackContractFailure" to contractFailure.get(), "finishRequested" to finishRequested.get(),
            "finalTextUtf16Units" to textChars,
            "lastFinalTextSha256" to lastFinalHash, "lastCallbackElapsedMs" to lastCallbackMs.get())
        @Synchronized fun finalTextHash(): String = completedHash ?: hex(digest.digest()).also { completedHash = it }
    }

    companion object {
        private const val SR = 16_000L
        private const val FRAME = 320
        private fun field(owner: Any, name: String): Any? = owner.javaClass.getDeclaredField(name)
            .apply { isAccessible = true }.get(owner)
        private fun hex(bytes: ByteArray) = bytes.joinToString("") { "%02x".format(it.toInt() and 255) }
        private fun waitUntil(deadlineNs: Long, check: () -> Unit) {
            while (true) {
                check()
                val remaining = deadlineNs - SystemClock.elapsedRealtimeNanos()
                if (remaining <= 0) return
                val sleep = minOf(remaining, 100_000_000L)
                Thread.sleep(sleep / 1_000_000, (sleep % 1_000_000).toInt())
            }
        }
        /**
         * Power-supply match for qualification. Some ROMs (for example EMUI 14) do not expose
         * `/sys/class/power_supply/usb/online`; there the battery callback is the only source, so
         * fall back to EXTRA_PLUGGED instead of failing every readiness sample on a null node.
         */
        private fun powerMatches(state: Map<String, Any?>, expectedUsb: Int): Boolean {
            val online = state["usbOnline"] as? Int
            if (online != null) return online == expectedUsb
            val plugged = (state["batteryPlugged"] as? Int) ?: -1
            if (plugged < 0) return false
            return (plugged != 0) == (expectedUsb != 0)
        }

        private fun deviceState(context: Context): Map<String, Any?> {
            val battery = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            val power = context.getSystemService(PowerManager::class.java)
            val temperature = battery?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1) ?: -1
            return mapOf(
                "usbOnline" to runCatching { File("/sys/class/power_supply/usb/online").readText().trim().toInt() }.getOrNull(),
                "interactive" to power.isInteractive,
                "keyguardLocked" to context.getSystemService(KeyguardManager::class.java).isKeyguardLocked,
                "batteryPlugged" to (battery?.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1) ?: -1),
                "batteryLevel" to (battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1),
                "batteryTemperatureDeciC" to temperature, "batteryTemperatureValid" to (temperature in 1..800),
                "thermalStatus" to if (android.os.Build.VERSION.SDK_INT >= 29) power.currentThermalStatus else -1)
        }
    }
}
