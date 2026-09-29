package com.amphion.asr.internal

import android.os.Handler
import android.os.HandlerThread
import com.amphion.asr.AsrResult
import org.junit.Assert.*
import org.junit.Test
import org.mockito.Mockito.mockConstruction
import org.mockito.Mockito.mockStatic
import android.os.SystemClock
import org.mockito.kotlin.*

class ProcessedAudioFenceTest {
    @Test fun progressCannotOvertakeFinalPostprocessingAndCloseDrainsBoth() {
        val pending = java.util.ArrayDeque<Runnable>()
        mockStatic(SystemClock::class.java).use {
        mockConstruction(HandlerThread::class.java).use {
            mockConstruction(Handler::class.java) { handler, _ ->
                doAnswer { invocation -> pending.add(invocation.getArgument(0)); true }
                    .whenever(handler).post(any())
            }.use {
                val events = mutableListOf<String>()
                val processor = PostProcessor(1,null,null,{ result, _ -> events += result.text },{ fail(it.toString()) })
                processor.postFinal(AsrResult("first"))
                processor.afterPendingFinals { events += "progress-1" }
                processor.postFinal(AsrResult("second"))
                processor.afterPendingFinals { events += "progress-2" }
                processor.close()
                assertTrue(events.isEmpty())
                while(pending.isNotEmpty()) pending.removeFirst().run()
                assertEquals(listOf("first","progress-1","second","progress-2"),events)
            }
        }
        }
    }
}
