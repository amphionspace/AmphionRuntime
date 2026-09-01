package com.amphion.dingqiao.demo

enum class CustomerScenario {
    TAP_VAD,
    PTT,
    TRANSCRIPTION,
    FORM,
    MEETING_MINUTES,
}

enum class DemoAudioSource {
    MIC,
    VOICE_RECOGNITION,
    VOICE_COMMUNICATION,
}

data class CustomerScenarioProfile(
    val scenario: CustomerScenario,
    val audioSource: DemoAudioSource,
    val vadBeginMs: Int? = null,
    val vadEndMs: Int,
    val maxAudioDurationMs: Int,
    val recognizerMode: String,
    val endpointMaxUtteranceMs: Int,
    val enablePartialResult: Boolean,
    val allowVoiceprint: Boolean,
    val rotateSession: Boolean,
    val lockAudioSource: Boolean,
)

object CustomerScenarioProfiles {
    const val SESSION_ROTATE_AUDIO_MS = 55_000

    private val profiles = mapOf(
        CustomerScenario.TAP_VAD to CustomerScenarioProfile(
            scenario = CustomerScenario.TAP_VAD,
            audioSource = DemoAudioSource.VOICE_COMMUNICATION,
            vadBeginMs = 5_000,
            vadEndMs = 1_600,
            maxAudioDurationMs = 20_000,
            recognizerMode = "short",
            endpointMaxUtteranceMs = 20_000,
            enablePartialResult = true,
            allowVoiceprint = true,
            rotateSession = true,
            lockAudioSource = false,
        ),
        CustomerScenario.PTT to CustomerScenarioProfile(
            scenario = CustomerScenario.PTT,
            audioSource = DemoAudioSource.VOICE_COMMUNICATION,
            vadEndMs = 1_600,
            maxAudioDurationMs = 62_000,
            recognizerMode = "short",
            endpointMaxUtteranceMs = 20_000,
            enablePartialResult = true,
            allowVoiceprint = true,
            rotateSession = true,
            lockAudioSource = false,
        ),
        CustomerScenario.TRANSCRIPTION to CustomerScenarioProfile(
            scenario = CustomerScenario.TRANSCRIPTION,
            audioSource = DemoAudioSource.VOICE_RECOGNITION,
            vadEndMs = 1_600,
            maxAudioDurationMs = 62_000,
            recognizerMode = "long",
            endpointMaxUtteranceMs = 60_000,
            enablePartialResult = true,
            allowVoiceprint = true,
            rotateSession = true,
            lockAudioSource = false,
        ),
        CustomerScenario.FORM to CustomerScenarioProfile(
            scenario = CustomerScenario.FORM,
            audioSource = DemoAudioSource.MIC,
            vadEndMs = 1_500,
            maxAudioDurationMs = 28_800_000,
            recognizerMode = "long",
            endpointMaxUtteranceMs = 60_000,
            enablePartialResult = true,
            allowVoiceprint = false,
            rotateSession = false,
            lockAudioSource = true,
        ),
        CustomerScenario.MEETING_MINUTES to CustomerScenarioProfile(
            scenario = CustomerScenario.MEETING_MINUTES,
            audioSource = DemoAudioSource.MIC,
            vadEndMs = 1_500,
            maxAudioDurationMs = 7_200_000,
            recognizerMode = "long",
            endpointMaxUtteranceMs = 60_000,
            enablePartialResult = true,
            allowVoiceprint = false,
            rotateSession = false,
            lockAudioSource = true,
        ),
    )

    fun forScenario(scenario: CustomerScenario): CustomerScenarioProfile =
        requireNotNull(profiles[scenario])

    fun usesContinuousRecognition(scenario: CustomerScenario): Boolean {
        val profile = forScenario(scenario)
        return profile.rotateSession && profile.maxAudioDurationMs > SESSION_ROTATE_AUDIO_MS
    }
}
