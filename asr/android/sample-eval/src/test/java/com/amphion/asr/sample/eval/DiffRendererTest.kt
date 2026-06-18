package com.amphion.asr.sample.eval

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * DiffRenderer 的 LCS 对齐算法单测。
 *
 * 这里只测纯函数 [DiffRenderer.align]（不依赖 Android Context），渲染部分留给手测。
 */
class DiffRendererTest {

    @Test fun `identical produces all match`() {
        val s = DiffRenderer.align("hello", "hello")
        assertEquals(5, s.size)
        s.forEach { assertEquals(DiffRenderer.Op.MATCH, it.op) }
    }

    @Test fun `empty hypothesis is all delete`() {
        val s = DiffRenderer.align("abc", "")
        assertEquals(3, s.size)
        s.forEach { assertEquals(DiffRenderer.Op.DEL, it.op) }
    }

    @Test fun `empty reference is all insert`() {
        val s = DiffRenderer.align("", "xyz")
        assertEquals(3, s.size)
        s.forEach { assertEquals(DiffRenderer.Op.INS, it.op) }
    }

    @Test fun `both empty produces nothing`() {
        assertEquals(0, DiffRenderer.align("", "").size)
    }

    @Test fun `single substitution aligns`() {
        // 当 LCS = 1 时一般化 alignment 可能是 MATCH+SUB+MATCH 或 SUB+MATCH+MATCH 等多种
        // 我们只要求总操作数 ≤ max(refLen, hypLen)
        val s = DiffRenderer.align("cat", "cut")
        // 至少包含 2 个 MATCH + 1 个 SUB
        val matches = s.count { it.op == DiffRenderer.Op.MATCH }
        val subs = s.count { it.op == DiffRenderer.Op.SUB }
        assertEquals(2, matches)
        assertEquals(1, subs)
    }

    @Test fun `chinese mixed alignment preserves order`() {
        val s = DiffRenderer.align("今天天气", "今晚天气")
        // 拼回 reference 序应该等于原始 ref（DEL/MATCH/SUB 都贡献 refChar）
        val ref = s.filter { it.refChar != null }.joinToString("") { it.refChar.toString() }
        assertEquals("今天天气", ref)
        val hyp = s.filter { it.hypChar != null }.joinToString("") { it.hypChar.toString() }
        assertEquals("今晚天气", hyp)
    }

    @Test fun `total ops bounded by sum of lengths`() {
        val ref = "hello world"
        val hyp = "halo word"
        val s = DiffRenderer.align(ref, hyp)
        // 任何 LCS 回溯序列长度都不会超过两边长度之和
        assert(s.size <= ref.length + hyp.length)
    }
}
