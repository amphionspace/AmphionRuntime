package com.lits.tts.sdk.internal

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
    private val executor: ExecutorService = Executors.newSingleThreadExecutor(TtsThreadFactory(engineThreadLabel()))
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

            val task = SynthesisTask(trimmedText, params)
            stoppedTasks = if (params.queueMode == QueueMode.PREEMPT) {
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
        if (params.speed !in 0.5f..2.0f) {
            return TtsErrorCode.RUNTIME_EXCEPTION to "speed out of range"
        }
        if (params.pitch !in 0.5f..2.0f) {
            return TtsErrorCode.RUNTIME_EXCEPTION to "pitch out of range"
        }
        if (params.volume !in 0.0f..2.0f) {
            return TtsErrorCode.RUNTIME_EXCEPTION to "volume out of range"
        }
        if (params.languageContext !in setOf("zh-en", "en-US")) {
            return TtsErrorCode.RUNTIME_EXCEPTION to "languageContext is not supported"
        }
        if (params.audioType != "pcm") {
            return TtsErrorCode.RUNTIME_EXCEPTION to "only pcm audioType is supported"
        }
        return null
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
            notifyStart(callback, task)
            val audio = synthesizer.synthesize(task.text, task.params, engineParams)
            if (task.cancelled.get() || destroyed) {
                notifyStop(callback, task)
                return
            }
            if (task.params.playType == PlayType.SYNTHESIZE_ONLY) {
                emitAudioChunks(callback, task, audio)
            }
            if (task.cancelled.get() || destroyed) {
                notifyStop(callback, task)
                return
            }
            notifyComplete(callback, task, CompleteResponse(CompleteType.SYNTHESIS_COMPLETE, "synthesis complete"))
            if (task.params.playType == PlayType.SYNTHESIZE_AND_PLAY && !task.cancelled.get() && !destroyed) {
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

    private fun emitAudioChunks(callback: SpeakListener, task: SynthesisTask, audio: SynthesizedAudio) {
        var offset = 0
        var sequence = 0
        while (offset < audio.pcm.size) {
            if (task.cancelled.get() || destroyed) return
            val end = minOf(offset + AUDIO_CHUNK_BYTES, audio.pcm.size)
            notifyData(callback, task, audio.pcm.copyOfRange(offset, end), SynthesisResponse(sequence = sequence))
            offset = end
            sequence += 1
            Thread.sleep(2)
        }
    }

    private fun notifyStart(callback: SpeakListener, task: SynthesisTask) {
        dispatchListener {
            if (!task.cancelled.get() && !destroyed) {
                callback.onStart(task.params.requestId, StartResponse())
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
    }
}
