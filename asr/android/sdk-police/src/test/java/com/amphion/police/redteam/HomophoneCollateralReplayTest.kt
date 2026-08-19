package com.amphion.police.redteam

import com.amphion.police.PoliceEnhancePipeline
import com.amphion.police.plate.PlateHomophoneDict
import com.amphion.police.plate.PlateNormalizer
import com.amphion.police.station.PoliceStationGazetteer
import com.amphion.police.station.PoliceStationHomophoneDict
import com.amphion.police.station.PoliceStationNormalizer
import com.amphion.police.terms.PoliceTermsGazetteer
import com.amphion.police.terms.PoliceTermsHomophoneDict
import com.amphion.police.terms.PoliceTermsNormalizer
import com.amphion.police.test.TestAssets
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.nio.charset.StandardCharsets

/**
 * Layer 3：red-team 100 句全 pipeline 回放（术语 → 车牌 → 派出所）。
 * 语料：evaluation/red_team/homophone_collateral_corpus_100.tsv
 */
class HomophoneCollateralReplayTest {

    private data class Row(
        val id: String,
        val category: String,
        val asrSimulated: String,
        val expectUnchanged: String,
        val expectMode: String,
        val expectContains: String,
        val riskHint: String,
    )

    private lateinit var termsNormalizer: PoliceTermsNormalizer
    private lateinit var plateNormalizer: PlateNormalizer
    private lateinit var stationNormalizer: PoliceStationNormalizer
    private val rows by lazy { loadCorpus() }
    private val reportLines = mutableListOf<String>()

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

    private fun applyPipeline(asr: String): PoliceEnhancePipeline.Result =
        PoliceEnhancePipeline.apply(
            asr,
            termsNormalizer,
            termsNormalizeEnabled = true,
            plateNormalizer,
            plateNormalizeEnabled = true,
            stationNormalizer,
            stationNormalizeEnabled = true,
        )

    @Test
    fun redTeam_A_district_mustStayIdentical() {
        val failures = mutableListOf<String>()
        for (row in rows.filter { it.category == "A_district" }) {
            val out = applyPipeline(row.asrSimulated).text
            if (out != row.asrSimulated) {
                failures += "${row.id}: ${row.asrSimulated.take(40)} -> ${out.take(40)}"
            }
            record(row, out, out == row.asrSimulated)
        }
        assertTrue(
            "A_district collateral (${failures.size}):\n" + failures.joinToString("\n"),
            failures.isEmpty(),
        )
    }

    @Test
    fun redTeam_identity_all_categories() {
        val failedIds = mutableSetOf<String>()
        val failures = mutableListOf<String>()
        for (row in rows.filter { it.expectMode == "identity" }) {
            val out = applyPipeline(row.asrSimulated).text
            val ok = out == row.asrSimulated
            record(row, out, ok)
            if (!ok) {
                failedIds += row.id
                failures += "${row.id}(${row.category}): ${row.asrSimulated.take(36)} -> ${out.take(36)}"
            }
        }
        flushReport()
        val abIds = rows.filter { it.category in setOf("A_district", "B_common") && it.expectMode == "identity" }
            .map { it.id }
            .toSet()
        val abFail = failedIds.count { it in abIds }
        assertEquals(
            "A+B identity failures (target 0): $abFail of ${abIds.size}\n" +
                failures.filter { it.substringBefore("(") in abIds }.joinToString("\n"),
            0,
            abFail,
        )
    }

    @Test
    fun redTeam_fix_station_mishear() {
        for (row in rows.filter { it.expectMode == "fix_station" }) {
            val out = applyPipeline(row.asrSimulated).text
            for (needle in row.expectContains.split("|").filter { it.isNotBlank() }) {
                assertTrue("${row.id} should contain '$needle' in $out", needle in out)
            }
            assertFalse("${row.id} must not corrupt 高新区", out.contains("高新Q"))
            record(row, out, true)
        }
        flushReport()
    }

    @Test
    fun redTeam_fix_terms_mishear() {
        for (row in rows.filter { it.expectMode == "fix_terms" }) {
            val out = applyPipeline(row.asrSimulated).text
            for (needle in row.expectContains.split("|").filter { it.isNotBlank() }) {
                assertTrue("${row.id} should contain '$needle' in $out", needle in out)
            }
            record(row, out, true)
        }
        flushReport()
    }

