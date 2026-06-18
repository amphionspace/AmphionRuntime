package com.amphion.police.plate

import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

class PlateNormalizerV2Test {

    private lateinit var kb: PlateKnowledgeBase
    private lateinit var readingMap: PlateReadingMap
    private lateinit var normalizer: PlateNormalizerV2

    @Before
    fun setUp() {
        kb = loadKnowledgeBase()
        readingMap = loadReadingMap(kb)
        normalizer = PlateNormalizerV2.create(kb, readingMap)
    }

    private fun norm(text: String): String = normalizer.normalize(text).text

    @Test
    fun chineseDigitsConvertedNationwide() {
        assertEquals("冀A12345", norm("冀A一二三四五"))
        assertEquals("辽B10088", norm("辽B幺零零八八"))
        assertEquals("鲁A12345", norm("鲁A一二三四五"))
    }

    @Test
    fun provinceHomophoneCorrected() {
        // 济→冀（省份同音）
        assertEquals("冀R12345", norm("济R一二三四五"))
        // 素→苏
        assertEquals("苏A12345", norm("素A一二三四五"))
    }

    @Test
    fun oneToManyDisambiguationByValidation() {
        // 优→{V,U}；苏 合法字母含 U 不含 V，应选 苏U
        assertEquals("苏U12345", norm("苏优一二三四五"))
    }

    @Test
    fun multiplePlatesInOneSentence() {
        assertEquals(
            "鲁A12345和豫B67890",
            norm("鲁A一二三四五和豫B六七八九零"),
        )
    }

    @Test
    fun alreadyValidPlateUnchanged() {
        assertEquals("辽B12345", norm("辽B12345"))
        assertEquals("冀R88888", norm("冀R88888"))
    }

    @Test
    fun noOverCorrectionWhenNoValidPlate() {
        // 继→冀 是同音，但「继续核查」不构成车牌，应保持原样
        assertEquals("我们继续核查", norm("我们继续核查"))
        // 向→湘 同音，但无车牌主体
        assertEquals("向前走两步", norm("向前走两步"))
    }

    @Test
    fun realisticPoliceSentence() {
        assertEquals(
            "请核查辽B10088这辆车",
            norm("请核查辽B幺零零八八这辆车"),
        )
    }

    // ---- P3: 普通(7) vs 新能源(8) 长度歧义 ----

    @Test
    fun newEnergySmallByMaximalMunch() {
        // 8 位小型新能源（D 居首）：凑满 8 位且合法，最大匹配吃满 8 位，不退化成 7 位普通牌。
        assertEquals("京AD12345", norm("京AD一二三四五"))
        // F 混动标识同理
        assertEquals("京AF12345", norm("京AF一二三四五"))
    }

    @Test
    fun newEnergyLargeTailPreserved() {
        // 8 位大型新能源（D 居末）：已规范输入应原样保留，不被截成 7 位。
        assertEquals("辽B12345D", norm("辽B12345D"))
        assertEquals("辽B12345D", norm("辽B一二三四五D"))
    }

    @Test
    fun normalPlateNotInflatedToEightWhenNotNewEnergy() {
        // 第 8 位虽是数字但 8 位不构成合法新能源（首/末非 D/F）→ 退回 7 位普通牌，
        // 多余的第 8 位不被并入车牌、原样保留。
        assertEquals("辽B12345六", norm("辽B一二三四五六"))
    }

    @Test
    fun followingChineseWordNotEaten() {
        // 车牌后接的中文若无字母/数字读音候选，定位阶段即停在第 7 位，不会被并入凑成 8 位。
        assertEquals("辽B12345的车", norm("辽B一二三四五的车"))
    }

    // ---- P4: 锚词/上下文接受门（降过纠） ----

    @Test
    fun multiRiskyHomophoneRejectedWithoutAnchor() {
        // 济→冀(省份近音) + 西→C(字母近音) = 2 个冒险替换，且无车牌锚词 → 判为过纠，保留原文。
        assertEquals("济西一二三四五", norm("济西一二三四五"))
    }

