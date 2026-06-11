package com.amphion.police.station

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.StringReader

class PoliceStationNormalizerTest {

    private lateinit var normalizer: PoliceStationNormalizer

    @Before
    fun setUp() {
        normalizer = PoliceStationNormalizer.create(
            PoliceStationHomophoneDict.loadFromReader(loadProductionHomophones()),
            PoliceStationGazetteer.loadFromReader(loadProductionGazetteer()),
        )
    }

    @Test
    fun extractStation_stripsLeadingVerbs() {
        assertEquals(
            "张掖路派出所",
            PoliceStationTextUtil.extractStation("帮忙看看张掖路派出所今天的接警情况。"),
        )
        assertEquals(
            "中关村派出所",
            PoliceStationTextUtil.extractStation("帮忙对比一下中关村派出所最近两个工作日的接警数据。"),
        )
        assertEquals(
            "南京市秦淮区夫子庙派出所",
            PoliceStationTextUtil.extractStation(
                "麻烦汇总南京市秦淮区夫子庙派出所周末两天的接警总量和日均数量。",
            ),
        )
        assertEquals(
            "高新派出所",
            PoliceStationTextUtil.extractStation("汇总高新派出所本季度以来的接警总量和日均数量。"),
        )
        assertEquals(
            "海口市美兰区海甸派出所",
            PoliceStationTextUtil.extractStation("帮忙导出海口市美兰区海甸派出所六月以来的接警统计结果。"),
        )
    }

    @Test
    fun normalize_round01_homophoneFixes() {
        val cases = listOf(
            "帮我查一下武汉市洪善区冠善派出所今天晚高峰按日期汇总的接警数据。" to "武汉市洪山区关山派出所",
            "给我看一下南昌市西湖区神经塔派出所近五个工作日分辖区的接警。" to "南昌市西湖区绳金塔派出所",
            "帮忙导出广州市海珠区琢洲派出所近十五天的接警统计结果。" to "广州市海珠区琶洲派出所",
            "请把银川市金凤区、上海西路派出所上周的接警情况整理一下。" to "银川市金凤区上海西路派出所",
            "把沈阳市铁溪区新工派出所今天上午的接警数据，按派井时段列一下。" to "沈阳市铁西区兴工派出所",
        )
        for ((raw, expectedStation) in cases) {
            val r = normalizer.normalize(raw)
            assertTrue("raw=$raw hyp=${r.text}", r.text.contains(expectedStation))
            assertEquals(expectedStation, r.primaryStation)
        }
    }

    @Test
    fun normalize_knownStationUnchanged() {
        val input = "汇总中关村派出所上个月的接警情况。"
        val r = normalizer.normalize(input)
        assertEquals("中关村派出所", r.primaryStation)
        assertTrue(r.spans.any { it.valid })
    }

    @Test
    fun normalize_p2_commaBeforeStation() {
        val raw = "请把拉萨市城关区八阔，派出所前天的接警情况整理一下。"
        val r = normalizer.normalize(raw)
        assertTrue(r.text.contains("萨市城关区八廓派出所"))
        assertTrue(!r.text.contains("，派出所"))
    }

    @Test
    fun normalize_p2_adminPunct() {
        val raw = "请把银川市金凤区、上海西路派出所上周的接警情况整理一下。"
        val r = normalizer.normalize(raw)
        assertEquals("银川市金凤区上海西路派出所", r.primaryStation)
        assertTrue(!r.text.contains("、"))
    }

    @Test
    fun normalize_p3_sentencePolish() {
        val raw = "看一下泉城路派出所，本周一共接警多少？"
        val r = normalizer.normalize(raw)
        assertEquals("看一下泉城路派出所本周一共接警多少起。", r.text)
    }

