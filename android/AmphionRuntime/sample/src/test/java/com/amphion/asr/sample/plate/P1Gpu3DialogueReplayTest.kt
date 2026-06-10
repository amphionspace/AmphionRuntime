package com.amphion.asr.sample.plate

import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.nio.charset.StandardCharsets

/**
 * 离线回放 P1 gpu3 dialogue 536 条真机 asr_raw，评估 PlateNormalizer 修复后指标。
 * 数据：evaluation/plate_number/p1_gpu3_dialogue/{plate_eval.tsv, metadata.gpu3.jsonl}
 */
class P1Gpu3DialogueReplayTest {

    private val evalDir: File by lazy {
        val fromModule = File("../../../../evaluation/plate_number/p1_gpu3_dialogue")
        if (fromModule.isDirectory) fromModule.canonicalFile
        else File(System.getProperty("user.dir"))
            .resolve("../../../../evaluation/plate_number/p1_gpu3_dialogue")
            .canonicalFile
    }

    private fun normalizer(): PlateNormalizer {
        val csv = File("src/main/assets/plate/plate_homophones.csv")
        val dict = PlateHomophoneDict.loadFromReader(
            BufferedReader(FileReader(csv, StandardCharsets.UTF_8)),
        )
        return PlateNormalizer.create(dict)
    }

    data class Row(
        val expectedPlate: String,
        val asrRaw: String,
        val oldNormalized: String,
        val oldExtracted: String,
        val oldValid: Boolean,
        val refText: String,
    )

