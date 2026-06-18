package com.amphion.police.plate

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.BufferedReader
import java.io.File

/** round12 手测 27 句（timestamp >= 1780665556299）回放。 */
class Round12ManualReplayTest {

    private lateinit var normalizer: PlateNormalizer

    @Before
    fun setUp() {
        normalizer = PlateNormalizer.create(loadProductionDict())
    }

    private fun loadProductionDict(): PlateHomophoneDict {
        val f = TestAssets.resolve("plate/plate_homophones.csv")
        return PlateHomophoneDict.loadFromReader(BufferedReader(f.reader()))
    }

    private fun resolveRound12Tsv(): File {
        var dir: File? = File(System.getProperty("user.dir") ?: ".")
        repeat(8) {
            val base = dir ?: return@repeat
            val f = File(base, "plate-eval-round12/plate_eval.tsv")
            if (f.isFile) return f
            dir = base.parentFile
        }
        return File("plate-eval-round12/plate_eval.tsv")
    }

    private val manualCases: List<Pair<String, String>> = listOf(
        "麻烦帮我核查GR八三三八零车辆情况。" to "冀R83380",
        "帮忙核查车牌号GR九四三九零的车辆基础信息。" to "冀R94390",
        "请确认一下G二五九九七三车辆目前是否有异常记录？" to "冀R59973",
        "查一下GR七幺二三七车辆现在的基本情况。" to "冀R71237",
        "帮忙核实一下G二九五零五八是不是目标车辆？" to "冀R95058",
        "帮我看下GR幺四四六幺车辆有没有关联警情？" to "冀R14461",
        "帮忙核查一下车牌号为GR四三六幺六的情况。" to "冀R43616",
        "请确认一下GR七零六二四车辆目前是否有异常记录？" to "冀R70624",
        "帮忙核实一下，GR三八八五是不是目标车辆？" to "冀R38885",
        "看一下车牌号为继，而九八六七零的车辆有没有处置记？" to "冀R98670",
        "请帮忙查询辽B八八四九车辆情况。" to "辽B88849",
        "查下辽B七四七七七车辆现在的基本情况。" to "辽B74777",
        "帮忙查一下辽B三幺八八这辆车的登记情况。" to "辽B31888",
        "帮忙看一下辽B幺六幺四四车辆近期有没有相关警？" to "辽B16144",
        "麻烦查一下车牌号，辽B二三五六三，近期有没有被记录过？" to "辽B23563",
        "请帮忙查询辽B二六零八八车辆情况。" to "辽B26088",
        "查一下车牌号为辽B幺八四二二的车有没有登记信息？" to "辽B18422",
        "帮忙核对一下，辽B幺四四五六这辆车是不是报警人说的车？" to "辽B14456",
        "查一下辽B六八四三二车辆现在的基本情况。" to "辽B68432",
        "帮我看下辽B八四七四四车辆有没有关联警情？" to "辽B84744",
        "看一下车牌号为辽B九幺三四七的车辆有没有处置记录？" to "辽B91347",
    )

    @Test
    fun replay_manual_unique_cases() {
        var match = 0
        val fixable = mutableListOf<String>()
        val asrDigitDrop = mutableListOf<String>()
        manualCases.forEach { (raw, expected) ->
            val r = normalizer.normalize(raw)
            val ok = r.primaryPlate == expected
            if (ok) {
                match++
            } else {
                println("FAIL exp=$expected got=${r.primaryPlate}\n  raw=$raw\n  norm=${r.text}")
                val tail = raw.substringAfter("GR").substringAfter("G二").substringAfter("辽B")
                    .substringAfter("继，而").substringAfter("冀R")
                val n = tail.count { it in "零〇一二三四五六七八九幺两" || it.isDigit() }
                if (n < 5) asrDigitDrop.add(expected) else fixable.add(expected)
            }
        }
        val total = manualCases.size
        println(
            "[round12 manual replay] exact_match=$match/$total " +
                "asr_digit_drop=${asrDigitDrop.size} still_fixable=${fixable.size}",
        )
        if (fixable.isNotEmpty()) {
            println("still_fixable: $fixable")
        }
        assertTrue("fixable failures: $fixable", fixable.isEmpty())
    }
}
