package com.amphion.asr.sample.eval

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * DeviceWerEstimator 的字符级 Levenshtein + 比率计算单测。
 *
 * 测试覆盖：
 * - 完全匹配 → 0
 * - 完全不匹配 → 接近 1
 * - 中英文混合
 * - 空 reference / 空 hypothesis 的边界
 * - 编辑距离公式正确性（与人工计算对齐）
 */
class DeviceWerEstimatorTest {

    @Test fun `identical strings have zero WER`() {
        assertEquals(0.0, DeviceWerEstimator.estimate("hello", "hello"), 1e-9)
        assertEquals(0.0, DeviceWerEstimator.estimate("你好世界", "你好世界"), 1e-9)
    }

    @Test fun `single substitution counts as 1 over reference length`() {
        // "hello" vs "jello" 距离 1 / 5 = 0.2
        assertEquals(0.2, DeviceWerEstimator.estimate("hello", "jello"), 1e-9)
    }

    @Test fun `pure deletion counts toward WER`() {
        // "hello" vs "" 距离 5 / 5 = 1.0
        assertEquals(1.0, DeviceWerEstimator.estimate("hello", ""), 1e-9)
        // "hello" vs null 同上
        assertEquals(1.0, DeviceWerEstimator.estimate("hello", null), 1e-9)
    }

    @Test fun `pure insertion gives wer larger than 1`() {
        // "" vs anything 按 spec 返回 1.0（避免除以 0）
        assertEquals(1.0, DeviceWerEstimator.estimate("", "hello"), 1e-9)
        // 当 reference 极短而 hypothesis 极长，WER > 1 是允许的（不裁剪）
        val r = DeviceWerEstimator.estimate("a", "abcde")
        assertEquals(4.0, r, 1e-9)
    }

    @Test fun `empty both returns zero`() {
        assertEquals(0.0, DeviceWerEstimator.estimate("", ""), 1e-9)
        assertEquals(0.0, DeviceWerEstimator.estimate("", null), 1e-9)
    }

    @Test fun `chinese single char substitution`() {
        // "今天" vs "明天" → 距离 1 / 2 = 0.5
        assertEquals(0.5, DeviceWerEstimator.estimate("今天", "明天"), 1e-9)
    }

    @Test fun `mixed zh_en deletion`() {
        // "hello world" vs "hello" 距离 6 (空格+world) / 11
        val r = DeviceWerEstimator.estimate("hello world", "hello")
        assertEquals(6.0 / 11.0, r, 1e-9)
    }

    @Test fun `format percent shows accuracy not wer`() {
        // formatPercent 把 WER 翻转成准确率（1 - WER）展示，便于测试员理解
        assertEquals("91.7%", DeviceWerEstimator.formatPercent(0.0833))
        assertEquals("100.0%", DeviceWerEstimator.formatPercent(0.0))
        assertEquals("0.0%", DeviceWerEstimator.formatPercent(1.0))
        // WER > 1 时准确率钳到 0，不出现负数
        assertEquals("0.0%", DeviceWerEstimator.formatPercent(1.5))
    }

    @Test fun `edit distance symmetric`() {
        // 对称性
        val a = "今天 weather 很好"
        val b = "今晚 weather 不错"
        assertEquals(
            DeviceWerEstimator.editDistance(a, b),
            DeviceWerEstimator.editDistance(b, a),
        )
    }
}
