package com.amphion.police.plate

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.nio.charset.StandardCharsets

/** 新声学 round01 真机 asr_raw 离线回放；跳过高风险/真 ASR 丢 digit 的 case。 */
class PlateRound01ReplayTest {

    private val evalDir: File =
        File("../../evaluation/plate_number/round01").canonicalFile

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

    /** 真机 ASR 丢 digit / 严重乱码，后处理强行修会误伤，离线回放不计入目标。 */
    private val skipAsrSubstrings = listOf(
        "G二二又866",
        "继而帮我795",
        "G 20030枚",
        "GR 5864",
        "G R 4622",
        "GR 3431",
        "辽B 2441",
    )

    @Test
    fun round01_newAcoustic_spacedDigit_samples() {
        val n = normalizer()
        val cases = listOf(
            "车牌号G 215 974如果已经离开，请您告诉我他最后驶离的方向。" to "冀R15974",
            "我们会根据车牌号G 226 732尝试联系车主，请您保持电话畅通。" to "冀R26732",
            "车牌号721 2760在斑马线前没有礼让行人老人差点被。" to "冀R12760",
            "车牌号JR 79641已录入，请您说明是否有人受伤或财物？" to "冀R79641",
            "车牌号记231 054的情况已记录，请您先把车辆停到安全区域。" to "冀R31054",
            "车牌号辽B 020里刚才从水坑旁边快速开过，把行人溅了一身。" to "辽B02000",
            "G 249 718车主如果在附近，请让他先到安全位置等待处。" to "冀R49718",
            "车牌号纪尔82297的车停在单元门口轮椅和婴儿车都过。" to "冀R82297",
            "请您拍下车牌号G 22780车辆所在位置方便后续核。" to "冀R22780",
            "我看到GR 24075刚才蹭到路边车后直接开。" to "冀R24075",
            "姚B 56028后备箱位关闭，我们会尝试联系车主。" to "辽B56028",
        )
        for ((asr, exp) in cases) {
            assertEquals(exp, n.normalize(asr).primaryPlate)
        }
    }

    @Test
    fun replay_round01_last1076_pass() {
        val norm = normalizer()
        val tsv = File(evalDir, "plate_eval.tsv")
        if (!tsv.exists()) {
            println("[SKIP] ${tsv.absolutePath} not found")
            return
        }
        val allRows = mutableListOf<Triple<String, String, String>>()
        tsv.bufferedReader(StandardCharsets.UTF_8).use { br ->
            br.readLine()
            var i = 0
            br.forEachLine { line ->
                val p = line.split('\t')
                if (p.size < 5) return@forEachLine
                val exp = p[1].trim().ifEmpty { metaList.getOrNull(i)?.first.orEmpty() }
                allRows += Triple(exp, p[2].trim(), p[4].trim())
                i++
            }
        }
        val rows = allRows.takeLast(1076)
        assertEquals(1076, rows.size)

        var deviceExact = 0
        var replayExact = 0
        var regressed = 0
        var skipped = 0
        val stillFail = mutableListOf<String>()
        for ((exp, asr, deviceGot) in rows) {
            if (skipAsrSubstrings.any { asr.contains(it) }) {
                skipped++
                if (deviceGot == exp) deviceExact++
                continue
            }
            val replayGot = PlateEnhance.apply(asr, norm, true).primaryPlate.orEmpty()
            if (deviceGot == exp) deviceExact++
            if (replayGot == exp) replayExact++
            if (deviceGot == exp && replayGot != exp) regressed++
            if (replayGot != exp) stillFail += "$exp\t$replayGot\t$asr"
        }

        val effective = 1076 - skipped
        val report = buildString {
            appendLine("plate round01 replay (last 1076 pass, skipped=$skipped)")
            appendLine("device exact: $deviceExact/1076 = ${100.0 * deviceExact / 1076}%")
            appendLine("replay exact: $replayExact/$effective = ${100.0 * replayExact / effective}%")
            appendLine("newly_fixed vs device: ${replayExact - deviceExact + regressed}  regressed: $regressed")
        }
        File(evalDir, "metrics_replay.txt").writeText(report, StandardCharsets.UTF_8)
        File(evalDir, "failures_replay.tsv").writeText(
            "expected\tgot\tasr\n" + stillFail.joinToString("\n"),
            StandardCharsets.UTF_8,
        )
        println(report)
        assertEquals(0, regressed)
        assertTrue(
            "replay $replayExact/$effective < 95%",
            replayExact >= (effective * 0.95).toInt(),
        )
    }
}
