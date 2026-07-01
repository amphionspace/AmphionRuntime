package com.lits.tts.sdk.internal

import android.os.SystemClock

import com.lits.tts.sdk.CompleteResponse
import com.lits.tts.sdk.CompleteType
import com.lits.tts.sdk.CreateEngineParams
import com.lits.tts.sdk.PlayType
import com.lits.tts.sdk.QueueMode
import com.lits.tts.sdk.SpeakListener
import com.lits.tts.sdk.SpeakParams
import com.lits.tts.sdk.StartResponse
import com.lits.tts.sdk.StopResponse
import com.lits.tts.sdk.StopType
import com.lits.tts.sdk.SynthesisResponse
import com.lits.tts.sdk.TextToSpeechEngine
import com.lits.tts.sdk.TextToSpeechException
import com.lits.tts.sdk.TtsErrorCode
import com.lits.tts.sdk.VoiceInfo
import java.util.ArrayDeque
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.ThreadFactory
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

internal class TextToSpeechEngineImpl(
    private val engineParams: CreateEngineParams,
    private val voice: VoiceInfo,
    private val engineName: String?,
    @Suppress("unused") private val workPath: String?,
    private val onRelease: () -> Unit,
    private val synthesizer: PcmSynthesizer,
) : TextToSpeechEngine {
    private val lock = Any()
    private val queue = ArrayDeque<SynthesisTask>()
    private val seenRequestIds = mutableSetOf<String>()
    private val executor: ExecutorService = Executors.newCachedThreadPool(TtsThreadFactory(engineThreadLabel()))
    private val player = AndroidPcmPlayer()

    @Volatile
    private var listener: SpeakListener? = null

    @Volatile
    private var destroyed = false

    @Volatile
    private var released = false

    private var current: SynthesisTask? = null

    override fun setListener(listener: SpeakListener) {
        ensureNotDestroyed()
        this.listener = listener
    }

    override fun speak(text: String, params: SpeakParams) {
        if (destroyed) {
            val callback = listener
            if (callback != null) {
                notifyError(callback, params.requestId, TtsErrorCode.ENGINE_DESTROYED, withEngineName("engine has been destroyed"))
                return
            }
            throw TextToSpeechException(TtsErrorCode.ENGINE_DESTROYED, withEngineName("engine has been destroyed"))
        }
        val callback = listener ?: throw TextToSpeechException(
            TtsErrorCode.ENGINE_NOT_INITIALIZED,
            withEngineName("listener must be set before speak"),
        )
        val trimmedText = text.trim()
        val error = validateSpeak(trimmedText, params)
        if (error != null) {
            markRequestSeenIfPossible(params.requestId)
            notifyError(callback, params.requestId, error.first, error.second)
            return
        }
        val normalizedParams = normalizeSpeakParams(params)
        val normalizedText = TtsInputTextNormalizer.ensureTerminalPunctuation(trimmedText, engineParams.language)

        val stoppedTasks: List<SynthesisTask>
        synchronized(lock) {
            if (destroyed) {
                notifyError(callback, params.requestId, TtsErrorCode.ENGINE_DESTROYED, withEngineName("engine has been destroyed"))
                return
            }
            if (!seenRequestIds.add(params.requestId)) {
                notifyError(callback, params.requestId, TtsErrorCode.RUNTIME_EXCEPTION, withEngineName("requestId duplicated"))
                return
            }

            val task = SynthesisTask(normalizedText, normalizedParams)
            stoppedTasks = if (normalizedParams.queueMode == QueueMode.PREEMPT) {
                cancelAllLocked()
            } else {
                emptyList()
            }
            queue.add(task)
            startNextLocked()
        }
        stoppedTasks.forEach { notifyStop(callback, it) }
    }

    override fun stop() {
        val callback = listener
        val stoppedTasks = synchronized(lock) {
            if (destroyed) {
                throw TextToSpeechException(TtsErrorCode.ENGINE_DESTROYED, withEngineName("engine has been destroyed"))
            }
            cancelAllLocked()
        }
        player.stop()
        if (callback != null) {
            stoppedTasks.forEach { notifyStop(callback, it) }
        }
    }

    override fun isBusy(): Boolean {
        ensureNotDestroyed()
        return synchronized(lock) {
            current?.cancelled?.get() == false || queue.any { !it.cancelled.get() }
        }
    }

    override fun shutdown() {
        val callback = listener
        val stoppedTasks = synchronized(lock) {
            if (destroyed) {
                throw TextToSpeechException(TtsErrorCode.ENGINE_DESTROYED, withEngineName("engine has been destroyed"))
            }
            destroyed = true
            cancelAllLocked()
        }
        if (callback != null) {
            stoppedTasks.forEach { notifyStop(callback, it) }
        }
        player.stop()
        executor.shutdownNow()
        releaseOnce()
    }

    private fun validateSpeak(text: String, params: SpeakParams): Pair<Int, String>? {
        if (destroyed) return TtsErrorCode.ENGINE_DESTROYED to withEngineName("engine has been destroyed")
        if (text.isEmpty() || text.length > 10000) {
            return TtsErrorCode.TEXT_LENGTH_INVALID to "text length must be 1..10000"
        }
        if (params.requestId.isBlank()) {
            return TtsErrorCode.RUNTIME_EXCEPTION to "requestId must not be blank"
        }
        if (engineParams.language !in setOf("zh-en", "en-US")) {
            return TtsErrorCode.LANGUAGE_UNSUPPORTED to "language is not supported"
        }
        if (voice.voiceId != engineParams.voiceId) {
            return TtsErrorCode.VOICE_UNSUPPORTED to "voiceId is not supported"
        }
        if (params.pitch !in 0.5f..2.0f) {
            return TtsErrorCode.RUNTIME_EXCEPTION to "pitch out of range"
        }
        if (params.volume !in 0.0f..2.0f) {
            return TtsErrorCode.RUNTIME_EXCEPTION to "volume out of range"
        }
        if (params.languageContext !in setOf("zh-CN", "zh-en", "en-US")) {
            return TtsErrorCode.RUNTIME_EXCEPTION to "languageContext is not supported"
        }
        if (params.audioType != "pcm") {
            return TtsErrorCode.RUNTIME_EXCEPTION to "only pcm audioType is supported"
        }
        return null
    }

    private fun normalizeSpeakParams(params: SpeakParams): SpeakParams {
        val normalizedLanguageContext = when (params.languageContext) {
            "zh-CN", "zh-en" -> "zh-en"
            else -> params.languageContext
        }
        val normalizedSpeed = params.speed.takeIf { it.isFinite() }?.coerceIn(0.5f, 2.0f) ?: 1.0f
        return params.copy(
            speed = normalizedSpeed,
            languageContext = normalizedLanguageContext,
        )
    }

    private fun markRequestSeenIfPossible(requestId: String) {
        if (requestId.isBlank()) return
        synchronized(lock) {
            seenRequestIds.add(requestId)
        }
    }

    private fun cancelAllLocked(): List<SynthesisTask> {
        val tasks = buildList {
            current?.let { add(it) }
            addAll(queue)
        }
        tasks.forEach { it.cancelled.set(true) }
        queue.clear()
        current = null
        return tasks
    }

    private fun startNextLocked() {
        if (current != null || queue.isEmpty() || destroyed) return
        val task = queue.removeFirst()
        current = task
        executor.execute { runTask(task) }
    }

    private fun runTask(task: SynthesisTask) {
        val callback = listener
        try {
            if (callback == null || task.cancelled.get() || destroyed) return
            task.startedAtMs = SystemClock.elapsedRealtime()
            var sequence = 0
            val useStreamingSynthesis = synthesizer.canStream(task.params, engineParams)
            val useStreamingPlayback =
                task.params.playType == PlayType.SYNTHESIZE_AND_PLAY &&
                    useStreamingSynthesis &&
                    synthesizer.supportsInternalPlayback() &&
                    synthesizer.streamingSampleRate(engineParams) != null
            val dataPath = when {
                task.params.playType == PlayType.SYNTHESIZE_ONLY && useStreamingSynthesis -> "model_stream_callback"
                useStreamingPlayback -> "model_stream_playback"
                task.params.playType == PlayType.SYNTHESIZE_ONLY -> "buffered_pcm_callback"
                else -> "buffered_pcm_playback"
            }
            val responseSampleRate = synthesizer.streamingSampleRate(engineParams) ?: DEFAULT_SAMPLE_RATE
            notifyStart(
                callback = callback,
                task = task,
                sampleRate = responseSampleRate,
                isStreaming = useStreamingSynthesis,
                dataPath = dataPath,
                modelInfo = synthesizer.debugSummary(),
                loadProfileInfo = synthesizer.loadProfileInfo(),
            )
            var synthesisCompleteNotified = false
            val audio = if (task.params.playType == PlayType.SYNTHESIZE_ONLY && useStreamingSynthesis) {
                synthesizer.synthesizeStreaming(
                    text = task.text,
                    params = task.params,
                    engineParams = engineParams,
                    isCancelled = { task.cancelled.get() || destroyed },
                ) { chunk ->
                    if (!task.cancelled.get() && !destroyed) {
                        notifyData(
                            callback,
                            task,
                            chunk,
                            SynthesisResponse(
                                sequence = sequence,
                                isStreaming = true,
                                chunkSource = "model_stream",
                            ),
                        )
                        sequence += 1
                    }
                }
            } else if (useStreamingPlayback) {
                var synthesized: SynthesizedAudio? = null
                val sampleRate = synthesizer.streamingSampleRate(engineParams)
                    ?: throw IllegalStateException("streaming sample rate is unavailable")
                player.playStreaming(
                    sampleRate = sampleRate,
                    cancelled = task.cancelled,
                    soundChannel = task.params.soundChannel,
                    queueCapacity = pcmQueueCapacity(task.params),
                    producer = { chunkWriter ->
                        synthesized = synthesizer.synthesizeStreaming(
                            text = task.text,
                            params = task.params,
                            engineParams = engineParams,
                            collectOutput = false,
                            isCancelled = { task.cancelled.get() || destroyed },
                        ) { chunk ->
                            if (!task.cancelled.get() && !destroyed) {
                                chunkWriter(chunk)
                            }
                        }
                    },
                    onSynthesisComplete = {
                        val produced = synthesized
                        if (produced != null && !task.cancelled.get() && !destroyed) {
                            synthesisCompleteNotified = true
                            notifyComplete(
                                callback,
                                task,
                                buildSynthesisCompleteResponse(
                                    audio = produced,
                                    playbackStartMs = task.playbackStartMs.get(),
                                ),
                            )
                        }
                    },
                    onFirstAudioWritten = {
                        val startedAt = task.startedAtMs
                        if (startedAt >= 0L) {
                            task.playbackStartMs.compareAndSet(-1L, SystemClock.elapsedRealtime() - startedAt)
                        }
                    },
                )
                synthesized ?: throw IllegalStateException("streaming playback produced no synthesized audio")
            } else {
                synthesizer.synthesize(task.text, task.params, engineParams)
            }
            if (task.cancelled.get() || destroyed) {
                notifyStop(callback, task)
                return
            }
            if (task.params.playType == PlayType.SYNTHESIZE_ONLY && !useStreamingSynthesis) {
                emitAudioChunks(callback, task, audio, "buffered_pcm")
            }
            if (task.cancelled.get() || destroyed) {
                notifyStop(callback, task)
                return
            }
            if (!synthesisCompleteNotified) {
                notifyComplete(callback, task, buildSynthesisCompleteResponse(audio))
            }
            if (task.params.playType == PlayType.SYNTHESIZE_AND_PLAY && !useStreamingPlayback && !task.cancelled.get() && !destroyed) {
                if (synthesizer.supportsInternalPlayback()) {
                    player.playBlocking(audio, task.cancelled, task.params.soundChannel)
                }
            }
            if (task.params.playType == PlayType.SYNTHESIZE_AND_PLAY && !task.cancelled.get() && !destroyed) {
                notifyComplete(callback, task, CompleteResponse(CompleteType.PLAYBACK_COMPLETE, "playback complete"))
            }
        } catch (interrupted: InterruptedException) {
            Thread.currentThread().interrupt()
            if (callback != null) notifyStop(callback, task)
        } catch (error: RuntimeException) {
            val (code, message) = parseRuntimeError(error)
            if (callback != null) notifyError(callback, task.params.requestId, code, message)
        } finally {
            synchronized(lock) {
                if (current === task) current = null
                startNextLocked()
            }
        }
    }

    private fun pcmQueueCapacity(params: SpeakParams): Int {
        val value = params.extraParams["pcmQueueCapacity"] ?: params.extraParams["pcmQueueSize"]
        return when (value) {
            is Number -> value.toInt()
            is String -> value.toIntOrNull()
            else -> null
        }?.coerceIn(1, 256) ?: DEFAULT_PCM_QUEUE_CAPACITY
    }

    private fun emitAudioChunks(
        callback: SpeakListener,
        task: SynthesisTask,
        audio: SynthesizedAudio,
        chunkSource: String,
    ) {
        var offset = 0
        var sequence = 0
        while (offset < audio.pcm.size) {
            if (task.cancelled.get() || destroyed) return
            val end = minOf(offset + AUDIO_CHUNK_BYTES, audio.pcm.size)
            notifyData(
                callback,
                task,
                audio.pcm.copyOfRange(offset, end),
                SynthesisResponse(
                    sequence = sequence,
                    isStreaming = false,
                    chunkSource = chunkSource,
                ),
            )
            offset = end
            sequence += 1
            Thread.sleep(2)
        }
    }

    private fun buildSynthesisCompleteResponse(
        audio: SynthesizedAudio,
        playbackStartMs: Long = -1L,
    ): CompleteResponse {
        val audioDurationMs = audioDurationMs(audio.audioBytes, audio.sampleRate)
        val firstPacketMs = when {
            audio.firstChunkMs >= 0L -> audio.firstChunkMs
            audio.synthesisMs >= 0L -> audio.synthesisMs
            else -> -1L
        }
        return CompleteResponse(
            type = CompleteType.SYNTHESIS_COMPLETE,
            message = "synthesis complete",
            firstPacketMs = firstPacketMs,
            synthesisMs = audio.synthesisMs,
            audioDurationMs = audioDurationMs,
            rtf = if (audio.synthesisMs >= 0L && audioDurationMs > 0L) {
                audio.synthesisMs.toDouble() / audioDurationMs.toDouble()
            } else {
                -1.0
            },
            profilingInfo = audio.profilingInfo,
            playbackStartMs = playbackStartMs,
        )
    }

    private fun audioDurationMs(audioBytes: Long, sampleRate: Int): Long {
        if (sampleRate <= 0) return 0L
        return audioBytes * 1000L / (sampleRate.toLong() * BYTES_PER_FRAME)
    }

    private fun notifyStart(
        callback: SpeakListener,
        task: SynthesisTask,
        sampleRate: Int,
        isStreaming: Boolean,
        dataPath: String,
        modelInfo: String,
        loadProfileInfo: String,
    ) {
        dispatchListener {
            if (!task.cancelled.get() && !destroyed) {
                callback.onStart(
                    task.params.requestId,
                    StartResponse(
                        sampleRate = sampleRate,
                        isStreaming = isStreaming,
                        dataPath = dataPath,
                        modelSource = if (modelInfo.contains("source=external")) "external" else "bundled",
                        modelInfo = modelInfo,
                        loadProfileInfo = loadProfileInfo,
                    ),
                )
            }
        }
    }

    private fun notifyData(
        callback: SpeakListener,
        task: SynthesisTask,
        audio: ByteArray,
        response: SynthesisResponse,
    ) {
        dispatchListener {
            if (!task.cancelled.get() && !destroyed) {
                callback.onData(task.params.requestId, audio, response)
            }
        }
    }

    private fun notifyComplete(callback: SpeakListener, task: SynthesisTask, response: CompleteResponse) {
        dispatchListener {
            if (!task.cancelled.get() && !destroyed) {
                callback.onComplete(task.params.requestId, response)
            }
        }
    }

    private fun notifyStop(callback: SpeakListener, task: SynthesisTask) {
        if (task.stopNotified.compareAndSet(false, true)) {
            dispatchListener {
                callback.onStop(task.params.requestId, StopResponse(StopType.STOP_ALL, "stopped"))
            }
        }
    }

    private fun notifyError(callback: SpeakListener, requestId: String, errorCode: Int, errorMessage: String) {
        dispatchListener {
            callback.onError(requestId, errorCode, errorMessage)
        }
    }

    private fun dispatchListener(block: () -> Unit) {
        LISTENER_EXECUTOR.execute(block)
    }

    private fun ensureNotDestroyed() {
        if (destroyed) {
            throw TextToSpeechException(TtsErrorCode.ENGINE_DESTROYED, withEngineName("engine has been destroyed"))
        }
    }

    private fun engineThreadLabel(): String = engineName ?: voice.voiceId

    private fun withEngineName(message: String): String =
        engineName?.let { "$message (engineName=$it)" } ?: message

    private fun releaseOnce() {
        if (!released) {
            released = true
            player.stop()
            synthesizer.close()
            onRelease()
        }
    }

    private fun parseRuntimeError(error: RuntimeException): Pair<Int, String> {
        val message = error.message.orEmpty()
        val code = message.substringBefore(':').toIntOrNull()
        return if (code != null) {
            code to message.substringAfter(':', message)
        } else {
            TtsErrorCode.RUNTIME_EXCEPTION to (error.message ?: "synthesis runtime exception")
        }
    }

    private data class SynthesisTask(
        val text: String,
        val params: SpeakParams,
        val cancelled: AtomicBoolean = AtomicBoolean(false),
        val stopNotified: AtomicBoolean = AtomicBoolean(false),
        val playbackStartMs: AtomicLong = AtomicLong(-1L),
        @Volatile var startedAtMs: Long = -1L,
    )

    private class TtsThreadFactory(
        private val label: String,
    ) : ThreadFactory {
        override fun newThread(runnable: Runnable): Thread {
            return Thread(runnable, "lits-tts-engine-$label").apply { isDaemon = true }
        }
    }

    private class TtsListenerThreadFactory : ThreadFactory {
        override fun newThread(runnable: Runnable): Thread {
            return Thread(runnable, "lits-tts-listener").apply { isDaemon = true }
        }
    }

    private companion object {
        val LISTENER_EXECUTOR: ExecutorService = Executors.newSingleThreadExecutor(TtsListenerThreadFactory())
        const val AUDIO_CHUNK_BYTES = 4096
        const val BYTES_PER_FRAME = 2L
        const val DEFAULT_SAMPLE_RATE = 24000
        const val DEFAULT_PCM_QUEUE_CAPACITY = 128
    }
}
