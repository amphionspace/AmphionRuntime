package com.amphion.dingqiao.diarization

import android.content.Context
import com.amphion.asr.AsrResult
import com.amphion.asr.internal.ResultAudioTimeline
import com.amphion.dingqiao.*
import org.junit.Assert.*
import org.junit.Test
import org.mockito.Mockito.mockConstruction
import org.mockito.kotlin.*
import java.nio.file.Files

class CommunitySessionTest {
    private class Harness(val delay: Boolean = false) : AutoCloseable {
        val pending = java.util.ArrayDeque<() -> Unit>()
        val events = mutableListOf<String>()
        val results = mutableListOf<SpeakerDiarizationResult>()
        val snapshots = mutableListOf<List<Double>>()
        val runRangeSizes = mutableListOf<Int>()
        var afterUpdate: (() -> Unit)? = null
        val construction = mockConstruction(SpeakerDiarizationLocalClient::class.java) { client, _ ->
            doAnswer { invocation ->
                val starts = invocation.getArgument<DoubleArray>(3).copyOf()
                val begin = invocation.getArgument<Double>(4) / 16
                val complete = invocation.getArgument<(Result<CommunityDiarizationCluster>) -> Unit>(8)
                snapshots += starts.toList()
                runRangeSizes += invocation.getArgument<FloatArray>(6).size
                val run = {
                    val tracks = starts.map { doubleArrayOf(maxOf(begin, it / 16), it / 16 + 10000,0.0) }
                        .filter { it[1] > it[0] }
                    complete(Result.success(CommunityDiarizationCluster(1,
                        IntArray(starts.size * 3) { if (it % 3 == 0) 0 else -2 }, tracks)))
                }
                if (delay) pending.add(run) else run()
                null
            }.whenever(client).cluster(any(),any(),any(),any(),any(),any(),any(),any(),any())
            doAnswer { invocation ->
                val windows = invocation.getArgument<Int>(0)
                DiarizationEvidence(FloatArray(windows*589*3) { if(it%3==0) 1f else 0f },FloatArray(windows*768),
                    FloatArray(windows*256),FloatArray(windows*4),FloatArray(windows))
            }.whenever(client).readEvidence(any())
        }
        val directory = Files.createTempDirectory("community-session").toFile()
        val session = SpeakerDiarizationSession(mock<Context>(), directory,4,
            object : SpeakerDiarizationSessionObserver {
                override fun onUpdate(update: SpeakerDiarizationUpdate) {
                    events += "update:${update.utteranceId}"; afterUpdate?.invoke()
                }
                override fun onWindowResult(result: SpeakerDiarizationResult) {
                    events += "window"; results += result.copy(inferenceMs=0,rtf=0f)
                }
                override fun onFinished(result: SpeakerDiarizationResult) {
                    events += "finished"; results += result.copy(inferenceMs=0,rtf=0f)
                }
            })
        fun audio(end: Int) {
            session.onWindow(DiarizationLocalWindowResult("w$end",(end-10000)*16L,0,end*16L,
                maxOf(0,end-12000)*16L,(end-1500)*16L,false,
                CommunityDiarizationWindow(FloatArray(589*3) { if(it%3==0) 1f else 0f },FloatArray(768),0.0,0.0,0.0)))
        }
        fun asr(end: Int) {
            val result = AsrResult("你好",tokens=listOf("你","好"),timestamps=listOf((end-9000)/1000f,(end-1000)/1000f))
            ResultAudioTimeline.record(result,end*16L)
            session.observeAsrFinal(SpeechRecognitionResult(isFinal=true,result="你好",beginTime=end-9000,endTime=end),result)
            session.asrFinalDelivered(result)
            session.asrAudioProcessed(end*16L)
        }
        fun settle() { while(pending.isNotEmpty()) pending.removeFirst()() }
        fun finish() {
            session.finish()
            session.observeAsrFinal(SpeechRecognitionResult(isFinal=true,isLast=true),AsrResult("",isLast=true))
            session.onDrained(); settle()
        }
        override fun close() { session.cancel(); construction.close(); directory.deleteRecursively() }
    }

    @Test fun delayedClusteringUsesSnapshotAndCancellationDiscardsLateResults() {
        Harness(true).use { h ->
            h.session.append(ByteArray(20_000*32));h.audio(10000);h.asr(10000)
            assertEquals(listOf(0.0),h.snapshots.single())
            h.audio(12000)
            h.session.cancel();h.settle()
            assertTrue(h.events.isEmpty())
        }
    }

