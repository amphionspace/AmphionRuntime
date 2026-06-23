package com.amphion.police.plate

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test
import java.io.BufferedReader
import java.io.FileReader
import java.nio.charset.StandardCharsets

/** 京津冀 JJS 锚点化后：非车牌句 final 文本须保持 identity。 */
class JjsCollateralSelfCheckTest {

    private fun norm(): PlateNormalizer {
        val path = java.nio.file.Paths.get("src/main/assets/plate/plate_homophones.csv")
        val dict = PlateHomophoneDict.loadFromReader(
            BufferedReader(FileReader(path.toFile(), Charsets.UTF_8)),
        )
        return PlateNormalizer.create(dict)
    }

    @Test
    fun districtNames_mustNotCorrupt() {
        val n = norm()
        val gaoxin = "给我看一下成都市高新区桂溪派出所，昨天白天分辖区的接警趋势。"
        assertEquals(gaoxin, n.normalize(gaoxin).text)
        assertFalse(n.normalize(gaoxin).text.contains("高新Q"))

        val zhengdong = "帮我统计一下郑州市郑东新区如意湖派出所近七天的接警量。"
        assertEquals(zhengdong, n.normalize(zhengdong).text)
        assertFalse(n.normalize(zhengdong).text.contains("郑东新Q"))
    }

    @Test
    fun commonWords_mustStayIdentical() {
        val n = norm()
        val probes = listOf(
            "国民经济持续增长。",
            "今晚有京剧表演。",
            "推行精益生产管理。",
            "异地办案需要审批。",
            "培训基地已经建好。",
            "我对这件事记忆深刻。",
            "产品型号为 GR2024 标准版已上市。",
            "深呼吸几次后再开始上台发言。",
        )
        val corrupted = mutableListOf<String>()
        for (input in probes) {
            val out = n.normalize(input).text
            if (out != input) corrupted += "$input -> $out"
        }
        assertEquals(
            "non-plate sentences must be identity:\n" + corrupted.joinToString("\n"),
            0,
            corrupted.size,
        )
    }

    @Test
    fun plateQueries_stillNormalize() {
        val n = norm()
        assertEquals("京G73491", n.normalize("麻烦帮我核查经济73491车辆情况。").primaryPlate)
        assertEquals("冀G73491", n.normalize("帮忙核查一下车牌号为纪记73491的情况。").primaryPlate)
    }
}
