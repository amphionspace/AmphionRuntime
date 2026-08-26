package com.amphion.dingqiao.demo

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.AudioInfo
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.DingqiaoEventCode
import com.amphion.dingqiao.DingqiaoOnlineMode
import com.amphion.dingqiao.LicenseActivationCallback
import com.amphion.dingqiao.LicenseActivationResult
import com.amphion.dingqiao.PrepareRuntimeCallback
import com.amphion.dingqiao.RecognitionListener
import com.amphion.dingqiao.SpeechRecognitionEngine
import com.amphion.dingqiao.SpeechRecognitionResult
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.StartParams
import com.amphion.dingqiao.VoiceprintRegisterParams
import java.io.File
import java.security.MessageDigest
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Replays the original customer WAV evidence attached to the Feishu bug archive.
 *
 * Assets are supplied only at build time with -PdingqiaoEvalAudioDir and are never checked in.
 * Every case records the public callback timeline and validates the SDK lifecycle contract.
 */
@RunWith(AndroidJUnit4::class)
class DingqiaoCustomerBugEvidenceInstrumentedTest {

    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private val targetContext: Context get() = instrumentation.targetContext
    private val testContext: Context get() = instrumentation.context

    @Test
    fun bug02_customerLongAudio_preservesTailAndContinuousResults() {
        val writer = EvidenceWriter(targetContext, "bug02")
        prepare(writer)
        val engine = createEngine()
        try {
            val cases = listOf(
                Triple("bug02/A01.wav", "56", true),
                Triple("bug02/A02.wav", "1234567", true),
                Triple("bug02/A21.wav", "", false),
                Triple("bug02/A31_boundary.wav", "123456789", false),
            )
            val outcomes = cases.map { (asset, expected, tailAssertion) ->
                val outcome = decode(
                    engine = engine,
                    asset = asset,
                    frameSleepMs = runnerLong("frameSleepMs", 0L),
                    startExtra = longMeetingParams(maxAudioDurationMs = 300_000),
                    writer = writer,
                )
                val normalized = normalizeDigits(outcome.finalText)
                val expectedHit = expected.isEmpty() || normalized.contains(expected)
                writer.append(
                    "assertion",
                    mapOf(
                        "asset" to asset,
                        "expected" to expected,
                        "expectedHit" to expectedHit,
                        "tailAssertion" to tailAssertion,
                        "normalizedText" to normalized,
                    ),
                )
                assertLifecycle(outcome, asset)
                assertTrue("$asset must produce non-empty final text", outcome.finalText.isNotBlank())
                if (tailAssertion) {
                    assertTrue("$asset missing documented tail '$expected': ${outcome.finalText}", expectedHit)
                }
                outcome
            }
            assertTrue(
                "the 256s boundary sample must produce multiple non-empty finals",
                outcomes.last().finals.count { it.text.isNotBlank() } >= 3,
            )
        } finally {
            engine.shutdown()
        }
    }

    @Test
    fun bug08_remoteSourceAndSnr_recordsComparableEvidence() {
        val writer = EvidenceWriter(targetContext, "bug08")
        prepare(writer)
        val engine = createEngine()
        try {
            val direct = listOf(
                "bug08/A03_2m_oblique.wav",
                "bug08/A04_2m_front.wav",
                "bug08/A08_voice_communication.wav",
                "bug08/A09_mic.wav",
            ).map { asset ->
                decode(engine, asset, 0, standardParams(), writer).also {
                    assertLifecycle(it, asset)
                }
            }
            val a03Hash = assetSha256("bug08/A03_2m_oblique.wav")
            val a04Hash = assetSha256("bug08/A04_2m_front.wav")
            writer.append(
                "source-comparison",
                mapOf(
                    "a03Sha256" to a03Hash,
                    "a04Sha256" to a04Hash,
                    "byteIdentical" to (a03Hash == a04Hash),
                    "voiceCommunicationText" to direct[2].finalText,
                    "micText" to direct[3].finalText,
                ),
            )

            val snrAssets = wavAssets("bug08_snr").sorted()
            assertEquals("expected the eight customer SNR samples", 8, snrAssets.size)
            var hits = 0
            for (asset in snrAssets) {
                val outcome = decode(engine, asset, 0, standardParams(), writer)
                assertLifecycle(outcome, asset)
                val hit = normalizeDigits(outcome.finalText).contains("你好1234")
                if (hit) hits += 1
                writer.append("snr-assertion", mapOf("asset" to asset, "expected" to "你好1234", "hit" to hit))
            }
            writer.append(
                "summary",
                mapOf("snrHits" to hits, "snrTotal" to snrAssets.size, "snrAccuracy" to hits.toDouble() / snrAssets.size),
            )
        } finally {
            engine.shutdown()
        }
    }

