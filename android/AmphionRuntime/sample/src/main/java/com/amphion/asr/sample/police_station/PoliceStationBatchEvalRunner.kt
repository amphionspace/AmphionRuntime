package com.amphion.asr.sample.police_station

import android.util.Log
import com.amphion.asr.AsrCallback
import com.amphion.asr.AsrEngine
import com.amphion.asr.AsrError
import com.amphion.asr.AsrResult
import com.amphion.asr.AsrSession
import com.amphion.asr.sample.AsrTextEnhance
import com.amphion.asr.sample.AudioRecorder
import com.amphion.asr.sample.WavIo
import com.amphion.police.plate.PlateNormalizer
import com.amphion.police.station.PoliceStationNormalizeResult
import com.amphion.police.station.PoliceStationNormalizer
import com.amphion.police.terms.PoliceTermsNormalizer
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * 端侧批量派出所评测：读 WAV → +10dB → onFinal → 术语/车牌/派出所后处理 → TSV。
 */
class PoliceStationBatchEvalRunner(
    private val engine: AsrEngine,
    private val termsNormalizer: PoliceTermsNormalizer,
    private val termsNormalizeEnabled: Boolean,
    private val plateNormalizer: PlateNormalizer,
    private val plateNormalizeEnabled: Boolean,
    private val stationNormalizer: PoliceStationNormalizer,
    private val stationNormalizeEnabled: Boolean,
    private val evalRecorder: PoliceStationEvalRecorder,
    private val gainDb: Float = 10f,
) {

    data class Progress(
        val index: Int,
        val total: Int,
        val uttId: String,
        val status: String,
    )

    data class Result(
        val processed: Int,
        val skipped: Int,
        val failed: Int,
        val errors: List<String>,
    )

    fun run(
        cases: List<PoliceStationBatchEvalCase>,
        skipIds: Set<String>,
        onProgress: (Progress) -> Unit,
        shouldStop: () -> Boolean,
    ): Result {
        val gain = AudioRecorder.gainFactor(gainDb)
        var processed = 0
        var skipped = 0
        var failed = 0
        val errors = mutableListOf<String>()

        cases.forEachIndexed { idx, case ->
            if (shouldStop()) return Result(processed, skipped, failed, errors)
            if (case.uttId in skipIds) {
                skipped++
                onProgress(Progress(idx + 1, cases.size, case.uttId, "skip"))
                return@forEachIndexed
            }

            onProgress(Progress(idx + 1, cases.size, case.uttId, "decoding"))
            val outcome = decodeOne(case, gain)
            when (outcome.kind) {
                OutcomeKind.OK -> {
                    val enhanced = AsrTextEnhance.apply(
                        outcome.text,
                        termsNormalizer,
                        termsNormalizeEnabled,
                        plateNormalizer,
                        plateNormalizeEnabled,
                        stationNormalizer,
                        stationNormalizeEnabled,
                    )
                    val norm = enhanced.station
                    evalRecorder.append(
                        uttId = case.uttId,
                        refText = case.refText,
                        expectedStation = case.expectedStation,
                        asrRaw = outcome.text,
                        result = norm,
                    )
                    processed++
                    val hit = case.expectedStation.isNotEmpty() &&
                        (outcome.text.contains(case.expectedStation) ||
                            norm.text.contains(case.expectedStation))
                    onProgress(
                        Progress(
                            idx + 1,
                            cases.size,
                            case.uttId,
                            if (hit) "station_hit" else "miss",
                        ),
                    )
                }
                OutcomeKind.EMPTY -> {
                    failed++
                    val msg = "${case.uttId}: empty ASR"
                    errors.add(msg)
                    Log.w(TAG, msg)
                    evalRecorder.append(
                        uttId = case.uttId,
                        refText = case.refText,
                        expectedStation = case.expectedStation,
                        asrRaw = "",
                        result = PoliceStationNormalizeResult("", emptyList()),
                    )
                    onProgress(Progress(idx + 1, cases.size, case.uttId, "empty"))
                }
                OutcomeKind.ERROR -> {
                    failed++
                    errors.add("${case.uttId}: ${outcome.message}")
                    Log.w(TAG, "${case.uttId}: ${outcome.message}")
                    onProgress(Progress(idx + 1, cases.size, case.uttId, "error"))
                }
            }
        }
        return Result(processed, skipped, failed, errors)
    }

    private enum class OutcomeKind { OK, EMPTY, ERROR }

    private data class Outcome(
        val kind: OutcomeKind,
        val text: String = "",
        val message: String = "",
    )

    private fun decodeOne(case: PoliceStationBatchEvalCase, gain: Float): Outcome {
        val pcm = try {
            WavIo.readPcm16k(case.wavFile)
        } catch (t: Throwable) {
            return Outcome(OutcomeKind.ERROR, message = "read wav failed: ${t.message}")
        }
        if (pcm.isEmpty()) {
            return Outcome(OutcomeKind.ERROR, message = "empty pcm: ${case.wavFile.name}")
        }
        if (gain != 1f) AudioRecorder.applyGain(pcm, gain)

        val finals = Collections.synchronizedList(mutableListOf<String>())
        val errorRef = AtomicReference<String?>(null)
        val sessionStopped = CountDownLatch(1)
        var session: AsrSession? = null

        val callback = object : AsrCallback {
            override fun onFinal(result: AsrResult) {
                if (result.text.isNotEmpty()) finals.add(result.text)
            }

            override fun onFinalRejected(result: AsrResult) {
                if (result.text.isNotEmpty()) finals.add(result.text)
            }

            override fun onError(error: AsrError) {
                errorRef.compareAndSet(null, "${error.code} ${error.message}")
            }

            override fun onSessionStopped() {
                sessionStopped.countDown()
            }
        }

        return try {
            session = engine.newSession(callback)
            feedPcmBurst(session!!, pcm)
            feedTrailingSilence(session!!, TAIL_SILENCE_MS)

            val audioMs = (pcm.size + tailSilenceSamples(TAIL_SILENCE_MS)).toLong() *
                1000L / SAMPLE_RATE
            Thread.sleep(audioMs + DRAIN_BUFFER_MS)

            session!!.stop()

            if (!sessionStopped.await(FINAL_TIMEOUT_SEC, TimeUnit.SECONDS)) {
                Outcome(OutcomeKind.ERROR, message = "timeout waiting session stop")
            } else {
                waitForFinals(finals, FINAL_COLLECT_MS)
                errorRef.get()?.let { return Outcome(OutcomeKind.ERROR, message = it) }
                val text = finals.joinToString(" ").trim()
                if (text.isEmpty()) Outcome(OutcomeKind.EMPTY) else Outcome(OutcomeKind.OK, text)
            }
        } catch (t: Throwable) {
            Outcome(OutcomeKind.ERROR, message = t.message ?: "decode failed")
        } finally {
            try {
                session?.close()
            } catch (_: Throwable) {}
        }
    }

    private fun feedPcmBurst(session: AsrSession, pcm: ShortArray) {
        var off = 0
        while (off < pcm.size) {
            val n = minOf(CHUNK_SAMPLES, pcm.size - off)
            session.acceptPcmShort(pcm.copyOfRange(off, off + n))
            off += n
        }
    }

    private fun feedTrailingSilence(session: AsrSession, durationMs: Int) {
        feedPcmBurst(session, ShortArray(tailSilenceSamples(durationMs)))
    }

    private fun tailSilenceSamples(durationMs: Int): Int =
        SAMPLE_RATE * durationMs / 1000

    private fun waitForFinals(finals: MutableList<String>, maxWaitMs: Long) {
        val deadline = System.currentTimeMillis() + maxWaitMs
        var lastSize = finals.size
        var stableMs = 0L
        while (System.currentTimeMillis() < deadline) {
            Thread.sleep(50)
            val size = finals.size
            if (size == lastSize) {
                stableMs += 50
                if (stableMs >= 150) return
            } else {
                lastSize = size
                stableMs = 0
            }
        }
    }

    companion object {
        private const val TAG = "PoliceStationBatchEval"
        private const val SAMPLE_RATE = 16000
        private const val CHUNK_SAMPLES = 1600
        private const val TAIL_SILENCE_MS = 500
        private const val DRAIN_BUFFER_MS = 800L
        private const val FINAL_TIMEOUT_SEC = 45L
        private const val FINAL_COLLECT_MS = 2500L
    }
}
