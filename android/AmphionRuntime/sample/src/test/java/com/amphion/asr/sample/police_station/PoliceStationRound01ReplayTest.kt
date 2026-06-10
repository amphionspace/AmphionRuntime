package com.amphion.asr.sample.police_station

import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.nio.charset.StandardCharsets

/**
 * 离线回放派出所 Round01 真机 asr_raw，评估 P0–P4 后处理修复后指标。
 * 数据：evaluation/police_station/round01/police_station_eval.tsv
 */
class PoliceStationRound01ReplayTest {

    private val evalDir: File by lazy {
        val fromModule = File("../../../../evaluation/police_station/round01")
        if (fromModule.isDirectory) fromModule.canonicalFile
        else File(System.getProperty("user.dir"))
            .resolve("../../../../evaluation/police_station/round01")
            .canonicalFile
    }

    private fun normalizer(): PoliceStationNormalizer {
        val csv = resolveAsset("police_station/station_homophones.csv")
        val gaz = resolveAsset("police_station/station_gazetteer.txt")
        return PoliceStationNormalizer.create(
            PoliceStationHomophoneDict.loadFromReader(
                BufferedReader(FileReader(csv, StandardCharsets.UTF_8)),
            ),
            PoliceStationGazetteer.loadFromReader(
                BufferedReader(FileReader(gaz, StandardCharsets.UTF_8)),
            ),
        )
    }

    data class Row(
        val uttId: String,
        val refText: String,
        val expectedStation: String,
        val asrRaw: String,
        val oldNormalized: String,
        val oldStationHit: Boolean,
        val oldSentMatch: Boolean,
    )

    private fun loadRows(): List<Row> {
        val tsv = File(evalDir, "police_station_eval.tsv")
        require(tsv.isFile) { "missing ${tsv.absolutePath}" }

        val rows = mutableListOf<Row>()
        tsv.bufferedReader(StandardCharsets.UTF_8).use { br ->
            br.readLine() ?: error("empty tsv")
            br.forEachLine { line ->
                if (line.isBlank()) return@forEachLine
                val parts = line.split('\t')
                require(parts.size >= 10) { "bad line: $line" }
                val ref = parts[2].trim()
                rows += Row(
                    uttId = parts[1].trim(),
                    refText = ref,
                    expectedStation = PoliceStationTextUtil.extractStation(ref),
                    asrRaw = parts[4].trim(),
                    oldNormalized = parts[5].trim(),
                    oldStationHit = parts[8].trim().uppercase() == "Y",
                    oldSentMatch = parts[9].trim().uppercase() == "Y",
                )
            }
        }
        return rows
    }

    private fun levenshtein(a: String, b: String): Int {
        if (a == b) return 0
        if (a.isEmpty()) return b.length
        if (b.isEmpty()) return a.length
        var prev = IntArray(b.length + 1) { it }
        for (i in a.indices) {
            val cur = IntArray(b.length + 1)
            cur[0] = i + 1
            for (j in b.indices) {
                cur[j + 1] = minOf(
                    cur[j] + 1,
                    prev[j + 1] + 1,
                    prev[j] + if (a[i] == b[j]) 0 else 1,
                )
            }
            prev = cur
        }
        return prev[b.length]
    }

