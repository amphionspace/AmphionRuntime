package com.amphion.asr.sample.plate

import android.util.Log
import com.amphion.asr.AsrCallback
import com.amphion.asr.AsrEngine
import com.amphion.asr.AsrError
import com.amphion.asr.AsrResult
import com.amphion.asr.AsrSession
import com.amphion.asr.sample.AudioRecorder
import com.amphion.asr.sample.WavIo
import com.amphion.police.plate.PlateEnhance
import com.amphion.police.plate.PlateNormalizer
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * 端侧批量车牌评测：读 WAV → +10dB → acceptPcmShort → onFinal → PlateNormalizer → TSV。
 *
 * 与 [com.amphion.asr.sample.MainActivity] 麦克风链路同口径（不含目标说话人门控）。
 * 批量模式：连续灌 PCM（不对齐实时）、尾静音 flush、等 onFinal 后再 close session。
 */
class PlateBatchEvalRunner(
    private val engine: AsrEngine,
    private val normalizer: PlateNormalizer,
    private val evalRecorder: PlateEvalRecorder,
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
        cases: List<BatchEvalCase>,
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
                    val norm = PlateEnhance.apply(outcome.text, normalizer, normalizeEnabled = true)
                    evalRecorder.append(outcome.text, norm, case.expectedPlate)
                    processed++
                    onProgress(
                        Progress(
                            idx + 1,
                            cases.size,
                            case.uttId,
                            if (norm.spans.any { it.valid }) "ok" else "no_plate",
                        ),
                    )
                }
                OutcomeKind.EMPTY -> {
                    failed++
                    val msg = "${case.uttId}: empty ASR"
                    errors.add(msg)
                    Log.w(TAG, msg)
                    val norm = normalizer.normalize("")
                    evalRecorder.append("", norm, case.expectedPlate)
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

    private fun decodeOne(case: BatchEvalCase, gain: Float): Outcome {
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

            // acceptPcm 异步进 decoder 队列；按音频时长等待队列消化后再 stop
            val audioMs = (pcm.size + tailSilenceSamples(TAIL_SILENCE_MS)).toLong() *
                1000L / SAMPLE_RATE
            Thread.sleep(audioMs + DRAIN_BUFFER_MS)

            session!!.stop()

            if (!sessionStopped.await(FINAL_TIMEOUT_SEC, TimeUnit.SECONDS)) {
                Outcome(OutcomeKind.ERROR, message = "timeout waiting session stop")
            } else {
                // onSessionStopped 往往早于 ITN 后的 onFinal
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

    /** 连续灌入 100ms 块（不对齐 wall-clock，与 decode_streaming.py 一致）。 */
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

    /**
     * stop 之后 onFinal 可能晚于 onSessionStopped；轮询直到列表稳定或超时。
     */
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
        private const val TAG = "PlateBatchEval"
        private const val SAMPLE_RATE = 16000
        private const val CHUNK_SAMPLES = 1600 // 100 ms @ 16 kHz
        private const val TAIL_SILENCE_MS = 500
        private const val DRAIN_BUFFER_MS = 800L
        private const val FINAL_TIMEOUT_SEC = 45L
        private const val FINAL_COLLECT_MS = 2500L
    }
}
