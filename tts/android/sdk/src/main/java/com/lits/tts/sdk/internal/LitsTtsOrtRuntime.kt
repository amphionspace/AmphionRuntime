package com.lits.tts.sdk.internal

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.nio.FloatBuffer
import java.nio.LongBuffer
import java.util.Random
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import kotlin.math.cos
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt

internal class LitsTtsOrtRuntime(
    private val layout: LitsTtsAssetInstaller.InstalledLayout,
) : AutoCloseable {
    data class StreamingRuntimeMetrics(
        val hiddenEncoderMs: Long,
        val hiddenEncoderCalls: Int,
        val firstHiddenEncoderMs: Long,
        val decoderMs: Long,
        val decoderCalls: Int,
        val firstDecoderMs: Long,
        val vocoderMs: Long,
        val vocoderCalls: Int,
        val firstVocoderMs: Long,
        val firstChunkMs: Long,
        val chunkCount: Int,
        val melLength: Int,
        val chunkSize: Int,
        val firstChunkSize: Int,
        val finalDecoderMode: String,
    )

    private val environment: OrtEnvironment = OrtEnvironment.getEnvironment()
    private val acousticSession: OrtSession?
    private val vocoderSession: OrtSession
    private val hiddenEncoderSession: OrtSession?
    private val streamDecoderChunkSession: OrtSession?
    private val streamDecoderFinalSession: OrtSession?
    private val streamConditionChunkSession: OrtSession?
    private val streamConditionFinalSession: OrtSession?
    private val streamDecoderStepSession: OrtSession?
    val loadProfileInfo: String

    init {
        val sessionLoadStartedAt = System.nanoTime()
        val executor = Executors.newFixedThreadPool(SESSION_LOAD_THREADS) { runnable ->
            Thread(runnable, "lits-tts-ort-load").apply { isDaemon = true }
        }
        try {
            val acousticFuture = layout.acousticModel?.let { model ->
                executor.submit(Callable { createProfiledSession("acoustic", model.absolutePath, intraOpThreads = SESSION_LOAD_INTRA_OP_THREADS) })
            }
            val vocoderFuture = executor.submit(
                Callable { createProfiledSession("vocoder", layout.vocoderModel.absolutePath, intraOpThreads = SESSION_LOAD_INTRA_OP_THREADS) },
            )
            val hiddenFuture = layout.hiddenEncoderModel?.let { model ->
                executor.submit(Callable { createProfiledSession("hidden", model.absolutePath, intraOpThreads = SESSION_LOAD_INTRA_OP_THREADS) })
            }
            val chunkFuture = layout.streamDecoderChunkModel?.let { model ->
                executor.submit(Callable { createProfiledSession("chunk", model.absolutePath, intraOpThreads = SESSION_LOAD_INTRA_OP_THREADS) })
            }
            val finalFuture = layout.streamDecoderFinalModel?.let { model ->
                executor.submit(Callable { createProfiledSession("final", model.absolutePath, intraOpThreads = SESSION_LOAD_INTRA_OP_THREADS) })
            }
            val conditionChunkFuture = layout.streamConditionChunkModel?.let { model ->
                executor.submit(Callable { createProfiledSession("condChunk", model.absolutePath, intraOpThreads = SESSION_LOAD_INTRA_OP_THREADS) })
            }
            val conditionFinalFuture = layout.streamConditionFinalModel?.let { model ->
                executor.submit(Callable { createProfiledSession("condFinal", model.absolutePath, intraOpThreads = SESSION_LOAD_INTRA_OP_THREADS) })
            }
            val stepFuture = layout.streamDecoderStepModel?.let { model ->
                executor.submit(Callable { createProfiledSession("step", model.absolutePath, intraOpThreads = SESSION_LOAD_INTRA_OP_THREADS) })
            }
            val chunkLoaded = chunkFuture?.get()
            val finalLoaded = finalFuture?.get()
            val conditionChunkLoaded = conditionChunkFuture?.get()
            val conditionFinalLoaded = conditionFinalFuture?.get()
            val stepLoaded = stepFuture?.get()
            val loadedSessions = listOfNotNull(
                acousticFuture?.get(),
                vocoderFuture.get(),
                hiddenFuture?.get(),
                chunkLoaded,
                finalLoaded,
                conditionChunkLoaded,
                conditionFinalLoaded,
                stepLoaded,
            )
            acousticSession = loadedSessions.firstOrNull { it.label == "acoustic" }?.session
            vocoderSession = loadedSessions.first { it.label == "vocoder" }.session
            hiddenEncoderSession = loadedSessions.firstOrNull { it.label == "hidden" }?.session
            streamDecoderChunkSession = chunkLoaded?.session
            streamDecoderFinalSession = finalLoaded?.session
            streamConditionChunkSession = conditionChunkLoaded?.session
            streamConditionFinalSession = conditionFinalLoaded?.session
            streamDecoderStepSession = stepLoaded?.session
            loadProfileInfo = buildString {
                append("ortcreateWall=").append(elapsedMs(sessionLoadStartedAt)).append("ms")
                for (loaded in loadedSessions) {
                    append(",").append(loaded.label).append("=").append(loaded.elapsedMs).append("ms")
                }
            }
        } finally {
            executor.shutdown()
        }
    }

    fun synthesize(tokenIds: LongArray, speakerId: Int): FloatArray {
        val activeAcousticSession = acousticSession ?: error("acoustic session is unavailable")
        OnnxTensor.createTensor(environment, LongBuffer.wrap(tokenIds), longArrayOf(1L, tokenIds.size.toLong())).use { tokenTensor ->
            OnnxTensor.createTensor(environment, LongBuffer.wrap(longArrayOf(tokenIds.size.toLong())), longArrayOf(1L)).use { lengthTensor ->
                OnnxTensor.createTensor(environment, LongBuffer.wrap(longArrayOf(speakerId.toLong())), longArrayOf(1L)).use { speakerTensor ->
                    val acousticInputs = mapOf(
                        "token_ids" to tokenTensor,
                        "token_lengths" to lengthTensor,
                        "speaker_id" to speakerTensor,
                    )
                    activeAcousticSession.run(acousticInputs, setOf("mel")).use { acousticResult ->
                        val melTensor = acousticResult.get("mel").orElseThrow {
                            IllegalStateException("acoustic output 'mel' missing")
                        } as OnnxTensor
                        val melInfo = melTensor.info as ai.onnxruntime.TensorInfo
                        val melValues = melTensor.floatBuffer.toFloatArray(melInfo.numElements.toInt())
                        OnnxTensor.createTensor(environment, FloatBuffer.wrap(melValues), melInfo.shape).use { melInputTensor ->
                            vocoderSession.run(mapOf("mel" to melInputTensor), setOf("waveform")).use { vocoderResult ->
                                val waveformTensor = vocoderResult.get("waveform").orElseThrow {
                                    IllegalStateException("vocoder output 'waveform' missing")
                                } as OnnxTensor
                                val info = waveformTensor.info as ai.onnxruntime.TensorInfo
                                return waveformTensor.floatBuffer.toFloatArray(info.numElements.toInt())
                            }
                        }
                    }
                }
            }
        }
    }

    fun synthesizeStreaming(
        tokenIds: LongArray,
        speakerId: Int,
        manifest: LitsTtsAssetInstaller.ManifestInfo,
        chunkSizeOverride: Int? = null,
        firstChunkSizeOverride: Int? = null,
        onChunk: (FloatArray) -> Unit,
    ): StreamingRuntimeMetrics {
        val hiddenSession = hiddenEncoderSession ?: error("hidden encoder session is unavailable")
        val externalLoop = manifest.streamDecoderExternalLoop
        val chunkSession = if (externalLoop) null else streamDecoderChunkSession ?: error("stream decoder chunk session is unavailable")
        val finalSession = if (externalLoop) null else streamDecoderFinalSession ?: error("stream decoder final session is unavailable")
        val conditionChunkSession = if (externalLoop) {
            streamConditionChunkSession ?: error("stream condition chunk session is unavailable")
        } else {
            null
        }
        val conditionFinalSession = if (externalLoop) {
            streamConditionFinalSession ?: error("stream condition final session is unavailable")
        } else {
            null
        }
        val stepSession = if (externalLoop) {
            streamDecoderStepSession ?: error("stream decoder step session is unavailable")
        } else {
            null
        }
        val runtimeStartedAt = System.nanoTime()
        val hiddenStartedAt = System.nanoTime()
        val hidden = runHiddenEncoder(hiddenSession, tokenIds, speakerId)
        val hiddenEncoderMs = elapsedMs(hiddenStartedAt)
        val melLength = hidden.melLength
        val chunkSize = chunkSizeOverride?.takeIf { it > 0 } ?: manifest.streamingChunkSize
        val firstChunkSize = firstChunkSizeOverride?.takeIf { it > 0 } ?: chunkSize
        val preLookaheadLen = manifest.streamingPreLookaheadLen
        val melCacheLen = manifest.streamingMelCacheLen
        val sourceCacheLen = melCacheLen * manifest.hopLength
        val speechWindow = hammingWindow(sourceCacheLen * 2)

        val chunkSlices = buildStreamingChunkSlices(
            melLength = melLength,
            firstChunkSize = firstChunkSize,
            chunkSize = chunkSize,
        )
        var melCache: FloatArray? = null
        var waveformCache: FloatArray? = null
        var decoderMs = 0L
        var decoderCalls = 0
        var vocoderMs = 0L
        var vocoderCalls = 0
        var firstChunkMs = -1L
        var firstDecoderMs = -1L
        var firstVocoderMs = -1L
        var chunkCount = 0

        for ((index, chunkSlice) in chunkSlices.withIndex()) {
            val startIdx = chunkSlice.startIdx
            val currentChunkSize = chunkSlice.chunkSize
            val finalize = index == chunkSlices.lastIndex
            val windowStartIdx = max(0, startIdx - chunkSlice.previousChunkSize)
            val windowEndIdx = if (finalize) {
                melLength
            } else {
                min(melLength, startIdx + currentChunkSize + preLookaheadLen)
            }
            val windowFrames = max(0, windowEndIdx - windowStartIdx)
            var windowMuY = hidden.muY.sliceFrameRange(
                startFrame = windowStartIdx,
                frameCount = windowFrames,
                channels = hidden.muYShape[1].toInt(),
            )
            val outputFrames = if (finalize) {
                windowFrames
            } else {
                max(1, windowFrames - preLookaheadLen)
            }
            val windowMask = hidden.yMask.copyOfRange(windowStartIdx, windowStartIdx + outputFrames)
            val speakerEmbedding = hidden.speakerEmbedding
            val decoderStartedAt = System.nanoTime()
            val melWindow = if (externalLoop) {
                runExternalLoopDecoder(
                    conditionSession = if (finalize) {
                        conditionFinalSession ?: error("stream condition final session is unavailable")
                    } else {
                        conditionChunkSession ?: error("stream condition chunk session is unavailable")
                    },
                    stepSession = stepSession ?: error("stream decoder step session is unavailable"),
                    muY = windowMuY,
                    muFrames = windowFrames,
                    yMask = windowMask,
                    maskFrames = outputFrames,
                    speakerEmbedding = speakerEmbedding,
                    speakerEmbeddingShape = hidden.speakerEmbeddingShape,
                    timesteps = manifest.streamDecoderTimesteps,
                    temperature = manifest.streamDecoderTemperature,
                    seed = DECODER_NOISE_BASE_SEED + index,
                )
            } else {
                runDecoder(
                    session = if (finalize) {
                        finalSession ?: error("stream decoder final session is unavailable")
                    } else {
                        chunkSession ?: error("stream decoder chunk session is unavailable")
                    },
                    muY = windowMuY,
                    muFrames = windowFrames,
                    yMask = windowMask,
                    maskFrames = outputFrames,
                    speakerEmbedding = speakerEmbedding,
                    speakerEmbeddingShape = hidden.speakerEmbeddingShape,
                )
            }
            val decoderElapsedMs = elapsedMs(decoderStartedAt)
            decoderMs += decoderElapsedMs
            decoderCalls += if (externalLoop) manifest.streamDecoderTimesteps + 1 else 1
            var melChunk = melWindow.sliceFramesFrom(startIdx - windowStartIdx, hidden.muYShape[1].toInt())
            if (melCache != null) {
                melChunk = melCache.concatFrames(melChunk, hidden.muYShape[1].toInt())
            }
            val vocoderStartedAt = System.nanoTime()
            var waveform = runVocoder(melChunk, hidden.muYShape[1].toInt())
            val vocoderElapsedMs = elapsedMs(vocoderStartedAt)
            vocoderMs += vocoderElapsedMs
            vocoderCalls += 1
            if (waveformCache != null) {
                crossfadeLeadingInPlace(waveform, waveformCache, speechWindow)
            }
            val emitSamples = if (!finalize) (waveform.size - sourceCacheLen).coerceAtLeast(0) else waveform.size
            if (!finalize) {
                melCache = melChunk.tailFrames(melCacheLen, hidden.muYShape[1].toInt())
                waveformCache = waveform.takeLast(sourceCacheLen)
            }
            if (emitSamples > 0) {
                if (firstChunkMs < 0L) {
                    firstChunkMs = elapsedMs(runtimeStartedAt)
                    firstDecoderMs = decoderElapsedMs
                    firstVocoderMs = vocoderElapsedMs
                }
                chunkCount += 1
                onChunk(waveform.prefix(emitSamples))
            }
        }
        return StreamingRuntimeMetrics(
            hiddenEncoderMs = hiddenEncoderMs,
            hiddenEncoderCalls = 1,
            firstHiddenEncoderMs = hiddenEncoderMs,
            decoderMs = decoderMs,
            decoderCalls = decoderCalls,
            firstDecoderMs = firstDecoderMs,
            vocoderMs = vocoderMs,
            vocoderCalls = vocoderCalls,
            firstVocoderMs = firstVocoderMs,
            firstChunkMs = firstChunkMs,
            chunkCount = chunkCount,
            melLength = melLength,
            chunkSize = chunkSize,
            firstChunkSize = firstChunkSize,
            finalDecoderMode = if (externalLoop) "external_loop" else "final_session_preloaded",
        )
    }

    override fun close() {
        streamDecoderFinalSession?.close()
        streamDecoderChunkSession?.close()
        streamDecoderStepSession?.close()
        streamConditionFinalSession?.close()
        streamConditionChunkSession?.close()
        hiddenEncoderSession?.close()
        vocoderSession.close()
        acousticSession?.close()
    }

    companion object {
        internal data class StreamingChunkSlice(
            val startIdx: Int,
            val chunkSize: Int,
            val previousChunkSize: Int,
        )

        internal fun buildStreamingChunkSlices(
            melLength: Int,
            firstChunkSize: Int,
            chunkSize: Int,
        ): List<StreamingChunkSlice> {
            val normalizedFirstChunkSize = firstChunkSize.coerceAtLeast(1)
            val normalizedChunkSize = chunkSize.coerceAtLeast(1)
            if (melLength <= normalizedFirstChunkSize) {
                return listOf(StreamingChunkSlice(startIdx = 0, chunkSize = normalizedFirstChunkSize, previousChunkSize = 0))
            }

            val remainingAfterFirst = melLength - normalizedFirstChunkSize
            val upper = melLength - (remainingAfterFirst % normalizedChunkSize)
            val slices = mutableListOf<StreamingChunkSlice>()
            var startIdx = 0
            var currentChunkSize = normalizedFirstChunkSize
            var previousChunkSize = 0
            while (startIdx < upper) {
                slices += StreamingChunkSlice(
                    startIdx = startIdx,
                    chunkSize = currentChunkSize,
                    previousChunkSize = previousChunkSize,
                )
                previousChunkSize = currentChunkSize
                startIdx += currentChunkSize
                currentChunkSize = normalizedChunkSize
            }
            return slices.ifEmpty {
                listOf(StreamingChunkSlice(startIdx = 0, chunkSize = normalizedFirstChunkSize, previousChunkSize = 0))
            }
        }

        private fun createSessionOptions(
            intraOpThreads: Int,
            optimizationLevel: OrtSession.SessionOptions.OptLevel = DEFAULT_OPTIMIZATION_LEVEL,
        ): OrtSession.SessionOptions {
            return OrtSession.SessionOptions().apply {
                setIntraOpNumThreads(intraOpThreads)
                setInterOpNumThreads(1)
                setExecutionMode(OrtSession.SessionOptions.ExecutionMode.SEQUENTIAL)
                setOptimizationLevel(optimizationLevel)
            }
        }

        private fun vocoderThreads(): Int {
            return 2
        }

        fun floatToPcm16(waveform: FloatArray): ShortArray = ShortArray(waveform.size) { index ->
            val clipped = max(-1.0f, min(1.0f, waveform[index]))
            (clipped * Short.MAX_VALUE).roundToInt().toShort()
        }

        fun floatToPcm16Bytes(waveform: FloatArray): ByteArray {
            val output = ByteArray(waveform.size * 2)
            for (index in waveform.indices) {
                val clipped = max(-1.0f, min(1.0f, waveform[index]))
                val value = (clipped * Short.MAX_VALUE).roundToInt()
                output[index * 2] = (value and 0xff).toByte()
                output[index * 2 + 1] = ((value ushr 8) and 0xff).toByte()
            }
            return output
        }

        val DEFAULT_OPTIMIZATION_LEVEL: OrtSession.SessionOptions.OptLevel = OrtSession.SessionOptions.OptLevel.NO_OPT
        const val SESSION_LOAD_THREADS = 4
        const val SESSION_LOAD_INTRA_OP_THREADS = 1
        const val DECODER_NOISE_BASE_SEED = 20260624L

    }

    private data class ProfiledSession(
        val label: String,
        val session: OrtSession,
        val elapsedMs: Long,
    )

    private data class HiddenEncoderOutput(
        val muY: FloatArray,
        val muYShape: LongArray,
        val yMask: FloatArray,
        val melLength: Int,
        val speakerEmbedding: FloatArray,
        val speakerEmbeddingShape: LongArray,
    )

    private fun runHiddenEncoder(
        session: OrtSession,
        tokenIds: LongArray,
        speakerId: Int,
    ): HiddenEncoderOutput {
        OnnxTensor.createTensor(environment, LongBuffer.wrap(tokenIds), longArrayOf(1L, tokenIds.size.toLong())).use { tokenTensor ->
            OnnxTensor.createTensor(environment, LongBuffer.wrap(longArrayOf(tokenIds.size.toLong())), longArrayOf(1L)).use { lengthTensor ->
                OnnxTensor.createTensor(environment, LongBuffer.wrap(longArrayOf(speakerId.toLong())), longArrayOf(1L)).use { speakerTensor ->
                    session.run(
                        mapOf(
                            "token_ids" to tokenTensor,
                            "token_lengths" to lengthTensor,
                            "speaker_id" to speakerTensor,
                        ),
                        setOf("mu_y", "y_mask", "mel_length", "speaker_embedding"),
                    ).use { result ->
                        val muYTensor = result.get("mu_y").orElseThrow { IllegalStateException("hidden output 'mu_y' missing") } as OnnxTensor
                        val yMaskTensor = result.get("y_mask").orElseThrow { IllegalStateException("hidden output 'y_mask' missing") } as OnnxTensor
                        val melLengthTensor = result.get("mel_length").orElseThrow { IllegalStateException("hidden output 'mel_length' missing") } as OnnxTensor
                        val speakerEmbeddingTensor = result.get("speaker_embedding").orElseThrow {
                            IllegalStateException("hidden output 'speaker_embedding' missing")
                        } as OnnxTensor
                        val muYInfo = muYTensor.info as ai.onnxruntime.TensorInfo
                        val yMaskInfo = yMaskTensor.info as ai.onnxruntime.TensorInfo
                        val speakerInfo = speakerEmbeddingTensor.info as ai.onnxruntime.TensorInfo
                        return HiddenEncoderOutput(
                            muY = muYTensor.floatBuffer.toFloatArray(muYInfo.numElements.toInt()),
                            muYShape = muYInfo.shape,
                            yMask = yMaskTensor.floatBuffer.toFloatArray(yMaskInfo.numElements.toInt()),
                            melLength = melLengthTensor.longBuffer.toLongArray(1).first().toInt(),
                            speakerEmbedding = speakerEmbeddingTensor.floatBuffer.toFloatArray(speakerInfo.numElements.toInt()),
                            speakerEmbeddingShape = speakerInfo.shape,
                        )
                    }
                }
            }
        }
    }

    private fun createProfiledSession(
        label: String,
        modelPath: String,
        intraOpThreads: Int,
    ): ProfiledSession {
        val startedAt = System.nanoTime()
        val session = environment.createSession(modelPath, createSessionOptions(intraOpThreads = intraOpThreads))
        return ProfiledSession(label = label, session = session, elapsedMs = elapsedMs(startedAt))
    }

    private fun runDecoder(
        session: OrtSession,
        muY: FloatArray,
        muFrames: Int,
        yMask: FloatArray,
        maskFrames: Int,
        speakerEmbedding: FloatArray,
        speakerEmbeddingShape: LongArray,
    ): FloatArray {
        val channels = if (muFrames == 0) 80 else muY.size / muFrames
        OnnxTensor.createTensor(environment, FloatBuffer.wrap(muY), longArrayOf(1L, channels.toLong(), muFrames.toLong())).use { muTensor ->
            OnnxTensor.createTensor(environment, FloatBuffer.wrap(yMask), longArrayOf(1L, 1L, maskFrames.toLong())).use { maskTensor ->
                OnnxTensor.createTensor(environment, FloatBuffer.wrap(speakerEmbedding), speakerEmbeddingShape).use { speakerTensor ->
                    session.run(
                        mapOf(
                            "mu_y" to muTensor,
                            "y_mask" to maskTensor,
                            "speaker_embedding" to speakerTensor,
                        ),
                        setOf("mel"),
                    ).use { result ->
                        val melTensor = result.get("mel").orElseThrow { IllegalStateException("decoder output 'mel' missing") } as OnnxTensor
                        val melInfo = melTensor.info as ai.onnxruntime.TensorInfo
                        return melTensor.floatBuffer.toFloatArray(melInfo.numElements.toInt())
                    }
                }
            }
        }
    }

    private fun runExternalLoopDecoder(
        conditionSession: OrtSession,
        stepSession: OrtSession,
        muY: FloatArray,
        muFrames: Int,
        yMask: FloatArray,
        maskFrames: Int,
        speakerEmbedding: FloatArray,
        speakerEmbeddingShape: LongArray,
        timesteps: Int,
        temperature: Float,
        seed: Long,
    ): FloatArray {
        val channels = if (muFrames == 0) 80 else muY.size / muFrames
        val encodedMu = runConditionEncoder(conditionSession, muY, muFrames, yMask, maskFrames, channels)
        val encodedFrames = if (channels == 0) 0 else encodedMu.size / channels
        var x = gaussianNoise(encodedMu.size, temperature, seed)
        var mel = FloatArray(encodedMu.size)
        val stepCount = timesteps.coerceAtLeast(1)
        for (step in 0 until stepCount) {
            val output = runDecoderStep(
                session = stepSession,
                x = x,
                encodedMu = encodedMu,
                yMask = yMask,
                frames = encodedFrames,
                speakerEmbedding = speakerEmbedding,
                speakerEmbeddingShape = speakerEmbeddingShape,
                channels = channels,
                t = step.toFloat() / stepCount.toFloat(),
                dt = 1.0f / stepCount.toFloat(),
            )
            x = output.xNext
            mel = output.mel
        }
        return mel
    }

    private fun runConditionEncoder(
        session: OrtSession,
        muY: FloatArray,
        muFrames: Int,
        yMask: FloatArray,
        maskFrames: Int,
        channels: Int,
    ): FloatArray {
        OnnxTensor.createTensor(environment, FloatBuffer.wrap(muY), longArrayOf(1L, channels.toLong(), muFrames.toLong())).use { muTensor ->
            OnnxTensor.createTensor(environment, FloatBuffer.wrap(yMask), longArrayOf(1L, 1L, maskFrames.toLong())).use { maskTensor ->
                session.run(
                    mapOf("mu_y" to muTensor, "y_mask" to maskTensor),
                    setOf("encoded_mu"),
                ).use { result ->
                    val encodedTensor = result.get("encoded_mu").orElseThrow { IllegalStateException("condition output 'encoded_mu' missing") } as OnnxTensor
                    val encodedInfo = encodedTensor.info as ai.onnxruntime.TensorInfo
                    return encodedTensor.floatBuffer.toFloatArray(encodedInfo.numElements.toInt())
                }
            }
        }
    }

    private data class DecoderStepOutput(
        val xNext: FloatArray,
        val mel: FloatArray,
    )

    private fun runDecoderStep(
        session: OrtSession,
        x: FloatArray,
        encodedMu: FloatArray,
        yMask: FloatArray,
        frames: Int,
        speakerEmbedding: FloatArray,
        speakerEmbeddingShape: LongArray,
        channels: Int,
        t: Float,
        dt: Float,
    ): DecoderStepOutput {
        OnnxTensor.createTensor(environment, FloatBuffer.wrap(x), longArrayOf(1L, channels.toLong(), frames.toLong())).use { xTensor ->
            OnnxTensor.createTensor(environment, FloatBuffer.wrap(encodedMu), longArrayOf(1L, channels.toLong(), frames.toLong())).use { muTensor ->
                OnnxTensor.createTensor(environment, FloatBuffer.wrap(yMask), longArrayOf(1L, 1L, frames.toLong())).use { maskTensor ->
                    OnnxTensor.createTensor(environment, FloatBuffer.wrap(speakerEmbedding), speakerEmbeddingShape).use { speakerTensor ->
                        OnnxTensor.createTensor(environment, FloatBuffer.wrap(floatArrayOf(t)), longArrayOf(1L)).use { tTensor ->
                            OnnxTensor.createTensor(environment, FloatBuffer.wrap(floatArrayOf(dt)), longArrayOf(1L)).use { dtTensor ->
                                session.run(
                                    mapOf(
                                        "x" to xTensor,
                                        "encoded_mu" to muTensor,
                                        "y_mask" to maskTensor,
                                        "speaker_embedding" to speakerTensor,
                                        "t" to tTensor,
                                        "dt" to dtTensor,
                                    ),
                                    setOf("x_next", "mel"),
                                ).use { result ->
                                    val xNextTensor = result.get("x_next").orElseThrow { IllegalStateException("decoder step output 'x_next' missing") } as OnnxTensor
                                    val melTensor = result.get("mel").orElseThrow { IllegalStateException("decoder step output 'mel' missing") } as OnnxTensor
                                    val xNextInfo = xNextTensor.info as ai.onnxruntime.TensorInfo
                                    val melInfo = melTensor.info as ai.onnxruntime.TensorInfo
                                    return DecoderStepOutput(
                                        xNext = xNextTensor.floatBuffer.toFloatArray(xNextInfo.numElements.toInt()),
                                        mel = melTensor.floatBuffer.toFloatArray(melInfo.numElements.toInt()),
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    private fun gaussianNoise(size: Int, scale: Float, seed: Long): FloatArray {
        val random = Random(seed)
        val output = FloatArray(size)
        var index = 0
        while (index < size) {
            val u1 = random.nextDouble().coerceAtLeast(1e-12)
            val u2 = random.nextDouble()
            val radius = sqrt(-2.0 * ln(u1))
            val angle = 2.0 * Math.PI * u2
            output[index++] = (radius * cos(angle) * scale).toFloat()
            if (index < size) {
                output[index++] = (radius * sin(angle) * scale).toFloat()
            }
        }
        return output
    }

    private fun runVocoder(mel: FloatArray, melChannels: Int): FloatArray {
        val melFrames = if (melChannels == 0) 0 else mel.size / melChannels
        OnnxTensor.createTensor(environment, FloatBuffer.wrap(mel), longArrayOf(1L, melChannels.toLong(), melFrames.toLong())).use { melTensor ->
            vocoderSession.run(mapOf("mel" to melTensor), setOf("waveform")).use { result ->
                val waveformTensor = result.get("waveform").orElseThrow { IllegalStateException("vocoder output 'waveform' missing") } as OnnxTensor
                val info = waveformTensor.info as ai.onnxruntime.TensorInfo
                return waveformTensor.floatBuffer.toFloatArray(info.numElements.toInt())
            }
        }
    }

    private fun FloatArray.sliceFrames(frameCount: Int, channels: Int): FloatArray {
        if (frameCount <= 0) return FloatArray(0)
        val output = FloatArray(channels * frameCount)
        for (channel in 0 until channels) {
            val srcStart = channel * (size / channels)
            val dstStart = channel * frameCount
            copyInto(output, destinationOffset = dstStart, startIndex = srcStart, endIndex = srcStart + frameCount)
        }
        return output
    }

    private fun FloatArray.sliceFramesFrom(startFrame: Int, channels: Int): FloatArray {
        val totalFrames = size / channels
        val frameCount = max(0, totalFrames - startFrame)
        val output = FloatArray(channels * frameCount)
        for (channel in 0 until channels) {
            val srcStart = channel * totalFrames + startFrame
            val dstStart = channel * frameCount
            copyInto(output, destinationOffset = dstStart, startIndex = srcStart, endIndex = srcStart + frameCount)
        }
        return output
    }

    private fun FloatArray.sliceFrameRange(startFrame: Int, frameCount: Int, channels: Int): FloatArray {
        if (frameCount <= 0) return FloatArray(0)
        val totalFrames = size / channels
        val safeStart = startFrame.coerceIn(0, totalFrames)
        val safeFrameCount = min(frameCount, totalFrames - safeStart)
        val output = FloatArray(channels * safeFrameCount)
        for (channel in 0 until channels) {
            val srcStart = channel * totalFrames + safeStart
            val dstStart = channel * safeFrameCount
            copyInto(output, destinationOffset = dstStart, startIndex = srcStart, endIndex = srcStart + safeFrameCount)
        }
        return output
    }

    private fun FloatArray.tailFrames(frameCount: Int, channels: Int): FloatArray {
        val totalFrames = size / channels
        val startFrame = max(0, totalFrames - frameCount)
        return sliceFramesFrom(startFrame, channels)
    }

    private fun FloatArray.concatFrames(other: FloatArray, channels: Int): FloatArray {
        if (isEmpty()) return other
        if (other.isEmpty()) return this
        val leftFrames = size / channels
        val rightFrames = other.size / channels
        val output = FloatArray(channels * (leftFrames + rightFrames))
        for (channel in 0 until channels) {
            val outputStart = channel * (leftFrames + rightFrames)
            copyInto(output, destinationOffset = outputStart, startIndex = channel * leftFrames, endIndex = channel * leftFrames + leftFrames)
            other.copyInto(
                output,
                destinationOffset = outputStart + leftFrames,
                startIndex = channel * rightFrames,
                endIndex = channel * rightFrames + rightFrames,
            )
        }
        return output
    }

    private fun FloatArray.takeLast(count: Int): FloatArray {
        if (count <= 0 || isEmpty()) return FloatArray(0)
        val actual = min(count, size)
        return copyOfRange(size - actual, size)
    }

    private fun FloatArray.prefix(count: Int): FloatArray {
        if (count >= size) return this
        if (count <= 0) return FloatArray(0)
        return copyOfRange(0, count)
    }

    private fun crossfadeLeadingInPlace(waveform: FloatArray, previousTail: FloatArray, window: FloatArray) {
        val overlap = min(min(previousTail.size, waveform.size), window.size / 2)
        if (overlap <= 0) return
        for (index in 0 until overlap) {
            waveform[index] = waveform[index] * window[index] + previousTail[previousTail.size - overlap + index] * window[overlap + index]
        }
    }

    private fun hammingWindow(size: Int): FloatArray {
        if (size <= 0) return FloatArray(0)
        if (size == 1) return floatArrayOf(1.0f)
        val output = FloatArray(size)
        for (index in 0 until size) {
            output[index] = (0.54 - 0.46 * cos((2.0 * Math.PI * index) / (size - 1))).toFloat()
        }
        return output
    }
}

private fun FloatBuffer.toFloatArray(size: Int): FloatArray {
    val duplicate = duplicate()
    duplicate.rewind()
    return FloatArray(size).also { duplicate.get(it) }
}

private fun LongBuffer.toLongArray(size: Int): LongArray {
    val duplicate = duplicate()
    duplicate.rewind()
    return LongArray(size).also { duplicate.get(it) }
}

private fun elapsedMs(startedAt: Long): Long = (System.nanoTime() - startedAt) / 1_000_000L
