package com.amphion.police.terms

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.BufferedReader
import java.io.StringReader

class PoliceTermsNormalizerTest {

    private lateinit var normalizer: PoliceTermsNormalizer
    private lateinit var gazetteer: PoliceTermsGazetteer

    @Before
    fun setUp() {
        val homophones = PoliceTermsHomophoneDict.loadFromReader(
            BufferedReader(
                StringReader(
                    """
                    已签收订单,已签收警单,term
                    签收订单后,签收警单后,term
                    签收订单,签收警单,term
                    签收紧单,签收警单,term
                    签收简单,签收警单,term
                    纠纷简单,纠纷警单,term
                    促进过程中,处警过程中,term
                    出警人员,处警人员,term
                    签收经单,签收警单,term
                    """.trimIndent(),
                ),
            ),
        )
        gazetteer = PoliceTermsGazetteer.loadFromReader(
            BufferedReader(
                StringReader(
                    """
                    签收警单
                    签收警单后
                    已签收警单
                    签收警情
                    接警
                    处警
                    处警人员
                    处警过程中
                    报警人
                    警单
                    """.trimIndent(),
                ),
            ),
        )
        normalizer = PoliceTermsNormalizer.create(homophones, gazetteer)
    }

    @Test
    fun extractTerms_fromRefText() {
        val terms = PoliceTermsTextUtil.extractTerms(
            "请附近警力签收警单。",
            gazetteer,
        )
        assertEquals(listOf("签收警单"), terms)
    }

    @Test
    fun normalize_homophoneToKnownTerm() {
        val r = normalizer.normalize("请附近警力签收经单。")
        assertTrue(r.text.contains("签收警单"))
        assertTrue(r.spans.any { it.normalized == "签收警单" && it.valid })
    }

    @Test
    fun normalize_knownTermsUnchanged() {
        val input = "处警车辆已到达小区门口，请与报警人对接。"
        val r = normalizer.normalize(input)
        assertTrue(r.matchedTerms.contains("处警"))
        assertTrue(r.matchedTerms.contains("报警人"))
    }
}