    private fun loadRows(): List<Row> {
        val tsv = File(evalDir, "plate_eval.tsv")
        val meta = File(evalDir, "metadata.gpu3.jsonl")
        require(tsv.isFile) { "missing ${tsv.absolutePath}" }
        require(meta.isFile) { "missing ${meta.absolutePath}" }

        val refs = meta.readLines().map { line ->
            val text = Regex(""""text"\s*:\s*"([^"]*)"""")
                .find(line)!!.groupValues[1]
            text.replace("\\u0026", "&")
        }

        val rows = mutableListOf<Row>()
        tsv.bufferedReader(StandardCharsets.UTF_8).use { br ->
            val header = br.readLine() ?: error("empty tsv")
            var i = 0
            br.forEachLine { line ->
                if (line.isBlank()) return@forEachLine
                val parts = line.split('\t')
                require(parts.size >= 6) { "bad line: $line" }
                val refText = refs[i]
                rows += Row(
                    expectedPlate = parts[1].trim().ifEmpty { PlateTextUtil.extractPlate(refText) },
                    asrRaw = parts[2].trim(),
                    oldNormalized = parts[3].trim(),
                    oldExtracted = parts[4].trim(),
                    oldValid = parts[5].trim().uppercase() == "Y",
                    refText = refText,
                )
                i++
            }
        }
        require(rows.size == refs.size) { "rows=${rows.size} meta=${refs.size}" }
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
    fun replay_p1_gpu3_metrics() {
        val norm = normalizer()
        val rows = loadRows()
        assertEquals(536, rows.size)

        val provinces = PlateNormalizer.PROVINCES.toSet()
        var oldExact = 0
        var newExact = 0
        var oldValid = 0
        var newValid = 0
        var oldProv = 0
        var newProv = 0
        var oldPrefix = 0
        var newPrefix = 0
        var oldSent = 0
        var newSent = 0
        var cerEditsOld = 0
        var cerEditsNew = 0
        var cerLen = 0
        val stillFail = mutableListOf<String>()
        val newlyFixed = mutableListOf<String>()
        val regressed = mutableListOf<String>()

        for (row in rows) {
            val exp = row.expectedPlate
            val oldGot = row.oldExtracted
            val result = PlateEnhance.apply(row.asrRaw, norm, normalizeEnabled = true)
            val newGot = result.primaryPlate.orEmpty()
            val newValidFlag = result.spans.any { it.valid }

            if (oldGot == exp) oldExact++
            if (newGot == exp) newExact++
            if (row.oldValid) oldValid++
            if (newValidFlag) newValid++

            fun provOk(got: String) = got.isNotEmpty() && exp.isNotEmpty() && got[0] == exp[0]
            fun prefixOk(got: String) =
                got.length >= 2 && exp.length >= 2 && got[0] in provinces && got.take(2) == exp.take(2)

            if (provOk(oldGot)) oldProv++
            if (provOk(newGot)) newProv++
            if (prefixOk(oldGot)) oldPrefix++
            if (prefixOk(newGot)) newPrefix++

            val oldHyp = row.oldNormalized
            val newHyp = result.text
            if (oldHyp == row.refText) oldSent++
            if (newHyp == row.refText) newSent++
            cerLen += row.refText.length
            cerEditsOld += levenshtein(row.refText, oldHyp)
            cerEditsNew += levenshtein(row.refText, newHyp)

            when {
                oldGot != exp && newGot == exp -> newlyFixed += "$exp | ${row.asrRaw.take(60)}"
                oldGot == exp && newGot != exp -> regressed += "$exp old=$oldGot new=$newGot"
                newGot != exp -> stillFail += "$exp got=$newGot | ${row.asrRaw.take(50)}"
            }
        }

        val report = buildString {
            appendLine("P1 gpu3 dialogue 离线回放 (n=${rows.size})")
            appendLine("data=${evalDir.absolutePath}")
            appendLine()
            appendLine("=== 修复前（真机 plate_eval.tsv 落盘） ===")
            appendLine("完整车牌命中: $oldExact/${rows.size} = ${pct(oldExact, rows.size)}")
            appendLine("有效车牌提取:   $oldValid/${rows.size} = ${pct(oldValid, rows.size)}")
            appendLine("省份简称命中:   $oldProv/${rows.size} = ${pct(oldProv, rows.size)}")
            appendLine("省份前缀命中:   $oldPrefix/${rows.size} = ${pct(oldPrefix, rows.size)}")
            appendLine("整句完全匹配:   $oldSent/${rows.size} = ${pct(oldSent, rows.size)}")
            appendLine("语料级整句CER:  ${cerEditsOld.toDouble() / cerLen}")
            appendLine()
            appendLine("=== 修复后（当前 PlateNormalizer 回放 asr_raw） ===")
            appendLine("完整车牌命中: $newExact/${rows.size} = ${pct(newExact, rows.size)}")
            appendLine("有效车牌提取:   $newValid/${rows.size} = ${pct(newValid, rows.size)}")
            appendLine("省份简称命中:   $newProv/${rows.size} = ${pct(newProv, rows.size)}")
            appendLine("省份前缀命中:   $newPrefix/${rows.size} = ${pct(newPrefix, rows.size)}")
            appendLine("整句完全匹配:   $newSent/${rows.size} = ${pct(newSent, rows.size)}")
            appendLine("语料级整句CER:  ${cerEditsNew.toDouble() / cerLen}")
            appendLine()
            appendLine("=== 变化 ===")
            appendLine("新修复: ${newlyFixed.size}  回退: ${regressed.size}  仍失败: ${stillFail.size}")
            appendLine()
            if (newlyFixed.isNotEmpty()) {
                appendLine("--- 新修复样例 (最多15) ---")
                newlyFixed.take(15).forEach { appendLine(it) }
                appendLine()
            }
            if (regressed.isNotEmpty()) {
                appendLine("--- 回退样例 ---")
                regressed.forEach { appendLine(it) }
                appendLine()
            }
            if (stillFail.isNotEmpty()) {
                appendLine("--- 仍失败 (最多20) ---")
                stillFail.take(20).forEach { appendLine(it) }
            }
        }

        File(evalDir, "metrics_replay.txt").writeText(report, StandardCharsets.UTF_8)
        println(report)
        assertEquals(0, regressed.size)
    }

    private fun pct(n: Int, total: Int): String =
        if (total == 0) "0.0%" else "%.1f%%".format(100.0 * n / total)
}
