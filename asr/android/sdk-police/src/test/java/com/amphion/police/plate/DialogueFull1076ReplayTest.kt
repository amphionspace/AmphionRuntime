package com.amphion.police.plate

import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.nio.charset.StandardCharsets

/** 离线回放全量 1076 真机 asr_raw。 */
class DialogueFull1076ReplayTest {

    private val evalDir: File =
        File("../../evaluation/plate_number/dialogue_full_1076").canonicalFile

    private val metaList: List<Pair<String, String>> by lazy {
        val meta = File(evalDir, "../staging_dialogue_full_1076/metadata.jsonl").canonicalFile
        meta.readLines().map { line ->
            val text = Regex(""""text"\s*:\s*"([^"]*)"""")
                .find(line)!!.groupValues[1].replace("\\u0026", "&")
            val plate = PlateTextUtil.extractPlate(text)
            plate to text
        }
    }

    private fun normalizer(): PlateNormalizer {
        val csv = File("src/main/assets/plate/plate_homophones.csv")
        val dict = PlateHomophoneDict.loadFromReader(
            BufferedReader(FileReader(csv, StandardCharsets.UTF_8)),
        )
        return PlateNormalizer.create(dict)
    }

    @Test
    fun replay_dialogue_full_1076_no_regression() {
        val norm = normalizer()
        val tsv = File(evalDir, "plate_eval.tsv")
        val rows = mutableListOf<Triple<String, String, String>>() // exp, asr, deviceGot
        tsv.bufferedReader(StandardCharsets.UTF_8).use { br ->
            br.readLine()
            var i = 0
            br.forEachLine { line ->
                val p = line.split('\t')
                val exp = p[1].trim().ifEmpty { metaList[i].first }
                rows += Triple(exp, p[2].trim(), p[4].trim())
                i++
            }
        }
        assertEquals(1076, rows.size)

        var deviceExact = 0
        var replayExact = 0
        var regressed = 0
        for ((exp, asr, deviceGot) in rows) {
            val replayGot = PlateEnhance.apply(asr, norm, true).primaryPlate.orEmpty()
            if (deviceGot == exp) deviceExact++
            if (replayGot == exp) replayExact++
            if (deviceGot == exp && replayGot != exp) regressed++
        }

        val report = buildString {
            appendLine("dialogue full 1076 replay (n=1076)")
            appendLine("device exact: $deviceExact/1076 = ${100.0 * deviceExact / 1076}%")
            appendLine("replay exact: $replayExact/1076 = ${100.0 * replayExact / 1076}%")
            appendLine("newly_fixed: ${replayExact - deviceExact + regressed}  regressed: $regressed")
        }
        File(evalDir, "metrics_replay.txt").writeText(report, StandardCharsets.UTF_8)
        println(report)
        assertEquals(0, regressed)
    }
}