    @Test
    fun bug09PoliceCorpus_meetsCustomerExactMatchTarget() {
        val writer = EvidenceWriter(targetContext, "bug09-police")
        prepare(writer)
        val engine = createEngine()
        try {
            val assets = wavAssets("bug09_a14").sorted()
            assertTrue("customer police corpus must not be empty", assets.isNotEmpty())
            var lifecyclePass = 0
            var exactHits = 0
            for (asset in assets) {
                val expected = asset.substringBefore("/pcm/").substringAfterLast('/')
                val outcome = decode(engine, asset, 0, standardParams(police = true), writer)
                val lifecycleOk = lifecycleErrors(outcome).isEmpty()
                if (lifecycleOk) lifecyclePass += 1
                val hit = normalizeText(outcome.finalText).contains(normalizeText(expected))
                if (hit) exactHits += 1
                writer.append(
                    "police-assertion",
                    mapOf(
                        "asset" to asset,
                        "expected" to expected,
                        "hit" to hit,
                        "lifecycleOk" to lifecycleOk,
                        "text" to outcome.finalText,
                    ),
                )
            }
            val accuracy = exactHits.toDouble() / assets.size
            writer.append(
                "summary",
                mapOf(
                    "total" to assets.size,
                    "exactHits" to exactHits,
                    "exactAccuracy" to accuracy,
                    "lifecyclePass" to lifecyclePass,
                    "customerTarget" to 0.98,
                ),
            )
            assertEquals("all police cases must satisfy lifecycle", assets.size, lifecyclePass)
            assertTrue("customer police exact-match target is 98%, actual=$accuracy", accuracy >= 0.98)
        } finally {
            engine.shutdown()
        }
    }

    @Test
    fun bug10Hotwords_originalNamesAreRecognized() {
        val writer = EvidenceWriter(targetContext, "bug10-hotwords")
        prepare(writer)
        val hotwords = listOf("余祈根", "梅隆煜", "文赋成")
        val engine = createEngine(hotwords)
        try {
            val failures = mutableListOf<String>()
            val cases = listOf(
                "hotword/A05_yuqigen.wav" to "余祈根",
                "hotword/A32_wenfucheng.wav" to "文赋成",
            )
            for ((asset, expected) in cases) {
                val outcome = decode(engine, asset, 0, standardParams(), writer)
                val lifecycle = lifecycleErrors(outcome)
                val hit = normalizeText(outcome.finalText).contains(expected)
                writer.append(
                    "hotword-assertion",
                    mapOf(
                        "asset" to asset,
                        "expected" to expected,
                        "hit" to hit,
                        "lifecycleErrors" to JSONArray(lifecycle),
                    ),
                )
                if (lifecycle.isNotEmpty()) failures += "$asset lifecycle=$lifecycle"
                if (!hit) failures += "$asset missing '$expected': ${outcome.finalText}"
            }
            assertTrue("customer hotword failures: $failures", failures.isEmpty())
        } finally {
            engine.shutdown()
        }
    }

