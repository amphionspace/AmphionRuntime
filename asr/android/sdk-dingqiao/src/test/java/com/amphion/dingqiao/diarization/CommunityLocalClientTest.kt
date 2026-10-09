package com.amphion.dingqiao.diarization

import com.amphion.dingqiao.SpeakerDiarizationDegradedReason
import org.junit.Assert.*
import org.junit.Test
import org.mockito.kotlin.*
import java.io.File
import java.nio.file.Files
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class CommunityLocalClientTest {
    @Test fun delayedNativeWorkPreservesAudioOwnershipAndFinalWindowOrder() {
        fun run(delayFirst: Boolean, chunkBytes: Int): List<Pair<Long,Float>> {
            val directory = Files.createTempDirectory("community-spool").toFile()
            val entered = CountDownLatch(1); val release = CountDownLatch(if(delayFirst) 1 else 0)
            val drained = CountDownLatch(1); val closed = CountDownLatch(1)
            val results = mutableListOf<Pair<Long,Float>>()
            val errors = mutableListOf<String>()
            val model = mock<CommunityDiarizationInference>()
            var first = true
            whenever(model.process(any())).thenAnswer { invocation ->
                if(first) { first=false;entered.countDown();assertTrue(release.await(3,TimeUnit.SECONDS)) }
                val samples = invocation.getArgument<FloatArray>(0)
                CommunityDiarizationWindow(floatArrayOf(samples[0]),FloatArray(0),0.0,0.0,0.0)
            }
            val client = SpeakerDiarizationLocalClient(mock(),directory,object : SpeakerDiarizationLocalObserver {
                override fun onWindow(result: DiarizationLocalWindowResult) {
                    results += result.windowStartSample to result.result.segments[0]
                }
                override fun onDrained() { drained.countDown() }
                override fun onDegraded(reason: SpeakerDiarizationDegradedReason,message:String) { errors += message;drained.countDown() }
            }, { model })
            try {
                val audio = ByteArray(61*16000*2) { i ->
                    val sample = ((i/2)/16000+1).toShort().toInt()
                    (if(i%2==0) sample else sample shr 8).toByte()
                }
                for(offset in audio.indices step chunkBytes) client.append(audio.copyOfRange(offset,minOf(audio.size,offset+chunkBytes)))
                client.finish()
                assertTrue(entered.await(3,TimeUnit.SECONDS));release.countDown()
                assertTrue(drained.await(5,TimeUnit.SECONDS))
                assertTrue(errors.toString(),errors.isEmpty())
                // 2 s hop: 26 complete windows, then one padded tail for the last second.
                assertEquals(27,results.size)
                assertEquals((0L..26L).map { it*32000 },results.map { it.first })
                results.forEach { (sample,value) -> assertEquals((sample/16000+1)/32768f,value,0f) }
                client.cancel { closed.countDown() }
                assertTrue(closed.await(3,TimeUnit.SECONDS))
                verify(model,times(1)).close()
                return results
            } finally { release.countDown();client.cancel();directory.deleteRecursively() }
        }
        assertEquals(run(false,640),run(true,61*16000*2))
    }

    @Test fun stoppedInferenceDropsInFlightWindowAndStillClustersRetainedEvidence() {
        val directory = Files.createTempDirectory("community-stop").toFile()
        val entered = CountDownLatch(1);val release = CountDownLatch(1);val clustered = CountDownLatch(1)
        val model = mock<CommunityDiarizationInference>()
        whenever(model.process(any())).thenAnswer {
            entered.countDown();assertTrue(release.await(3,TimeUnit.SECONDS))
            CommunityDiarizationWindow(FloatArray(1767),FloatArray(768),0.0,0.0,0.0)
        }
        whenever(model.cluster(any(),any(),any(),any(),any(),any(),any(),any()))
            .thenReturn(CommunityDiarizationCluster(1,IntArray(3),emptyList()))
        val drained = CountDownLatch(1)
        val observer = mock<SpeakerDiarizationLocalObserver> { on { onDrained() } doAnswer { drained.countDown() } }
        val client = SpeakerDiarizationLocalClient(mock(),directory,observer,{ model })
        try {
            client.append(ByteArray(30*16000*2));client.finish()
            assertTrue(entered.await(3,TimeUnit.SECONDS))
            client.stopInference()
            client.cluster(FloatArray(1767),FloatArray(768),4,doubleArrayOf(0.0),0.0,
                FloatArray(0),FloatArray(0),FloatArray(0)) { if (it.isSuccess) clustered.countDown() }
            release.countDown()
            assertTrue(clustered.await(3,TimeUnit.SECONDS))
            // Drained means no queued or scheduled window is left to start.
            assertTrue(drained.await(3,TimeUnit.SECONDS))
            verify(model,times(1)).process(any())
            verify(observer,never()).onWindow(any())
            verify(observer,never()).onDegraded(any(),any())
        } finally { release.countDown();closeThenDelete(directory, client) }
    }

    @Test fun firstClientRemovesJobFilesLeftByAKilledProcess() {
        val workPath = Files.createTempDirectory("community-stale").toFile()
        val jobs = File(workPath, "speaker-diarization-jobs")
        val stale = File(jobs, "job-1").apply { mkdirs(); File(this, "embeddings.f32").writeBytes(ByteArray(16)) }
        val model = mock<CommunityDiarizationInference>()
        val first = SpeakerDiarizationLocalClient(mock(), workPath, mock(), { model })
        var second: SpeakerDiarizationLocalClient? = null
        try {
            assertFalse(stale.exists())
            val live = jobs.listFiles()!!.single()
            second = SpeakerDiarizationLocalClient(mock(), workPath, mock(), { model })
            assertTrue("a later client must not remove a live session's files", live.exists())
            assertEquals(2, jobs.listFiles()!!.size)
        } finally { closeThenDelete(workPath, first, second) }
    }

    // Cancellation removes job files later on each client's executor. Deleting the temp
    // tree before that finishes races the walk: with -ea, kotlin-stdlib asserts that a
    // directory it is entering still exists, and that error would also mask the test's
    // own failure. Wait first, on every path, without asserting during cleanup.
    private fun closeThenDelete(directory: File, vararg clients: SpeakerDiarizationLocalClient?) {
        val live = clients.filterNotNull()
        val quiescent = CountDownLatch(live.size)
        live.forEach { it.cancel { quiescent.countDown() } }
        quiescent.await(3,TimeUnit.SECONDS)
        directory.deleteRecursively()
    }

    @Test fun cancelWaitsForNativeReturnAndSuppressesItsLateWindow() {
        val directory = Files.createTempDirectory("community-cancel").toFile()
        val entered = CountDownLatch(1);val release = CountDownLatch(1);val closed = CountDownLatch(1)
        val model = mock<CommunityDiarizationInference>()
        whenever(model.process(any())).thenAnswer {
            entered.countDown();assertTrue(release.await(3,TimeUnit.SECONDS))
            CommunityDiarizationWindow(FloatArray(1767),FloatArray(768),0.0,0.0,0.0)
        }
        val observer = mock<SpeakerDiarizationLocalObserver>()
        val client = SpeakerDiarizationLocalClient(mock(),directory,observer,{ model })
        try {
            client.append(ByteArray(320000));assertTrue(entered.await(3,TimeUnit.SECONDS))
            client.cancel { closed.countDown() }
            assertEquals(1L,closed.count);verify(model,never()).close()
            release.countDown();assertTrue(closed.await(3,TimeUnit.SECONDS))
            verifyNoInteractions(observer);verify(model).close()
        } finally { release.countDown();client.cancel();directory.deleteRecursively() }
    }
}
