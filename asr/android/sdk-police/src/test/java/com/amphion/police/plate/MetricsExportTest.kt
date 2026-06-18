package com.amphion.police.plate

import com.amphion.police.test.TestAssets
import org.junit.Test
import java.io.BufferedReader
import java.io.File

/** 导出 round11 asr 规则回放结果，供 Mac 侧汇总指标。 */
class MetricsExportTest {

    @Test
    fun export_round11_replay_tsv() {
        val normalizer = PlateNormalizer.create(loadProductionDict())
        val tsv = resolveRound11Tsv()
        val out = resolveExportFile()
        if (!tsv.isFile) {
            println("[SKIP] ${tsv.absolutePath}")
            return
        }
        out.parentFile?.mkdirs()
        out.bufferedWriter(Charsets.UTF_8).use { w ->
            w.write("idx\texpected_plate\tasr_raw\tnormalized\tplate_extracted\tplate_valid\n")
            tsv.readLines().drop(1).forEachIndexed { idx, line ->
                val cols = line.split('\t')
                if (cols.size < 6) return@forEachIndexed
                val expected = cols[1].trim()
                val raw = cols[2].trim()
                val r = normalizer.normalize(raw)
                val plate = r.primaryPlate.orEmpty()
                val valid = if (r.spans.any { it.valid }) "Y" else "N"
                w.write(
                    listOf(
                        idx.toString(),
                        expected,
                        raw,
                        r.text,
                        plate,
                        valid,
                    ).joinToString("\t") + "\n",
                )
            }
        }
        println("[OK] exported ${out.absolutePath}")
    }

    @Test
    fun export_round12_manual_replay_tsv() {
        val normalizer = PlateNormalizer.create(loadProductionDict())
        val tsv = resolveRound12Tsv()
        val out = resolveManualExportFile()
        if (!tsv.isFile) {
            println("[SKIP] ${tsv.absolutePath}")
            return
        }
        val since = 1780665556299L
        out.parentFile?.mkdirs()
        out.bufferedWriter(Charsets.UTF_8).use { w ->
            w.write("timestamp_ms\tasr_raw\tnormalized\tplate_extracted\tplate_valid\n")
            tsv.readLines().drop(1).forEach { line ->
                val cols = line.split('\t')
                if (cols.size < 6) return@forEach
                val ts = cols[0].trim().toLongOrNull() ?: return@forEach
                if (ts < since) return@forEach
                val raw = cols[2].trim()
                if (raw.isEmpty()) return@forEach
                val r = normalizer.normalize(raw)
                val plate = r.primaryPlate.orEmpty()
                val valid = if (r.spans.any { it.valid }) "Y" else "N"
                w.write(
                    listOf(
                        cols[0].trim(),
                        raw,
                        r.text,
                        plate,
                        valid,
                    ).joinToString("\t") + "\n",
                )
            }
        }
        println("[OK] exported ${out.absolutePath}")
    }

    private fun loadProductionDict(): PlateHomophoneDict {
        val f = TestAssets.resolve("plate/plate_homophones.csv")
        return PlateHomophoneDict.loadFromReader(BufferedReader(f.reader()))
    }

    private fun resolveRound11Tsv(): File {
        var dir: File? = File(System.getProperty("user.dir") ?: ".")
        repeat(8) {
            val base = dir ?: return@repeat
            val candidate = File(base, "plate-eval-round11/plate_eval.tsv")
            if (candidate.isFile) return candidate
            dir = base.parentFile
        }
        return File("plate-eval-round11/plate_eval.tsv")
    }

    private fun resolveRound12Tsv(): File {
        var dir: File? = File(System.getProperty("user.dir") ?: ".")
        repeat(8) {
            val base = dir ?: return@repeat
            val candidate = File(base, "plate-eval-round12/plate_eval.tsv")
            if (candidate.isFile) return candidate
            dir = base.parentFile
        }
        return File("plate-eval-round12/plate_eval.tsv")
    }

    private fun resolveProjectRoot(): File {
        var dir: File? = File(System.getProperty("user.dir") ?: ".")
        repeat(8) {
            val base = dir ?: return@repeat
            if (File(base, "plate-eval-round11/plate_eval.tsv").isFile) {
                return base
            }
            dir = base.parentFile
        }
        return File(".")
    }

    private fun resolveExportFile(): File =
        File(resolveProjectRoot(), "plate-eval-round11/replay_export.tsv")

    private fun resolveManualExportFile(): File =
        File(resolveProjectRoot(), "plate-eval-round12/manual_replay_export.tsv")
}
