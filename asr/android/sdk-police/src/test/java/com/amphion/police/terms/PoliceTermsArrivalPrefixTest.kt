package com.amphion.police.terms

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import java.io.BufferedReader
import java.io.InputStreamReader

class PoliceTermsArrivalPrefixTest {

    private lateinit var v1Normalizer: PoliceTermsNormalizer
    private lateinit var v2Normalizer: PoliceTermsNormalizerV2

    @Before
    fun setUp() {
        fun reader(relativePath: String) = BufferedReader(
            InputStreamReader(TestAssets.resolve(relativePath).inputStream(), Charsets.UTF_8),
        )
        val terms = reader("police_terms/term_gazetteer.txt").readLines()
            .map { it.trim() }
            .filter { it.isNotEmpty() && !it.startsWith("#") }
            .distinct()
            .sortedByDescending { it.length }
        v1Normalizer = PoliceTermsNormalizer.create(
            PoliceTermsHomophoneDict.loadFromReader(reader("police_terms/term_homophones.csv")),
            PoliceTermsGazetteer.loadFromReader(reader("police_terms/term_gazetteer.txt")),
        )
        v2Normalizer = PoliceTermsNormalizerV2.create(
            PoliceTermsHomophoneDict.loadFromReader(reader("police_terms/term_homophones.csv")),
            PoliceTermsGazetteer.loadFromReader(reader("police_terms/term_gazetteer.txt")),
            terms,
            TermReadingMap.loadFromReader(reader("police_terms/term_homophones.csv")),
        )
    }

    @Test
    fun default_v1_normalizes_arrival_scene_subject_once() {
        assertEquals("我已到达现场。", v1Normalizer.normalize("已到达现场。").text)
        assertEquals("我已到达现场。", v1Normalizer.normalize("我已到达现场。").text)
        assertEquals("我已到达现场。", v1Normalizer.normalize("我我我已到达现场。").text)
    }

    @Test
    fun normalizes_arrival_scene_subject_once() {
        assertEquals("我已到达现场。", v2Normalizer.normalize("已到达现场。").text)
        assertEquals("我已到达现场。", v2Normalizer.normalize("我已到达现场。").text)
        assertEquals("我已到达现场。", v2Normalizer.normalize("我我我已到达现场。").text)
        assertEquals(
            "我已到达现场。",
            v2Normalizer.polish(v2Normalizer.normalize("我我我已到达现场。").text),
        )
    }

    @Test
    fun preserves_existing_client_misrecognition_corrections() {
        assertEquals("我已到达现场。", v1Normalizer.normalize("为到达现场。").text)
        assertEquals("我已到达现场。", v1Normalizer.normalize("我以到达现场。").text)
        assertEquals("我已到达现场。", v2Normalizer.normalize("为到达现场。").text)
        assertEquals("我已到达现场。", v2Normalizer.normalize("我以到达现场。").text)
    }

    @Test
    fun does_not_deduplicate_unrelated_repetition() {
        assertEquals("我我觉得已经到达现场。", v1Normalizer.normalize("我我觉得已经到达现场。").text)
        assertEquals("我我觉得已经到达现场。", v2Normalizer.normalize("我我觉得已经到达现场。").text)
    }
}
