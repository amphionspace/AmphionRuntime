package com.amphion.dingqiao

import android.content.Context
import com.amphion.asr.AsrEngine
import com.amphion.asr.AsrResult
import com.amphion.dingqiao.diarization.DiarizationTranscriptState
import com.amphion.dingqiao.diarization.SpeakerTimelineTurn
import java.util.concurrent.Executors
import kotlin.math.roundToInt
import org.junit.Assert.*
import org.junit.Test
import org.mockito.kotlin.mock

class ResultTimestampParityTest {
    @Test fun endpointTimestampMatchesTokenClockAndPreservesRealSpeakerChanges() {
        val directory = kotlin.io.path.createTempDirectory().toFile()
        val executor = Executors.newSingleThreadExecutor()
        val engine = DingqiaoRecognitionEngine(mock<Context>(), CreateEngineParams(),
            VoiceprintStore(directory), null, executor, {}, mock<AsrEngine>(), { it })
        try {
            val method = DingqiaoRecognitionEngine::class.java.getDeclaredMethod("resultPayload",
                AsrResult::class.java, Boolean::class.javaPrimitiveType, Boolean::class.javaPrimitiveType,
                String::class.java, java.lang.Float::class.java).apply { isAccessible = true }
            // Captured failing boundary: the last token rounds to 15220, but the
            // public endpoint used to truncate to 15219 and create a negative span.
            val input = AsrResult(text = "甲这个。", rawText = "甲这个", tokens = listOf("甲", "这", "个"),
                timestamps = listOf(8.3f, 15.0f, 15.219999f))
            val payload = method.invoke(engine, input, true, false, null, null) as SpeechRecognitionResult
            val times = input.timestamps.map { (it * 1000).roundToInt() }
            val state = DiarizationTranscriptState()
            state.addUtterance(input.rawText, payload.result, input.tokens, times,
                requireNotNull(payload.beginTime), requireNotNull(payload.endTime))
            state.applySpeakerTurns(listOf(SpeakerTimelineTurn(8000, 9534, "S2", emptyList()),
                SpeakerTimelineTurn(9972, 15158, "S1", emptyList())))
            val before = state.allTurns()
            assertEquals("public endpoint and token must use one clock", times.last(), payload.endTime)
            val result = state.finalUtterances()
            assertTrue(result.all { it.endTime >= it.beginTime })
            assertEquals(listOf("甲", "这个。"), result.map { it.text })
            assertTrue(result.last().speakerInferred)
            assertEquals(0f, result.last().confidence)
            assertEquals(before, state.allTurns())
            assertFalse(payload.isLast)

            val changed = DiarizationTranscriptState()
            changed.addUtterance(input.rawText, payload.result, input.tokens, times,
                requireNotNull(payload.beginTime), requireNotNull(payload.endTime))
            changed.applySpeakerTurns(listOf(SpeakerTimelineTurn(8000, 9534, "S2", emptyList()),
                SpeakerTimelineTurn(9972, 15158, "S1", emptyList()),
                SpeakerTimelineTurn(15158, 15300, "S2", emptyList())))
            assertEquals(listOf("S2", "S1", "S2"), changed.finalUtterances().map { it.speakerId })
            val empty = method.invoke(engine, AsrResult(""), true, true, null, null) as SpeechRecognitionResult
            assertNull(empty.beginTime)
            assertNull(empty.endTime)
            assertTrue(empty.isLast)
        } finally {
            engine.shutdown()
            executor.shutdownNow()
            directory.deleteRecursively()
        }
    }
}
