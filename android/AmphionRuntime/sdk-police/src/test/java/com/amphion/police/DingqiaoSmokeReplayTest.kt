package com.amphion.police

import com.amphion.police.plate.PlateHomophoneDict
import com.amphion.police.plate.PlateNormalizer
import com.amphion.police.station.PoliceStationGazetteer
import com.amphion.police.station.PoliceStationHomophoneDict
import com.amphion.police.station.PoliceStationNormalizer
import com.amphion.police.terms.PoliceTermsGazetteer
import com.amphion.police.terms.PoliceTermsHomophoneDict
import com.amphion.police.terms.PoliceTermsNormalizer
import com.amphion.police.test.TestAssets
import org.junit.Before
import org.junit.Test
import java.io.BufferedReader

/**
 * 鼎桥 Demo 真机 smoke 10 条口播用例回放。
 *
 * `asrRaw` 为三星真机/口播常见 ASR 误识（非朗读稿原文）；`mustContain` 为 Final 应出现的增强词。
 */
class DingqiaoSmokeReplayTest {

    private lateinit var termsNormalizer: PoliceTermsNormalizer
    private lateinit var plateNormalizer: PlateNormalizer
    private lateinit var stationNormalizer: PoliceStationNormalizer

    @Before
    fun setUp() {
        termsNormalizer = PoliceTermsNormalizer.create(
            PoliceTermsHomophoneDict.loadFromReader(
                BufferedReader(TestAssets.resolve("police_terms/term_homophones.csv").reader()),
            ),
            PoliceTermsGazetteer.loadFromReader(
                BufferedReader(TestAssets.resolve("police_terms/term_gazetteer.txt").reader()),
            ),
        )
        plateNormalizer = PlateNormalizer.create(
            PlateHomophoneDict.loadFromReader(
                BufferedReader(TestAssets.resolve("plate/plate_homophones.csv").reader()),
            ),
        )
        stationNormalizer = PoliceStationNormalizer.create(
            PoliceStationHomophoneDict.loadFromReader(
                BufferedReader(TestAssets.resolve("police_station/station_homophones.csv").reader()),
            ),
            PoliceStationGazetteer.loadFromReader(
                BufferedReader(TestAssets.resolve("police_station/station_gazetteer.txt").reader()),
            ),
        )
    }

    @Test
    fun replay_dingqiaoSmoke_oralCases() {
        val failures = mutableListOf<String>()
        fun case(id: Int, asrRaw: String, mustContain: List<String>) {
            val out = PoliceEnhancePipeline.apply(
                asrRaw,
                termsNormalizer,
                termsNormalizeEnabled = true,
                plateNormalizer,
                plateNormalizeEnabled = true,
                stationNormalizer,
                stationNormalizeEnabled = true,
            ).text
            for (needle in mustContain) {
                if (!out.contains(needle)) {
                    failures += "smoke#$id asr=[$asrRaw] final=[$out] missing [$needle]"
                }
            }
        }

        case(1, "巡逻组已签收订单，正在前往现场核实可疑人员。", listOf("签收警单"))
        case(1, "巡逻组已签收。 正在前往现场核实可疑人员。", listOf("签收警单"))
        case(2, "路面纠纷简单，请附近警力签收警单。", listOf("纠纷警单"))
        case(2, "路面纠纷简单，请附近警力签收。", listOf("纠纷警单", "签收警单"))
        case(3, "出警人员已经到达小区门口，请与报警人对接。", listOf("处警人员"))
        case(3, "出行人员已经到达小区门口，请与报警人对接。", listOf("处警人员"))
        case(4, "反馈显示暂不需要增派，现场秩序已恢复。", listOf("增派警力"))
        case(4, "反馈显示暂不需要增派。现场秩序已恢复。", listOf("增派警力"))
        case(5, "麻烦帮我核查车牌号冀R八三三八零的车辆情况。", listOf("冀R83380"))
        case(5, "麻烦帮我核查车牌号记R八三三八零的车辆情况。", listOf("冀R83380"))
        case(6, "请帮忙查询辽B八八四九车辆有没有关联警情。", listOf("辽B88849"))
        case(6, "请帮忙查询聊B八八四九车辆有没有关联警情。", listOf("辽B88849"))
        case(7, "查一下车牌号为冀R九八六七零有没有处置记录。", listOf("冀R98670"))
        case(8, "给我看一下南昌市西湖区神经塔派出所近五个工作日的接警情况。", listOf("绳金塔派出所"))
        case(9, "帮我查一下武汉市洪善区冠善派出所今天晚高峰的接警数据。", listOf("关山派出所"))
        case(10, "给我看一下南昌市西湖区神经塔派出所近五个工作日分辖区的接警车。", listOf("绳金塔派出所"))

        if (failures.isNotEmpty()) {
            org.junit.Assert.fail(failures.joinToString("\n"))
        }
    }
}