    @Test
    fun pttImmediateFinish_matchesDelayedCustomerSample() {
        val writer = EvidenceWriter(targetContext, "ptt-immediate")
        prepare(writer)
        val engine = createEngine()
        try {
            val immediate = decode(engine, "ptt/A10_immediate.wav", 0, pttParams(), writer)
            val delayed = decode(engine, "ptt/A11_delayed.wav", 0, pttParams(), writer)
            assertLifecycle(immediate, "PTT immediate")
            assertLifecycle(delayed, "PTT delayed")
            assertTrue("immediate PTT final must be non-empty", immediate.finalText.isNotBlank())
            assertTrue("delayed PTT final must be non-empty", delayed.finalText.isNotBlank())
            val equal = normalizeText(immediate.finalText) == normalizeText(delayed.finalText)
            writer.append(
                "comparison",
                mapOf(
                    "immediateText" to immediate.finalText,
                    "delayedText" to delayed.finalText,
                    "normalizedEqual" to equal,
                ),
            )
            assertTrue("immediate and delayed PTT samples must produce the same text", equal)
        } finally {
            engine.shutdown()
        }
    }

    @Test
    fun bug05Bug07Bug11_voiceprintAndSpeakerVadUseCustomerEvidence() {
        val writer = EvidenceWriter(targetContext, "voiceprint-speaker-vad")
        prepare(writer)
        val enrollmentAsset = "bug05/机主/enrollment_near.wav"
        val enrollmentPath = stageAsset(testContext, targetContext, enrollmentAsset, "customer_bug/enrollment_near.wav")
        val registration = SpeechRecognizeSdk.registerVoiceprint(
            VoiceprintRegisterParams(listOf(enrollmentPath), AudioInfo()),
        )
        val voiceprintId = registration.voiceprintId.keys.single()
        writer.append("voiceprint-registration", mapOf("asset" to enrollmentAsset, "voiceprintId" to voiceprintId))

        val engine = createEngine()
        try {
            val failures = mutableListOf<String>()
            val cases = listOf("bug05/C1.wav", "bug05/C2.wav", "bug05/C3.wav")
            for (asset in cases) {
                val outcome = decode(
                    engine,
                    asset,
                    runnerLong("voiceprintFrameSleepMs", 0L),
                    voiceprintParams(voiceprintId),
                    writer,
                )
                val lifecycle = lifecycleErrors(outcome)
                val nonEmpty = outcome.finals.filter { it.text.isNotBlank() }
                val allScored = nonEmpty.all { it.speakerSimilarity != null }
                val leakedOtherSpeaker = normalizeText(outcome.finalText).contains("你好")
                writer.append(
                    "voiceprint-assertion",
                    mapOf(
                        "asset" to asset,
                        "allNonEmptyFinalsScored" to allScored,
                        "leakedOtherSpeaker" to leakedOtherSpeaker,
                        "lifecycleErrors" to JSONArray(lifecycle),
                    ),
                )
                if (lifecycle.isNotEmpty()) failures += "$asset lifecycle=$lifecycle"
                if (!allScored) failures += "$asset has a non-empty final without speakerSimilarity"
                if (leakedOtherSpeaker) failures += "$asset leaked the documented other-speaker phrase"
            }
            assertTrue("customer voiceprint/Speaker VAD failures: $failures", failures.isEmpty())
        } finally {
            engine.shutdown()
        }
    }