    @Test
    fun replay_round01_metrics() {
        val norm = normalizer()
        val rows = loadRows()
        assertEquals(394, rows.size)

        var oldStationHit = 0
        var newStationHit = 0
        var oldSentMatch = 0
        var newSentMatch = 0
        var newGazValid = 0
        var cerEditsOld = 0
        var cerEditsNew = 0
        var cerLen = 0
        var decodeCollapse = 0
        val newlyFixedStation = mutableListOf<String>()
        val newlyFixedSent = mutableListOf<String>()
        val stillMissStation = mutableListOf<String>()

        for (row in rows) {
            val exp = row.expectedStation
            val oldHyp = row.oldNormalized.ifEmpty { row.asrRaw }
            val result = PoliceStationEnhance.apply(row.asrRaw, norm, normalizeEnabled = true)
            val newHyp = result.text

            if (result.decodeCollapse) decodeCollapse++

            val oldHit = exp.isNotEmpty() && exp in oldHyp
            val newHit = exp.isNotEmpty() && exp in newHyp
            if (oldHit) oldStationHit++
            if (newHit) newStationHit++
            if (row.oldSentMatch) oldSentMatch++
            if (newHyp == row.refText) newSentMatch++

            if (result.spans.any { it.valid }) newGazValid++

            cerLen += row.refText.length
            cerEditsOld += levenshtein(row.refText, oldHyp)
            cerEditsNew += levenshtein(row.refText, newHyp)

            if (!oldHit && newHit) {
                newlyFixedStation += "$exp | ${row.asrRaw.take(55)}"
            }
            if (!row.oldSentMatch && newHyp == row.refText) {
                newlyFixedSent += row.uttId
            }
            if (!newHit) {
                stillMissStation += "$exp got=${PoliceStationTextUtil.extractStation(newHyp)} | ${newHyp.take(50)}"
            }
        }

        val report = buildString {
            appendLine("派出所 Round01 离线回放 (n=${rows.size})")
            appendLine("data=${evalDir.absolutePath}")
            appendLine()
            appendLine("=== 修复前（真机 plate_eval 落盘，后处理未生效） ===")
            appendLine("站名命中率(P0口径): $oldStationHit/${rows.size} = ${pct(oldStationHit, rows.size)}")
            appendLine("整句完全匹配:       $oldSentMatch/${rows.size} = ${pct(oldSentMatch, rows.size)}")
            appendLine("语料级整句CER:      ${cerEditsOld.toDouble() / cerLen}")
            appendLine()
            appendLine("=== 修复后（当前 PoliceStationNormalizer 回放 asr_raw） ===")
            appendLine("站名命中率(P0口径): $newStationHit/${rows.size} = ${pct(newStationHit, rows.size)}")
            appendLine("整句完全匹配:       $newSentMatch/${rows.size} = ${pct(newSentMatch, rows.size)}")
            appendLine("gazetteer校验通过:  $newGazValid/${rows.size} = ${pct(newGazValid, rows.size)}")
            appendLine("语料级整句CER:      ${cerEditsNew.toDouble() / cerLen}")
            appendLine("解码崩溃跳过(P4):   $decodeCollapse/${rows.size}")
            appendLine()
            appendLine("=== 变化 ===")
            appendLine("站名新修复: ${newlyFixedStation.size}  整句新修复: ${newlyFixedSent.size}")
            appendLine("站名仍失败: ${stillMissStation.size}")
            appendLine()
            if (newlyFixedStation.isNotEmpty()) {
                appendLine("--- 站名新修复样例 (最多15) ---")
                newlyFixedStation.take(15).forEach { appendLine(it) }
                appendLine()
            }
            if (stillMissStation.isNotEmpty()) {
                appendLine("--- 站名仍失败 (最多20) ---")
                stillMissStation.take(20).forEach { appendLine(it) }
            }
        }

        File(evalDir, "metrics_replay.txt").writeText(report, StandardCharsets.UTF_8)
        println(report)
    }

    private fun resolveAsset(rel: String): File {
        val roots = listOf(
            "src/main/assets",
            "sample/src/main/assets",
        )
        val cwd = File(System.getProperty("user.dir") ?: ".")
        for (base in listOfNotNull(cwd, cwd.parentFile)) {
            for (r in roots) {
                val f = File(base, "$r/$rel")
                if (f.isFile) return f
            }
        }
        error("asset not found: $rel")
    }

    private fun pct(n: Int, total: Int): String =
        if (total == 0) "0.0%" else "%.1f%%".format(100.0 * n / total)
}
