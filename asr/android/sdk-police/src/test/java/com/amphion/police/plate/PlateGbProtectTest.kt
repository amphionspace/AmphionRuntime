package com.amphion.police.plate

import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

/** 守护：国标码 GB28181 不应被误纠成车牌「冀B…」（冀/辽 部署 tie-break 下）。 */
class PlateGbProtectTest {

    private lateinit var kb: PlateKnowledgeBase
    private lateinit var readingMap: PlateReadingMap

    @Before
    fun setUp() {
        kb = loadKnowledgeBase()
        readingMap = loadReadingMap(kb)
    }

    @Test
    fun gb28181_not_treated_as_plate() {
        val n = PlateNormalizerV2.create(kb, readingMap, contextProvinces = listOf('冀', '辽'))
        // 无车牌锚词 → GB28181 应原样保留（去空格），不得出现 冀B
        assertEquals("这个摄像头支持GB28181。", n.normalize("这个摄像头支持GB28181。").text)
        assertEquals("按GB28181接入平台。", n.normalize("按GB28181接入平台。").text)
        val spaced = n.normalize("这个摄像头支持GB 281 8181。").text
        assert(!spaced.contains("冀B")) { "不应误纠为冀B: $spaced" }
    }

    @Test
    fun real_plate_gb28181_with_anchor_still_corrected() {
        val n = PlateNormalizerV2.create(kb, readingMap, contextProvinces = listOf('冀', '辽'))
        // 有车牌锚词（车/查/牌/辆…）→ 真车牌被误识成 GB28181 时仍纠回 冀B28181
        for (c in listOf(
            "查询车牌GB28181的车主信息。",
            "发现一辆GB28181涉嫌套牌。",
            "帮我核查GB28181这辆车。",
        )) {
            val out = n.normalize(c).text
            println("IN : $c\nOUT: $out")
            assert(out.contains("冀B28181")) { "有锚词应纠回冀B28181: $out" }
        }
    }
}
