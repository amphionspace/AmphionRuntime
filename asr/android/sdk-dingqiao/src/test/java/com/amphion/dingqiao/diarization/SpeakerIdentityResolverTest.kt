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
    fun tracksWithoutSpeechEvidenceDoNotOpenAnIdentity() {
        // 客户 #29：录音开头 1.3 s 的按键/环境声轨道没有 ASR token，不能领走身份 0；
        // 证据（ASR final）到了再补分配，编号仍按到达顺序。
        var call = 0
        val directions = listOf(floatArrayOf(0f, 0f, 1f), floatArrayOf(1f, 0f, 0f), floatArrayOf(0f, 1f, 0f))
        val byCall: SpeakerEmbedFn = { directions[minOf(call++, 2)] }
        val r = SpeakerIdentityResolver(sr, 4, byCall)
        r.appendAudio(silence(20_000))
        val tokens = mutableListOf<Long>()
        val evidence: SpeechEvidenceFn = { b, e -> tokens.any { it >= b && it <= e + 600 } }
        val junk = track(0, 1_330)
        val a = track(2_400, 11_250, 1)
        assertEquals(SpeakerIdentityResolver.UNRESOLVED, r.resolve(listOf(junk), evidence)[0])
        assertEquals(0, r.identityCount())
        assertEquals(1, r.pendingCount)
        tokens += listOf(3_300L, 5_000L, 10_700L)
        assertEquals(0, r.retryPending(evidence))
        assertEquals(0, r.resolve(listOf(a), evidence)[0])          // A 拿到身份 0 → 「角色1」
        val b = track(12_000, 18_000)
        assertEquals(SpeakerIdentityResolver.UNRESOLVED, r.resolve(listOf(b), evidence)[0])
        tokens += listOf(12_800L, 17_900L)
        assertEquals(1, r.retryPending(evidence))
        assertEquals(1, b.identity)                                    // 写回 track.identity
        assertEquals(null, junk.identity)                              // 噪声轨道始终未赋身份
        assertEquals(2, r.identityCount())
        assertEquals(1, r.pendingCount)
        assertEquals(2, r.deferredCount)
        r.reset()
        assertEquals(0, r.pendingCount)
    }

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