    @Test
    fun bug01_finishShutdownRelicense_survivesMoreThanOneHourOfAcceptedPcm() {
        val writer = EvidenceWriter(targetContext, "bug01-release-race")
        prepare(writer)
        val engine = createEngine()
        val asset = "long_meeting/customer_20260820.wav"
        val pcm = readAssetPcm(testContext, asset)
        val acceptedBytes = AtomicLong(0)
        val listener = TimelineListener(acceptedBytes)
        engine.setListener(listener)
        val sessionId = "bug01-${System.currentTimeMillis()}"
        engine.startListening(StartParams(sessionId, AudioInfo(), longMeetingParams(8_000_000)))
        assertTrue("BUG-01 session failed to start: ${listener.errors}", listener.started.await(30, TimeUnit.SECONDS))

        val frameSleepMs = runnerLong("bug01FrameSleepMs", 0L)
        repeat(2) {
            feedPcm(engine, sessionId, pcm, frameSleepMs, acceptedBytes, listener)
        }
        val acceptedDurationMs = acceptedBytes.get() / 32
        assertTrue("derived stress input must exceed one hour", acceptedDurationMs > 3_600_000)
        val lastBeforeFinish = listener.finals.count { it.isLast }
        engine.finish(sessionId)
        engine.shutdown()
        relicenseAndPrepare(writer)
        val completed = listener.complete.await(240, TimeUnit.SECONDS)
        val outcome = listener.outcome(asset, completed, lastBeforeFinish)
        writer.append(
            "derived-input",
            mapOf(
                "sourceAsset" to asset,
                "sourceSha256" to assetSha256(asset),
                "repeatCount" to 2,
                "acceptedDurationMs" to acceptedDurationMs,
                "frameSleepMs" to frameSleepMs,
            ),
        )
        writer.append("decode", outcome.toMap())
        assertLifecycle(outcome, "BUG-01 finish/shutdown/relicense")

        val recoveryEngine = createEngine()
        try {
            val recovery = decode(
                recoveryEngine,
                "ptt/A10_immediate.wav",
                0,
                pttParams(),
                writer,
            )
            assertLifecycle(recovery, "BUG-01 recovery session")
            assertTrue("Runtime replacement must recover for the next session", recovery.finalText.isNotBlank())
        } finally {
            recoveryEngine.shutdown()
        }
    }

    @Test
    fun longMeetingPaced_hasNoCustomerReportedFortySecondResultStall() {
        val writer = EvidenceWriter(targetContext, "long-meeting-paced")
        prepare(writer)
        val engine = createEngine()
        try {
            val outcome = decode(
                engine,
                "long_meeting/customer_20260820.wav",
                DQ_FRAME_MS,
                longMeetingParams(18_000_000),
                writer,
                completeTimeoutSeconds = 180,
            )
            assertLifecycle(outcome, "paced long meeting")
            assertTrue("paced long meeting must produce text after 35m17s",
                outcome.finals.any { it.text.isNotBlank() && it.audioMsAtCallback >= 2_117_000 })
            assertTrue(
                "paced long meeting reproduced a >=40s VAD-active result stall: ${outcome.maxVadActiveTextGapMs}ms",
                outcome.maxVadActiveTextGapMs < 40_000,
            )
        } finally {
            engine.shutdown()
        }
    }

    private fun prepare(writer: EvidenceWriter) {
        targetContext.startActivity(
            Intent(targetContext, DeviceTestKeepAliveActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
        SystemClock.sleep(500)
        writer.append(
            "environment",
            mapOf(
                "model" to Build.MODEL,
                "manufacturer" to Build.MANUFACTURER,
                "android" to Build.VERSION.RELEASE,
                "sdk" to Build.VERSION.SDK_INT,
                "fingerprint" to Build.FINGERPRINT,
            ),
        )
        writer.append("prepare-stage", mapOf("stage" to "before-init"))
        SpeechRecognizeSdk.init(targetContext)
        writer.append("prepare-stage", mapOf("stage" to "after-init"))
        SpeechRecognizeSdk.setWorkPath(
            File(targetContext.getExternalFilesDir(null), "customer_bug_work").absolutePath,
        )

        val licensePath = stageAsset(testContext, targetContext, "licenses/valid.lic", "lic/runtime-valid.lic")
        val licenseDone = CountDownLatch(1)
        var licenseResultCode: Int? = null
        var licenseError: String? = null
        writer.append("prepare-stage", mapOf("stage" to "before-setLicense"))
        SpeechRecognizeSdk.setLicense(licensePath, object : LicenseActivationCallback {
            override fun onResult(result: LicenseActivationResult) {
                licenseResultCode = result.errorCode
                writer.append(
                    "prepare-stage",
                    mapOf("stage" to "license-result", "errorCode" to result.errorCode),
                )
                licenseDone.countDown()
            }

            override fun onError(errorCode: Int, errorMessage: String) {
                licenseError = "$errorCode $errorMessage"
                writer.append(
                    "prepare-stage",
                    mapOf("stage" to "license-error", "error" to licenseError),
                )
                licenseDone.countDown()
            }
        })
        writer.append("prepare-stage", mapOf("stage" to "after-setLicense-call"))
        check(licenseDone.await(20, TimeUnit.SECONDS)) { "setLicense callback timed out" }
        check(licenseError == null) { "setLicense failed: $licenseError" }
        check(licenseResultCode == 0) { "setLicense returned errorCode=$licenseResultCode" }

        val runtimeDone = CountDownLatch(1)
        var runtimeError: String? = null
        writer.append("prepare-stage", mapOf("stage" to "before-prepareRuntime"))
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() {
                writer.append("prepare-stage", mapOf("stage" to "runtime-ready"))
                runtimeDone.countDown()
            }

            override fun onError(errorCode: Int, errorMessage: String) {
                runtimeError = "$errorCode $errorMessage"
                writer.append(
                    "prepare-stage",
                    mapOf("stage" to "runtime-error", "error" to runtimeError),
                )
                runtimeDone.countDown()
            }
        })
        writer.append("prepare-stage", mapOf("stage" to "after-prepareRuntime-call"))
        check(runtimeDone.await(20, TimeUnit.SECONDS)) { "prepareRuntime callback timed out" }
        check(runtimeError == null) { "prepareRuntime failed: $runtimeError" }
        writer.append("prepare-stage", mapOf("stage" to "prepare-complete"))
    }

