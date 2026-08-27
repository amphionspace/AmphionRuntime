package com.amphion.dingqiao

import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Locale
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import com.amphion.asr.AmphionRuntime

/** Compile-time diagnostics collector. Normal debug/release builds retain no session data. */
internal object DiagnosticsModule {
    private const val SAMPLE_RATE = 16_000
    private const val MAX_AUDIO_BYTES = 300 * SAMPLE_RATE * 2
    private const val MAX_EVENTS = 512
    private const val MAX_RETAINED_RUNS = 3
    private const val MAX_DIRECTORY_BYTES = 200L * 1024L * 1024L
    private const val JOURNAL_INTERVAL_MS = 5_000L

    private data class Event(
        val sequence: Long,
        val wallTimeMs: Long,
        val monotonicTimeNs: Long,
        val publicSessionId: String,
        val thread: String,
        val name: String,
        val fields: Map<String, Any?>,
    )

    private data class AudioChunk(var pcm: ByteArray, val wallTimeMs: Long)

    private data class AudioSnapshot(
        val pcm: ByteArray,
        val totalInputBytes: Long,
        val frames: Long,
        val firstFrameTimeMs: Long,
        val lastFrameTimeMs: Long,
        val maxFrameGapMs: Long,
        val rms: Double,
        val peak: Double,
        val clipRate: Double,
        val rollingDroppedBytes: Long,
    )

    /** Bounded rolling capture matching the Harmony diagnostics collector. */
    private class AudioCapture {
        private val chunks = ArrayDeque<AudioChunk>()
        private var bytes = 0
        private var totalInputBytes = 0L
        private var frames = 0L
        private var rollingDroppedBytes = 0L

        fun append(input: ByteArray, nowMs: Long) {
            val evenBytes = input.size - input.size % 2
            if (evenBytes <= 0) return
            frames += 1
            totalInputBytes += evenBytes
            val accepted = if (evenBytes > MAX_AUDIO_BYTES) {
                rollingDroppedBytes += evenBytes - MAX_AUDIO_BYTES
                input.copyOfRange(evenBytes - MAX_AUDIO_BYTES, evenBytes)
            } else {
                input.copyOf(evenBytes)
            }
            chunks.addLast(AudioChunk(accepted, nowMs))
            bytes += accepted.size
            var overflow = bytes - MAX_AUDIO_BYTES
            while (overflow > 0 && chunks.isNotEmpty()) {
                val first = chunks.first()
                val removed = minOf(overflow, first.pcm.size)
                if (removed == first.pcm.size) chunks.removeFirst()
                else first.pcm = first.pcm.copyOfRange(removed, first.pcm.size)
                bytes -= removed
                overflow -= removed
                rollingDroppedBytes += removed
            }
        }

        fun snapshot(): AudioSnapshot {
            val merged = ByteArray(bytes)
            var offset = 0
            var squareSum = 0.0
            var peakValue = 0
            var clippedSamples = 0L
            var maxFrameGapMs = 0L
            var previousTime = -1L
            chunks.forEach { chunk ->
                chunk.pcm.copyInto(merged, offset)
                offset += chunk.pcm.size
                if (previousTime >= 0) maxFrameGapMs = maxOf(maxFrameGapMs, chunk.wallTimeMs - previousTime)
                previousTime = chunk.wallTimeMs
                var index = 0
                while (index + 1 < chunk.pcm.size) {
                    val sample = (chunk.pcm[index].toInt() and 0xff) or (chunk.pcm[index + 1].toInt() shl 8)
                    val signed = sample.toShort().toInt()
                    val magnitude = kotlin.math.abs(signed)
                    squareSum += signed.toDouble() * signed
                    peakValue = maxOf(peakValue, magnitude)
                    if (magnitude >= 32767) clippedSamples += 1
                    index += 2
                }
            }
            val samples = bytes / 2
            return AudioSnapshot(
                merged,
                totalInputBytes,
                frames,
                chunks.firstOrNull()?.wallTimeMs ?: -1,
                chunks.lastOrNull()?.wallTimeMs ?: -1,
                maxFrameGapMs,
                if (samples > 0) kotlin.math.sqrt(squareSum / samples) / 32768.0 else 0.0,
                peakValue / 32768.0,
                if (samples > 0) clippedSamples.toDouble() / samples else 0.0,
                rollingDroppedBytes,
            )
        }
    }