    @Test
    fun normalize_tier1_round01Failures() {
        val cases = listOf(
            "棒棒对比一下，深圳市富田区莲花派出所最近两个工作日和上一个周期的接警数据。" to
                "深圳市福田区莲花派出所",
            "帮我看一下西安市贝林区南大街派出所昨天夜间的接警高峰时段。" to
                "西安市碑林区南大街派出所",
            "看看深圳市落户区东门派出所昨天的接警情况有没有异常波动。" to
                "深圳市罗湖区东门派出所",
            "把重庆市沙坪坝区慈溪口派出所近三天接警最多的时段列出来。" to
                "重庆市沙坪坝区磁器口派出所",
            "帮忙查一下苏州市工业园区湖溪派出所。昨天白天接警数量。" to
                "苏州市工业园区湖西派出所",
            "帮忙看看呼和浩特市塞罕区大学东路派出所六月以来的接警情况。" to
                "呼和浩特市赛罕区大学东路派出所",
            "查一下宁波市鄞州区户民派出所今天早高峰的接警峰值和最低值。" to
                "宁波市鄞州区福明派出所",
            "麻烦核一下济南市市中区赶石桥派出所。本周末各时段的接警数据。" to
                "济南市市中区杆石桥派出所",
            "给我拉一下昆明市盘龙区坨东派出所本月有没有接警记录。" to
                "昆明市盘龙区拓东派出所",
            "统计合肥市蜀山区比价山派出所今天的接警记录按天分一下。" to
                "合肥市蜀山区笔架山派出所",
            "把哈尔滨市道外区境与派出所今天晚高峰接警最多的时段列出来。" to
                "哈尔滨市道外区靖宇派出所",
            "帮我查一下乌鲁木齐市三伊巴克区友好路派出所今天下午按日期汇总的接警数据。" to
                "乌鲁木齐市沙依巴克区友好路派出所",
            "统计天翼广场派出所六月以来的接警纪录，按天分以下。" to
                "天一广场派出所",
            "请把拉萨市城管区巴阔派出所前天的接警情况整理一下。" to
                "萨市城关区八廓派出所",
        )
        for ((raw, expectedStation) in cases) {
            val r = normalizer.normalize(raw)
            assertTrue("raw=$raw hyp=${r.text}", r.text.contains(expectedStation))
            assertEquals(expectedStation, r.primaryStation)
        }
    }

    @Test
    fun normalize_tier2_round01Failures() {
        val cases = listOf(
            "看看华山路派出所最近一个月的接接警情况有没有异常波动？" to
                "黄山路派出所",
            "给我看一下石家庄市雨花区裕兴派出所，昨天晚上的接京明细和总量。" to
                "石家庄市裕华区裕兴派出所",
            "麻烦汇总，郑州市振东新区，如野湖派出所，昨天夜间的接警。" to
                "郑州市郑东新区如意湖派出所",
            "帮忙看看乌市广场派出所近十五天的接警情况。" to
                "五四广场派出所",
            "麻烦和一下关前街派出所最近一周的处境高峰时段。" to
                "观前街派出所",
            "帮我统计一下贵阳市关山湖区金阳派出所，昨天夜间的处警明细和总量。" to
                "贵阳市观山湖区金阳派出所",
            "查一下四季大道派出所近十五天的处警数据，顺便看总数。" to
                "世纪大道派出所",
            "帮我看一下杭州市余杭区良珠派出所上个月按日期汇总的出京数据。" to
                "杭州市余杭区良渚派出所",
            "帮忙道出大连市沙河口区新海湾派出所昨天的处警统计结果。" to
                "大连市沙河口区星海湾派出所",
            "给我拉一下银川市警方局上海西路派出所上周各市段的处警数据。" to
                "银川市金凤区上海西路派出所",
            "整理南京市秦淮区父子庙派出所，今天早高峰的出警数据按日期排序。" to
                "南京市秦淮区夫子庙派出所",
            "请把上海市建安区南京西路派出所最近两个工作日的出警情况整理一下。" to
                "上海市静安区南京西路派出所",
            "把上海市徐汇区曹河经派出所最近三天处警最多的时段列出来。" to
                "上海市徐汇区漕河泾派出所",
            "帮我统计一下郑州市振东新区，如意湖派出所近七天的处警明细和总量。" to
                "郑州市郑东新区如意湖派出所",
            "帮我统计一下郑州市振东新区，如意湖派出所近七天的处景明细和总量。" to
                "郑州市郑东新区如意湖派出所",
            "帮忙看看长沙市天心区坡之街派出所，昨天夜间出警数量。" to
                "长沙市天心区坡子街派出所",
            "查一下沈阳市申河区中街派出所，今天的出警数据，顺便看总数。" to
                "沈阳市沈河区中街派出所",
            "帮忙导出青岛市市北区泰东派出所最近一个月的出警统计。" to
                "青岛市市北区台东派出所",
            "麻烦看一下南宁市西乡塘区恒阳派出所近三十天处警亮有没有明显变化？" to
                "南宁市西乡塘区衡阳派出所",
            "帮忙对比一下大连市干净资区周岁至派出所，最近三天和上一个周期的出警数据。" to
                "大连市甘井子区周水子派出所",
            "请帮忙整理一下海口市穷山区阜成派出所本周末的出警。" to
                "海口市琼山区府城派出所",
            "看下华业路派出所，前天一共出警多少起。" to
                "花园路派出所",
            "请把合肥市包河区五谷路派出所近三天的处警情况整理一。" to
                "合肥市包河区芜湖路派出所",
            "麻烦看一下太原市兴化岭区鼓楼派出所，昨天出警的有没有明显变化？" to
                "太原市杏花岭区鼓楼派出所",
            "帮忙汇总一下重庆市沙坪坝区瓷器口派出所六月以来的处警数据。" to
                "重庆市沙坪坝区磁器口派出所",
            "给我拉一下广州市海珠区耙州派出所，今天上午各时段的处警数据。" to
                "广州市海珠区琶洲派出所",
        )
        for ((raw, expectedStation) in cases) {
            val r = normalizer.normalize(raw)
            assertTrue("raw=$raw hyp=${r.text}", r.text.contains(expectedStation))
            assertEquals(expectedStation, r.primaryStation)
        }
    }