    private fun createEngine(hotwords: List<String> = emptyList()): SpeechRecognitionEngine {
        val extra = mutableMapOf<String, Any>("disablePrepack" to true)
        if (hotwords.isNotEmpty()) extra["sysGeneralLexicon"] = hotwords
        return SpeechRecognizeSdk.createEngine(
            CreateEngineParams("zh-CN", DingqiaoOnlineMode.OFFLINE, extra),
        )
    }

    private fun decode(
        engine: SpeechRecognitionEngine,
        asset: String,
        frameSleepMs: Long,
        startExtra: Map<String, Any>,
        writer: EvidenceWriter,
        completeTimeoutSeconds: Long = 90,
    ): DecodeOutcome {
        awaitIdle(engine, 60_000)
        val pcm = readAssetPcm(testContext, asset)
        val acceptedBytes = AtomicLong(0)
        val listener = TimelineListener(acceptedBytes)
        engine.setListener(listener)
        val sessionId = "customer-${asset.hashCode().toUInt().toString(16)}-${System.nanoTime()}"
        val startedAt = SystemClock.elapsedRealtime()
        engine.startListening(StartParams(sessionId, AudioInfo(), startExtra))
        val started = listener.started.await(30, TimeUnit.SECONDS)
        if (!started) {
            runCatching { engine.cancel(sessionId) }
            val outcome = listener.outcome(asset, false, listener.finals.count { it.isLast })
            writer.append("decode", outcome.toMap() + mapOf("startTimeout" to true))
            return outcome
        }
        feedPcm(engine, sessionId, pcm, frameSleepMs, acceptedBytes, listener)
        val lastBeforeFinish = listener.finals.count { it.isLast }
        engine.finish(sessionId)
        val completed = listener.complete.await(completeTimeoutSeconds, TimeUnit.SECONDS)
        awaitIdle(engine, TimeUnit.SECONDS.toMillis(completeTimeoutSeconds))
        val outcome = listener.outcome(asset, completed, lastBeforeFinish)
        writer.append(
            "decode",
            outcome.toMap() + mapOf(
                "sourceSha256" to assetSha256(asset),
                "wallMs" to (SystemClock.elapsedRealtime() - startedAt),
                "frameSleepMs" to frameSleepMs,
            ),
        )
        return outcome
    }

