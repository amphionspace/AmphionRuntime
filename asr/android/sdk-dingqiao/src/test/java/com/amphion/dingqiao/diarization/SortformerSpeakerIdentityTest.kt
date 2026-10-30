package com.amphion.dingqiao.diarization

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

/** 对齐鸿蒙 `asr/tools/tests/test_harmony_sortformer_identity.py` 的同一组规则。 */
class SortformerSpeakerIdentityTest {
    @Test
    fun slotsBecomeRolesInOrderOfFirstSpeech() {
        val identity = SortformerSpeakerIdentity(maxSpeakers = 4)
        // 槽位 2 先说，槽位 0 后说：公开编号按首次发声顺序，不按槽位号。
        val first = identity.commit(intArrayOf(40, -1, 10, -1))
        assertArrayEquals(intArrayOf(1, -1, 0, -1), first.mapping)
        assertEquals(0, first.before)
        assertEquals(2, first.after)
    }

    @Test
    fun anAssignedSlotKeepsItsRoleForTheSession() {
        val identity = SortformerSpeakerIdentity(maxSpeakers = 4)
        identity.commit(intArrayOf(10, -1, -1, -1))
        val later = identity.commit(intArrayOf(5, 20, -1, -1))
        // 槽位 0 已是角色 0，第二次提交里它更早也不会改编号；槽位 1 拿到下一个编号。
        assertArrayEquals(intArrayOf(0, 1, -1, -1), later.mapping)
        assertEquals(1, later.before)
        assertEquals(2, later.after)
    }

    @Test
    fun silentSlotsStayUnknown() {
        val identity = SortformerSpeakerIdentity(maxSpeakers = 4)
        val mapping = identity.commit(intArrayOf(-1, -1, -1, -1))
        assertArrayEquals(intArrayOf(-1, -1, -1, -1), mapping.mapping)
        assertEquals(0, identity.publishedCount())
    }

    @Test
    fun slotsBeyondTheCallerCapStayAnonymous() {
        val identity = SortformerSpeakerIdentity(maxSpeakers = 2)
        val mapping = identity.commit(intArrayOf(30, 10, 20, 40))
        // 上限 2：最早两个拿编号，其余保持 -1，且后续提交也不再分配。
        assertArrayEquals(intArrayOf(-1, 0, 1, -1), mapping.mapping)
        assertEquals(2, identity.publishedCount())
        val again = identity.commit(intArrayOf(50, -1, -1, 60))
        assertArrayEquals(intArrayOf(-1, 0, 1, -1), again.mapping)
        assertEquals(2, again.after)
    }

    @Test
    fun tiesFollowSlotOrderWhichIsArrivalOrder() {
        val identity = SortformerSpeakerIdentity(maxSpeakers = 4)
        val mapping = identity.commit(intArrayOf(-1, 7, 7, -1))
        assertArrayEquals(intArrayOf(-1, 0, 1, -1), mapping.mapping)
    }
}