    @Test
    fun redTeam_fix_plate_positive() {
        for (row in rows.filter { it.expectMode == "fix_plate" }) {
            val result = applyPipeline(row.asrSimulated)
            val out = result.text
            if (row.id == "E10") {
                assertTrue("${row.id} should map 新区 prefix to 新Q", out.contains("新Q"))
            } else {
                val plate = result.plate.primaryPlate
                val needles = row.expectContains.split("|").filter { it.isNotBlank() }
                val hit = needles.any { needle ->
                    out.contains(needle) || (plate != null && plate.contains(needle))
                }
                assertTrue(
                    "${row.id} expect ${row.expectContains} plate=$plate text=$out",
                    hit,
                )
            }
            record(row, out, true)
        }
        flushReport()
    }

    @Test
    fun redTeam100_writeCollateralReport() {
        for (row in rows) {
            val result = applyPipeline(row.asrSimulated)
            val out = result.text
            val pass = when (row.expectMode) {
                "identity" -> out == row.asrSimulated
                "fix_station", "fix_terms", "fix_mixed" -> {
                    val needles = row.expectContains.split("|").filter { it.isNotBlank() }
                    needles.all { it in out } &&
                        !out.contains("高新Q") &&
                        !out.contains("郑东新Q")
                }
                "fix_plate" -> {
                    if (row.id == "E10") {
                        out.contains("新Q")
                    } else {
                        val needles = row.expectContains.split("|").filter { it.isNotBlank() }
                        needles.any { needle ->
                            out.contains(needle) ||
                                (result.plate.primaryPlate?.contains(needle) == true)
                        }
                    }
                }
                else -> false
            }
            record(row, out, pass)
        }
        flushReport()
    }

    @Test
    fun redTeam_fix_mixed_noDistrictCorruption() {
        for (row in rows.filter { it.expectMode == "fix_mixed" }) {
            val result = applyPipeline(row.asrSimulated)
            val out = result.text
            assertFalse("${row.id} must not contain 高新Q", out.contains("高新Q"))
            assertFalse("${row.id} must not contain 郑东新Q", out.contains("郑东新Q"))
            for (needle in row.expectContains.split("|").filter { it.isNotBlank() }) {
                assertTrue("${row.id} should contain '$needle'", needle in out)
            }
            record(row, out, true)
        }
        flushReport()
    }

    private fun record(row: Row, out: String, pass: Boolean) {
        reportLines += listOf(
            row.id,
            row.category,
            row.expectMode,
            if (pass) "PASS" else "FAIL",
            row.asrSimulated.replace('\t', ' '),
            out.replace('\t', ' '),
            row.riskHint,
        ).joinToString("\t")
    }

    private fun flushReport() {
        if (reportLines.isEmpty()) return
        val corpus = resolveCorpusFile()
        val outFile = (corpus.parentFile ?: corpus).resolve("collateral_report_full.tsv")
        val header = "id\tcategory\texpect_mode\tstatus\tin\tout\trisk_hint"
        val body = reportLines.distinct().joinToString("\n")
        outFile.writeText("$header\n$body\n", StandardCharsets.UTF_8)
        reportLines.clear()
    }

    private fun loadCorpus(): List<Row> {
        val tsv = resolveCorpusFile()
        require(tsv.isFile) { "missing corpus ${tsv.absolutePath}" }
        val list = mutableListOf<Row>()
        tsv.bufferedReader(StandardCharsets.UTF_8).use { br ->
            br.readLine() ?: error("empty corpus")
            br.forEachLine { line ->
                if (line.isBlank()) return@forEachLine
                val p = line.split('\t')
                require(p.size >= 10) { "bad line (need expect_mode): $line" }
                list += Row(
                    id = p[0].trim(),
                    category = p[1].trim(),
                    asrSimulated = p[3].trim(),
                    expectUnchanged = p[4].trim(),
                    expectMode = p.getOrElse(8) { "identity" }.trim().ifEmpty { "identity" },
                    expectContains = p.getOrElse(9) { "" }.trim(),
                    riskHint = p[6].trim(),
                )
            }
        }
        assertEquals(100, list.size)
        return list
    }

    private fun resolveCorpusFile(): File {
        System.getProperty("redteam.corpus")
            ?.trim()
            ?.takeIf { it.isNotEmpty() }
            ?.let { return File(it) }
        var dir: File? = File(System.getProperty("user.dir") ?: ".")
        repeat(8) {
            val base = dir ?: return File("../../../../evaluation/red_team/homophone_collateral_corpus_100.tsv")
            val candidate = File(base, "evaluation/red_team/homophone_collateral_corpus_100.tsv")
            if (candidate.isFile) return candidate
            dir = base.parentFile
        }
        return File("../../../../evaluation/red_team/homophone_collateral_corpus_100.tsv")
    }
}
