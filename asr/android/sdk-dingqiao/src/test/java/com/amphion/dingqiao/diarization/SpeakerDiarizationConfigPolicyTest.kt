package com.amphion.dingqiao.diarization

import com.amphion.dingqiao.SpeakerDiarizationConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

/** 对齐鸿蒙 test_speaker_identity_mode_defaults_to_model_and_rejects_typos（0.3.27 起默认 voiceprint）。 */
class SpeakerDiarizationConfigPolicyTest {
    @Test
    fun defaultIsVoiceprintAndModelIsAnExplicitFallback() {
        assertEquals("voiceprint", SpeakerDiarizationConfig().speakerIdentityMode)
        assertEquals("voiceprint", validateSpeakerIdentityMode(null))
        assertEquals("voiceprint", validateSpeakerIdentityMode(""))
        assertEquals("model", validateSpeakerIdentityMode("model"))
        assertEquals("voiceprint", validateSpeakerDiarizationConfig(SpeakerDiarizationConfig(maxSpeakers = 2)))
        assertEquals("model", validateSpeakerDiarizationConfig(SpeakerDiarizationConfig(4, "model")))
    }

    @Test
    fun typosFailInsteadOfSilentlyFallingBackToTheModel() {
        val error = assertThrows(IllegalArgumentException::class.java) { validateSpeakerIdentityMode("voice-print") }
        assertEquals(true, error.message!!.contains("speakerIdentityMode"))
        assertThrows(IllegalArgumentException::class.java) { validateSpeakerIdentityMode("Model") }
        assertThrows(IllegalArgumentException::class.java) {
            validateSpeakerDiarizationConfig(SpeakerDiarizationConfig(4, "campplus"))
        }
    }

    @Test
    fun maxSpeakersRangeIsStillEnforced() {
        assertThrows(IllegalArgumentException::class.java) { validateSpeakerDiarizationConfig(SpeakerDiarizationConfig(0)) }
        assertThrows(IllegalArgumentException::class.java) { validateSpeakerDiarizationConfig(SpeakerDiarizationConfig(5)) }
    }
}
