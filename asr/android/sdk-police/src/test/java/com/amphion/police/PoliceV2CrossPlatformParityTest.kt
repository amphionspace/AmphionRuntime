package com.amphion.police

import com.amphion.police.plate.PlateNormalizerV2
import com.amphion.police.plate.loadKnowledgeBase
import com.amphion.police.plate.loadReadingMap
import com.amphion.police.station.PoliceStationGazetteer
import com.amphion.police.station.PoliceStationHomophoneDict
import com.amphion.police.station.PoliceStationNormalizerV2
import com.amphion.police.station.StationReadingMap
import com.amphion.police.terms.PoliceTermsGazetteer
import com.amphion.police.terms.PoliceTermsHomophoneDict
import com.amphion.police.terms.PoliceTermsNormalizerV2
import com.amphion.police.terms.TermReadingMap
import com.amphion.police.test.TestAssets
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader

/** Locks Android V2 and Harmony V2 to the same behavior corpus. */
class PoliceV2CrossPlatformParityTest {

    private fun reader(path: String): BufferedReader = BufferedReader(FileReader(TestAssets.resolve(path)))

    private fun terms(): PoliceTermsNormalizerV2 {
        val values = reader("police_terms/term_gazetteer.txt").readLines()
            .map { it.trim() }.filter { it.isNotEmpty() && !it.startsWith("#") }
            .distinct().sortedByDescending { it.length }
        return PoliceTermsNormalizerV2.create(
            PoliceTermsHomophoneDict.loadFromReader(reader("police_terms/term_homophones.csv")),
            PoliceTermsGazetteer.loadFromReader(reader("police_terms/term_gazetteer.txt")),
            values,
            TermReadingMap.loadFromReader(reader("police_terms/term_homophones.csv")),
        )
    }

    private fun station(): PoliceStationNormalizerV2 {
        val values = reader("police_station/station_gazetteer.txt").readLines()
            .map { it.trim() }.filter { it.isNotEmpty() && !it.startsWith("#") }
            .distinct().sortedByDescending { it.length }
        return PoliceStationNormalizerV2.create(
            PoliceStationHomophoneDict.loadFromReader(reader("police_station/station_homophones.csv")),
            PoliceStationGazetteer.loadFromReader(reader("police_station/station_gazetteer.txt")),
            values,
            StationReadingMap.loadFromReader(reader("police_station/station_homophones.csv")),
        )
    }

    private fun corpus(): File {
        var directory: File? = File(System.getProperty("user.dir") ?: ".").canonicalFile
        repeat(10) {
            val base = directory ?: return@repeat
            for (relative in listOf(
                "asr/harmony/sdk-police/tests/police_v2_parity.tsv",
                "harmony/sdk-police/tests/police_v2_parity.tsv",
            )) {
                val candidate = File(base, relative)
                if (candidate.isFile) return candidate
            }
            directory = base.parentFile
        }
        error("police_v2_parity.tsv not found")
    }

    @Test
    fun android_v2_matches_cross_platform_corpus() {
        val kb = loadKnowledgeBase()
        val plate = PlateNormalizerV2.create(kb, loadReadingMap(kb), listOf('冀', '辽'))
        val terms = terms()
        val station = station()

        corpus().useLines { lines ->
            lines.filter { it.isNotBlank() && !it.startsWith("#") }.forEachIndexed { index, line ->
                val fields = line.split('\t')
                require(fields.size == 4) { "invalid parity case ${index + 1}: $line" }
                val (domain, assertion, input, expected) = fields
                val actual = when (domain) {
                    "plate" -> plate.normalize(input).text
                    "terms" -> terms.normalize(input).text
                    "station" -> station.normalize(input).text
                    else -> error("unknown domain: $domain")
                }
                if (assertion == "contains") {
                    assertTrue("case ${index + 1}: $input -> $actual, missing $expected", expected in actual)
                } else {
                    assertEquals("case ${index + 1}: $input", expected, actual)
                }
            }
        }
    }
}
