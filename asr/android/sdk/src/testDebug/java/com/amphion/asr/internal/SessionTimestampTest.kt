package com.amphion.asr.internal

import com.amphion.asr.AsrResult
import com.k2fsa.sherpa.onnx.OnlineRecognizerResult
import org.junit.Assert.*
import org.junit.Test
import org.mockito.kotlin.mock

class SessionTimestampTest {
    @Test
    fun resultKeepsItsOwnStreamOriginAcrossLaterResets() {
        // Exercise the actual conversion without starting Android decoder/callback threads.
        val session = mock<SessionImpl>()
        val type = SessionImpl::class.java
        type.getDeclaredField("sampleRate").apply { isAccessible = true }.setInt(session, 16000)
        val origin = type.getDeclaredField("streamStartSample").apply { isAccessible = true }
        val convert = type.getDeclaredMethod("toAsrResult", OnlineRecognizerResult::class.java)
            .apply { isAccessible = true }
        val native = OnlineRecognizerResult("你好", arrayOf("你", "好"), floatArrayOf(.5f, 1f), floatArrayOf(-.2f, -.3f))
        origin.setLong(session, 0)
        val first = convert.invoke(session, native) as AsrResult
        origin.setLong(session, 160000)
        val second = convert.invoke(session, native) as AsrResult
        origin.setLong(session, 320000)
        assertEquals(listOf(.5f, 1f), first.timestamps)
        assertEquals(listOf(10.5f, 11f), second.timestamps)
        assertEquals(first.text, second.text)
        assertEquals(first.rawText, second.rawText)
        assertEquals(first.tokens, second.tokens)
        assertEquals(first.tokenConfidences, second.tokenConfidences)
        val empty = convert.invoke(session, OnlineRecognizerResult("", emptyArray(), floatArrayOf(), floatArrayOf())) as AsrResult
        assertTrue(empty.timestamps.isEmpty())
    }
}
