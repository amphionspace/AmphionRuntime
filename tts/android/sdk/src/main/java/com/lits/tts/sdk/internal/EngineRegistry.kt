package com.lits.tts.sdk.internal

import com.lits.tts.sdk.CreateEngineParams
import com.lits.tts.sdk.RunMode
import com.lits.tts.sdk.TextToSpeechEngine
import com.lits.tts.sdk.TextToSpeechException
import com.lits.tts.sdk.TtsErrorCode
import com.lits.tts.sdk.VoiceInfo
import com.lits.tts.sdk.VoiceQuery
import java.util.concurrent.atomic.AtomicInteger

internal object EngineRegistry {
    private const val MAX_PROCESS_INSTANCES = 3
    private val instanceCount = AtomicInteger(0)
    private val supportedLanguages = listOf("zh-en", "en-US")
    private val supportedLanguageSet = supportedLanguages.toSet()

    private val speakers = listOf(
        RegisteredVoice(
            voiceId = "lits-female-01",
            gender = "Female",
            description = "Lits_delivery female speaker 01",
            speakerId = 0,
        ),
        RegisteredVoice(
            voiceId = "lits-female-02",
            gender = "Female",
            description = "Lits_delivery female speaker 02",
            speakerId = 1,
        ),
    )
    private val voices = supportedLanguages.flatMap { language ->
        speakers.map { speaker -> speaker.toVoiceInfo(language) }
    }

    fun createEngine(params: CreateEngineParams, workPath: String?): TextToSpeechEngine {
        val speaker = resolveVoice(params)
        validateLocate(params.locate)
        validateEngineName(params.engineName)
        val engineName = params.engineName?.trim()
        if (!params.modelLoadOnCreate) {
            throw TextToSpeechException(
                TtsErrorCode.CREATE_ENGINE_FAILED,
                "modelLoadOnCreate=false is not supported",
            )
        }
        if (instanceCount.incrementAndGet() > MAX_PROCESS_INSTANCES) {
            instanceCount.decrementAndGet()
            throw TextToSpeechException(TtsErrorCode.ENGINE_LIMIT_REACHED, "engine instance limit reached")
        }
        val synthesizer = createSynthesizer(speaker, workPath)
        return try {
            synthesizer.preload()
            TextToSpeechEngineImpl(
                engineParams = params,
                voice = speaker.toVoiceInfo(params.language),
                engineName = engineName,
                workPath = workPath,
                onRelease = { instanceCount.decrementAndGet() },
                synthesizer = synthesizer,
            )
        } catch (error: Throwable) {
            runCatching { synthesizer.close() }
            instanceCount.decrementAndGet()
            throw TextToSpeechException(
                TtsErrorCode.CREATE_ENGINE_FAILED,
                error.message ?: "failed to preload TTS engine",
            )
        }
    }

    fun hasActiveEngines(): Boolean = instanceCount.get() > 0

    fun listVoices(params: VoiceQuery): List<VoiceInfo> {
        validateRequestId(params.requestId)
        validateMode(params.mode)
        if (params.language != null) {
            validateLanguage(params.language)
        }
        return voices.filter { params.language == null || it.language == params.language }
    }

    private fun validateRequestId(requestId: String) {
        if (requestId.isBlank()) {
            throw TextToSpeechException(TtsErrorCode.RUNTIME_EXCEPTION, "requestId must not be blank")
        }
    }

    private fun validateMode(mode: RunMode) {
        if (mode != RunMode.OFFLINE) {
            throw TextToSpeechException(TtsErrorCode.CREATE_ENGINE_FAILED, "only OFFLINE mode is supported")
        }
    }

    private fun validateLocate(locate: String) {
        if (locate.isBlank()) {
            throw TextToSpeechException(TtsErrorCode.CREATE_ENGINE_FAILED, "locate must not be blank")
        }
    }

    private fun validateEngineName(engineName: String?) {
        if (engineName != null && engineName.isBlank()) {
            throw TextToSpeechException(TtsErrorCode.CREATE_ENGINE_FAILED, "engineName must not be blank")
        }
    }

    private fun validateLanguage(language: String) {
        if (language !in supportedLanguageSet) {
            throw TextToSpeechException(TtsErrorCode.LANGUAGE_UNSUPPORTED, "language is not supported")
        }
    }

    private fun resolveVoice(params: CreateEngineParams): RegisteredVoice {
        validateMode(params.mode)
        validateLanguage(params.language)
        return speakers.firstOrNull { it.voiceId == params.voiceId }
            ?: throw TextToSpeechException(TtsErrorCode.VOICE_UNSUPPORTED, "voiceId is not supported")
    }

    private fun createSynthesizer(speaker: RegisteredVoice, workPath: String?): PcmSynthesizer =
        AndroidAppContext.tryGet()?.let { context ->
            LitsDeliveryPcmSynthesizer(context = context, workPath = workPath, speakerId = speaker.speakerId)
        } ?: DeterministicPcmSynthesizer()

    private data class RegisteredVoice(
        val voiceId: String,
        val gender: String,
        val description: String,
        val speakerId: Int,
    ) {
        fun toVoiceInfo(language: String): VoiceInfo = VoiceInfo(
            language = language,
            voiceId = voiceId,
            gender = gender,
            description = description,
        )
    }
}
