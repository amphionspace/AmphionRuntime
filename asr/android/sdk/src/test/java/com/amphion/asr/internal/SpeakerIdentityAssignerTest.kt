package com.amphion.asr.internal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SpeakerIdentityAssignerTest {
    /** 造一个指定方向的单位向量，用来控制两两余弦相似度。 */
    private fun direction(vararg values: Float): FloatArray = values

    @Test
    fun distinctVoicesGetDistinctIdentities() {
        val assigner = SpeakerIdentityAssigner(maxSpeakers = 4)
        val a = assigner.assign(direction(1f, 0f, 0f), durationSeconds = 3.0)
        val b = assigner.assign(direction(0f, 1f, 0f), durationSeconds = 3.0)
        val c = assigner.assign(direction(0f, 0f, 1f), durationSeconds = 3.0)

        assertEquals(0, a.identity)
        assertEquals(1, b.identity)
        assertEquals(2, c.identity)
        assertEquals(3, assigner.identityCount())
    }

    @Test
    fun sameVoiceReturningLaterRejoinsItsIdentity() {
        // 这正是客户场景里被 Sortformer 做错的事：同一个人后来又说话，应回到原身份。
        val assigner = SpeakerIdentityAssigner(maxSpeakers = 4)
        assertEquals(0, assigner.assign(direction(1f, 0f, 0f), 3.0).identity)
        assertEquals(1, assigner.assign(direction(0f, 1f, 0f), 3.0).identity)

        val again = assigner.assign(direction(0.98f, 0.2f, 0f), 3.0)
        assertEquals(0, again.identity)
        assertTrue("并入已有身份时应报余弦相似度", again.confidence > 0.9)
        assertEquals(2, assigner.identityCount())
    }

    @Test
    fun newIdentityReportsZeroConfidence() {
        val assigner = SpeakerIdentityAssigner(maxSpeakers = 4)
        assertEquals(0.0, assigner.assign(direction(1f, 0f, 0f), 3.0).confidence, 0.0)
    }

    @Test
    fun shortTurnsAreLeftUnassignedAndDoNotMoveCentroids() {
        val assigner = SpeakerIdentityAssigner(maxSpeakers = 4)
        assigner.assign(direction(1f, 0f, 0f), 3.0)

        val short = assigner.assign(direction(0f, 1f, 0f), durationSeconds = 0.3)
        assertEquals(SpeakerIdentityAssigner.UNASSIGNED, short.identity)
        assertEquals("短段不得开出新身份", 1, assigner.identityCount())

        // 质心没被那个短段带偏：同向量的长段仍回到身份 0
        assertEquals(0, assigner.assign(direction(1f, 0f, 0f), 3.0).identity)
    }

    @Test
    fun capReachedMergesIntoNearestInsteadOfCreating() {
        val assigner = SpeakerIdentityAssigner(maxSpeakers = 2)
        assertEquals(0, assigner.assign(direction(1f, 0f, 0f), 3.0).identity)
        assertEquals(1, assigner.assign(direction(0f, 1f, 0f), 3.0).identity)

        // 第三个人与身份 0 更接近；满员后只能并入最近的，不能开第三个
        val third = assigner.assign(direction(0.6f, 0f, 0.8f), 3.0)
        assertEquals(0, third.identity)
        assertEquals(2, assigner.identityCount())
    }

    @Test
    fun embeddingsNeedNotBeNormalizedByCaller() {
        val assigner = SpeakerIdentityAssigner(maxSpeakers = 4)
        assertEquals(0, assigner.assign(direction(3f, 0f, 0f), 3.0).identity)
        // 同方向、不同模长，必须判为同一人
        val scaled = assigner.assign(direction(17f, 0f, 0f), 3.0)
        assertEquals(0, scaled.identity)
        assertEquals(1.0, scaled.confidence, 1e-6)
    }

    @Test
    fun resetClearsIdentitiesButIsNotForEveryCommitCycle() {
        val assigner = SpeakerIdentityAssigner(maxSpeakers = 4)
        assigner.assign(direction(1f, 0f, 0f), 3.0)
        assigner.assign(direction(0f, 1f, 0f), 3.0)
        assertEquals(2, assigner.identityCount())

        assigner.reset()
        assertEquals(0, assigner.identityCount())
        // reset 之后第一个段重新从 0 开始编号——这正是为什么不能按提交周期调用它
        assertEquals(0, assigner.assign(direction(0f, 1f, 0f), 3.0).identity)
    }

    @Test
    fun arrivalOrderDecidesIdentityNumbers() {
        val first = SpeakerIdentityAssigner(maxSpeakers = 4)
        val second = SpeakerIdentityAssigner(maxSpeakers = 4)
        val x = direction(1f, 0f, 0f)
        val y = direction(0f, 1f, 0f)

        assertEquals(0, first.assign(x, 3.0).identity)
        assertEquals(1, first.assign(y, 3.0).identity)
        assertEquals(0, second.assign(y, 3.0).identity)
        assertEquals(1, second.assign(x, 3.0).identity)
        // 编号按到达顺序，不是声音本身的属性
        assertNotEquals(first.assign(x, 3.0).identity, second.assign(x, 3.0).identity)
    }

    @Test
    fun zeroVectorIsLeftUnassignedWithoutCrashing() {
        val assigner = SpeakerIdentityAssigner(maxSpeakers = 4)
        val zero = assigner.assign(FloatArray(192), 3.0)
        // 全零向量归一化后仍为零，与任何质心的相似度为 0；首段会开出身份但不应崩
        assertEquals(0, zero.identity)
        assertEquals(0.0, zero.confidence, 0.0)
        assertEquals(SpeakerIdentityAssigner.UNASSIGNED, assigner.assign(FloatArray(0), 3.0).identity)
    }
}
