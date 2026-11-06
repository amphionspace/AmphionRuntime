package com.amphion.dingqiao.diarization

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

/**
 * 对齐 asr/tools/tests/test_harmony_speaker_identity_resolver.py 的同一组期望：
 * - Sortformer 按槽位报 runs，resolver 必须按**起始时间**重排后再分配（分配器是增量的）
 * - 取不到音频 / 嵌入失败时必须留"未赋身份"，不猜
 * - 返回的身份数组与入参同序（调用方要写回对应的 track）
 */
class SpeakerIdentityResolverTest {
    private val sr = 16_000
    private fun silence(ms: Int) = ByteArray(sr * ms / 1000 * 2)
    private fun track(begin: Long, end: Long, slot: Int = 0) = SortformerTrack(begin, end, slot)
    private val fixed: SpeakerEmbedFn = { floatArrayOf(1f, 0f, 0f) }

    @Test
    fun identitiesFollowArrivalOrderNotSlotOrder() {
        val r = SpeakerIdentityResolver(sr, 4, fixed)
        r.appendAudio(silence(10_000))
        // 入参刻意按槽位排：槽位 1 的段在前，但它在时间上更晚
        val ids = r.resolve(listOf(track(5_000, 6_000, 1), track(1_000, 2_000, 0)))
        assertEquals(2, ids.size)
        assertEquals(0, ids[0])
        assertEquals(0, ids[1])
        assertEquals(1, r.identityCount())
    }

    @Test
    fun distinctVoicesInOneSlotBecomeDistinctIdentities() {
        var call = 0
        val alternating: SpeakerEmbedFn = {
            call += 1
            if (call == 1) floatArrayOf(1f, 0f, 0f) else floatArrayOf(0f, 1f, 0f)
        }
        val r = SpeakerIdentityResolver(sr, 4, alternating)
        r.appendAudio(silence(10_000))
        val ids = r.resolve(listOf(track(1_000, 3_000), track(5_000, 7_000)))
        assertNotEquals("两个人不能并成一个身份", ids[0], ids[1])
        assertEquals(2, r.identityCount())
    }

    @Test
    fun evictedAudioLeavesIdentityUnresolved() {
        val r = SpeakerIdentityResolver(sr, 4, fixed, retainSeconds = 2.0)
        r.appendAudio(silence(5_000))                      // 只留最后 2 秒
        val ids = r.resolve(listOf(track(0, 1_000), track(3_500, 4_500)))
        assertEquals("已覆盖的段必须未赋身份", SpeakerIdentityResolver.UNRESOLVED, ids[0])
        assertEquals("仍在窗内的段应被分配", 0, ids[1])
        assertEquals(1, r.audioMissCount)
    }

    @Test
    fun embedFailureLeavesIdentityUnresolved() {
        val r = SpeakerIdentityResolver(sr, 4, { null })
        r.appendAudio(silence(5_000))
        assertEquals(SpeakerIdentityResolver.UNRESOLVED, r.resolve(listOf(track(1_000, 3_000)))[0])
        assertEquals(1, r.embedFailureCount)
        assertEquals("嵌入失败不得开出身份", 0, r.identityCount())
    }

    @Test
    fun emptyEmbeddingIsTreatedAsFailure() {
        val r = SpeakerIdentityResolver(sr, 4, { FloatArray(0) })
        r.appendAudio(silence(5_000))
        assertEquals(SpeakerIdentityResolver.UNRESOLVED, r.resolve(listOf(track(1_000, 3_000)))[0])
        assertEquals(1, r.embedFailureCount)
    }

    @Test
    fun shortTurnIsLeftUnresolvedByTheAssigner() {
        val r = SpeakerIdentityResolver(sr, 4, fixed)
        r.appendAudio(silence(5_000))
        assertEquals(SpeakerIdentityResolver.UNRESOLVED, r.resolve(listOf(track(1_000, 1_300)))[0])   // 0.3 s < 0.5 s
        assertEquals(0, r.identityCount())
        // 取到了音频、嵌入也成功，所以两个诊断计数都应为 0
        assertEquals(0, r.audioMissCount)
        assertEquals(0, r.embedFailureCount)
    }

    @Test
    fun resetClearsIdentitiesAndAudio() {
        val r = SpeakerIdentityResolver(sr, 4, fixed)
        r.appendAudio(silence(5_000))
        r.resolve(listOf(track(1_000, 3_000)))
        assertEquals(1, r.identityCount())
        r.reset()
        assertEquals(0, r.identityCount())
        assertEquals("reset 后音频也应清空", SpeakerIdentityResolver.UNRESOLVED, r.resolve(listOf(track(1_000, 3_000)))[0])
    }

    @Test
    fun embeddingInputIsCappedButDurationGateUsesTheWholeTurn() {
        var seen = -1
        val r = SpeakerIdentityResolver(sr, 4, { samples -> seen = samples.size; floatArrayOf(1f, 0f, 0f) })
        r.appendAudio(silence(12_000))
        val ids = r.resolve(listOf(track(0, 10_000)))
        assertEquals("只送前 3 秒去算嵌入", sr * SpeakerIdentityResolver.EMBED_MAX_SECONDS, seen)
        assertEquals("整段 10 s 必须被分配，不能因截断后'看起来短'被丢", 0, ids[0])
        // 截断后超出窗口的段：10 s 段的前 3 s 仍在窗内即可取到
        val r2 = SpeakerIdentityResolver(sr, 4, fixed, retainSeconds = 5.0)
        r2.appendAudio(silence(8_000))
        assertEquals(0, r2.resolve(listOf(track(3_500, 8_000)))[0])
    }
}
