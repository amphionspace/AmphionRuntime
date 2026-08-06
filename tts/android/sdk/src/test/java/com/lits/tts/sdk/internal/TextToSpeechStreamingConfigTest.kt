package com.lits.tts.sdk.internal

import com.lits.tts.sdk.SpeakParams
import com.lits.tts.sdk.StartResponse
import com.lits.tts.sdk.TtsStreamingConfig
import org.junit.Assert.assertEquals
import org.junit.Test

class TextToSpeechStreamingConfigTest {
    @Test
    fun streamingConfigTakesPrecedenceOverLegacyExtraParamsForChunkSize() {
        val params = SpeakParams(
            requestId = "precedence",
            extraParams = mapOf("streamingChunkSize" to 80, "chunkSize" to 96),
            streamingConfig = TtsStreamingConfig(chunkSize = 24),
        )

        assertEquals(24, streamingChunkSizeOverride(params))
    }

    @Test
    fun legacyExtraParamsRemainSupportedForChunkSize() {
        val params = SpeakParams(
            requestId = "legacy",
            extraParams = mapOf("streamingChunkSize" to "32"),
        )

        assertEquals(32, streamingChunkSizeOverride(params))
    }

    @Test
    fun streamingConfigTakesPrecedenceOverLegacyExtraParamsForFirstChunkSize() {
        val params = SpeakParams(
            requestId = "first-chunk",
            extraParams = mapOf("streamingFirstChunkSize" to 80, "firstChunkSize" to 96),
            streamingConfig = TtsStreamingConfig(chunkSize = 100, firstChunkSize = 50),
        )

        assertEquals(50, streamingFirstChunkSizeOverride(params))
    }

    @Test
    fun startResponseCanReportEffectiveStreamingParameters() {
        val response = StartResponse(
            isStreaming = true,
            dataPath = "model_stream_playback",
            streamingChunkSize = 32,
            pcmQueueCapacity = 7,
        )

        assertEquals(32, response.streamingChunkSize)
        assertEquals(7, response.pcmQueueCapacity)
    }
}