    private fun feedPcm(
        engine: SpeechRecognitionEngine,
        sessionId: String,
        pcm: ByteArray,
        frameSleepMs: Long,
        acceptedBytes: AtomicLong,
        listener: TimelineListener,
    ) {
        var offset = 0
        var frames = 0
        while (offset < pcm.size) {
            val size = minOf(DQ_FRAME, pcm.size - offset)
            val frame = ByteArray(DQ_FRAME)
            System.arraycopy(pcm, offset, frame, 0, size)
            engine.writeAudio(sessionId, frame)
            acceptedBytes.addAndGet(DQ_FRAME.toLong())
            offset += size
            frames += 1
            if (frames % 50 == 0) listener.observeFeedProgress()
            if (frameSleepMs > 0) Thread.sleep(frameSleepMs)
        }
        listener.observeFeedProgress()
    }

    private fun relicenseAndPrepare(writer: EvidenceWriter) {
        val licensePath = stageAsset(testContext, targetContext, "licenses/valid.lic", "customer_bug/relicense.lic")
        val licenseDone = CountDownLatch(1)
        var licenseError: String? = null
        SpeechRecognizeSdk.setLicense(licensePath, object : LicenseActivationCallback {
            override fun onResult(result: LicenseActivationResult) {
                if (result.errorCode != 0) licenseError = "${result.errorCode}:${result.errorMessage}"
                licenseDone.countDown()
            }

            override fun onError(errorCode: Int, errorMessage: String) {
                licenseError = "$errorCode:$errorMessage"
                licenseDone.countDown()
            }
        })
        assertTrue("relicense timed out", licenseDone.await(240, TimeUnit.SECONDS))
        assertTrue("relicense failed: $licenseError", licenseError == null)

        val runtimeDone = CountDownLatch(1)
        var runtimeError: String? = null
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() = runtimeDone.countDown()
            override fun onError(errorCode: Int, errorMessage: String) {
                runtimeError = "$errorCode:$errorMessage"
                runtimeDone.countDown()
            }
        })
        assertTrue("prepareRuntime after relicense timed out", runtimeDone.await(240, TimeUnit.SECONDS))
        assertTrue("prepareRuntime after relicense failed: $runtimeError", runtimeError == null)
        writer.append("runtime-recovery", mapOf("licenseError" to licenseError, "runtimeError" to runtimeError))
    }

    private fun standardParams(police: Boolean = true): Map<String, Any> = mapOf(
        "enablePartialResult" to true,
        "enablePoliceEnhancement" to police,
        "maxAudioDuration" to 300_000,
        "endpointMaxUtteranceMs" to 60_000,
        "vadEnd" to 1_500,
    )

    private fun pttParams(): Map<String, Any> = mapOf(
        "enablePartialResult" to true,
        "enablePoliceEnhancement" to true,
        "maxAudioDuration" to 62_000,
        "endpointMaxUtteranceMs" to 20_000,
        "enableContinuousRecognition" to true,
        "vadEnd" to 1_600,
    )

    private fun longMeetingParams(maxAudioDurationMs: Int): Map<String, Any> = mapOf(
        "enablePartialResult" to true,
        "enablePoliceEnhancement" to true,
        "maxAudioDuration" to maxAudioDurationMs,
        "endpointMaxUtteranceMs" to 60_000,
        "enableContinuousRecognition" to false,
        "vadEnd" to 1_500,
    )

    private fun voiceprintParams(voiceprintId: String): Map<String, Any> = mapOf(
        "enablePartialResult" to true,
        "enablePoliceEnhancement" to true,
        "enableVoiceprintVerification" to true,
        "enableSpeakerVad" to true,
        "voiceprintIds" to listOf(voiceprintId),
        "speakerVadThreshold" to 0.35,
        "speakerVadWindowMs" to 1_500,
        "speakerVadHopMs" to 500,
        "speakerVadConsecutiveBelow" to 2,
        "vadBegin" to 1_000,
        "vadEnd" to 1_600,
        "maxAudioDuration" to 62_000,
        "endpointMaxUtteranceMs" to 20_000,
    )

    private fun assertLifecycle(outcome: DecodeOutcome, label: String) {
        val errors = lifecycleErrors(outcome)
        assertTrue("$label lifecycle failures: $errors", errors.isEmpty())
    }

    private fun lifecycleErrors(outcome: DecodeOutcome): List<String> = buildList {
        if (!outcome.completed) add("missing complete")
        if (outcome.errors.isNotEmpty()) add("errors=${outcome.errors}")
        if (outcome.lastBeforeFinish != 0) add("lastBeforeFinish=${outcome.lastBeforeFinish}")
        if (outcome.finals.count { it.isLast } != 1) add("lastCount=${outcome.finals.count { it.isLast }}")
        if (outcome.completeCount != 1) add("completeCount=${outcome.completeCount}")
        val lastIndex = outcome.trace.indexOfFirst { it.kind == "final" && it.isLast }
        val completeIndex = outcome.trace.indexOfFirst { it.kind == "complete" }
        if (lastIndex < 0 || completeIndex <= lastIndex) add("last/complete order invalid")
    }

    private fun wavAssets(path: String): List<String> {
        val children = testContext.assets.list(path).orEmpty()
        if (children.isEmpty()) return if (path.endsWith(".wav", true)) listOf(path) else emptyList()
        return children.flatMap { child -> wavAssets(if (path.isBlank()) child else "$path/$child") }
    }

    private fun assetSha256(asset: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(64 * 1024)
        testContext.assets.open(asset).use { input ->
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                if (count > 0) digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun runnerLong(name: String, fallback: Long): Long =
        InstrumentationRegistry.getArguments().getString(name)?.toLongOrNull() ?: fallback

    private fun normalizeText(value: String): String = value.lowercase()
        .replace(Regex("[\\s，。！？、；：,.!?;:'\"“”‘’（）()【】\\[\\]_-]"), "")

    private fun normalizeDigits(value: String): String {
        var normalized = normalizeText(value)
        mapOf(
            "零" to "0", "〇" to "0", "一" to "1", "幺" to "1", "二" to "2",
            "两" to "2", "三" to "3", "四" to "4", "五" to "5", "六" to "6",
            "七" to "7", "八" to "8", "九" to "9",
        ).forEach { (from, to) -> normalized = normalized.replace(from, to) }
        return normalized
    }

    private data class FinalEvidence(
        val text: String,
        val isLast: Boolean,
        val beginTime: Int?,
        val endTime: Int?,
        val speakerSimilarity: Float?,
        val audioMsAtCallback: Long,
        val wallMs: Long,
    ) {
        fun toJson(): JSONObject = JSONObject()
            .put("text", text)
            .put("isLast", isLast)
            .put("beginTime", beginTime)
            .put("endTime", endTime)
            .put("speakerSimilarity", speakerSimilarity)
            .put("audioMsAtCallback", audioMsAtCallback)
            .put("wallMs", wallMs)
    }

    private data class TraceEvidence(
        val kind: String,
        val isLast: Boolean,
        val audioMsAtCallback: Long,
        val wallMs: Long,
    ) {
        fun toJson(): JSONObject = JSONObject()
            .put("kind", kind)
            .put("isLast", isLast)
            .put("audioMsAtCallback", audioMsAtCallback)
            .put("wallMs", wallMs)
    }

    private data class DecodeOutcome(
        val asset: String,
        val completed: Boolean,
        val completeCount: Int,
        val lastBeforeFinish: Int,
        val finals: List<FinalEvidence>,
        val errors: List<String>,
        val trace: List<TraceEvidence>,
        val maxVadActiveTextGapMs: Long,
    ) {
        val finalText: String get() = finals.filter { it.text.isNotBlank() }.joinToString("") { it.text }

        fun toMap(): Map<String, Any?> = mapOf(
            "asset" to asset,
            "completed" to completed,
            "completeCount" to completeCount,
            "lastBeforeFinish" to lastBeforeFinish,
            "finalText" to finalText,
            "finals" to JSONArray(finals.map { it.toJson() }),
            "errors" to JSONArray(errors),
            "trace" to JSONArray(trace.map { it.toJson() }),
            "maxVadActiveTextGapMs" to maxVadActiveTextGapMs,
        )
    }

    private class TimelineListener(private val acceptedBytes: AtomicLong) : RecognitionListener {
        val started = CountDownLatch(1)
        val complete = CountDownLatch(1)
        val finals: MutableList<FinalEvidence> = Collections.synchronizedList(mutableListOf())
        val errors: MutableList<String> = Collections.synchronizedList(mutableListOf())
        val trace: MutableList<TraceEvidence> = Collections.synchronizedList(mutableListOf())
        private val startedWallMs = SystemClock.elapsedRealtime()

        @Volatile private var completeCount = 0
        @Volatile private var vadActive = false
        @Volatile private var firstSpeechAudioMs = -1L
        @Volatile private var lastNonEmptyTextAudioMs = -1L
        @Volatile private var maxVadActiveTextGapMs = 0L

        override fun onStart(sessionId: String, eventMessage: String) {
            addTrace("start")
            started.countDown()
        }

        override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) {
            when (eventCode) {
                DingqiaoEventCode.SPEECH_BEGIN -> {
                    vadActive = true
                    if (firstSpeechAudioMs < 0) firstSpeechAudioMs = audioMs()
                }
                DingqiaoEventCode.SPEECH_END -> vadActive = false
            }
            addTrace("event:$eventCode")
        }

        override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
            val audioMs = audioMs()
            if (result.result.isNotBlank()) lastNonEmptyTextAudioMs = audioMs
            if (result.isFinal) {
                finals += FinalEvidence(
                    text = result.result,
                    isLast = result.isLast,
                    beginTime = result.beginTime,
                    endTime = result.endTime,
                    speakerSimilarity = result.speakerSimilarity,
                    audioMsAtCallback = audioMs,
                    wallMs = wallMs(),
                )
                addTrace("final", result.isLast)
            } else {
                addTrace("partial")
            }
        }

        override fun onComplete(sessionId: String, eventMessage: String) {
            completeCount += 1
            addTrace("complete")
            complete.countDown()
        }

        override fun onError(sessionId: String, errorCode: Int, errorMessage: String) {
            errors += "$errorCode:$errorMessage"
            addTrace("error:$errorCode")
            complete.countDown()
        }

        fun observeFeedProgress() {
            if (!vadActive) return
            val anchor = maxOf(firstSpeechAudioMs, lastNonEmptyTextAudioMs)
            if (anchor >= 0) maxVadActiveTextGapMs = maxOf(maxVadActiveTextGapMs, audioMs() - anchor)
        }

        fun outcome(asset: String, completed: Boolean, lastBeforeFinish: Int): DecodeOutcome = DecodeOutcome(
            asset = asset,
            completed = completed,
            completeCount = completeCount,
            lastBeforeFinish = lastBeforeFinish,
            finals = synchronized(finals) { finals.toList() },
            errors = synchronized(errors) { errors.toList() },
            trace = synchronized(trace) { trace.toList() },
            maxVadActiveTextGapMs = maxVadActiveTextGapMs,
        )

        private fun addTrace(kind: String, isLast: Boolean = false) {
            trace += TraceEvidence(kind, isLast, audioMs(), wallMs())
        }

        private fun audioMs(): Long = acceptedBytes.get() / 32
        private fun wallMs(): Long = SystemClock.elapsedRealtime() - startedWallMs
    }

    private class EvidenceWriter(context: Context, caseName: String) {
        val file = File(context.filesDir, "customer_bug_gate/$caseName.jsonl").apply {
            parentFile?.mkdirs()
            writeText("", Charsets.UTF_8)
        }

        @Synchronized
        fun append(type: String, fields: Map<String, Any?>) {
            val obj = JSONObject().put("type", type).put("ts", System.currentTimeMillis())
            fields.forEach { (key, value) -> obj.put(key, value ?: JSONObject.NULL) }
            file.appendText(obj.toString() + "\n", Charsets.UTF_8)
        }
    }
}