    private data class Session(
        val sourceSessionId: String,
        val publicSessionId: String,
        val startedAtMs: Long,
        val config: Map<String, Any?>,
        val audio: AudioCapture = AudioCapture(),
        var terminal: Boolean = false,
        var abnormal: Boolean = false,
        val abnormalReasons: MutableList<String> = mutableListOf(),
        var finishIntent: Boolean = false,
        var hasNonEmptyFinal: Boolean = false,
    ) {
        fun markAbnormal(reason: String) {
            abnormal = true
            if (reason !in abnormalReasons) abnormalReasons += reason
        }
    }

    private val lock = Any()
    private val ioLock = Any()
    private val sessions = linkedMapOf<String, Session>()
    private val events = ArrayDeque<Event>()
    private var rootPath: File? = null
    private var runId: String = newRunId()
    private var sequence = 0L
    private var sessionSequence = 0L
    private var journalGeneration = 0L
    private var journalFuture: ScheduledFuture<*>? = null
    private var deliveredModelManifest: String? = null
    private val journalExecutor = Executors.newSingleThreadScheduledExecutor { task ->
        Thread(task, "amphion-diagnostics").apply { isDaemon = true }
    }

    fun isBuildEnabled(): Boolean = BuildConfig.DIAGNOSTICS_ENABLED

    fun setRootPath(path: File) {
        if (!isBuildEnabled()) return
        synchronized(lock) {
            rootPath = path
            recoverCrashJournalsLocked(path)
        }
    }

    fun setDeliveredModelManifest(value: String) {
        if (!isBuildEnabled()) return
        synchronized(lock) {
            deliveredModelManifest = value.trim().takeIf { it.startsWith("{") && it.endsWith("}") }
        }
    }

    fun beginSession(sessionId: String, config: Map<String, Any?>) {
        if (!isBuildEnabled()) return
        runCatching {
            synchronized(lock) {
                sessionSequence += 1
                sessions[sessionId] = Session(
                    sessionId,
                    "session-$sessionSequence",
                    System.currentTimeMillis(),
                    config.toMap(),
                )
                appendEventLocked(sessionId, "START_LISTENING", emptyMap())
                scheduleJournalLocked(0)
            }
        }
    }

    fun record(sessionId: String, name: String, fields: Map<String, Any?> = emptyMap()) {
        if (!isBuildEnabled()) return
        runCatching {
            synchronized(lock) {
                appendEventLocked(sessionId, name, fields)
                val session = sessions[sessionId]
                if (name == "FINISH_REQUESTED" || name == "AUTO_FINISH_REQUESTED") {
                    session?.finishIntent = true
                }
                if (name == "CALLBACK_RESULT" && fields["isFinal"] == true) {
                    val textChars = (fields["textChars"] as? Number)?.toInt()
                        ?: (fields["text"]?.toString()?.length ?: 0)
                    if (textChars > 0) session?.hasNonEmptyFinal = true
                    if (fields["isLast"] == true && session != null) {
                        if (!session.finishIntent) session.markAbnormal("isLast-before-finish")
                        if (textChars == 0 && !session.hasNonEmptyFinal) session.markAbnormal("empty-final")
                    }
                }
                if (name == "CALLBACK_COMPLETE" || name == "CANCEL_REQUESTED") {
                    session?.terminal = true
                }
                if (name == "CALLBACK_ERROR") {
                    session?.markAbnormal("callback-error")
                    session?.terminal = true
                }
                val urgent = name == "CALLBACK_ERROR" || name == "CALLBACK_COMPLETE" ||
                    name == "CANCEL_REQUESTED" || name == "AUTO_FINISH_REQUESTED" ||
                    name == "CALLBACK_RESULT" && (fields["isFinal"] == true || fields["isLast"] == true)
                scheduleJournalLocked(if (urgent) 0 else JOURNAL_INTERVAL_MS)
            }
        }
    }

