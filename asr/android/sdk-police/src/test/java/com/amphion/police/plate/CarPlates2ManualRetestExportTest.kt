package com.amphion.police.plate

import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.nio.charset.StandardCharsets

/** 导出各省回放仍失败 case，供人工喊测（格式同上海 shanghai_manual_retest_18）。 */
class CarPlates2ManualRetestExportTest {

    private val evalDir: File by lazy {
        val fromModule = File("../../../../evaluation/plate_number/car_plates2_zh_20260612_0331")
        if (fromModule.isDirectory) fromModule.canonicalFile
        else File(System.getProperty("user.dir"))
            .resolve("../../../../evaluation/plate_number/car_plates2_zh_20260612_0331")
            .canonicalFile
    }

    private val casesTsv: File by lazy {
        File("../../../../evaluation/plate_number/staging_car_plates2_zh_20260612_0331/cases.tsv")
            .canonicalFile
    }

    private val targetRegions = listOf(
        "shandong", "shanxi", "henan", "liaoning", "heilongjiang", "jilin", "zhejiang",
    )

    private fun normalizer(): PlateNormalizer {
        val csv = File("src/main/assets/plate/plate_homophones.csv")
        val dict = PlateHomophoneDict.loadFromReader(
            BufferedReader(FileReader(csv, StandardCharsets.UTF_8)),
        )
        return PlateNormalizer.create(dict)
    }

    @Test
    fun export_manual_retest_still_fail() {
        val norm = normalizer()
        val cases = casesTsv.readLines().drop(1).map { line ->
            val p = line.split("\t")
            listOf(p[0], p[2], p[3], if (p.size > 4) p[4] else "")
        }
        val evalRows = evalDir.resolve("plate_eval.tsv").readLines().drop(1).map { line ->
            line.split("\t")
        }

        val summary = StringBuilder()
        summary.appendLine("=== car_plates2 人工复测导出（回放仍失败）===")
        summary.appendLine()

        for (region in targetRegions) {
            val fails = mutableListOf<List<String>>()
            var total = 0
            var replayOk = 0
            for ((case, row) in cases.zip(evalRows)) {
                if (case[2] != region) continue
                total++
                val exp = row[1].ifEmpty { case[1] }
                val asr = row[2]
                val deviceGot = row[4]
                val replayGot = norm.normalize(asr).primaryPlate ?: ""
                if (replayGot == exp) {
                    replayOk++
                    continue
                }
                fails += listOf(
                    case[0],
                    exp,
                    deviceGot,
                    replayGot,
                    case[3],
                    asr,
                )
            }

            val tsvPath = evalDir.resolve("manual_retest_${region}_still_fail.tsv")
            val txtPath = evalDir.resolve("manual_retest_${region}_still_fail.txt")
            val header = "idx\tutt_id\texpected\tdevice_got\treplay_got\ttts_text\tdevice_asr"
            val tsvBody = fails.mapIndexed { i, row ->
                "${i + 1}\t${row.joinToString("\t") { it.replace("\t", " ") }}"
            }.joinToString("\n")
            tsvPath.writeText("$header\n$tsvBody\n")

            val txt = buildString {
                appendLine("${regionLabel(region)} 回放仍失败 ${fails.size} 条（total=$total replay=$replayOk）")
                appendLine("请按 tts_text 朗读，对比 device_asr（TTS批测）与实机识别。")
                appendLine()
                fails.forEachIndexed { i, row ->
                    appendLine("--- #${i + 1} ${row[0]} ---")
                    appendLine("期望车牌: ${row[1]}")
                    appendLine("请朗读: ${row[4]}")
                    appendLine("TTS批测ASR: ${row[5]}")
                    appendLine("机端: ${row[2]} | 回放: ${row[3]}")
                    appendLine()
                }
            }
            txtPath.writeText(txt)

            summary.appendLine(
                "${regionLabel(region)}: replay=${replayOk}/$total still_fail=${fails.size} " +
                    "-> ${tsvPath.name}",
            )
        }

        val allPath = evalDir.resolve("manual_retest_provinces_summary.txt")
        allPath.writeText(summary.toString())
        println(summary.toString())
    }

    private fun regionLabel(region: String): String = when (region) {
        "shandong" -> "山东"
        "shanxi" -> "山西"
        "henan" -> "河南"
        "liaoning" -> "辽宁"
        "heilongjiang" -> "黑龙江"
        "jilin" -> "吉林"
        "zhejiang" -> "浙江"
        else -> region
    }
}