    @Test fun reentrantCancelFromUpdateSuppressesQueuedFinal() {
        Harness(true).use { h ->
            h.session.append(ByteArray(10000*32));h.audio(10000);h.asr(10000)
            h.afterUpdate = { h.session.cancel() }
            h.finish()
            assertTrue(h.events.any { it.startsWith("update") })
            assertFalse(h.events.contains("finished"))
        }
    }

    @Test fun audioAndAsrArrivalOrderPreserveFrozenWindowsAndTerminalResult() {
        fun run(asrFirst: Boolean, delayed: Boolean): List<SpeakerDiarizationResult> = Harness(delayed).use { h ->
            h.session.append(ByteArray(140000*32))
            for(end in 10000..140000 step 2000) {
                if (asrFirst && end%10000==0) h.asr(end)
                h.audio(end)
                if (!asrFirst && end%10000==0) h.asr(end)
                if (end%20000==0) h.settle()
            }
            h.finish()
            assertEquals(2,h.results.size)
            assertEquals(listOf(false,true),h.results.map { it.isSessionFinal })
            assertEquals(14,h.results.sumOf { it.utterances.size })
            assertEquals(1,h.results.last().speakerCount)
            h.results
        }
        val immediate = run(true,false)
        assertEquals(immediate,run(false,true))
    }

    @Test fun commitsKeepFullHistoryAndPassRunEvidenceToClustering() {
        Harness().use { h ->
            h.session.append(ByteArray(160000*32))
            for (end in 10000..160000 step 2000) { h.audio(end); if (end%10000==0) h.asr(end) }
            h.finish()
            assertEquals(listOf(false,true),h.results.map { it.isSessionFinal })
            // A public commit freezes display state only; later clustering still sees every window.
            assertEquals(76,h.snapshots.last().size)
            assertEquals(0.0,h.snapshots.last().first(),0.0)
            assertEquals(h.snapshots.map { it.size*4 },h.runRangeSizes)
        }
    }

    @Test fun finishTimeoutSalvageFreezesInferredFrontAndLeavesTailUnknown() {
        Harness(true).use { h ->
            h.session.append(ByteArray(40_000*32))
            // Non-overlapping windows keep the mock's single-speaker tracks free of overlap.
            h.audio(10_000); h.audio(20_000)
            h.asr(10_000); h.asr(20_000); h.asr(30_000); h.asr(40_000)
            h.settle()
            h.session.finish()
            h.session.observeAsrFinal(SpeechRecognitionResult(isFinal=true,isLast=true),AsrResult("",isLast=true))
            h.settle()
            assertFalse("inference has not drained", h.events.contains("finished"))
            h.session.salvage()
            h.audio(30_000) // the dropped in-flight window cannot extend frozen evidence
            h.settle()
            verify(h.construction.constructed().single()).stopInference()
            val result = h.results.single()
            assertTrue(result.isSessionFinal)
            assertEquals(SpeakerDiarizationDegradedReason.FINISH_TIMEOUT, result.degradedReason)
            assertEquals(listOf(0, 0, -1, -1), result.utterances.map { it.speakerIndex })
            assertTrue(result.speakerTurns.isNotEmpty())
            assertTrue(result.speakerTurns.all { it.endTime <= 20_000 && it.speakerIndex == 0 })
            assertEquals(1, result.speakerCount)
            h.session.salvage(); h.session.onDrained(); h.settle()
            assertEquals(1, h.events.count { it == "finished" })
        }
    }

    @Test fun salvageAfterDrainKeepsTheCompleteFinalResult() {
        Harness(true).use { h ->
            h.session.append(ByteArray(20_000*32))
            h.audio(10_000); h.audio(20_000)
            h.asr(10_000); h.asr(20_000)
            h.session.finish()
            h.session.observeAsrFinal(SpeechRecognitionResult(isFinal=true,isLast=true),AsrResult("",isLast=true))
            h.session.onDrained()
            h.session.salvage()
            h.settle()
            verify(h.construction.constructed().single(), never()).stopInference()
            assertFalse(h.results.single().degraded)
            assertEquals(listOf(0, 0), h.results.single().utterances.map { it.speakerIndex })
        }
    }

    @Test fun confirmedSilenceCompletesWithoutWaitingForPaddedModelTail() {
        Harness(true).use { h ->
            h.session.append(ByteArray(1000*32));h.session.finish(true)
            h.session.observeAsrFinal(SpeechRecognitionResult(isFinal=true,isLast=true),AsrResult("",isLast=true))
            assertEquals(listOf("finished"),h.events)
            assertTrue(h.snapshots.isEmpty())
        }
    }
}
