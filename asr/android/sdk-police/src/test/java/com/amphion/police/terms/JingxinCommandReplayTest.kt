package com.amphion.police.terms

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import java.io.BufferedReader

/** 甲方真人测：打开警信 语音指令谐音回放。 */
class JingxinCommandReplayTest {

    private lateinit var normalizer: PoliceTermsNormalizer

    @Before
    fun setUp() {
        normalizer = PoliceTermsNormalizer.create(
            PoliceTermsHomophoneDict.loadFromReader(
                BufferedReader(TestAssets.resolve("police_terms/term_homophones.csv").reader()),
            ),
            PoliceTermsGazetteer.loadFromReader(
                BufferedReader(TestAssets.resolve("police_terms/term_gazetteer.txt").reader()),
            ),
            fstRuntime = null,
        )
    }

    @Test
    fun replay_openJingxin_clientConfusions() {
        assertFixed("打开景信", "打开警信")
        assertFixed("打开景讯", "打开警信")
        assertFixed("打开警醒", "打开警信")
        assertFixed("打开井信", "打开警信")
        assertFixed("打开警讯", "打开警信")
    }

    @Test
    fun replay_openJingxin_correctUnchanged() {
        assertFixed("打开警信", "打开警信")
    }

    @Test
    fun replay_round06_clientVoiceCommands() {
        assertFixed("帮我打开警讯", "帮我打开警信")
        assertFixed("帮我打开景讯", "帮我打开警信")
        assertFixed("帮我打开时中", "帮我打开时钟")
        assertFixed("启动帮协功能", "启动帮写功能")
        assertFixed("启动帮血功能", "启动帮写功能")
        assertFixed("打开邦田功能", "打开帮填功能")
        assertFixed("打开邦田", "打开帮填")
        assertFixed("打开帮田", "打开帮填")
        assertFixed("启动邦田", "启动帮填")
        assertFixed("启动邦田功能", "启动帮填功能")
        assertFixed("启动帮田功能", "启动帮填功能")
    }

    private fun assertFixed(raw: String, expected: String) {
        assertEquals(expected, normalizer.normalize(raw).text)
    }
}
