package com.amphion.asr.sample

import com.amphion.asr.sample.plate.PlateNormalizer
import com.amphion.asr.sample.police_station.PoliceStationNormalizer
import com.amphion.asr.sample.police_terms.PoliceTermsGazetteer
import com.amphion.asr.sample.police_terms.PoliceTermsHomophoneDict
import com.amphion.asr.sample.police_terms.PoliceTermsNormalizer
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader

/** 三域后处理串联：术语 → 车牌 → 派出所。 */
class AsrTextEnhanceTest {

    private lateinit var termsNormalizer: PoliceTermsNormalizer
    private lateinit var plateNormalizer: PlateNormalizer
    private lateinit var stationNormalizer: PoliceStationNormalizer

    @Before
    fun setUp() {
        termsNormalizer = PoliceTermsNormalizer.create(
            PoliceTermsHomophoneDict.loadFromReader(
                BufferedReader(FileReader(resolveAsset("police_terms/term_homophones.csv"))),
            ),
            PoliceTermsGazetteer.loadFromReader(
                BufferedReader(FileReader(resolveAsset("police_terms/term_gazetteer.txt"))),
            ),
        )
        plateNormalizer = PlateNormalizer.create(
            com.amphion.asr.sample.plate.PlateHomophoneDict.loadFromReader(
                BufferedReader(FileReader(resolveAsset("plate/plate_homophones.csv"))),
            ),
        )
        stationNormalizer = PoliceStationNormalizer.create(
            com.amphion.asr.sample.police_station.PoliceStationHomophoneDict.loadFromReader(
                BufferedReader(FileReader(resolveAsset("police_station/station_homophones.csv"))),
            ),
            com.amphion.asr.sample.police_station.PoliceStationGazetteer.loadFromReader(
                BufferedReader(FileReader(resolveAsset("police_station/station_gazetteer.txt"))),
            ),
        )
    }

    @Test
    fun apply_termsThenPlateThenStation() {
        val raw = "给我看一下南昌市西湖区神经塔派出所近五个工作日分辖区的接警车。"
        val out = AsrTextEnhance.apply(
            raw,
            termsNormalizer,
            termsNormalizeEnabled = true,
            plateNormalizer,
            plateNormalizeEnabled = true,
            stationNormalizer,
            stationNormalizeEnabled = true,
        )
        assertTrue(out.text.contains("南昌市西湖区绳金塔派出所"))
        assertTrue(out.station.spans.any { it.valid })
    }

    private fun resolveAsset(rel: String): File {
        val roots = listOf("src/main/assets", "sample/src/main/assets")
        val cwd = File(System.getProperty("user.dir") ?: ".")
        for (base in listOfNotNull(cwd, cwd.parentFile)) {
            for (r in roots) {
                val f = File(base, "$r/$rel")
                if (f.isFile) return f
            }
        }
        error("asset not found: $rel")
    }
}
