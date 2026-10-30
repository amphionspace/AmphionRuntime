package com.amphion.dingqiao.diarization

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** 只测纯逻辑：预览帧折算与原生 JSON 解析，不加载原生库。 */
class SortformerDiarizationInferenceTest {
    @Test
    fun previewFramesAreAMultipleOfEightWithinTheChunk() {
        // 0 或负数关闭预览
        assertEquals(0, SortformerDiarizationInference.previewFrames(0))
        assertEquals(0, SortformerDiarizationInference.previewFrames(-1))
        // 默认 5000 ms：5000/80 = 62 个编码帧 -> 496 个 mel 帧
        assertEquals(496, SortformerDiarizationInference.previewFrames(5_000))
        // 下限 8（80 ms 一个编码帧），上限 984（整块 992 以下）
        assertEquals(8, SortformerDiarizationInference.previewFrames(10))
        assertEquals(984, SortformerDiarizationInference.previewFrames(100_000))
        for (ms in 1..20_000 step 37) {
            val frames = SortformerDiarizationInference.previewFrames(ms)
            assertEquals(0, frames % 8)
            assertTrue(frames in 8..984)
        }
    }

    @Test
    fun parseReadsEventsRunsAndCounters() {
        val rendered = """
            {"events":[
              {"kind":"preview","beginFrame":0,"frames":200,"inferenceMs":41.5,
               "runs":[[[0,120]],[],[],[]]},
              {"kind":"final","beginFrame":0,"frames":992,"inferenceMs":398.2,
               "runs":[[[0,300],[400,500]],[[310,390]],[],[]]}
            ],"melFrames":992,"samples":158720}
        """.trimIndent()
        val result = SortformerDiarizationInference.parse(rendered)
        assertEquals(2, result.events.size)
        assertEquals(992L, result.melFrames)
        assertEquals(158_720L, result.samples)

        val preview = result.events[0]
        assertTrue(preview.preview)
        assertEquals(200, preview.frames)
        assertEquals(listOf(FrameSpan(0, 120)), preview.runs[0])
        // 预览里只有槽位 0 发声，其余槽位无区间
        assertArrayEquals(intArrayOf(0, -1, -1, -1), preview.firstSpeechFrames())

        val finalEvent = result.events[1]
        assertTrue(!finalEvent.preview)
        assertEquals(2, finalEvent.runs[0].size)
        assertEquals(FrameSpan(310, 390), finalEvent.runs[1][0])
        assertArrayEquals(intArrayOf(0, 310, -1, -1), finalEvent.firstSpeechFrames())
    }

    @Test
    fun parseToleratesAnEmptyFeed() {
        val result = SortformerDiarizationInference.parse("""{"events":[],"melFrames":0,"samples":0}""")
        assertTrue(result.events.isEmpty())
        assertEquals(0L, result.samples)
    }
}
