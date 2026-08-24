package com.amphion.police.station

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.BufferedReader
import java.io.InputStreamReader

/** cp5500 station residuals plus collision guards for the closed-set V2 matcher. */
class PoliceStationNormalizerV2SafetyTest {
    private fun reader(path: String): BufferedReader =
        BufferedReader(InputStreamReader(TestAssets.resolve(path).inputStream(), Charsets.UTF_8))

    private fun v2(): PoliceStationNormalizerV2 {
        val names = reader("police_station/station_gazetteer.txt").readLines()
            .map { it.trim() }
            .filter { it.isNotEmpty() && !it.startsWith("#") }
            .distinct()
            .sortedByDescending { it.length }
        return PoliceStationNormalizerV2.create(
            PoliceStationHomophoneDict.loadFromReader(
                reader("police_station/station_homophones.csv"),
            ),
            PoliceStationGazetteer.loadFromReader(
                reader("police_station/station_gazetteer.txt"),
            ),
            names,
            StationReadingMap.loadFromReader(
                reader("police_station/station_homophones.csv"),
            ),
        )
    }

    @Test
    fun recoversCp5500WholeStationAliases() {
        val normalizer = v2()
        val cases = linkedMapOf(
            "统计天意广场派出所六月以来的接警记录。" to "天一广场派出所",
            "麻烦核前街派出所最近一周的处警高峰时段。" to "观前街派出所",
            "麻烦汇总郑州市郑东新区，如有湖派出所昨天夜间的接警总量。" to
                "郑州市郑东新区如意湖派出所",
            "把二荣路派出所前天的接警数据按派警时段列一下。" to "二龙路派出所",
            "给我拉一下海口市琼山区釜城派出所最近两个工作日的接警记录。" to
                "海口市琼山区府城派出所",
            "请把银川市金丰区上海西路派出所上周的接警情况整理一下。" to
                "银川市金凤区上海西路派出所",
            "麻烦看下南宁市西厢塘区衡阳派出所近30天出警量。" to
                "南宁市西乡塘区衡阳派出所",
            "麻烦核一下北京市海淀区山地派出所今天的出警高峰。" to
                "北京市海淀区上地派出所",
        )
        for ((raw, expectedStation) in cases) {
            assertTrue("raw=$raw", expectedStation in normalizer.normalize(raw).text)
        }
    }

    @Test
    fun refusesTruncatedOrAmbiguousStationGuesses() {
        val normalizer = v2()
        val truncated = normalizer.normalize("麻烦核区中街派出所最近一个月的接警数据。").text
        assertFalse(truncated, "中央大街派出所" in truncated)
        assertFalse(truncated, "沈阳市沈河区中街派出所" in truncated)

        val unknown = "请联系长安新城派出所值班人员。"
        assertEquals(unknown, normalizer.normalize(unknown).text)

        for (raw in listOf(
            "请联系天猫广场派出所值班人员。",
            "请联系天狗广场派出所值班人员。",
        )) {
            assertEquals("raw=$raw", raw, normalizer.normalize(raw).text)
        }
    }

    @Test
    fun keepsCorrectLhasaCanonicalName() {
        val input = "请查拉萨市城关区八廓派出所今天的接警记录。"
        val output = v2().normalize(input).text
        assertEquals(input, output)
    }
}