    fun captureAudio(sessionId: String, audio: ByteArray) {
        if (!isBuildEnabled() || audio.isEmpty()) return
        runCatching {
            synchronized(lock) {
                val session = sessions[sessionId] ?: return@synchronized
                session.audio.append(audio, System.currentTimeMillis())
                scheduleJournalLocked(JOURNAL_INTERVAL_MS)
            }
        }
    }

    fun export(): String {
        check(isBuildEnabled()) { "diagnostics are not enabled in this AAR" }
        return synchronized(ioLock) {
            val snapshot = synchronized(lock) {
                val root = checkNotNull(rootPath) { "diagnostics root path is not configured" }
                Snapshot(root, runId, sessions.values.map(::copySession), events.toList())
            }
            val exportRoot = File(snapshot.root, "asr-diagnostics").apply { mkdirs() }
            check(exportRoot.isDirectory) { "cannot create diagnostics export directory" }
            val runDir = File(exportRoot, snapshot.runId).apply { mkdirs() }
            check(runDir.isDirectory) { "cannot create diagnostics run directory" }
            appendResourceSample(runDir, snapshot)
            writeSnapshot(runDir, snapshot, automatic = false)
            rotateRuns(exportRoot, snapshot.runId)
            runDir.absolutePath
        }
    }

    internal fun resetForTests() {
        synchronized(lock) {
            journalFuture?.cancel(false)
            journalFuture = null
            journalGeneration += 1
        }
        // A task that already left the scheduler cannot be cancelled. Wait until its filesystem
        // critical section exits before publishing the next test/run identity.
        synchronized(ioLock) {}
        synchronized(lock) {
            sessions.clear()
            events.clear()
            rootPath = null
            runId = newRunId()
            sequence = 0
            sessionSequence = 0
            deliveredModelManifest = null
        }
    }

    internal fun flushForTests() {
        if (isBuildEnabled()) flushBackground(synchronized(lock) { journalGeneration })
    }

    private data class SessionSnapshot(
        val publicSessionId: String,
        val startedAtMs: Long,
        val config: Map<String, Any?>,
        val audio: AudioSnapshot,
        val terminal: Boolean,
        val abnormal: Boolean,
        val abnormalReasons: List<String>,
    )

    private data class Snapshot(
        val root: File,
        val runId: String,
        val sessions: List<SessionSnapshot>,
        val events: List<Event>,
    )

    private fun copySession(session: Session): SessionSnapshot = SessionSnapshot(
        publicSessionId = session.publicSessionId,
        startedAtMs = session.startedAtMs,
        config = session.config.toMap(),
        audio = session.audio.snapshot(),
        terminal = session.terminal,
        abnormal = session.abnormal,
        abnormalReasons = session.abnormalReasons.toList(),
    )

    private fun appendEventLocked(sessionId: String, name: String, fields: Map<String, Any?>) {
        while (events.size >= MAX_EVENTS) events.removeFirst()
        sequence += 1
        events.addLast(
            Event(
                sequence,
                System.currentTimeMillis(),
                System.nanoTime(),
                sessions[sessionId]?.publicSessionId.orEmpty(),
                Thread.currentThread().name,
                name,
                fields.toMap(),
            ),
        )
    }

