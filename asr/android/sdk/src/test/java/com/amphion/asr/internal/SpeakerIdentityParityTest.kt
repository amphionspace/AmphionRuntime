package com.amphion.asr.internal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * 真实嵌入的跨端等价性：Kotlin 实现必须与主机 python 参考逐条一致。
 *
 * 固件来自 `111223-816`（Sortformer 在它上面把同一人拆到两个槽位、又把另一人并进来，
 * 是客户症状的原形）的 36 个逐槽位发言段，嵌入是真实 CAM++ 输出。
 * 主机那份 python 就是量出"留一标定 34/34 对、对照臂 28/34"的实现
 * （`asr/tools/speaker/20_eval_campplus_identity_hybrid.py`），所以这条用例保证
 * **发出去的和量过的是同一个算法**。
 */
class SpeakerIdentityParityTest {
    private fun fixture(): File {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            val candidate = File(dir, "asr/test-fixtures/speaker-identity/campplus_identity_parity.json")
            if (candidate.isFile) return candidate
            dir = dir.parentFile
        }
        throw AssertionError("找不到等价性固件 campplus_identity_parity.json")
    }

    /** 只取需要的字段，避免为一个测试引入 JSON 依赖。 */
    private fun numbers(block: String, key: String): List<Double> {
        val marker = "\"$key\""
        val at = block.indexOf(marker)
        if (at < 0) return emptyList()
        val open = block.indexOf('[', at)
        val close = block.indexOf(']', open)
        return block.substring(open + 1, close)
            .split(',')
            .mapNotNull { it.trim().toDoubleOrNull() }
    }

    private fun scalar(block: String, key: String): Double {
        val marker = "\"$key\""
        val at = block.indexOf(marker)
        val colon = block.indexOf(':', at)
        val end = block.indexOfFirst(colon) { it == ',' || it == '\n' || it == '}' }
        return block.substring(colon + 1, end).trim().toDouble()
    }

    private fun String.indexOfFirst(from: Int, predicate: (Char) -> Boolean): Int {
        for (index in from until length) if (predicate(this[index])) return index
        return length
    }

    @Test
    fun kotlinMatchesHostReferenceOnRealEmbeddings() {
        val text = fixture().readText()
        val threshold = scalar(text, "mergeThreshold")
        val minAssign = scalar(text, "minAssignSeconds")
        val cap = scalar(text, "maxSpeakers").toInt()
        assertEquals("固件阈值必须与实现默认值一致", SpeakerIdentityAssigner.MERGE_THRESHOLD, threshold, 0.0)
        assertEquals(SpeakerIdentityAssigner.MIN_ASSIGN_SECONDS, minAssign, 0.0)

        // 按 "begin" 切出每个 turn 块，顺序即到达顺序
        val blocks = text.split("\"begin\":").drop(1)
        assertTrue("固件应有多个 turn", blocks.size >= 30)

        val assigner = SpeakerIdentityAssigner(cap, threshold, minAssign)
        var checked = 0
        for (block in blocks) {
            val duration = scalar(block, "duration")
            val embedding = numbers(block, "embedding")
            val expectedIdentity = scalar(block, "identity").toInt()
            val expectedConfidence = scalar(block, "confidence")
            assertTrue("嵌入维度异常", embedding.size > 100)

            val decision = assigner.assign(
                FloatArray(embedding.size) { embedding[it].toFloat() },
                duration,
            )
            assertEquals("第 $checked 段身份不一致", expectedIdentity, decision.identity)
            assertEquals("第 $checked 段 confidence 不一致", expectedConfidence, decision.confidence, 1e-4)
            checked += 1
        }
        assertEquals(blocks.size, checked)
    }
}
