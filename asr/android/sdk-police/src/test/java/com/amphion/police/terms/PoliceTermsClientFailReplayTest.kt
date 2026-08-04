package com.amphion.police.terms

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * 甲方真人测失败句回放（round11）：签收警单 / 到达现场 / 帮我反馈。
 */
class PoliceTermsClientFailReplayTest {

    private lateinit var v2: PoliceTermsNormalizerV2

    @Before
    fun setUp() {
        fun reader(rel: String) =
            BufferedReader(InputStreamReader(TestAssets.resolve(rel).inputStream(), Charsets.UTF_8))
        val terms = reader("police_terms/term_gazetteer.txt").readLines()
            .map { it.trim() }
            .filter { it.isNotEmpty() && !it.startsWith("#") }
            .distinct()
            .sortedByDescending { it.length }
        v2 = PoliceTermsNormalizerV2.create(
            PoliceTermsHomophoneDict.loadFromReader(reader("police_terms/term_homophones.csv")),
            PoliceTermsGazetteer.loadFromReader(reader("police_terms/term_gazetteer.txt")),
            terms,
            TermReadingMap.loadFromReader(reader("police_terms/term_homophones.csv")),
        )
    }

    @Test
    fun fixes_jiedan_receive_simple() {
        assertEquals("签收警单", v2.normalize("接收简单").text)
        assertEquals("请签收警单", v2.normalize("请接收简单").text)
        assertEquals("签收警单", v2.normalize("接收警单").text)
        assertEquals("签收警单", v2.normalize("接收订单").text)
        assertEquals("签收警单后", v2.normalize("接收简单后").text)
    }

    @Test
    fun fixes_arrived_scene() {
        assertEquals("我已到达现场", v2.normalize("为到达现场").text)
        assertEquals("我已到达现场", v2.normalize("已到达现场").text)
        assertEquals("我已到达现场", v2.normalize("我以到达现场").text)
        assertEquals("我已到达现场。", v2.normalize("为到达现场。").text)
    }

    @Test
    fun fixes_bang_wo_fankui() {
        assertEquals("帮我反馈", v2.normalize("把我反馈").text)
        assertEquals("帮我反馈一下", v2.normalize("把我反馈一下").text)
        assertEquals(
            "处理完了，帮我反馈一下",
            v2.normalize("处理完了，把我反馈一下").text,
        )
        assertEquals(
            "处理完了帮我反馈一下",
            v2.normalize("处理完了把我反馈一下").text,
        )
        assertEquals(
            "我已到场，帮我反馈",
            v2.normalize("为到场帮我反馈").text,
        )
    }
}