    private fun eventJson(event: Event): String = jsonObject(
        linkedMapOf(
            "schemaVersion" to 2,
            "sequence" to event.sequence,
            "wallTimeMs" to event.wallTimeMs,
            "monotonicTimeNs" to event.monotonicTimeNs,
            "sessionId" to event.publicSessionId,
            "thread" to event.thread,
            "event" to event.name,
            "fields" to event.fields,
        ),
    )

    private fun summaryJson(snapshot: Snapshot): String = jsonObject(
        linkedMapOf(
            "schemaVersion" to 2,
            "runId" to snapshot.runId,
            "diagnosticsBuild" to true,
            "sessionCount" to snapshot.sessions.size,
            "abnormalSessionCount" to snapshot.sessions.count { it.abnormal },
            "sessions" to snapshot.sessions.map { session ->
                linkedMapOf(
                    "sessionId" to session.publicSessionId,
                    "startedAtMs" to session.startedAtMs,
                    "terminal" to session.terminal,
                    "abnormal" to session.abnormal,
                    "abnormalReasons" to session.abnormalReasons,
                    "audioBytesSeen" to session.audio.totalInputBytes,
                    "audioBytesCaptured" to session.audio.pcm.size,
                    "config" to session.config,
                )
            },
        ),
    ) + "\n"

    private fun jsonObject(values: Map<String, Any?>): String = values.entries.joinToString(
        prefix = "{",
        postfix = "}",
        separator = ",",
    ) { (key, value) -> "${jsonString(key)}:${jsonValue(value)}" }

    private fun jsonValue(value: Any?): String = when (value) {
        null -> "null"
        is String -> jsonString(value)
        is Boolean, is Byte, is Short, is Int, is Long -> value.toString()
        is Float -> if (value.isFinite()) value.toString() else "null"
        is Double -> if (value.isFinite()) value.toString() else "null"
        is Map<*, *> -> jsonObject(value.entries.associate { it.key.toString() to it.value })
        is Iterable<*> -> value.joinToString(prefix = "[", postfix = "]", separator = ",", transform = ::jsonValue)
        else -> jsonString(value.toString())
    }

    private fun jsonString(value: String): String = buildString(value.length + 2) {
        append('"')
        value.forEach { char ->
            when (char) {
                '"' -> append("\\\"")
                '\\' -> append("\\\\")
                '\b' -> append("\\b")
                '\u000c' -> append("\\f")
                '\n' -> append("\\n")
                '\r' -> append("\\r")
                '\t' -> append("\\t")
                else -> if (char.code < 0x20) append(String.format(Locale.ROOT, "\\u%04x", char.code)) else append(char)
            }
        }
        append('"')
    }

