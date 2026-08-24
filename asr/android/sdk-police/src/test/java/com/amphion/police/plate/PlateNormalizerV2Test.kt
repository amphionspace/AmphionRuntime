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
    fun shanxi_jin_human_retest_mishears() {
        val home = PlateNormalizerV2.create(kb, readingMap, listOf('冀', '辽'))
        assertEquals("晋K63745", home.normalize("麻烦核实一下净K 63745这辆车的情况。").primaryPlate)
        assertEquals("晋J28491", home.normalize("帮我看下进这28491车辆有没有关联警。").primaryPlate)
        assertEquals("晋J28491", home.normalize("请帮忙查询建寨28491车辆情况。").primaryPlate)
    }

    @Test
    fun zhejiang_zhe_human_retest_mishears() {
        assertEquals("浙J63745", normalizer.normalize("麻烦帮我核查这这63745车辆情况。").primaryPlate)
    }

    @Test
    fun shanghai_hu19374_missing_authority_letter() {
        assertEquals("沪F19374", normalizer.normalize("帮我查一下车牌号为沪19374的车辆信息。").primaryPlate)
    }

    @Test
    fun shandong_luyu_to_luE_from_human_retest() {
        assertEquals("鲁E60538", normalizer.normalize("麻烦帮我核查鲁豫60538车辆情况。").primaryPlate)
    }

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

    @Test
    fun droppedProvinceNoopInsideLongDigitRun() {
        // 回归：身份证/手机号等长数字串里不得截一段当车牌（即便句中有「核查/号码」等锚词、有辖区省）。
        val n = PlateNormalizerV2.create(kb, readingMap, contextProvinces = listOf('冀', '辽'))
        assertEquals(
            "帮我核查身份证号码为37050319911230983。",
            n.normalize("帮我核查身份证号码为37050319911230983。").text,
        )
        assertEquals(
            "帮我核查身份证号码为370 503 19911230983。",
            n.normalize("帮我核查身份证号码为370 503 19911230983。").text,
        )
    }

    @Test
    fun droppedProvinceStillFillsIsolatedPlate() {
        // 守卫不应误伤真正孤立的丢省份车牌：唯一合法省份仍应补省。
        val n = PlateNormalizerV2.create(kb, readingMap, contextProvinces = listOf('冀', '辽'))
        assertEquals("查一下车牌冀R30983", n.normalize("查一下车牌R30983").text)
    }

    @Test
    fun cp5500_hebeiPrefixResidualsRequireExplicitPlateContext() {
        val n = PlateNormalizerV2.create(kb, readingMap, contextProvinces = listOf('冀', '辽'))
        val cases = linkedMapOf(
            "车牌号GIR17685车辆" to "车牌号冀R17685车辆",
            "车牌号GI230755车辆" to "车牌号冀R30755车辆",
            "车牌号GL72713车辆" to "车牌号冀R72713车辆",
            "车牌号7236403车辆" to "车牌号冀R36403车辆",
            "车牌号GR227996车辆" to "车牌号冀R27996车辆",
            "车牌号及R231054车辆" to "车牌号冀R31054车辆",
            "车牌号寄200959车辆" to "车牌号冀R00959车辆",
            "车牌号汽201463车辆" to "车牌号冀R01463车辆",
            "车牌号GR5864~5车辆" to "车牌号冀R58645车辆",
            "GIR24075离开时是往主路方向还是小区方向走的" to
                "冀R24075离开时是往主路方向还是小区方向走的",
            "GIR24075刚才蹭到路边车后直接开走了" to
                "冀R24075刚才蹭到路边车后直接开走了",
            "我们已经记录GIR91648，请您先不要和车主发生争执" to
                "我们已经记录冀R91648，请您先不要和车主发生争执",
        )
        for ((raw, expected) in cases) assertEquals("raw=$raw", expected, n.normalize(raw).text)
    }

    @Test
    fun cp5500_hebeiPrefixResidualsDoNotRewriteGenericIdentifiers() {
        val n = PlateNormalizerV2.create(kb, readingMap, contextProvinces = listOf('冀', '辽'))
        for (raw in listOf(
            "产品型号GIR17685",
            "设备编号GI230755",
            "设备编号GI R17685",
            "设备编号寄200959",
            "产品型号GL72713",
            "订单号7236403",
            "记录7236403",
            "确认GIR17685",
            "设备编号GIR17685车辆正在运行",
            "设备编号为GIR17685车辆正在运行",
            "产品型号是GL72713车辆正在运行",
            "车牌号GIR17685A车辆",
            "工单GIR17685对应的车辆正在运行",
            "ＸＧＩＲ17685车辆正在运行",
            "关于校园欺凌73504号案件",
            "GR2024",
            "GB28181",
            "合法车牌辽L72713",
            "合法车牌冀R22585",
        )) {
            assertEquals("raw=$raw", raw, n.normalize(raw).text)
        }
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