    @Test
    fun multiRiskyHomophoneAcceptedWithAnchor() {
        // 同样的 2 个冒险替换，但上下文出现「车牌号」锚词 → 放宽接受，落地纠正。
        assertEquals("车牌号冀C12345", norm("车牌号济西一二三四五"))
    }

    @Test
    fun singleRiskyHomophoneStillCorrectedWithoutAnchor() {
        // 仅 1 个冒险替换（省份近音）仍属高置信，无锚词也纠正。
        assertEquals("冀R12345", norm("济R一二三四五"))
    }

    // ---- P5-2: 重复字符折叠 ----

    @Test
    fun collapsesRepeatedLetter() {
        // ASR 把机关字母听成两遍：黑KK41258 → 黑K41258（折叠后覆盖全部 8 个口述字符）。
        assertEquals("黑K41258", norm("黑KK41258"))
    }

    @Test
    fun doesNotCollapseLegitDoubleLetterPlate() {
        // 真实双字母牌 青AA88P0 本就是完整 7 位，不应被折叠破坏。
        assertEquals("青AA88P0", norm("青AA88P0"))
    }

    // ---- P5-2: 丢省份兜底（需注入部署地省份） ----

    @Test
    fun fillsDroppedProvinceWithSingleContext() {
        val n = PlateNormalizerV2.create(kb, readingMap, contextProvinces = listOf('黑'))
        assertEquals("车牌号黑H28491的", n.normalize("车牌号H 28491的").text)
    }

    @Test
    fun droppedProvinceNoopWhenNoContext() {
        // 默认无上下文省份 → 不臆造，原样保留。
        assertEquals("车牌号H 28491的", norm("车牌号H 28491的"))
    }

    @Test
    fun droppedProvinceNoopWhenAmbiguous() {
        // 黑/豫 都含机关位 H，两省都合法 = 歧义，不补。
        val n = PlateNormalizerV2.create(kb, readingMap, contextProvinces = listOf('黑', '豫'))
        assertEquals("车牌号H 28491的", n.normalize("车牌号H 28491的").text)
    }

    @Test
    fun droppedProvinceNoopWithoutAnchor() {
        // 无车牌锚词 → 即便有上下文省份也不补（防裸串误补）。
        val n = PlateNormalizerV2.create(kb, readingMap, contextProvinces = listOf('黑'))
        assertEquals("H 28491", n.normalize("H 28491").text)
    }

    // ---- P5-3: 省份读成字母/生僻近音、数字补位、suppress 平局 ----

    @Test
    fun provinceReadAsAsciiLetter() {
        // 豫(yù) 被 ASR 读成 ASCII「U」：UC84915 → 豫C84915。U 作起点由读音表 U→豫 驱动。
        assertEquals("豫C84915", norm("UC84915"))
    }

    @Test
    fun provinceReadAsHomophoneChar() {
        // 鲁(lǔ) 听成 卢/路/如：卢F19374 → 鲁F19374。
        assertEquals("鲁F19374", norm("卢F19374"))
        // 浙(zhè) 听成 折：折B31672 → 浙B31672。
        assertEquals("浙B31672", norm("折B31672"))
    }

    @Test
    fun digitPaddingAtAuthorityPosition() {
        // 机关位字母 E(yī) 被听成数字「1」，导致「省+6 位数字」：黑160538 → 黑E60538。
        // 仅机关位回退到字母；序号位走最短路保留数字。
        assertEquals("黑E60538", norm("黑160538"))
    }

    @Test
    fun digitPaddingDoesNotTouchSerialDigits() {
        // 序号位的「1」必须保持为数字（恒等 cost0 胜过 1→E），不得被补成字母。
        assertEquals("冀A11111", norm("冀A11111"))
        assertEquals("辽B10088", norm("辽B10088"))
    }

    @Test
    fun suppressResolvesTieToCorrectLetter() {
        // base 含 优→V(噪声) 与 优→U；suppress 优→V 后唯一候选 U，平局消解：豫优46729 → 豫U46729。
        assertEquals("豫U46729", norm("豫优46729"))
    }
}