    private fun writeWav(path: File, pcm: ByteArray) {
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
            put("RIFF".toByteArray(Charsets.US_ASCII))
            putInt(36 + pcm.size)
            put("WAVE".toByteArray(Charsets.US_ASCII))
            put("fmt ".toByteArray(Charsets.US_ASCII))
            putInt(16)
            putShort(1)
            putShort(1)
            putInt(SAMPLE_RATE)
            putInt(SAMPLE_RATE * 2)
            putShort(2)
            putShort(16)
            put("data".toByteArray(Charsets.US_ASCII))
            putInt(pcm.size)
        }.array()
        FileOutputStream(path).use { output ->
            output.write(header)
            output.write(pcm)
        }
    }

    private fun scheduleJournalLocked(delayMs: Long) {
        if (rootPath == null) return
        journalFuture?.takeIf { !it.isDone }?.let { current ->
            if (delayMs > 0) return
            current.cancel(false)
        }
        val expectedGeneration = journalGeneration
        journalFuture = journalExecutor.schedule({
            runCatching { flushBackground(expectedGeneration) }
        }, delayMs, TimeUnit.MILLISECONDS)
    }

    private fun flushBackground(expectedGeneration: Long) = synchronized(ioLock) io@{
        val snapshot = synchronized(lock) {
            if (expectedGeneration != journalGeneration) return@io
            val root = rootPath ?: return@io
            journalFuture = null
            Snapshot(root, runId, sessions.values.map(::copySession), events.toList())
        }
        if (snapshot.sessions.any { it.terminal }) {
            val exportRoot = File(snapshot.root, "asr-diagnostics").apply { mkdirs() }
            val runDir = File(exportRoot, snapshot.runId).apply { mkdirs() }
            appendResourceSample(runDir, snapshot)
            writeSnapshot(runDir, snapshot, automatic = true)
            rotateRuns(exportRoot, snapshot.runId)
        }

        val pendingRoot = File(snapshot.root, "asr-diagnostics-pending").apply { mkdirs() }
        val stable = File(pendingRoot, snapshot.runId)
        val next = File(pendingRoot, "${snapshot.runId}.next")
        next.deleteRecursively()
        val activeIds = snapshot.sessions.filterNot { it.terminal }.map { it.publicSessionId }.toSet()
        if (activeIds.isEmpty()) {
            stable.deleteRecursively()
            return@io
        }
        next.mkdirs()
        val activeSnapshot = snapshot.copy(
            sessions = snapshot.sessions.filter { it.publicSessionId in activeIds },
            events = snapshot.events.filter {
                it.publicSessionId.isEmpty() || it.publicSessionId in activeIds
            },
        )
        appendResourceSample(next, activeSnapshot)
        writeSnapshot(next, activeSnapshot, automatic = true)
        stable.deleteRecursively()
        check(next.renameTo(stable)) { "cannot publish diagnostics crash journal" }
    }

    private fun writeSnapshot(runDir: File, snapshot: Snapshot, automatic: Boolean) {
        runDir.mkdirs()
        File(runDir, "events.ndjson").bufferedWriter().use { writer ->
            snapshot.events.forEach { writer.append(eventJson(it)).append('\n') }
        }
        File(runDir, "callbacks.ndjson").bufferedWriter().use { writer ->
            snapshot.events.filter { it.name.startsWith("CALLBACK_") }
                .forEach { writer.append(eventJson(it)).append('\n') }
        }
        snapshot.sessions.forEach { session ->
            val sessionDir = File(File(runDir, "sessions"), safeName(session.publicSessionId))
                .apply { mkdirs() }
            val timeline = snapshot.events.filter { it.publicSessionId == session.publicSessionId }
            File(sessionDir, "timeline.json").writeText(
                timeline.joinToString(prefix = "[", postfix = "]\n", separator = ",", transform = ::eventJson),
            )
            File(sessionDir, "result.json").writeText(
                jsonObject(
                    linkedMapOf(
                        "sessionId" to session.publicSessionId,
                        "terminal" to session.terminal,
                        "abnormal" to session.abnormal,
                        "abnormalReasons" to session.abnormalReasons,
                    ),
                ) + "\n",
            )
            if (session.audio.pcm.isNotEmpty()) {
                writeWav(File(sessionDir, "sdk-input.wav"), session.audio.pcm)
                File(sessionDir, "sdk-input.json").writeText(
                    jsonObject(
                        linkedMapOf(
                            "sampleRate" to SAMPLE_RATE,
                            "channels" to 1,
                            "sampleBit" to 16,
                            "bytes" to session.audio.pcm.size,
                            "totalInputBytes" to session.audio.totalInputBytes,
                            "frames" to session.audio.frames,
                            "samples" to session.audio.pcm.size / 2,
                            "durationMs" to session.audio.pcm.size / 2 * 1000 / SAMPLE_RATE,
                            "actualWriteAudioDurationMs" to session.audio.totalInputBytes / 2 * 1000 / SAMPLE_RATE,
                            "firstFrameTimeMs" to session.audio.firstFrameTimeMs,
                            "lastFrameTimeMs" to session.audio.lastFrameTimeMs,
                            "maxFrameGapMs" to session.audio.maxFrameGapMs,
                            "rms" to session.audio.rms,
                            "peak" to session.audio.peak,
                            "clipRate" to session.audio.clipRate,
                            "truncated" to (session.audio.rollingDroppedBytes > 0),
                            "ringBuffer" to false,
                            "preTriggerDroppedBytes" to 0,
                            "rollingDroppedBytes" to session.audio.rollingDroppedBytes,
                            "audioSource" to "caller-provided-external-stream",
                            "source" to "public-writeAudio-input",
                            "includesColdStartPreRoll" to true,
                            "includesInternalSilence" to false,
                            "includesInternalReplay" to false,
                        ),
                    ) + "\n",
                )
            }
        }
        File(runDir, "summary.json").writeText(summaryJson(snapshot), Charsets.UTF_8)
        File(runDir, "effective-config.json").writeText(
            """{"enabled":true,"mode":"CUSTOMER_SUPPORT","captureAudio":true,"includeRecognitionText":true,"maxSessionAudioSec":300,"maxSessionEvents":512}
""",
        )
        val runtimeReady = runCatching { AmphionRuntime.isRuntimeReady() }.getOrDefault(false)
        val sdkVersion = runCatching { AmphionRuntime.version() }.getOrDefault("unknown")
        File(runDir, "native-state.json").writeText(
            jsonObject(
                linkedMapOf(
                    "sdkVersion" to sdkVersion,
                    "runtimeReady" to runtimeReady,
                    "modelLoaded" to runtimeReady,
                    "systemVersion" to System.getProperty("os.version", "unknown"),
                    "capturedAtMs" to System.currentTimeMillis(),
                ),
            ) + "\n",
        )
        File(runDir, "build-identity.json").writeText(
            jsonObject(
                linkedMapOf(
                    "sdkVersion" to sdkVersion,
                    "diagnosticBuild" to true,
                    "diagnosticSchemaVersion" to 2,
                    "binaryHashStatus" to "not-available-at-runtime",
                ),
            ) + "\n",
        )
        val delivered = synchronized(lock) { deliveredModelManifest }
        File(runDir, "model-manifest.json").writeText(
            if (delivered == null) {
                """{"modelLoaded":$runtimeReady,"modelContentExcludedForPrivacy":true,"deliveredManifestError":"not-available"}
"""
            } else {
                """{"modelLoaded":$runtimeReady,"modelContentExcludedForPrivacy":true,"deliveredManifest":$delivered}
"""
            },
        )
        File(runDir, "manifest.json").writeText(
            jsonObject(
                linkedMapOf(
                    "schemaVersion" to 2,
                    "runId" to snapshot.runId,
                    "createdAtMs" to System.currentTimeMillis(),
                    "mode" to "CUSTOMER_SUPPORT",
                    "automaticPersistence" to automatic,
                    "privacy" to "audio and recognition text are included only in diagnostics builds; identifiers are opaque",
                    "files" to listOf(
                        "events.ndjson", "callbacks.ndjson", "summary.json", "effective-config.json",
                        "build-identity.json", "model-manifest.json", "resource-samples.csv", "native-state.json",
                    ),
                ),
            ) + "\n",
        )
    }

    private fun appendResourceSample(runDir: File, snapshot: Snapshot) {
        val status = runCatching { File("/proc/self/status").readText() }.getOrDefault("")
        fun value(key: String, kb: Boolean = false): Long {
            val suffix = if (kb) "\\s*kB" else ""
            return Regex("(?m)^${Regex.escape(key)}:\\s*(\\d+)$suffix")
                .find(status)?.groupValues?.get(1)?.toLongOrNull() ?: -1
        }
        val header = "wallTimeMs,rssKb,anonymousRssKb,fileRssKb,threadCount,fdCount," +
            "activeSessionCount,audioQueueDepth,maxAudioQueueDepth,nativeCallsInFlight," +
            "nativeHeapKb,decodeQueueDepth,avgDecodeRtf\n"
        val line = listOf(
            System.currentTimeMillis(), value("VmRSS", true), value("RssAnon", true),
            value("RssFile", true), value("Threads"), File("/proc/self/fd").list()?.size ?: -1,
            snapshot.sessions.count { !it.terminal }, -1, -1, -1, value("RssAnon", true), -1, -1,
        ).joinToString(",") + "\n"
        val file = File(runDir, "resource-samples.csv")
        if (!file.exists()) file.writeText(header)
        file.appendText(line)
    }

    private fun recoverCrashJournalsLocked(root: File) {
        val pendingRoot = File(root, "asr-diagnostics-pending")
        if (!pendingRoot.isDirectory) return
        val exportRoot = File(root, "asr-diagnostics").apply { mkdirs() }
        pendingRoot.listFiles()?.filter { it.isDirectory && it.name.endsWith(".next") }?.forEach { next ->
            if (!File(next, "manifest.json").isFile) next.deleteRecursively() else {
                val stable = File(pendingRoot, next.name.removeSuffix(".next"))
                stable.deleteRecursively()
                next.renameTo(stable)
            }
        }
        pendingRoot.listFiles()?.filter { it.isDirectory && File(it, "manifest.json").isFile }
            ?.forEach { source ->
                File(source, "crash-recovery.json").writeText(
                    """{"schemaVersion":1,"recoveredAtMs":${System.currentTimeMillis()},"reason":"previous-process-ended-with-active-session","possibleTailLossMs":$JOURNAL_INTERVAL_MS}
""",
                )
                markRecoveredCrash(source)
                val destination = File(exportRoot, source.name)
                destination.deleteRecursively()
                source.renameTo(destination)
            }
        rotateRuns(exportRoot, "")
    }

    private fun markRecoveredCrash(runDir: File) {
        runCatching {
            val summary = File(runDir, "summary.json")
            var text = summary.readText()
            if (!text.contains("\"recoveredCrash\"")) {
                text = text.replaceFirst("{", "{\"recoveredCrash\":true,")
            }
            val sessionCount = Regex("\"sessionCount\":(\\d+)").find(text)?.groupValues?.get(1) ?: "0"
            text = text.replace(Regex("\"abnormalSessionCount\":\\d+"), "\"abnormalSessionCount\":$sessionCount")
            text = text.replace("\"abnormal\":false", "\"abnormal\":true")
            text = text.replace("\"abnormalReasons\":[]", "\"abnormalReasons\":[\"process-crash-recovery\"]")
            summary.writeText(text)

            val manifest = File(runDir, "manifest.json")
            var manifestText = manifest.readText()
            if (!manifestText.contains("\"recoveredCrash\"")) {
                manifestText = manifestText.replaceFirst(
                    "{",
                    "{\"recoveredCrash\":true,\"possibleTailLossMs\":$JOURNAL_INTERVAL_MS,",
                )
            }
            manifest.writeText(manifestText)
        }
    }

    private fun rotateRuns(root: File, keepName: String) {
        var retainedBytes = 0L
        root.listFiles()?.filter { it.isDirectory }?.sortedByDescending { it.name }
            ?.forEachIndexed { index, file ->
                val bytes = treeBytes(file)
                if (file.name != keepName &&
                    (index >= MAX_RETAINED_RUNS || retainedBytes + bytes > MAX_DIRECTORY_BYTES)
                ) {
                    file.deleteRecursively()
                } else {
                    retainedBytes += bytes
                }
            }
    }

    private fun treeBytes(file: File): Long = if (file.isFile) file.length() else
        file.listFiles()?.sumOf(::treeBytes) ?: 0L

    private fun safeName(value: String): String = value.replace(Regex("[^A-Za-z0-9._-]"), "_").take(80)

    private fun newRunId(): String = "run-${System.currentTimeMillis()}-${UUID.randomUUID()}"
}
