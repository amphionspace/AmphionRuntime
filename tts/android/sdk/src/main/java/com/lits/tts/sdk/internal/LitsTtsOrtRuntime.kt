package com.lits.tts.sdk.internal

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OnnxJavaType
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import ai.onnxruntime.TensorInfo
import android.os.Process
import android.os.SystemClock
import android.util.Log
import java.nio.FloatBuffer
import java.nio.LongBuffer
import java.nio.ShortBuffer
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
    private val parallelSessionCreate: Boolean = LitsTtsRuntimeOptions.parallelOrtCreate,
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
        val secondChunkSize: Int,
        val steadyChunkSize: Int,
        val chunkGrowthFactor: Int,
        val maxChunkSize: Int,
        val melCacheLen: Int,
        val flowStep: Int,
        val finalDecoderMode: String,
        val powerMode: String,
        val cpuBudgetCore: Double,
        val throttleMs: Long,
        val throttleCount: Int,
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
    private val streamDecoderCacheInitSession: OrtSession?
    private val streamDecoderCacheStepSession: OrtSession?
    val loadProfileInfo: String

    init {
        val sessionLoadStartedAt = System.nanoTime()
        val loadDecoderCacheSessions = EXPLICIT_DECODER_CACHE_ENABLED
        val sessionSpecs = listOf(
            SessionSpec("acoustic", layout.acousticModel?.absolutePath),
            SessionSpec("vocoder", layout.vocoderModel.absolutePath),
            SessionSpec("hidden", layout.hiddenEncoderModel?.absolutePath),
            SessionSpec("chunk", layout.streamDecoderChunkModel?.absolutePath),
            SessionSpec("final", layout.streamDecoderFinalModel?.absolutePath),
            SessionSpec("condChunk", layout.streamConditionChunkModel?.absolutePath),
            SessionSpec("condFinal", layout.streamConditionFinalModel?.absolutePath),
            SessionSpec("step", layout.streamDecoderStepModel?.absolutePath),
            SessionSpec("stepCacheInit", layout.streamDecoderCacheInitModel?.absolutePath.takeIf { loadDecoderCacheSessions }),
            SessionSpec("stepCache", layout.streamDecoderCacheStepModel?.absolutePath.takeIf { loadDecoderCacheSessions }),
        )
        val loadedSessions = if (parallelSessionCreate) {
            loadSessionsParallel(sessionSpecs)
        } else {
            loadSessionsSequential(sessionSpecs)
        }
        acousticSession = loadedSessions["acoustic"]?.session
        vocoderSession = loadedSessions["vocoder"]?.session ?: error("vocoder session is unavailable")
        hiddenEncoderSession = loadedSessions["hidden"]?.session
        streamDecoderChunkSession = loadedSessions["chunk"]?.session
        streamDecoderFinalSession = loadedSessions["final"]?.session
        streamConditionChunkSession = loadedSessions["condChunk"]?.session
        streamConditionFinalSession = loadedSessions["condFinal"]?.session
        streamDecoderStepSession = loadedSessions["step"]?.session
        streamDecoderCacheInitSession = loadedSessions["stepCacheInit"]?.session
        streamDecoderCacheStepSession = loadedSessions["stepCache"]?.session
        loadProfileInfo = buildString {
            append("ortcreateWall=").append(elapsedMs(sessionLoadStartedAt)).append("ms")
            append(",parallel=").append(parallelSessionCreate)
            for (loaded in loadedSessions.values) {
                append(",").append(loaded.label).append("=").append(loaded.elapsedMs).append("ms")
            }
        }
    }

    private fun loadSessionsSequential(specs: List<SessionSpec>): Map<String, ProfiledSession> =
        buildMap {
            for (spec in specs) {
                if (spec.path != null) {
                    put(spec.label, createProfiledSession(spec.label, spec.path, intraOpThreads = inferenceThreadsForLabel(spec.label)))
                }
            }
        }

    private fun loadSessionsParallel(specs: List<SessionSpec>): Map<String, ProfiledSession> {
        val activeSpecs = specs.filter { it.path != null }
        if (activeSpecs.size <= 1) return loadSessionsSequential(specs)
        val executor = Executors.newFixedThreadPool(activeSpecs.size.coerceAtMost(SESSION_LOAD_THREADS)) { runnable ->
            Thread(runnable, "lits-tts-ort-load").apply { isDaemon = true }
        }
        val loaded = mutableListOf<ProfiledSession>()
        return try {
            val futures = activeSpecs.associate { spec ->
                spec.label to executor.submit(
                    Callable {
                        createProfiledSession(
                            label = spec.label,
                            modelPath = spec.path ?: error("missing session path"),
                            intraOpThreads = inferenceThreadsForLabel(spec.label),
                        )
                    },
                )
            }
            buildMap {
                for (spec in specs) {
                    val future = futures[spec.label] ?: continue
                    val session = future.get()
                    loaded += session
                    put(spec.label, session)
                }
            }
        } catch (error: Throwable) {
            loaded.forEach { runCatching { it.session.close() } }
            throw error
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
                        val melInfo = melTensor.info as TensorInfo
                        val melValues = readFloatTensor(melTensor)
                        createFloatTensor(vocoderSession, "mel", melValues, melInfo.shape).use { melInputTensor ->
                            vocoderSession.run(mapOf("mel" to melInputTensor), setOf("waveform")).use { vocoderResult ->
                                val waveformTensor = vocoderResult.get("waveform").orElseThrow {
                                    IllegalStateException("vocoder output 'waveform' missing")
                                } as OnnxTensor
                                return readFloatTensor(waveformTensor)
                            }
                        }
                    }
                }
            }
        }
    }

    /**
     * Pay the one-time first-run cost of every streaming session (MLAS thread-pool
     * spin-up, arena allocation, first tensor allocations) with a tiny throwaway
     * synthesis, so the user's first real speak does not carry that penalty.
     * Best-effort: any failure is logged and ignored.
     */
    fun warmup(manifest: LitsTtsAssetInstaller.ManifestInfo) {
        if (!manifest.supportsStreaming) return
        val startedAt = System.nanoTime()
        runCatching {
            synthesizeStreaming(
                tokenIds = WARMUP_TOKEN_IDS,
                speakerId = 0,
                manifest = manifest,
                onChunk = {},
            )
        }.onSuccess {
            Log.i(ORT_LOG_TAG, "warmup complete elapsedMs=${elapsedMs(startedAt)}")
        }.onFailure { error ->
            Log.w(ORT_LOG_TAG, "warmup failed elapsedMs=${elapsedMs(startedAt)}", error)
        }
    }

    fun synthesizeStreaming(
        tokenIds: LongArray,
        speakerId: Int,
        manifest: LitsTtsAssetInstaller.ManifestInfo,
        lengthScale: Float = 1.0f,
        chunkSizeOverride: Int? = null,
        firstChunkSizeOverride: Int? = null,
        secondChunkSizeOverride: Int? = null,
        steadyChunkSizeOverride: Int? = null,
        chunkGrowthFactorOverride: Int? = null,
        maxChunkSizeOverride: Int? = null,
        flowStepOverride: Int? = null,
        previousChunkContextFramesOverride: Int? = null,
        powerModeOverride: String? = null,
        cpuBudgetCoreOverride: Double? = null,
        isCancelled: () -> Boolean = { false },
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
        val conditionFinalSession = if (externalLoop && !manifest.streamFinalZeroPadWithChunkCondition) {
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
        if (isCancelled()) {
            return cancelledStreamingMetrics()
        }
        val hiddenStartedAt = System.nanoTime()
        val hidden = runHiddenEncoder(hiddenSession, tokenIds, speakerId, lengthScale.coerceIn(MIN_LENGTH_SCALE, MAX_LENGTH_SCALE))
        val hiddenEncoderMs = elapsedMs(hiddenStartedAt)
        if (isCancelled()) {
            return cancelledStreamingMetrics(hiddenEncoderMs = hiddenEncoderMs, firstHiddenEncoderMs = hiddenEncoderMs)
        }
        val melLength = hidden.melLength
        val chunkSize = chunkSizeOverride?.takeIf { it > 0 } ?: manifest.streamingChunkSize
        // Keep the explicit decoder-step state cache opt-in. With the default false,
        // every chunk uses the ordinary decoder step model without encoder/decoder
        // state tensors carried between chunks.
        val decoderCacheInfo = manifest.streamDecoderCacheInfo
        val useDecoderCache = EXPLICIT_DECODER_CACHE_ENABLED && externalLoop &&
            LitsTtsRuntimeOptions.decoderCacheEnabled &&
            decoderCacheInfo != null &&
            decoderCacheInfo.requiresFixedChunkSize == chunkSize &&
            streamDecoderCacheInitSession != null &&
            streamDecoderCacheStepSession != null
        val firstChunkSize = if (useDecoderCache) {
            chunkSize
        } else {
            firstChunkSizeOverride?.takeIf { it > 0 } ?: LitsTtsRuntimeOptions.streamingFirstChunkSize
        }
        val secondChunkSize = if (useDecoderCache) {
            chunkSize
        } else {
            secondChunkSizeOverride?.takeIf { it > 0 } ?: LitsTtsRuntimeOptions.streamingSecondChunkSize
        }
        val steadyChunkSize = if (useDecoderCache) {
            chunkSize
        } else {
            steadyChunkSizeOverride?.takeIf { it > 0 } ?: LitsTtsRuntimeOptions.streamingSteadyChunkSize
        }
        val chunkGrowthFactor = if (useDecoderCache) {
            1
        } else {
            chunkGrowthFactorOverride?.takeIf { it > 1 } ?: LitsTtsRuntimeOptions.streamingChunkGrowthFactor
        }
        val maxChunkSize = if (useDecoderCache) {
            chunkSize
        } else {
            maxChunkSizeOverride?.takeIf { it > 0 } ?: LitsTtsRuntimeOptions.streamingMaxChunkSize
        }
        val flowStep = flowStepOverride?.takeIf { it > 0 }
            ?: manifest.streamDecoderTimesteps.takeIf { it > 0 }
            ?: DEFAULT_FLOW_STEP
        val powerConfig = PowerConfig.from(powerModeOverride, cpuBudgetCoreOverride)
        val throttler = CpuBudgetThrottler(
            cpuBudgetCore = powerConfig.cpuBudgetCore,
            maxThrottleSleepMs = powerConfig.maxThrottleSleepMs,
        )
        val preLookaheadLen = manifest.streamingPreLookaheadLen
        val melCacheLen = LitsTtsRuntimeOptions.streamingMelCacheLen.takeIf { it > 0 } ?: manifest.streamingMelCacheLen
        val decoderLeftContextFrames = LitsTtsRuntimeOptions.decoderLeftContextFrames
            .takeIf { it >= 0 }
            ?: 16
        val sourceCacheLen = melCacheLen * manifest.hopLength
        val speechWindow = hammingWindow(sourceCacheLen * 2)

        val chunkSlices = buildStreamingChunkSlices(
            melLength = melLength,
            firstChunkSize = firstChunkSize,
            chunkSize = chunkSize,
            secondChunkSize = secondChunkSize,
            steadyChunkSize = steadyChunkSize,
            chunkGrowthFactor = chunkGrowthFactor,
            maxChunkSize = maxChunkSize,
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
        val decoderStepCaches = if (useDecoderCache) arrayOfNulls<DecoderStepCacheState>(flowStep.coerceAtLeast(1)) else null

        for ((index, chunkSlice) in chunkSlices.withIndex()) {
            if (isCancelled()) {
                break
            }
            val startIdx = chunkSlice.startIdx
            val currentChunkSize = chunkSlice.chunkSize
            val finalize = index == chunkSlices.lastIndex
            val previousContextFrames = previousChunkContextFramesOverride
                ?.takeIf { it >= 0 }
                ?.coerceAtMost(chunkSlice.previousChunkSize)
                ?: min(decoderLeftContextFrames, chunkSlice.previousChunkSize)
            val windowStartIdx = max(0, startIdx - previousContextFrames)
            val windowEndIdx = if (finalize) {
                melLength
            } else {
                min(melLength, startIdx + currentChunkSize + preLookaheadLen)
            }
            val windowFrames = max(0, windowEndIdx - windowStartIdx)
            val channels = hidden.muYShape[1].toInt()
            var windowMuY = hidden.muY.sliceFrameRange(
                startFrame = windowStartIdx,
                frameCount = windowFrames,
                channels = channels,
            )
            val outputFrames = if (finalize) {
                windowFrames
            } else {
                max(1, windowFrames - preLookaheadLen)
            }
            val windowMask = hidden.yMask.copyOfRange(windowStartIdx, windowStartIdx + outputFrames)
            val conditionFrames = if (externalLoop && finalize && manifest.streamFinalZeroPadWithChunkCondition) {
                windowMuY = windowMuY.padTrailingFrames(preLookaheadLen, channels)
                windowFrames + preLookaheadLen
            } else {
                windowFrames
            }
            val speakerEmbedding = hidden.speakerEmbedding
            val decoderStartedAt = System.nanoTime()
            val melWindow = if (externalLoop) {
                runExternalLoopDecoder(
                    conditionSession = if (finalize) {
                        if (manifest.streamFinalZeroPadWithChunkCondition) {
                            conditionChunkSession ?: error("stream condition chunk session is unavailable")
                        } else {
                            conditionFinalSession ?: error("stream condition final session is unavailable")
                        }
                    } else {
                        conditionChunkSession ?: error("stream condition chunk session is unavailable")
                    },
                    stepSession = stepSession ?: error("stream decoder step session is unavailable"),
                    cacheInitSession = streamDecoderCacheInitSession,
                    cacheStepSession = streamDecoderCacheStepSession,
                    cacheInfo = if (useDecoderCache) decoderCacheInfo else null,
                    stepCaches = decoderStepCaches,
                    muY = windowMuY,
                    muFrames = conditionFrames,
                    yMask = windowMask,
                    maskFrames = outputFrames,
                    previousContextFrames = previousContextFrames,
                    speakerEmbedding = speakerEmbedding,
                    speakerEmbeddingShape = hidden.speakerEmbeddingShape,
                    timesteps = flowStep,
                    temperature = manifest.streamDecoderTemperature,
                    seed = DECODER_NOISE_BASE_SEED + index,
                    isCancelled = isCancelled,
                    throttler = throttler,
                )
            } else {
                if (isCancelled()) {
                    break
                }
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
            throttler.maybeThrottle(isCancelled)
            val decoderElapsedMs = elapsedMs(decoderStartedAt)
            decoderMs += decoderElapsedMs
            decoderCalls += if (externalLoop) flowStep + 1 else 1
            if (isCancelled()) {
                break
            }
            var melChunk = melWindow.sliceFramesFrom(startIdx - windowStartIdx, hidden.muYShape[1].toInt())
            if (melCache != null) {
                melChunk = melCache.concatFrames(melChunk, hidden.muYShape[1].toInt())
            }
            if (isCancelled()) {
                break
            }
            val vocoderStartedAt = System.nanoTime()
            var waveform = runVocoder(melChunk, hidden.muYShape[1].toInt())
            throttler.maybeThrottle(isCancelled)
            val vocoderElapsedMs = elapsedMs(vocoderStartedAt)
            vocoderMs += vocoderElapsedMs
            vocoderCalls += 1
            if (isCancelled()) {
                break
            }
            if (waveformCache != null) {
                crossfadeLeadingInPlace(waveform, waveformCache, speechWindow)
            }
            val emitSamples = if (!finalize) (waveform.size - sourceCacheLen).coerceAtLeast(0) else waveform.size
            if (!finalize) {
                melCache = melChunk.tailFrames(melCacheLen, hidden.muYShape[1].toInt())
                waveformCache = waveform.takeLast(sourceCacheLen)
            }
            if (emitSamples > 0) {
                if (isCancelled()) {
                    break
                }
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
            secondChunkSize = secondChunkSize,
            steadyChunkSize = steadyChunkSize,
            chunkGrowthFactor = chunkGrowthFactor,
            maxChunkSize = maxChunkSize,
            melCacheLen = melCacheLen,
            flowStep = flowStep,
            finalDecoderMode = if (externalLoop) {
                if (manifest.streamFinalZeroPadWithChunkCondition) "external_loop_zero_final" else "external_loop"
            } else {
                "final_session_preloaded"
            },
            powerMode = powerConfig.mode,
            cpuBudgetCore = powerConfig.cpuBudgetCore,
            throttleMs = throttler.throttleMs,
            throttleCount = throttler.throttleCount,
        )
    }

    override fun close() {
        streamDecoderFinalSession?.close()
        streamDecoderChunkSession?.close()
        streamDecoderCacheStepSession?.close()
        streamDecoderCacheInitSession?.close()
        streamDecoderStepSession?.close()
        streamConditionFinalSession?.close()
        streamConditionChunkSession?.close()
        hiddenEncoderSession?.close()
        vocoderSession.close()
        acousticSession?.close()
    }

    companion object {
        // Keep the explicit encoder/decoder state-cache experiment disabled for this
        // Android path. The implementation remains present for a later benchmark.
        private const val EXPLICIT_DECODER_CACHE_ENABLED = false

        internal data class StreamingChunkSlice(
            val startIdx: Int,
            val chunkSize: Int,
            val previousChunkSize: Int,
        )

        internal fun buildStreamingChunkSlices(
            melLength: Int,
            firstChunkSize: Int,
            chunkSize: Int,
            secondChunkSize: Int? = null,
            steadyChunkSize: Int? = null,
            chunkGrowthFactor: Int? = null,
            maxChunkSize: Int? = null,
        ): List<StreamingChunkSlice> {
            val normalizedFirstChunkSize = firstChunkSize.coerceAtLeast(1)
            val normalizedChunkSize = chunkSize.coerceAtLeast(1)
            val normalizedSecondChunkSize = secondChunkSize?.coerceAtLeast(1) ?: normalizedChunkSize
            val normalizedSteadyChunkSize = steadyChunkSize?.coerceAtLeast(1) ?: normalizedChunkSize
            val normalizedGrowthFactor = chunkGrowthFactor?.takeIf { it > 1 } ?: 1
            val normalizedMaxChunkSize = maxChunkSize?.coerceAtLeast(1)
            if (melLength <= normalizedFirstChunkSize) {
                return listOf(StreamingChunkSlice(startIdx = 0, chunkSize = normalizedFirstChunkSize, previousChunkSize = 0))
            }
            if (secondChunkSize == null && steadyChunkSize == null && chunkGrowthFactor == null) {
                val remainingAfterFirst = melLength - normalizedFirstChunkSize
                val upper = melLength - (remainingAfterFirst % normalizedChunkSize)
                val legacySlices = mutableListOf<StreamingChunkSlice>()
                var legacyStartIdx = 0
                var legacyCurrentChunkSize = normalizedFirstChunkSize
                var legacyPreviousChunkSize = 0
                while (legacyStartIdx < upper) {
                    legacySlices += StreamingChunkSlice(
                        startIdx = legacyStartIdx,
                        chunkSize = legacyCurrentChunkSize,
                        previousChunkSize = legacyPreviousChunkSize,
                    )
                    legacyPreviousChunkSize = legacyCurrentChunkSize
                    legacyStartIdx += legacyCurrentChunkSize
                    legacyCurrentChunkSize = normalizedChunkSize
                }
                return legacySlices.ifEmpty {
                    listOf(StreamingChunkSlice(startIdx = 0, chunkSize = normalizedFirstChunkSize, previousChunkSize = 0))
                }
            }

            val slices = mutableListOf<StreamingChunkSlice>()
            var startIdx = 0
            var currentChunkSize = normalizedFirstChunkSize
            var previousChunkSize = 0
            while (startIdx < melLength) {
                slices += StreamingChunkSlice(
                    startIdx = startIdx,
                    chunkSize = currentChunkSize,
                    previousChunkSize = previousChunkSize,
                )
                previousChunkSize = currentChunkSize
                startIdx += currentChunkSize
                currentChunkSize = when (slices.size) {
                    1 -> normalizedSecondChunkSize
                    2 -> normalizedSteadyChunkSize
                    else -> {
                        val grown = (currentChunkSize * normalizedGrowthFactor).coerceAtLeast(1)
                        normalizedMaxChunkSize?.let { min(grown, it) } ?: grown
                    }
                }
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
            return LitsTtsRuntimeOptions.vocoderThreads.coerceAtLeast(1)
        }

        private fun inferenceThreadsForLabel(label: String): Int = when (label) {
            "hidden" -> LitsTtsRuntimeOptions.hiddenEncoderThreads
            "condChunk", "condFinal" -> LitsTtsRuntimeOptions.conditionEncoderThreads
            "chunk", "final", "step", "stepCacheInit", "stepCache" ->
                LitsTtsRuntimeOptions.decoderStepThreads
            "vocoder" -> vocoderThreads()
            else -> 1
        }.coerceAtLeast(1)

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

        val DEFAULT_OPTIMIZATION_LEVEL: OrtSession.SessionOptions.OptLevel = optimizationLevelFromProperty()
        const val SESSION_LOAD_THREADS = 4
        const val DEFAULT_FLOW_STEP = 4
        const val DEFAULT_FIRST_CHUNK_SIZE = 25
        const val DEFAULT_BALANCED_CPU_BUDGET_CORE = 0.85
        const val DEFAULT_LOW_POWER_CPU_BUDGET_CORE = 0.55

        /** "ㄅㄚˉ" (ba1) per zh_en_symbols.json — a minimal valid token sequence for warmup. */
        private val WARMUP_TOKEN_IDS = longArrayOf(4L, 26L, 47L)
        const val DECODER_NOISE_BASE_SEED = 20260624L
        const val MIN_LENGTH_SCALE = 0.5f
        const val MAX_LENGTH_SCALE = 2.0f
        const val ORT_LOG_TAG = "LitsTtsOrtRuntime"
        private const val ORT_OPTIMIZATION_PROPERTY = "lits.ort.optimization"

        private fun optimizationLevelFromProperty(): OrtSession.SessionOptions.OptLevel =
            when (System.getProperty(ORT_OPTIMIZATION_PROPERTY)?.trim()?.uppercase()) {
                "NO_OPT" -> OrtSession.SessionOptions.OptLevel.NO_OPT
                "BASIC_OPT" -> OrtSession.SessionOptions.OptLevel.BASIC_OPT
                "EXTENDED_OPT" -> OrtSession.SessionOptions.OptLevel.EXTENDED_OPT
                "LAYOUT_OPT" -> OrtSession.SessionOptions.OptLevel.LAYOUT_OPT
                "ALL_OPT" -> OrtSession.SessionOptions.OptLevel.ALL_OPT
                else -> OrtSession.SessionOptions.OptLevel.ALL_OPT
            }

    }

    private data class ProfiledSession(
        val label: String,
        val session: OrtSession,
        val elapsedMs: Long,
    )

    private data class SessionSpec(
        val label: String,
        val path: String?,
    )

    private data class HiddenEncoderOutput(
        val muY: FloatArray,
        val muYShape: LongArray,
        val yMask: FloatArray,
        val melLength: Int,
        val speakerEmbedding: FloatArray,
        val speakerEmbeddingShape: LongArray,
    )

    private fun createFloatTensor(
        session: OrtSession,
        inputName: String,
        values: FloatArray,
        shape: LongArray,
    ): OnnxTensor {
        val inputType = (session.inputInfo[inputName]?.info as? TensorInfo)?.type
        if (inputType == OnnxJavaType.FLOAT16) {
            val halfValues = ShortArray(values.size) { index -> floatToHalfBits(values[index]) }
            return OnnxTensor.createTensor(environment, ShortBuffer.wrap(halfValues), shape, OnnxJavaType.FLOAT16)
        }
        return OnnxTensor.createTensor(environment, FloatBuffer.wrap(values), shape)
    }

    private fun readFloatTensor(tensor: OnnxTensor): FloatArray {
        val info = tensor.info as TensorInfo
        return if (info.type == OnnxJavaType.FLOAT16) {
            tensor.shortBuffer.toFloatArray(info.numElements.toInt())
        } else {
            tensor.floatBuffer.toFloatArray(info.numElements.toInt())
        }
    }

    private fun runHiddenEncoder(
        session: OrtSession,
        tokenIds: LongArray,
        speakerId: Int,
        lengthScale: Float,
    ): HiddenEncoderOutput {
        OnnxTensor.createTensor(environment, LongBuffer.wrap(tokenIds), longArrayOf(1L, tokenIds.size.toLong())).use { tokenTensor ->
            OnnxTensor.createTensor(environment, LongBuffer.wrap(longArrayOf(tokenIds.size.toLong())), longArrayOf(1L)).use { lengthTensor ->
                OnnxTensor.createTensor(environment, LongBuffer.wrap(longArrayOf(speakerId.toLong())), longArrayOf(1L)).use { speakerTensor ->
                    createFloatTensor(session, "length_scale", floatArrayOf(lengthScale), longArrayOf(1L)).use { lengthScaleTensor ->
                        session.run(
                            mapOf(
                                "token_ids" to tokenTensor,
                                "token_lengths" to lengthTensor,
                                "speaker_id" to speakerTensor,
                                "length_scale" to lengthScaleTensor,
                            ),
                            setOf("mu_y", "y_mask", "mel_length", "speaker_embedding"),
                        ).use { result ->
                            val muYTensor = result.get("mu_y").orElseThrow { IllegalStateException("hidden output 'mu_y' missing") } as OnnxTensor
                            val yMaskTensor = result.get("y_mask").orElseThrow { IllegalStateException("hidden output 'y_mask' missing") } as OnnxTensor
                            val melLengthTensor = result.get("mel_length").orElseThrow { IllegalStateException("hidden output 'mel_length' missing") } as OnnxTensor
                            val speakerEmbeddingTensor = result.get("speaker_embedding").orElseThrow {
                                IllegalStateException("hidden output 'speaker_embedding' missing")
                            } as OnnxTensor
                            val muYInfo = muYTensor.info as TensorInfo
                            val yMaskInfo = yMaskTensor.info as TensorInfo
                            val speakerInfo = speakerEmbeddingTensor.info as TensorInfo
                            val yMaskElements = yMaskInfo.numElements.toInt()
                            val rawMelLength = melLengthTensor.longBuffer.toLongArray(1).first().toInt()
                            return HiddenEncoderOutput(
                                muY = readFloatTensor(muYTensor),
                                muYShape = muYInfo.shape,
                                yMask = readFloatTensor(yMaskTensor),
                                melLength = protectMelLength(rawMelLength, muYInfo.shape, yMaskInfo.shape, yMaskElements),
                                speakerEmbedding = readFloatTensor(speakerEmbeddingTensor),
                                speakerEmbeddingShape = speakerInfo.shape,
                            )
                        }
                    }
                }
            }
        }
    }

    private fun protectMelLength(
        rawMelLength: Int,
        muYShape: LongArray,
        yMaskShape: LongArray,
        yMaskElements: Int,
    ): Int {
        val muFrames = muYShape.getOrNull(2)?.takeIf { it > 0L }?.toInt()
        val maskFrames = yMaskShape.getOrNull(2)?.takeIf { it > 0L }?.toInt()
        val maxFrames = listOfNotNull(muFrames, maskFrames)
            .minOrNull()
            ?: yMaskElements.coerceAtLeast(1)
        return rawMelLength.coerceIn(1, maxFrames.coerceAtLeast(1))
    }

    private fun createProfiledSession(
        label: String,
        modelPath: String,
        intraOpThreads: Int,
    ): ProfiledSession {
        val startedAt = System.nanoTime()
        val file = java.io.File(modelPath)
        Log.i(ORT_LOG_TAG, "createSession start label=$label path=$modelPath bytes=${file.length()} exists=${file.isFile}")
        return try {
            val session = environment.createSession(modelPath, createSessionOptions(intraOpThreads = intraOpThreads))
            ProfiledSession(label = label, session = session, elapsedMs = elapsedMs(startedAt)).also {
                Log.i(ORT_LOG_TAG, "createSession complete label=$label elapsedMs=${it.elapsedMs}")
            }
        } catch (error: Throwable) {
            Log.e(ORT_LOG_TAG, "createSession failed label=$label path=$modelPath bytes=${file.length()}", error)
            throw error
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
        createFloatTensor(session, "mu_y", muY, longArrayOf(1L, channels.toLong(), muFrames.toLong())).use { muTensor ->
            createFloatTensor(session, "y_mask", yMask, longArrayOf(1L, 1L, maskFrames.toLong())).use { maskTensor ->
                createFloatTensor(session, "speaker_embedding", speakerEmbedding, speakerEmbeddingShape).use { speakerTensor ->
                    session.run(
                        mapOf(
                            "mu_y" to muTensor,
                            "y_mask" to maskTensor,
                            "speaker_embedding" to speakerTensor,
                        ),
                        setOf("mel"),
                    ).use { result ->
                        val melTensor = result.get("mel").orElseThrow { IllegalStateException("decoder output 'mel' missing") } as OnnxTensor
                        return readFloatTensor(melTensor)
                    }
                }
            }
        }
    }

    private fun runExternalLoopDecoder(
        conditionSession: OrtSession,
        stepSession: OrtSession,
        cacheInitSession: OrtSession?,
        cacheStepSession: OrtSession?,
        cacheInfo: LitsTtsAssetInstaller.StreamDecoderCacheInfo?,
        stepCaches: Array<DecoderStepCacheState?>?,
        muY: FloatArray,
        muFrames: Int,
        yMask: FloatArray,
        maskFrames: Int,
        previousContextFrames: Int,
        speakerEmbedding: FloatArray,
        speakerEmbeddingShape: LongArray,
        timesteps: Int,
        temperature: Float,
        seed: Long,
        isCancelled: () -> Boolean,
        throttler: CpuBudgetThrottler,
    ): FloatArray {
        val channels = if (muFrames == 0) 80 else muY.size / muFrames
        if (isCancelled()) {
            return FloatArray(channels * maskFrames)
        }
        val encodedMu = runConditionEncoder(conditionSession, muY, muFrames, yMask, maskFrames, channels)
        throttler.maybeThrottle(isCancelled)
        if (isCancelled()) {
            return FloatArray(encodedMu.size)
        }
        val encodedFrames = if (channels == 0) 0 else encodedMu.size / channels
        val cacheEnabled = cacheInfo != null &&
            cacheInitSession != null &&
            cacheStepSession != null &&
            stepCaches != null
        val cacheContextFrames = if (cacheEnabled) previousContextFrames.coerceIn(0, encodedFrames) else 0
        val stepFrames = encodedFrames - cacheContextFrames
        val stepEncodedMu = if (cacheContextFrames > 0) {
            encodedMu.sliceFramesFrom(cacheContextFrames, channels)
        } else {
            encodedMu
        }
        val stepMask = if (cacheContextFrames > 0) {
            yMask.copyOfRange(cacheContextFrames, maskFrames)
        } else {
            yMask
        }
        var x = gaussianNoise(stepEncodedMu.size, temperature, seed)
        var mel = FloatArray(stepEncodedMu.size)
        val stepCount = timesteps.coerceAtLeast(1)
        for (step in 0 until stepCount) {
            if (isCancelled()) {
                break
            }
            val previousState = stepCaches?.getOrNull(step)
            if (cacheEnabled) {
                val output = runDecoderStepWithCache(
                    session = if (previousState == null) {
                        cacheInitSession ?: error("stream decoder cache init session is unavailable")
                    } else {
                        cacheStepSession ?: error("stream decoder cache step session is unavailable")
                    },
                    stateNames = cacheInfo?.stateNames.orEmpty(),
                    previousState = previousState,
                    x = x,
                    encodedMu = stepEncodedMu,
                    yMask = stepMask,
                    frames = stepFrames,
                    speakerEmbedding = speakerEmbedding,
                    speakerEmbeddingShape = speakerEmbeddingShape,
                    channels = channels,
                    t = step.toFloat() / stepCount.toFloat(),
                    dt = 1.0f / stepCount.toFloat(),
                )
                x = output.xNext
                mel = output.mel
                stepCaches?.set(step, output.cache)
            } else {
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
            throttler.maybeThrottle(isCancelled)
        }
        return if (cacheContextFrames > 0) {
            FloatArray(channels * cacheContextFrames).concatFrames(mel, channels)
        } else {
            mel
        }
    }

    private fun cancelledStreamingMetrics(
        hiddenEncoderMs: Long = 0L,
        firstHiddenEncoderMs: Long = -1L,
    ): StreamingRuntimeMetrics {
        return StreamingRuntimeMetrics(
            hiddenEncoderMs = hiddenEncoderMs,
            hiddenEncoderCalls = if (hiddenEncoderMs > 0L) 1 else 0,
            firstHiddenEncoderMs = firstHiddenEncoderMs,
            decoderMs = 0L,
            decoderCalls = 0,
            firstDecoderMs = -1L,
            vocoderMs = 0L,
            vocoderCalls = 0,
            firstVocoderMs = -1L,
            firstChunkMs = -1L,
            chunkCount = 0,
            melLength = 0,
            chunkSize = 0,
            firstChunkSize = 0,
            secondChunkSize = 0,
            steadyChunkSize = 0,
            chunkGrowthFactor = 1,
            maxChunkSize = 0,
            melCacheLen = 0,
            flowStep = 0,
            finalDecoderMode = "cancelled",
            powerMode = "fast",
            cpuBudgetCore = 0.0,
            throttleMs = 0L,
            throttleCount = 0,
        )
    }

    private data class PowerConfig(
        val mode: String,
        val cpuBudgetCore: Double,
        val maxThrottleSleepMs: Long,
    ) {
        companion object {
            fun from(modeOverride: String?, budgetOverride: Double?): PowerConfig {
                val mode = modeOverride?.lowercase()?.trim().orEmpty()
                return when (mode) {
                    "balanced", "balance" -> {
                        val budget = budgetOverride
                            ?.takeIf { it.isFinite() && it > 0.05 }
                            ?.coerceIn(0.5, 1.0)
                            ?: DEFAULT_BALANCED_CPU_BUDGET_CORE
                        PowerConfig("balanced", budget, BALANCED_MAX_THROTTLE_SLEEP_MS)
                    }
                    "low_power" -> {
                        val budget = budgetOverride
                            ?.takeIf { it.isFinite() && it > 0.05 }
                            ?.coerceIn(0.1, 1.0)
                            ?: DEFAULT_LOW_POWER_CPU_BUDGET_CORE
                        PowerConfig("low_power", budget, LOW_POWER_MAX_THROTTLE_SLEEP_MS)
                    }
                    else -> PowerConfig("fast", 0.0, 0L)
                }
            }

            private const val BALANCED_MAX_THROTTLE_SLEEP_MS = 8L
            private const val LOW_POWER_MAX_THROTTLE_SLEEP_MS = 40L
        }
    }

    private class CpuBudgetThrottler(
        private val cpuBudgetCore: Double,
        private val maxThrottleSleepMs: Long,
    ) {
        private val startedWallMs = SystemClock.elapsedRealtime()
        private val startedCpuMs = Process.getElapsedCpuTime()

        var throttleMs: Long = 0L
            private set
        var throttleCount: Int = 0
            private set

        fun maybeThrottle(isCancelled: () -> Boolean) {
            if (cpuBudgetCore <= 0.0 || isCancelled()) return
            val cpuMs = Process.getElapsedCpuTime() - startedCpuMs
            val wallMs = (SystemClock.elapsedRealtime() - startedWallMs).coerceAtLeast(1L)
            val targetWallMs = (cpuMs.toDouble() / cpuBudgetCore).toLong()
            val sleepMs = (targetWallMs - wallMs).coerceIn(0L, maxThrottleSleepMs)
            if (sleepMs <= 0L) return
            try {
                Thread.sleep(sleepMs)
                throttleMs += sleepMs
                throttleCount += 1
            } catch (interrupted: InterruptedException) {
                Thread.currentThread().interrupt()
            }
        }

    }

    private fun runConditionEncoder(
        session: OrtSession,
        muY: FloatArray,
        muFrames: Int,
        yMask: FloatArray,
        maskFrames: Int,
        channels: Int,
    ): FloatArray {
        createFloatTensor(session, "mu_y", muY, longArrayOf(1L, channels.toLong(), muFrames.toLong())).use { muTensor ->
            createFloatTensor(session, "y_mask", yMask, longArrayOf(1L, 1L, maskFrames.toLong())).use { maskTensor ->
                session.run(
                    mapOf("mu_y" to muTensor, "y_mask" to maskTensor),
                    setOf("encoded_mu"),
                ).use { result ->
                    val encodedTensor = result.get("encoded_mu").orElseThrow { IllegalStateException("condition output 'encoded_mu' missing") } as OnnxTensor
                    return readFloatTensor(encodedTensor)
                }
            }
        }
    }

    private data class DecoderStepOutput(
        val xNext: FloatArray,
        val mel: FloatArray,
    )

    private data class DecoderStepCacheState(
        val values: List<FloatArray>,
        val shapes: List<LongArray>,
    )

    private data class DecoderStepCacheOutput(
        val xNext: FloatArray,
        val mel: FloatArray,
        val cache: DecoderStepCacheState,
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
        createFloatTensor(session, "x", x, longArrayOf(1L, channels.toLong(), frames.toLong())).use { xTensor ->
            createFloatTensor(session, "encoded_mu", encodedMu, longArrayOf(1L, channels.toLong(), frames.toLong())).use { muTensor ->
                createFloatTensor(session, "y_mask", yMask, longArrayOf(1L, 1L, frames.toLong())).use { maskTensor ->
                    createFloatTensor(session, "speaker_embedding", speakerEmbedding, speakerEmbeddingShape).use { speakerTensor ->
                        createFloatTensor(session, "t", floatArrayOf(t), longArrayOf(1L)).use { tTensor ->
                            createFloatTensor(session, "dt", floatArrayOf(dt), longArrayOf(1L)).use { dtTensor ->
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
                                    return DecoderStepOutput(
                                        xNext = readFloatTensor(xNextTensor),
                                        mel = readFloatTensor(melTensor),
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    private fun runDecoderStepWithCache(
        session: OrtSession,
        stateNames: List<String>,
        previousState: DecoderStepCacheState?,
        x: FloatArray,
        encodedMu: FloatArray,
        yMask: FloatArray,
        frames: Int,
        speakerEmbedding: FloatArray,
        speakerEmbeddingShape: LongArray,
        channels: Int,
        t: Float,
        dt: Float,
    ): DecoderStepCacheOutput {
        val tensors = mutableListOf<OnnxTensor>()
        return try {
            val inputs = LinkedHashMap<String, OnnxTensor>()
            fun addTensor(name: String, values: FloatArray, shape: LongArray) {
                val tensor = createFloatTensor(session, name, values, shape)
                tensors += tensor
                inputs[name] = tensor
            }
            addTensor("x", x, longArrayOf(1L, channels.toLong(), frames.toLong()))
            addTensor("encoded_mu", encodedMu, longArrayOf(1L, channels.toLong(), frames.toLong()))
            addTensor("y_mask", yMask, longArrayOf(1L, 1L, frames.toLong()))
            addTensor("speaker_embedding", speakerEmbedding, speakerEmbeddingShape)
            addTensor("t", floatArrayOf(t), longArrayOf(1L))
            addTensor("dt", floatArrayOf(dt), longArrayOf(1L))
            if (previousState != null) {
                for (index in stateNames.indices) {
                    addTensor(stateNames[index], previousState.values[index], previousState.shapes[index])
                }
            }
            val outputNames = buildSet {
                add("x_next")
                add("mel")
                stateNames.forEach { add(it.toNextCacheName()) }
            }
            session.run(inputs, outputNames).use { result ->
                val xNextTensor = result.get("x_next").orElseThrow {
                    IllegalStateException("decoder cache step output 'x_next' missing")
                } as OnnxTensor
                val melTensor = result.get("mel").orElseThrow {
                    IllegalStateException("decoder cache step output 'mel' missing")
                } as OnnxTensor
                val nextValues = mutableListOf<FloatArray>()
                val nextShapes = mutableListOf<LongArray>()
                for (stateName in stateNames) {
                    val outputName = stateName.toNextCacheName()
                    val tensor = result.get(outputName).orElseThrow {
                        IllegalStateException("decoder cache step output '$outputName' missing")
                    } as OnnxTensor
                    nextValues += readFloatTensor(tensor)
                    nextShapes += (tensor.info as TensorInfo).shape.copyOf()
                }
                DecoderStepCacheOutput(
                    xNext = readFloatTensor(xNextTensor),
                    mel = readFloatTensor(melTensor),
                    cache = DecoderStepCacheState(values = nextValues, shapes = nextShapes),
                )
            }
        } finally {
            tensors.forEach { runCatching { it.close() } }
        }
    }

    private fun String.toNextCacheName(): String =
        if (startsWith("cache_")) "next_$this" else "next_cache_$this"

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
        createFloatTensor(vocoderSession, "mel", mel, longArrayOf(1L, melChannels.toLong(), melFrames.toLong())).use { melTensor ->
            vocoderSession.run(mapOf("mel" to melTensor), setOf("waveform")).use { result ->
                val waveformTensor = result.get("waveform").orElseThrow { IllegalStateException("vocoder output 'waveform' missing") } as OnnxTensor
                return readFloatTensor(waveformTensor)
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

    private fun FloatArray.padTrailingFrames(frameCount: Int, channels: Int): FloatArray {
        if (frameCount <= 0 || isEmpty()) return this
        val currentFrames = size / channels
        val outputFrames = currentFrames + frameCount
        val output = FloatArray(channels * outputFrames)
        for (channel in 0 until channels) {
            val srcStart = channel * currentFrames
            val dstStart = channel * outputFrames
            copyInto(output, destinationOffset = dstStart, startIndex = srcStart, endIndex = srcStart + currentFrames)
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

private fun ShortBuffer.toFloatArray(size: Int): FloatArray {
    val duplicate = duplicate()
    duplicate.rewind()
    return FloatArray(size) { halfBitsToFloat(duplicate.get()) }
}

private fun floatToHalfBits(value: Float): Short {
    val bits = java.lang.Float.floatToRawIntBits(value)
    val sign = (bits ushr 16) and 0x8000
    val exponent = (bits ushr 23) and 0xff
    val mantissa = bits and 0x7fffff
    return when {
        exponent == 0xff -> (sign or if (mantissa == 0) 0x7c00 else 0x7e00).toShort()
        exponent > 142 -> (sign or 0x7c00).toShort()
        exponent < 113 -> {
            if (exponent < 103) {
                sign.toShort()
            } else {
                val shifted = mantissa or 0x800000
                val shift = 126 - exponent
                var halfMantissa = shifted ushr shift
                if (((shifted ushr (shift - 1)) and 1) != 0) halfMantissa += 1
                (sign or halfMantissa).toShort()
            }
        }
        else -> {
            val halfExponent = exponent - 112
            var halfMantissa = mantissa ushr 13
            if ((mantissa and 0x1000) != 0) {
                halfMantissa += 1
                if (halfMantissa == 0x400) {
                    return (sign or ((halfExponent + 1) shl 10)).toShort()
                }
            }
            (sign or (halfExponent shl 10) or halfMantissa).toShort()
        }
    }
}

private fun halfBitsToFloat(value: Short): Float {
    val bits = value.toInt() and 0xffff
    val sign = (bits and 0x8000) shl 16
    val exponent = (bits ushr 10) and 0x1f
    val mantissa = bits and 0x3ff
    val floatBits = when (exponent) {
        0 -> {
            if (mantissa == 0) {
                sign
            } else {
                var normalizedMantissa = mantissa
                var normalizedExponent = -1
                while ((normalizedMantissa and 0x400) == 0) {
                    normalizedMantissa = normalizedMantissa shl 1
                    normalizedExponent -= 1
                }
                normalizedMantissa = normalizedMantissa and 0x3ff
                sign or ((normalizedExponent + 127) shl 23) or (normalizedMantissa shl 13)
            }
        }
        0x1f -> sign or 0x7f800000 or (mantissa shl 13)
        else -> sign or ((exponent + 112) shl 23) or (mantissa shl 13)
    }
    return java.lang.Float.intBitsToFloat(floatBits)
}

private fun LongBuffer.toLongArray(size: Int): LongArray {
    val duplicate = duplicate()
    duplicate.rewind()
    return LongArray(size).also { duplicate.get(it) }
}

private fun elapsedMs(startedAt: Long): Long = (System.nanoTime() - startedAt) / 1_000_000L
