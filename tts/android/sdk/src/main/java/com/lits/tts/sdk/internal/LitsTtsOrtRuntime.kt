package com.lits.tts.sdk.internal

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.nio.FloatBuffer
import java.nio.LongBuffer
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

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
    val loadProfileInfo: String

    init {
        val sessionProfiles = mutableListOf<String>()
        acousticSession = layout.acousticModel?.let {
            createProfiledSession("acoustic", it.absolutePath, intraOpThreads = 2, sessionProfiles)
        }
        vocoderSession = createProfiledSession("vocoder", layout.vocoderModel.absolutePath, intraOpThreads = vocoderThreads(), sessionProfiles)
        hiddenEncoderSession = layout.hiddenEncoderModel?.let {
            createProfiledSession("hidden", it.absolutePath, intraOpThreads = 2, sessionProfiles)
        }
        streamDecoderChunkSession = layout.streamDecoderChunkModel?.let {
            createProfiledSession("chunk", it.absolutePath, intraOpThreads = 2, sessionProfiles)
        }
        streamDecoderFinalSession = if (USE_ZERO_LOOKAHEAD_FINAL_DECODER) {
            sessionProfiles += "final=chunk_zero_lookahead"
            null
        } else {
            layout.streamDecoderFinalModel?.let {
                createProfiledSession("final", it.absolutePath, intraOpThreads = 2, sessionProfiles)
            }
        }
        loadProfileInfo = sessionProfiles.joinToString(separator = ",")
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
        val chunkSession = streamDecoderChunkSession ?: error("stream decoder chunk session is unavailable")
        val finalSession = streamDecoderFinalSession
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
            if (finalize && USE_ZERO_LOOKAHEAD_FINAL_DECODER) {
                windowMuY = windowMuY.appendZeroFrames(preLookaheadLen, hidden.muYShape[1].toInt())
            }
            val melWindow = runDecoder(
                session = if (finalize && !USE_ZERO_LOOKAHEAD_FINAL_DECODER) {
                    finalSession ?: error("stream decoder final session is unavailable")
                } else {
                    chunkSession
                },
                muY = windowMuY,
                muFrames = if (finalize && USE_ZERO_LOOKAHEAD_FINAL_DECODER) windowFrames + preLookaheadLen else windowFrames,
                yMask = windowMask,
                maskFrames = outputFrames,
                speakerEmbedding = speakerEmbedding,
                speakerEmbeddingShape = hidden.speakerEmbeddingShape,
            )
            val decoderElapsedMs = elapsedMs(decoderStartedAt)
            decoderMs += decoderElapsedMs
            decoderCalls += 1
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
            finalDecoderMode = if (USE_ZERO_LOOKAHEAD_FINAL_DECODER) "chunk_zero_lookahead" else "final_session",
        )
    }

    override fun close() {
        streamDecoderFinalSession?.close()
        streamDecoderChunkSession?.close()
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

        private fun createSessionOptions(intraOpThreads: Int): OrtSession.SessionOptions {
            return OrtSession.SessionOptions().apply {
                setIntraOpNumThreads(intraOpThreads)
                setInterOpNumThreads(1)
                setExecutionMode(OrtSession.SessionOptions.ExecutionMode.SEQUENTIAL)
                setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT)
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

        private const val USE_ZERO_LOOKAHEAD_FINAL_DECODER = true
    }

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
        sessionProfiles: MutableList<String>,
    ): OrtSession {
        val startedAt = System.nanoTime()
        return environment.createSession(modelPath, createSessionOptions(intraOpThreads = intraOpThreads)).also {
            sessionProfiles += "$label=${elapsedMs(startedAt)}ms"
        }
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

    private fun FloatArray.appendZeroFrames(frameCount: Int, channels: Int): FloatArray {
        if (frameCount <= 0 || channels <= 0) return this
        val totalFrames = size / channels
        val output = FloatArray(channels * (totalFrames + frameCount))
        for (channel in 0 until channels) {
            copyInto(
                output,
                destinationOffset = channel * (totalFrames + frameCount),
                startIndex = channel * totalFrames,
                endIndex = channel * totalFrames + totalFrames,
            )
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