    @Test
    fun gazetteerHomophone_doesNotReplaceOutsideStationSpan() {
        val cases = listOf(
            "今天经过华山路附近，没有报警。" to "华山路",
            "关前街有很多商铺，请留意。" to "关前街",
            "从四季大道往东走。" to "四季大道",
        )
        for ((raw, keep) in cases) {
            val r = normalizer.normalize(raw)
            assertTrue("raw=$raw hyp=${r.text}", r.text.contains(keep))
            assertTrue("should not inject 派出所 correction: $raw", !r.text.contains("黄山路派出所"))
        }
    }

    @Test
    fun gazetteerHomophone_correctsStationSpanWhenInGazetteer() {
        val r = normalizer.normalize("看看华山路派出所最近一个月的接警情况。")
        assertEquals("黄山路派出所", r.primaryStation)
        assertTrue(r.text.contains("黄山路派出所"))
    }

    @Test
    fun decodeGuard_skipsGibberish() {
        val raw = "同济通讯统计通通控控。公共治理滚滚滚滚滚滚。"
        val r = normalizer.normalize(raw)
        assertTrue(r.decodeCollapse)
        assertEquals(raw, r.text)
    }

    private fun loadProductionHomophones(): BufferedReader {
        val f = resolveAsset("police_station/station_homophones.csv")
        return f.bufferedReader(Charsets.UTF_8)
    }

    private fun loadProductionGazetteer(): BufferedReader {
        val f = resolveAsset("police_station/station_gazetteer.txt")
        return f.bufferedReader(Charsets.UTF_8)
    }

    private fun resolveAsset(rel: String): File {
        val roots = listOf(
            "src/main/assets",
            "sample/src/main/assets",
            "android/AmphionRuntime/sample/src/main/assets",
        )
        val cwd = File(System.getProperty("user.dir") ?: ".")
        for (base in listOfNotNull(cwd, cwd.parentFile, cwd.parentFile?.parentFile)) {
            if (base == null) continue
            for (r in roots) {
                val f = File(base, "$r/$rel")
                if (f.isFile) return f
            }
        }
        error("asset not found: $rel")
    }
}
