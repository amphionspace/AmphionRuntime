package com.amphion.dingqiao

import java.io.File
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class DiagnosticsModuleTest {
    private lateinit var root: File

    @Before
    fun setUp() {
        root = kotlin.io.path.createTempDirectory().toFile()
        DiagnosticsModule.resetForTests()
    }

    @After
    fun tearDown() {
        DiagnosticsModule.resetForTests()
        root.deleteRecursively()
    }

    @Test
    fun exportAvailabilityAndCaptureMatchCompileTimeBuildVariant() {
        if (!BuildConfig.DIAGNOSTICS_ENABLED) {
            val failure = runCatching { DiagnosticsModule.export() }.exceptionOrNull()
            assertTrue(failure is IllegalStateException)
            assertTrue(failure?.message.orEmpty().contains("not enabled"))
            return
        }

        DiagnosticsModule.setRootPath(root)
        DiagnosticsModule.beginSession(
            "diagnostics-session",
            mapOf(
                "recognizerMode" to "long",
                "voiceprintIdCount" to 1,
            ),
        )
        val pcm = byteArrayOf(1, 0, 2, 0, 3, 0, 4, 0)
        DiagnosticsModule.captureAudio("diagnostics-session", pcm)
        DiagnosticsModule.record("diagnostics-session", "CALLBACK_START")
        DiagnosticsModule.record(
            "diagnostics-session",
            "CALLBACK_RESULT",
            mapOf("isFinal" to true, "isLast" to true, "text" to "测试"),
        )
        DiagnosticsModule.record("diagnostics-session", "CALLBACK_COMPLETE")

        val output = File(DiagnosticsModule.export())
        assertTrue(output.isDirectory)
        val events = File(output, "events.ndjson").readText()
        assertTrue(events.contains("CALLBACK_START"))
        assertTrue(events.contains("CALLBACK_COMPLETE"))
        assertTrue(events.contains("测试"))
        val summary = File(output, "summary.json").readText()
        assertTrue(summary.contains("\"terminal\":true"))
        assertTrue(summary.contains("\"voiceprintIdCount\":1"))
        assertFalse(summary.contains("voiceprintIds"))
        assertFalse(events.contains("diagnostics-session"))
        assertTrue(File(output, "callbacks.ndjson").isFile)
        assertTrue(File(output, "resource-samples.csv").isFile)
        assertTrue(File(output, "native-state.json").isFile)
        assertTrue(File(output, "build-identity.json").isFile)
        assertTrue(File(output, "model-manifest.json").isFile)
        assertTrue(File(output, "manifest.json").readText().contains("identifiers are opaque"))
        val sessionDir = File(output, "sessions/session-1")
        val wav = File(sessionDir, "sdk-input.wav").readBytes()
        assertEquals(44 + pcm.size, wav.size)
        assertEquals("RIFF", wav.copyOfRange(0, 4).toString(Charsets.US_ASCII))
        assertTrue(File(sessionDir, "sdk-input.json").isFile)
    }

    @Test
    fun crashJournalIsRecoveredAndMarkedAbnormal() {
        if (!BuildConfig.DIAGNOSTICS_ENABLED) return
        DiagnosticsModule.setRootPath(root)
        DiagnosticsModule.beginSession("private-id", emptyMap())
        DiagnosticsModule.captureAudio("private-id", byteArrayOf(1, 0, 2, 0))
        DiagnosticsModule.flushForTests()
        DiagnosticsModule.resetForTests()

        DiagnosticsModule.setRootPath(root)
        val recovered = File(root, "asr-diagnostics").listFiles().orEmpty().single()
        assertTrue(File(recovered, "crash-recovery.json").isFile)
        val summary = File(recovered, "summary.json").readText()
        assertTrue(summary.contains("\"recoveredCrash\":true"))
        assertTrue(summary.contains("\"abnormal\":true"))
        assertTrue(summary.contains("process-crash-recovery"))
        assertFalse(summary.contains("private-id"))
        val manifest = File(recovered, "manifest.json").readText()
        assertTrue(manifest.contains("\"possibleTailLossMs\":5000"))
    }

    @Test
    fun recordsLifecycleAbnormalReasonsAndOriginThread() {
        if (!BuildConfig.DIAGNOSTICS_ENABLED) return
        DiagnosticsModule.setRootPath(root)
        DiagnosticsModule.beginSession("source-session", emptyMap())
        val thread = Thread({
            DiagnosticsModule.record(
                "source-session",
                "CALLBACK_RESULT",
                mapOf("isFinal" to true, "isLast" to true, "textChars" to 0),
            )
        }, "diagnostic-callback-origin")
        thread.start()
        thread.join()
        val output = File(DiagnosticsModule.export())
        val events = File(output, "events.ndjson").readText()
        assertTrue(events.contains("diagnostic-callback-origin"))
        val summary = File(output, "summary.json").readText()
        assertTrue(summary.contains("isLast-before-finish"))
        assertTrue(summary.contains("empty-final"))
    }
}
