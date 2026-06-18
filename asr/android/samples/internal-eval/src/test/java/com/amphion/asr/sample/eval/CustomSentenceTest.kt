package com.amphion.asr.sample.eval

import com.amphion.asr.sample.eval.model.CustomSentence
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * CustomSentence sha 派生 + normalize + 边界条件的纯逻辑测试。
 *
 * 重点验证：
 * - 同 text 派生相同 id（跨设备聚合的基础）
 * - normalize 容忍空白差异
 * - 不同 text 派生不同 id（碰撞概率假设）
 * - 边界 text（空、纯空格）正确拒绝
 */
class CustomSentenceTest {

    @Test fun `same text produces same id`() {
        val a = CustomSentence.deriveId("明天上午十点开 weekly meeting")
        val b = CustomSentence.deriveId("明天上午十点开 weekly meeting")
        assertEquals(a, b)
    }

    @Test fun `normalize collapses whitespace`() {
        val a = CustomSentence.deriveId("hello   world")
        val b = CustomSentence.deriveId("hello world")
        val c = CustomSentence.deriveId("  hello world  ")
        val d = CustomSentence.deriveId("hello\tworld")
        val e = CustomSentence.deriveId("hello\nworld")
        assertEquals(a, b)
        assertEquals(b, c)
        assertEquals(c, d)
        assertEquals(d, e)
    }

    @Test fun `case is significant`() {
        // 大小写在 ASR 里可能是真实差异（"OK" vs "ok"），不折叠
        val a = CustomSentence.deriveId("Hello World")
        val b = CustomSentence.deriveId("hello world")
        assertNotEquals(a, b)
    }

    @Test fun `punctuation is significant`() {
        // 中文标点会影响 ITN / WER，不去
        val a = CustomSentence.deriveId("今天天气真好")
        val b = CustomSentence.deriveId("今天天气真好！")
        assertNotEquals(a, b)
    }

    @Test fun `different text produces different id`() {
        val a = CustomSentence.deriveId("apple")
        val b = CustomSentence.deriveId("banana")
        assertNotEquals(a, b)
    }

    @Test fun `id has correct prefix and length`() {
        val id = CustomSentence.deriveId("anything")
        assertTrue(id.startsWith("custom_"))
        // custom_ (7) + 12 hex
        assertEquals(19, id.length)
    }

    @Test fun `isCustomSentenceId detects prefix`() {
        assertTrue(CustomSentence.isCustomSentenceId("custom_abcdef012345"))
        assertTrue(CustomSentence.isCustomSentenceId(CustomSentence.deriveId("text")))
        assertFalse(CustomSentence.isCustomSentenceId("zh_en_mixed_001"))
        assertFalse(CustomSentence.isCustomSentenceId(""))
        assertFalse(CustomSentence.isCustomSentenceId(null))
    }

    @Test(expected = IllegalArgumentException::class)
    fun `empty text throws`() {
        CustomSentence.deriveId("")
    }

    @Test(expected = IllegalArgumentException::class)
    fun `whitespace-only text throws`() {
        CustomSentence.deriveId("   \n  \t  ")
    }

    @Test fun `adHoc returns Sentence with custom category`() {
        val s = CustomSentence.adHoc("  hello   world  ")
        assertEquals("hello world", s.text)
        assertEquals(CustomSentence.CUSTOM_CATEGORY_ID, s.categoryId)
        assertTrue(CustomSentence.isCustomSentenceId(s.id))
        // 等价于直接 deriveId
        assertEquals(CustomSentence.deriveId("hello world"), s.id)
    }
}
