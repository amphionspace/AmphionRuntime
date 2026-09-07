package com.amphion.police

import com.amphion.police.plate.PlateNormalizerV2
import com.amphion.police.plate.loadKnowledgeBase
import com.amphion.police.plate.loadExactResiduals
import com.amphion.police.plate.loadReadingMap
import com.amphion.police.station.PoliceStationGazetteer
import com.amphion.police.station.PoliceStationHomophoneDict
import com.amphion.police.station.PoliceStationNormalizerV2
import com.amphion.police.station.StationReadingMap
import com.amphion.police.terms.PoliceTermsExactHomophoneDict
import com.amphion.police.terms.PoliceTermsGazetteer
import com.amphion.police.terms.PoliceTermsHomophoneDict
import com.amphion.police.terms.PoliceTermsNormalizerV2
import com.amphion.police.terms.TermReadingMap
import com.amphion.police.test.TestAssets
import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.BufferedReader
import java.io.FileReader

/** 2026-08-27 甲方验收表标红结果：整句残差修复及同音负例。 */
class PoliceAcceptance20260827Test {

    private val plateCases = linkedMapOf(
        "川A五L五五" to "川A5L555",
        "二A二B222" to "鄂A2B222",
        "沪AD6666" to "沪AD66666",
        "沪B18117" to "沪B181117",
        "一A三K234" to "冀A3K234",
        "京A00001警" to "京A0001警",
        "仅挨12345" to "京A12345",
        "AA12345" to "京AA12345",
        "今爱滴9999" to "京AD99999",
        "LN6660" to "辽NLN666L",
        "卢比六A六六" to "鲁B6A666",
        "LNL661" to "鲁LNL661N",
        "苏一七街987" to "苏E7J987",
        "像2000警" to "湘A0000警",
        "相比BP 226" to "湘BBP226P",
        "预案11000 - 1000" to "豫A1Y111",
        "粤A0235警" to "粤A0235警",
        "月比12345" to "粤B12345",
        "粤BF000000000" to "粤BF00000",
        "乐里八八哔" to "粤BPB888B",
        "粤12177" to "粤E217777",
        "四A八八F八八" to "浙A88F88",
    )

    private val termCases = linkedMapOf(
        "防暴" to "防盗",
        "服务欺凌" to "服务欺诈",
        "化解矛盾矛" to "化解矛盾",
        "活" to "活儿",
        "警戒" to "警鉴",
        "借贷" to "警戒带",
        "开启盘查智能" to "开启盘查智能体",
        "耐心疏散" to "耐心疏导",
        "启动计算机" to "启动计算器",
        "取256号" to "去二百五十六号",
        "事故" to "事主",
        "左车" to "锁车",
        "外面真冷" to "外面真冷啊",
        "现场缉枪" to "现场勘查箱",
        "询问笔录" to "讯问笔录",
        "主要警综" to "主要警种",
    )

    private fun reader(path: String): BufferedReader =
        BufferedReader(FileReader(TestAssets.resolve(path)))

    private fun terms(): PoliceTermsNormalizerV2 {
        val values = reader("police_terms/term_gazetteer.txt").readLines()
            .map { it.trim() }
            .filter { it.isNotEmpty() && !it.startsWith("#") }
            .distinct()
            .sortedByDescending { it.length }
        return PoliceTermsNormalizerV2.create(
            PoliceTermsHomophoneDict.loadFromReader(reader("police_terms/term_homophones.csv")),
            PoliceTermsGazetteer.loadFromReader(reader("police_terms/term_gazetteer.txt")),
            values,
            TermReadingMap.loadFromReader(reader("police_terms/term_homophones.csv")),
            PoliceTermsExactHomophoneDict.loadFromReader(
                reader("police_terms/term_exact_homophones.csv"),
            ),
        )
    }

    private fun plate(): PlateNormalizerV2 {
        val kb = loadKnowledgeBase()
        return PlateNormalizerV2.create(
            kb,
            loadReadingMap(kb),
            listOf('冀', '辽'),
            loadExactResiduals(),
        )
    }

    private fun station(): PoliceStationNormalizerV2 {
        val values = reader("police_station/station_gazetteer.txt").readLines()
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
            values,
            StationReadingMap.loadFromReader(
                reader("police_station/station_homophones.csv"),
            ),
        )
    }

    private fun enhance(
        raw: String,
        terms: PoliceTermsNormalizerV2,
        plate: PlateNormalizerV2,
        station: PoliceStationNormalizerV2,
    ): String {
        val afterTerms = terms.normalize(raw).text
        val afterPlate = plate.normalize(afterTerms).text
        val afterStation = station.normalize(afterPlate).text
        return terms.polish(afterStation)
    }

    @Test
    fun recovers_all_marked_plate_residuals() {
        val normalizer = plate()

        for ((raw, expected) in plateCases) {
            assertEquals("raw=$raw", expected, normalizer.normalize(raw).text)
            assertEquals("punctuated raw=$raw", "  $expected。 ", normalizer.normalize("  $raw。 ").text)
        }
    }

    @Test
    fun recovers_all_marked_term_and_command_residuals() {
        val normalizer = terms()

        for ((raw, expected) in termCases) {
            assertEquals("raw=$raw", expected, normalizer.normalize(raw).text)
            assertEquals("punctuated raw=$raw", "  $expected。 ", normalizer.normalize("  $raw。 ").text)
        }
    }

    @Test
    fun keeps_legitimate_contexts_around_ambiguous_marked_terms() {
        val normalizer = terms()
        val inputs = listOf(
            "请检查防暴设备是否完好。",
            "交通事故已经处理完毕。",
            "依法询问证人并制作询问笔录。",
            "请启动计算机完成系统升级。",
            "银行借贷业务需要风险审核。",
            "警戒状态仍未解除。",
            "他今天没有活干。",
            "耐心疏散围观群众。",
            "现场缉枪行动已经开始。",
            "主要警综系统已经升级。",
            "外面真冷，我们先回去吧。",
            "左车道正在施工。",
        )

        for (input in inputs) assertEquals(input, normalizer.normalize(input).text)
    }

    @Test
    fun keeps_plate_residual_strings_when_they_are_only_mentioned_in_context() {
        val normalizer = plate()
        val inputs = listOf(
            "请复述川A五L五五这个错误。",
            "表格里记录了今爱滴9999这条错听。",
            "原始输出粤BF000000000需要人工核对。",
        )

        for (input in inputs) assertEquals(input, normalizer.normalize(input).text)
    }

    @Test
    fun recovers_all_marked_residuals_through_the_full_v2_pipeline() {
        val terms = terms()
        val plate = plate()
        val station = station()

        for ((raw, expected) in plateCases + termCases) {
            assertEquals("raw=$raw", expected, enhance(raw, terms, plate, station))
            assertEquals(
                "punctuated raw=$raw",
                "  $expected。 ",
                enhance("  $raw。 ", terms, plate, station),
            )
        }
    }
}
