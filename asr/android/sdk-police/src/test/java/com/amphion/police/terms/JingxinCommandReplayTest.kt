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

    @Test
    fun replay_round07_clientMeetingAndDocs() {
        assertFixed(
            "帮我创建一个下午三点的会议，主题为群访群智工作会议",
            "帮我创建一个下午三点的会议，主题为群访群治工作会议",
        )
        assertFixed(
            "创建主题为报警人的工作会议，下午三点开始",
            "创建主题为报警的工作会议，下午三点开始",
        )
        assertFixed("我有哪些代办公文", "我有哪些待办公文")
        assertFixed("查一下代办公文", "查一下待办公文")
        assertFixed("帮我查一下有哪些代办公文", "帮我查一下有哪些待办公文")
    }

    @Test
    fun replay_round08_clientCommands() {
        assertFixed(
            "打开景信发消息给刘队长，内容为：今天几点集合？",
            "打开警信发消息给刘队长，内容为：今天几点集合？",
        )
        assertFixed("用维康姆想张伟发起呼叫", "用WeCom向张伟发起呼叫")
        assertFixed("呼叫停止中心", "呼叫情指中心")
        assertFixed("我已到港，帮我打卡", "我已到岗，帮我打卡")
        assertFixed("创建一个简单", "创建一个警单")
        assertFixed("创建简单", "创建警单")
        assertFixed("查看报警人现场视频", "查看报警现场视频")
    }

    private fun assertFixed(raw: String, expected: String) {
        assertEquals(expected, normalizer.normalize(raw).text)
    }
}
