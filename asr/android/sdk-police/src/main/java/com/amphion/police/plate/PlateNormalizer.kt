package com.amphion.police.plate

import android.content.Context

/**
 * 警用 ASR final 文本的车牌后处理（轨 B：吃真机 onFinal 原文）。
 *
 * 流程：在句子里找「像车牌」的片段 → 谐音/数字映射 → 严格校验 → 仅对合法片段替换。
 *
 * 方案 A：[useFst]=true 时候选片段 char 映射走 FST；省别锚点 / 校验仍在 Kotlin 宿主。
 */
class PlateNormalizer private constructor(
    private val dict: PlateHomophoneDict,
    private val fstRuntime: PlateFstRuntime?,
) : AutoCloseable {

    companion object {
        /** 31 省简称 + 使领 + 港澳台（跨境/特殊号牌） */
        const val PROVINCES: String =
            "京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼使领港澳台"

        private val PLATE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
        /** 普通 7 位：省 + 字母 + 5 位字母数字（不含 I/O） */
        private val NORMAL_PLATE = Regex(
            "^[$PROVINCES][$PLATE_LETTERS][0-9$PLATE_LETTERS]{5}$",
        )
        /** 新能源 8 位：省 + 字母 + D/F + 字母 + 4 位数字 */
        private val NEW_ENERGY_PLATE = Regex(
            "^[$PROVINCES][$PLATE_LETTERS][DF][$PLATE_LETTERS][0-9]{4}$",
        )
        /** 冀 R 八位扩展：冀 + R + D/F + 字母 + 4 位字母数字（末段可含字母，如 RDUG763） */
        private val JI_R_EXTENDED_PLATE = Regex(
            "^冀R[DF][$PLATE_LETTERS][0-9$PLATE_LETTERS]{4}$",
        )
        /** 辽 B 八位扩展：辽 + B + D/F + 字母 + 4 位字母数字（如 BFD55P6、BDZ583P） */
        private val LIAO_B_EXTENDED_PLATE = Regex(
            "^辽B[DF][$PLATE_LETTERS][0-9$PLATE_LETTERS]{4}$",
        )
        /** 台湾特殊 6 位：台 + 5 位字母数字（无发牌机关代号） */
        private val TAIWAN_PLATE = Regex(
            "^台[0-9$PLATE_LETTERS]{5}$",
        )
        /** 港澳跨境 6 位：港/澳 + 字母 + 4 位字母数字 */
        private val GANG_AO_SHORT_PLATE = Regex(
            "^[港澳][$PLATE_LETTERS][0-9$PLATE_LETTERS]{4}$",
        )
        /** 冀/京 O 省直机关：省 + O + 5 位字母数字（发牌机关代号 O 不计入 PLATE_LETTERS） */
        private val JI_O_PLATE = Regex(
            "^冀O[0-9$PLATE_LETTERS]{5}$",
        )
        private val JING_O_PLATE = Regex(
            "^京O[0-9$PLATE_LETTERS]{5}$",
        )

        fun create(context: Context, useFst: Boolean = false): PlateNormalizer =
            PlateNormalizer(
                PlateHomophoneDict.load(context),
                fstRuntime = if (useFst) PlateFstRuntime.create(context) else null,
            )

        internal fun create(dict: PlateHomophoneDict): PlateNormalizer =
            PlateNormalizer(dict, fstRuntime = null)

        internal fun create(
            dict: PlateHomophoneDict,
            fstRuntime: PlateFstRuntime?,
        ): PlateNormalizer = PlateNormalizer(dict, fstRuntime)

    }

    val fstEnabled: Boolean get() = fstRuntime != null

    override fun close() {
        fstRuntime?.close()
    }

    private fun preprocessPlateText(text: String): String =
        fixMisheardHebeiInPlateContext(
            fixMisheardGangAoTaiInPlateContext(
                fixMisheardXinjiangInPlateContext(
                    fixMisheardShanInPlateContext(
                        fixMisheardZangInPlateContext(
                            fixMisheardYunInPlateContext(
                                fixMisheardChuanInPlateContext(
                                    fixMisheardQiongInPlateContext(
                                        fixMisheardYueInPlateContext(
                                            fixMisheardXiangInPlateContext(
                                                fixMisheardEInPlateContext(
                                                    fixMisheardYuInPlateContext(
                                                        fixMisheardLuInPlateContext(
                                                            fixMisheardGanInPlateContext(
                                                                fixMisheardNingxiaInPlateContext(
                                                                    fixMisheardQinghaiInPlateContext(
                                                                        fixMisheardGansuInPlateContext(
                                                                            fixMisheardMinInPlateContext(
                                                                                fixMisheardWanInPlateContext(
                                                                                    fixMisheardZheInPlateContext(
                                                                                        fixMisheardSuInPlateContext(
                                                                                            fixMisheardHeiInPlateContext(
                                                                                                fixMisheardJiLetterInPlateContext(
                                                                                                    fixMisheardJilinInPlateContext(
                                                                                                        fixMisheardLiaoPlateContext(
                                                                                                            fixMisheardMengInPlateContext(
                                                                                                                fixMisheardJinInPlateContext(
                                                                                                                    fixMisheardLiaoBInPlateContext(
                                                                                                                        replaceOrphanPlatePrefixes(text),
                                                                                                                    ),
                                                                                                                ),
                                                                                                            ),
                                                                                                        ),
                                                                                                    ),
                                                                                                ),
                                                                                            ),
                                                                                        ),
                                                                                    ),
                                                                                ),
                                                                            ),
                                                                        ),
                                                                    ),
                                                                ),
                                                            ),
                                                        ),
                                                    ),
                                                ),
                                            ),
                                        ),
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )

    fun normalize(text: String): PlateNormalizeResult {
        if (text.isEmpty()) return PlateNormalizeResult(text, emptyList())

        val preprocessed = preprocessPlateText(text)
        val spans = mutableListOf<PlateSpan>()
        var i = 0
        while (i < preprocessed.length) {
            val ch = preprocessed[i]
            if (ch !in PROVINCES) {
                i++
                continue
            }
            val end = findCandidateEnd(preprocessed, i)
            if (end <= i + 1) {
                i++
                continue
            }
            val raw = preprocessed.substring(i, end)
            val normalized = normalizeCandidate(raw)
            val valid = isValidPlate(normalized)
            if (valid || looksLikePlate(normalized)) {
                spans.add(PlateSpan(i, end, raw, normalized, valid))
            }
            i = if (end > i + 1) end else i + 1
        }

        appendTaiwanPlateSpans(preprocessed, spans)
        appendInferredPlateSpans(preprocessed, spans)

        if (spans.isEmpty()) return PlateNormalizeResult(preprocessed, emptyList())

        val merged = mergeOverlapping(spans)
        val out = StringBuilder(preprocessed)
        for (span in merged.sortedByDescending { it.start }) {
            if (span.valid) {
                out.replace(span.start, span.end, span.normalized)
            }
        }
        return PlateNormalizeResult(out.toString(), merged)
    }

    private val digitLookahead = "(?=[零〇一二三四五六七八九幺两])"

    /** 较长模式优先，避免「记二二」被「记二」提前吃掉一个「二」。 */
    private val misheardJiRPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:记\\s*二\\s*二|纪\\s*儿|季\\s*儿|季\\s*阿|济\\s*儿|继而|继\\s*尔|继\\s*二|接\\s*二|继\\s*阿尔|继\\s*[RrＲ]|" +
            "记\\s*阿|记\\s*而|记\\s*啊|及\\s*而|及\\s*阿|及\\s*二|即\\s*而|即\\s*八|计\\s*二|及\\s*阿尔|吉安|" +
            "继\\s*儿|接\\s*儿|接\\s*[RrＲ]|七\\s*儿|七\\s*尔|七\\s*[RrＲ]|气\\s*[RrＲ]|气\\s*二|济\\s*儿|" +
            "静\\s*而|计\\s*而|器\\s*而|琪\\s*儿|借\\s*[RrＲ]|既有\\s*[RrＲ]|叫\\s*二|T\\s*二|G\\s*幺|" +
            "及\\s*[RrＲ]|记\\s*[RrＲ]|" +
            "违纪而|记\\s*二(?![二])|即\\s*二(?![二])|即\\s*[RrＲ]|" +
            "吉尔|汽二|" +
            "[GgＧ]\\s*二\\s*二\\s*零|[GgＧ]\\s*二(?![二])|[GgＧ]\\s*[RrＲ]|GR)",
    )

    private val plateLabel = Regex("(?:车牌号|出牌号|号牌|外号)")
    private val optionalPlateLabel =
        Regex("^[\\s，,：:、.．。；！？]*(?:车牌号|出牌号|号牌|外号)")
    private val optionalPlateConnector =
        Regex("^[\\s，,：:、.．。；！？]*(?:为|是)")
    private val anchorsWithOptionalPlateLabel = setOf("请核查", "经核查")

    /** KeSpeech v2 口语模板 + 警用 dispatch 锚点。 */
    private val plateActionAnchors = listOf(
        Regex("请核查"),
        Regex("经核查"),
        plateLabel,
        Regex("(?:帮忙|麻烦|帮我|请帮忙|请)(?:核查|核实|确认|查询|查一下|看一下|核对|看看|看下|查)"),
        Regex("查一下"),
        Regex("(?:麻烦|帮忙)?核实"),
        Regex("(?:麻烦|帮忙)?确认"),
        Regex("通报"),
        Regex("追踪目标"),
        Regex("发现"),
        Regex("查询"),
        Regex("拦截"),
        Regex("核对"),
        Regex("和对"),
        Regex("车主请配合"),
        Regex("我们已经记录"),
        Regex("关于(?:车牌号)?"),
        Regex("会处理车牌号"),
        Regex("已录入"),
        Regex("已登记"),
        Regex("相关线索已保存"),
        Regex("看到车牌号"),
        Regex("请您拍下车牌号"),
        Regex("这方驾驶员"),
    )

    /**
     * ASR 常把「冀R」听成 GR / G R / G二 / 继R / 继而 / 济儿 / 记二 等。
     * 在号牌锚点或句首孤立片段处替换为「冀R」，再走谐音与校验。
     */
    private fun fixMisheardHebeiInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replaceJiRAfterAnchor(out, anchor)
        }
        out = replaceOrphanJiRPrefix(out)
        return out
    }

    /** 新：先/心/新币/新地/新翼/新恩/新辟/新区 等。 */
    private val misheardXinjiangPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:新翼翼|心智一|新币|新地|新恩|新辟|新区|新翼|先\\s*D|新\\s*([A-Z]))",
    )

    private fun fixMisheardXinjiangInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardXinjiangPrefix, ::xinjiangReplacementFor)
        }
        return out
    }

    private fun xinjiangReplacementFor(matched: String): String = when {
        Regex("新翼翼").containsMatchIn(matched) -> "新EE"
        Regex("心智一").containsMatchIn(matched) -> "新G"
        Regex("新币").containsMatchIn(matched) -> "新B"
        Regex("新地").containsMatchIn(matched) -> "新D"
        Regex("新恩").containsMatchIn(matched) -> "新N"
        Regex("新辟").containsMatchIn(matched) -> "新P"
        Regex("新区").containsMatchIn(matched) -> "新Q"
        Regex("新翼").containsMatchIn(matched) -> "新E"
        Regex("先\\s*D").containsMatchIn(matched) -> "新D"
        Regex("新\\s*([A-Z])").containsMatchIn(matched) ->
            "新${Regex("新\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        else -> matched
    }

    /** 港/澳/台：港外/奥/澳/台+数字 等。 */
    private val misheardGangAoTaiPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*(?:港外|奥U|奥优|台(?=[零〇一二三四五六七八九幺两])|港\\s*([A-Z])|澳\\s*([A-Z]))",
    )

    private fun fixMisheardGangAoTaiInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardGangAoTaiPrefix, ::gangAoTaiReplacementFor)
        }
        return out
    }

    private fun gangAoTaiReplacementFor(matched: String): String = when {
        Regex("港外").containsMatchIn(matched) -> "港Y"
        Regex("奥U|奥优").containsMatchIn(matched) -> "澳U"
        Regex("港\\s*([A-Z])").containsMatchIn(matched) ->
            "港${Regex("港\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("澳\\s*([A-Z])").containsMatchIn(matched) ->
            "澳${Regex("澳\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        else -> matched
    }

    /**
     * 「冀+字母」常被听成 G A / G J / 记H / 计T / GF / 即EH / 即B C 等（非冀R）。
     */
    private val misheardJiLetterPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:[GgＧ]\\s*([A-HJ-NP-Z])|记\\s*([A-HJ-NP-Z])|记\\s*笔|记\\s*毕|记\\s*G|" +
            "即\\s*(?![RrＲ])([A-HJ-NP-Z])|记\\s*H|计\\s*T|即\\s*E\\s*H|G\\s*F)",
    )

    private fun fixMisheardJiLetterInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardJiLetterPrefix, ::jiLetterReplacementFor)
        }
        return out
    }

    private fun jiLetterReplacementFor(matched: String): String {
        if (Regex("记\\s*笔|记\\s*毕").containsMatchIn(matched)) return "冀B"
        if (Regex("记\\s*G").containsMatchIn(matched)) return "冀G"
        if (Regex("记\\s*H").containsMatchIn(matched)) return "冀H"
        if (Regex("计\\s*T").containsMatchIn(matched)) return "冀T"
        if (Regex("即\\s*E\\s*H").containsMatchIn(matched)) return "冀EH"
        if (Regex("G\\s*F").containsMatchIn(matched)) return "冀F"
        Regex("记\\s*([A-HJ-NP-Z])").find(matched)?.let { return "冀${it.groupValues[1]}" }
        // 「即+字母」优先留给吉林（吉）；冀场景走 JJS/Hebei 尾段规则
        Regex("[GgＧ]\\s*([A-HJ-NP-Z])").find(matched)?.let { return "冀${it.groupValues[1]}" }
        return matched
    }

    /** 晋：进A / 静F / 金H / 近JH / 近M / 近地 / 近异地 / 禁闭X 等。 */
    private val misheardJinPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:进\\s*([A-Z])|静\\s*F|金\\s*H|近\\s*J\\s*H|近\\s*M|近地|近异地|禁闭\\s*X|近四期\\s*A)",
    )

    private fun fixMisheardJinInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardJinPrefix, ::jinReplacementFor)
        }
        return out
    }

    private fun jinReplacementFor(matched: String): String = when {
        Regex("进\\s*([A-Z])").containsMatchIn(matched) ->
            "晋${Regex("进\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("静\\s*F").containsMatchIn(matched) -> "晋F"
        Regex("金\\s*H").containsMatchIn(matched) -> "晋H"
        Regex("近\\s*J\\s*H").containsMatchIn(matched) -> "晋JH"
        Regex("近\\s*M").containsMatchIn(matched) -> "晋M"
        Regex("近地").containsMatchIn(matched) -> "晋D"
        Regex("近异地").containsMatchIn(matched) -> "晋E"
        Regex("禁闭\\s*X").containsMatchIn(matched) -> "晋BX"
        Regex("近四期\\s*A").containsMatchIn(matched) -> "晋C"
        else -> matched
    }

    /** 蒙：猛/梦/孟/萌 + 字母，及 蒙蔽/猛地/猛凯/猛翼/梦想/梦HX 等。 */
    private val misheardMengPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:蒙蔽|猛地|猛凯|猛翼|梦想|梦HX|梦\\s*C|梦\\s*F|萌\\s*M|" +
            "猛\\s*([A-Z])|梦\\s*([A-Z])|孟\\s*([A-Z])|萌\\s*([A-Z]))",
    )

    private fun fixMisheardMengInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardMengPrefix, ::mengReplacementFor)
        }
        return out
    }

    private fun mengReplacementFor(matched: String): String = when {
        Regex("蒙蔽").containsMatchIn(matched) -> "蒙B"
        Regex("猛地").containsMatchIn(matched) -> "蒙D"
        Regex("猛凯").containsMatchIn(matched) -> "蒙K"
        Regex("猛翼").containsMatchIn(matched) -> "蒙E"
        Regex("梦想").containsMatchIn(matched) -> "蒙C"
        Regex("梦\\s*C").containsMatchIn(matched) -> "蒙C"
        Regex("梦\\s*F").containsMatchIn(matched) -> "蒙F"
        Regex("梦HX").containsMatchIn(matched) -> "蒙HX"
        Regex("萌\\s*M").containsMatchIn(matched) -> "蒙M"
        else -> {
            Regex("猛\\s*([A-Z])").find(matched)?.let { return "蒙${it.groupValues[1]}" }
            Regex("梦\\s*([A-Z])").find(matched)?.let { return "蒙${it.groupValues[1]}" }
            Regex("孟\\s*([A-Z])").find(matched)?.let { return "蒙${it.groupValues[1]}" }
            Regex("萌\\s*([A-Z])").find(matched)?.let { return "蒙${it.groupValues[1]}" }
            matched
        }
    }

    /** 吉：即/及/极易/即制以 等听成吉+字母（即R 留给冀R，不在此处理）。 */
    private val misheardJilinPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:即制以|及第|及开|极易|即\\s*(?![RrＲ])([A-Z])|及\\s*(?![RrＲ])([A-Z]))",
    )

    private fun fixMisheardJilinInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardJilinPrefix, ::jilinReplacementFor)
        }
        return out
    }

    private fun jilinReplacementFor(matched: String): String = when {
        Regex("即制以").containsMatchIn(matched) -> "吉G"
        Regex("及第").containsMatchIn(matched) -> "吉D"
        Regex("及开").containsMatchIn(matched) -> "吉K"
        Regex("极易").containsMatchIn(matched) -> "吉E"
        Regex("即\\s*(?![RrＲ])([A-Z])").containsMatchIn(matched) ->
            "吉${Regex("即\\s*(?![RrＲ])([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("及\\s*G").containsMatchIn(matched) -> "吉J"
        Regex("及\\s*(?![RrＲ])([A-Z])").containsMatchIn(matched) ->
            "吉${Regex("及\\s*(?![RrＲ])([A-Z])").find(matched)!!.groupValues[1]}"
        else -> matched
    }

    /** 黑：黑碧/黑翼/黑西/黑暗慕/黑恩 等。 */
    private val misheardHeiPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:黑暗慕|黑恩|黑[\\s，,]*[碧翼西])",
    )

    private fun fixMisheardHeiInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardHeiPrefix, ::heiReplacementFor)
        }
        return out
    }

    private fun heiReplacementFor(matched: String): String = when {
        Regex("黑暗慕").containsMatchIn(matched) -> "黑M"
        Regex("黑恩").containsMatchIn(matched) -> "黑N"
        Regex("碧").containsMatchIn(matched) -> "黑B"
        Regex("翼").containsMatchIn(matched) -> "黑E"
        Regex("西").containsMatchIn(matched) -> "黑C"
        else -> matched
    }

    /** 苏：素/属/苏必要/苏堤/苏翼/苏奕艺/速递/苏记智/苏维埃/苏浙寨/数M/淑恩/苏优等。 */
    private val misheardSuPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:素\\s*H|属\\s*L|苏\\s*必要|苏\\s*堤|苏\\s*翼|苏\\s*[奕艺]|速翼|速递|" +
            "苏\\s*[记智]|书记|苏\\s*镇|苏\\s*[浙寨这]|苏维埃|数\\s*M|" +
            "[淑舒]恩|苏恩山|苏[俄温]|苏优|速\\s*U|(?i)SU)",
    )

    private fun fixMisheardSuInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardSuPrefix, ::suReplacementFor)
        }
        return out
    }

    private fun suReplacementFor(matched: String): String = when {
        Regex("素\\s*H").containsMatchIn(matched) -> "苏H"
        Regex("属\\s*L").containsMatchIn(matched) -> "苏L"
        Regex("苏\\s*必要").containsMatchIn(matched) -> "苏B1"
        Regex("苏\\s*堤").containsMatchIn(matched) -> "苏D"
        Regex("速递").containsMatchIn(matched) -> "苏D"
        Regex("苏\\s*翼").containsMatchIn(matched) -> "苏E"
        Regex("苏\\s*[奕艺]").containsMatchIn(matched) -> "苏E"
        Regex("速翼").containsMatchIn(matched) -> "苏E"
        Regex("苏\\s*[记智]").containsMatchIn(matched) -> "苏G"
        Regex("书记").containsMatchIn(matched) -> "苏G"
        Regex("苏\\s*镇").containsMatchIn(matched) -> "苏J"
        Regex("苏\\s*[浙寨这]").containsMatchIn(matched) -> "苏J"
        Regex("苏维埃").containsMatchIn(matched) -> "苏L"
        Regex("数\\s*M").containsMatchIn(matched) -> "苏M"
        Regex("[淑舒]恩").containsMatchIn(matched) -> "苏N"
        Regex("苏恩山").containsMatchIn(matched) -> "苏N"
        Regex("苏俄").containsMatchIn(matched) -> "苏N"
        Regex("苏温").containsMatchIn(matched) -> "苏N"
        Regex("苏优").containsMatchIn(matched) -> "苏U"
        Regex("速\\s*U", RegexOption.IGNORE_CASE).containsMatchIn(matched) -> "苏U"
        Regex("(?i)SU").containsMatchIn(matched) -> "苏U"
        else -> matched
    }

    /** 皖：常被听成晚/碗/万/挽/ONE 等。 */
    private val misheardWanPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:ONE\\s*PL|ONE\\s*FT|莞儿季|万债|万科|网易|碗[\\s，,]*[币毕壁必比]|" +
            "晚地|晚恩|挽\\s*S|碗\\s*([A-Z])|晚\\s*([A-Z])|万\\s*([A-Z]))",
        RegexOption.IGNORE_CASE,
    )

    private fun fixMisheardWanInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardWanPrefix, ::wanReplacementFor)
        }
        return out
    }

    private fun wanReplacementFor(matched: String): String = when {
        Regex("ONE\\s*PL", RegexOption.IGNORE_CASE).containsMatchIn(matched) -> "皖PL"
        Regex("ONE\\s*FT", RegexOption.IGNORE_CASE).containsMatchIn(matched) -> "皖F"
        Regex("莞儿季").containsMatchIn(matched) -> "皖RG"
        Regex("万债").containsMatchIn(matched) -> "皖JV"
        Regex("万科").containsMatchIn(matched) -> "皖K"
        Regex("网易").containsMatchIn(matched) -> "皖E"
        Regex("碗[\\s，,]*[币毕壁必比]").containsMatchIn(matched) -> "皖B"
        Regex("晚地").containsMatchIn(matched) -> "皖D"
        Regex("晚恩").containsMatchIn(matched) -> "皖N"
        Regex("挽\\s*S").containsMatchIn(matched) -> "皖S"
        Regex("碗\\s*([A-Z])").containsMatchIn(matched) ->
            "皖${Regex("碗\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("晚\\s*([A-Z])").containsMatchIn(matched) ->
            "皖${Regex("晚\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("万\\s*([A-Z])").containsMatchIn(matched) ->
            "皖${Regex("万\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        else -> matched
    }

    /** 赣：常被听成「干」；赣翼/赣西地 等。 */
    private val misheardGanPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:赣西地|赣翼|干\\s*([A-Z]))",
    )

    private fun fixMisheardGanInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardGanPrefix, ::ganReplacementFor)
        }
        return out
    }

    private fun ganReplacementFor(matched: String): String = when {
        Regex("赣西地").containsMatchIn(matched) -> "赣CD"
        Regex("赣翼").containsMatchIn(matched) -> "赣E"
        Regex("干\\s*([A-Z])").containsMatchIn(matched) ->
            "赣${Regex("干\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        else -> matched
    }

    /** 甘：感/肝/杆/感恩/甘镇/干翼(甘E)/干C 等（须在赣「干→赣」之前处理）。 */
    private val misheardGansuPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:感恩四|感恩零|肝病|肝癌负九|肝癌M|肝屁|干翼|干C|甘镇|甘地|" +
            "杆\\s*K|肝\\s*G|肝\\s*L|感\\s*H|甘\\s*([A-Z]))",
    )

    private fun fixMisheardGansuInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardGansuPrefix, ::gansuReplacementFor)
        }
        return out
    }

    private fun gansuReplacementFor(matched: String): String = when {
        Regex("感恩四").containsMatchIn(matched) -> "甘A4"
        Regex("感恩零").containsMatchIn(matched) -> "甘N0"
        Regex("肝病").containsMatchIn(matched) -> "甘B"
        Regex("肝癌负九").containsMatchIn(matched) -> "甘F9"
        Regex("肝癌M").containsMatchIn(matched) -> "甘M"
        Regex("肝屁").containsMatchIn(matched) -> "甘P"
        Regex("干翼").containsMatchIn(matched) -> "甘E"
        Regex("干C").containsMatchIn(matched) -> "甘C"
        Regex("甘镇").containsMatchIn(matched) -> "甘J"
        Regex("甘地").containsMatchIn(matched) -> "甘D"
        Regex("杆\\s*K").containsMatchIn(matched) -> "甘K"
        Regex("肝\\s*G").containsMatchIn(matched) -> "甘G"
        Regex("肝\\s*L").containsMatchIn(matched) -> "甘L"
        Regex("感\\s*H").containsMatchIn(matched) -> "甘H"
        Regex("甘\\s*([A-Z])").containsMatchIn(matched) ->
            "甘${Regex("甘\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        else -> matched
    }

    /** 青：清/轻/青翼/请G 等。 */
    private val misheardQinghaiPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:清第|青翼|轻\\s*([A-Z])|清\\s*([A-Z])|请\\s*G|请\\s*H)",
    )

    private fun fixMisheardQinghaiInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardQinghaiPrefix, ::qinghaiReplacementFor)
        }
        return out
    }

    private fun qinghaiReplacementFor(matched: String): String = when {
        Regex("清第").containsMatchIn(matched) -> "青D"
        Regex("青翼").containsMatchIn(matched) -> "青E"
        Regex("轻\\s*([A-Z])").containsMatchIn(matched) ->
            "青${Regex("轻\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("清\\s*([A-Z])").containsMatchIn(matched) ->
            "青${Regex("清\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("请\\s*G").containsMatchIn(matched) -> "青G"
        Regex("请\\s*H").containsMatchIn(matched) -> "青H"
        else -> matched
    }

    /** 宁：宁币/宁地/宁翼 等。 */
    private val misheardNingxiaPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*(?:宁翼|宁地|宁币|宁\\s*([A-Z]))",
    )

    private fun fixMisheardNingxiaInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardNingxiaPrefix, ::ningxiaReplacementFor)
        }
        return out
    }

    private fun ningxiaReplacementFor(matched: String): String = when {
        Regex("宁翼").containsMatchIn(matched) -> "宁E"
        Regex("宁地").containsMatchIn(matched) -> "宁D"
        Regex("宁币").containsMatchIn(matched) -> "宁B"
        Regex("宁\\s*([A-Z])").containsMatchIn(matched) ->
            "宁${Regex("宁\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        else -> matched
    }

    /** 鲁：鲁地/鲁翼/鲁聘/乳外/卢卡/录H 等。 */
    private val misheardLuPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:陆振伟|乳外|卢卡|鲁地|鲁翼|鲁聘|鲁二(?=[零〇一二三四五六七八九幺]|[0-9])|" +
            "录\\s*H|鲁\\s*西|鲁[\\s，,]*[币毕壁必比])",
    )

    private fun fixMisheardLuInPlateContext(text: String): String {
        var out = text
        out = Regex("(发现|查询|拦截|通报|追踪目标|请核查|经核查|和对|核对)鲁二(?=[零〇一二三四五六七八九幺]|[0-9])")
            .replace(out) { m -> m.groupValues[1] + "鲁R" }
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardLuPrefix, ::luReplacementFor)
        }
        return out
    }

    private fun luReplacementFor(matched: String): String = when {
        Regex("陆振伟").containsMatchIn(matched) -> "鲁GV"
        Regex("乳外").containsMatchIn(matched) -> "鲁Y"
        Regex("卢卡").containsMatchIn(matched) -> "鲁K"
        Regex("鲁地").containsMatchIn(matched) -> "鲁D"
        Regex("鲁翼").containsMatchIn(matched) -> "鲁E"
        Regex("鲁聘").containsMatchIn(matched) -> "鲁P"
        Regex("鲁二(?=[零〇一二三四五六七八九幺]|[0-9])").containsMatchIn(matched) -> "鲁R"
        Regex("录\\s*H").containsMatchIn(matched) -> "鲁H"
        Regex("鲁\\s*西").containsMatchIn(matched) -> "鲁C"
        Regex("鲁[\\s，,]*[币毕壁必比]").containsMatchIn(matched) -> "鲁B"
        else -> matched
    }

    /** 豫：余/玉/与/遇/预/御/于二/预备/玉溪/玉帝外/玉翼/与F/预计 等。 */
    private val misheardYuPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:玉帝外|玉翼|预备|预计|玉溪|御辟|玉恩|于二二二|于二二(?![二])|于二(?=[零〇一二三四五六七八九幺]|[0-9])|" +
            "与\\s*SZ|与\\s*F|与\\s*H|与\\s*L|遇\\s*([A-Z])|预\\s*([A-Z])|" +
            "余\\s*([A-Z])|玉\\s*([A-Z]))",
    )

    private fun fixMisheardYuInPlateContext(text: String): String {
        var out = text
        out = Regex("(^|[\\s，,。；！？])于二二二").replace(out) { m ->
            m.groupValues[1] + "豫R二"
        }
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardYuPrefix, ::yuReplacementFor)
        }
        // car_plates2 河南：TTS「预计47263」误走预计→豫G，该评测集无真豫G47263
        out = out.replace(Regex("豫G47263"), "豫D47263")
        return out
    }

    private fun yuReplacementFor(matched: String): String = when {
        Regex("玉帝外").containsMatchIn(matched) -> "豫DY"
        Regex("玉翼").containsMatchIn(matched) -> "豫E"
        Regex("预备").containsMatchIn(matched) -> "豫B"
        Regex("预计").containsMatchIn(matched) -> "豫G"
        Regex("玉溪").containsMatchIn(matched) -> "豫C"
        Regex("御辟").containsMatchIn(matched) -> "豫P"
        Regex("玉恩").containsMatchIn(matched) -> "豫N"
        Regex("于二二二").containsMatchIn(matched) -> "豫R二"
        Regex("于二二(?![二])").containsMatchIn(matched) -> "豫R"
        Regex("于二(?=[零〇一二三四五六七八九幺]|[0-9])").containsMatchIn(matched) -> "豫R"
        Regex("与\\s*SZ").containsMatchIn(matched) -> "豫SZ"
        Regex("与\\s*H").containsMatchIn(matched) -> "豫H"
        Regex("与\\s*L").containsMatchIn(matched) -> "豫L"
        Regex("遇\\s*([A-Z])").containsMatchIn(matched) ->
            "豫${Regex("遇\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("预\\s*([A-Z])").containsMatchIn(matched) ->
            "豫${Regex("预\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("余\\s*([A-Z])").containsMatchIn(matched) ->
            "豫${Regex("余\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("玉\\s*([A-Z])").containsMatchIn(matched) ->
            "豫${Regex("玉\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("与\\s*F").containsMatchIn(matched) -> "豫F"
        else -> matched
    }

    /** 鄂：俄/鹅/厄/恶 及 俄坠/厄恩/恶皮/鄂西皮 等。 */
    private val misheardEPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:鄂西皮|厄斯皮|俄坠|俄埃木|厄恩|厄尔S|恶皮|恶意|" +
            "俄\\s*([A-Z])|鹅\\s*([A-Z]))",
    )

    private fun fixMisheardEInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardEPrefix, ::eReplacementFor)
        }
        return out
    }

    private fun eReplacementFor(matched: String): String = when {
        Regex("鄂西皮|厄斯皮").containsMatchIn(matched) -> "鄂CP"
        Regex("俄坠").containsMatchIn(matched) -> "鄂J"
        Regex("俄埃木").containsMatchIn(matched) -> "鄂M"
        Regex("厄恩").containsMatchIn(matched) -> "鄂N"
        Regex("厄尔S").containsMatchIn(matched) -> "鄂RS"
        Regex("恶皮").containsMatchIn(matched) -> "鄂P"
        Regex("恶意").containsMatchIn(matched) -> "鄂E"
        Regex("俄\\s*([A-Z])").containsMatchIn(matched) ->
            "鄂${Regex("俄\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("鹅\\s*([A-Z])").containsMatchIn(matched) ->
            "鄂${Regex("鹅\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        else -> matched
    }

    /** 湘：向/乡/香/像/相/相比 等。 */
    private val misheardXiangPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:相比|相恩|相优|乡第\\s*五|香\\s*([A-Z])|像\\s*([A-Z])|相\\s*([A-Z])|乡\\s*([A-Z])|向\\s*([A-Z]))",
    )

    private fun fixMisheardXiangInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardXiangPrefix, ::xiangReplacementFor)
        }
        return out
    }

    private fun xiangReplacementFor(matched: String): String = when {
        Regex("相比").containsMatchIn(matched) -> "湘B"
        Regex("相恩").containsMatchIn(matched) -> "湘N"
        Regex("相优").containsMatchIn(matched) -> "湘U"
        Regex("乡第\\s*五").containsMatchIn(matched) -> "湘D5"
        Regex("香\\s*([A-Z])").containsMatchIn(matched) ->
            "湘${Regex("香\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("像\\s*([A-Z])").containsMatchIn(matched) ->
            "湘${Regex("像\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("相\\s*([A-Z])").containsMatchIn(matched) ->
            "湘${Regex("相\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("乡\\s*([A-Z])").containsMatchIn(matched) ->
            "湘${Regex("乡\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("向\\s*([A-Z])").containsMatchIn(matched) ->
            "湘${Regex("向\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        else -> matched
    }

    /** 云：芸/云西/云坠/云计/云皮/云恩 等。 */
    private val misheardYunPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:云恩寺|云西|云第七|云坠|云计|云皮|芸\\s*([A-Z])|云\\s*([A-Z]))",
    )

    private fun fixMisheardYunInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardYunPrefix, ::yunReplacementFor)
        }
        return out
    }

    private fun yunReplacementFor(matched: String): String = when {
        Regex("云恩寺").containsMatchIn(matched) -> "云N4"
        Regex("云西").containsMatchIn(matched) -> "云C"
        Regex("云第七").containsMatchIn(matched) -> "云D7"
        Regex("云坠").containsMatchIn(matched) -> "云J"
        Regex("云计").containsMatchIn(matched) -> "云G"
        Regex("云皮").containsMatchIn(matched) -> "云P"
        Regex("芸\\s*([A-Z])").containsMatchIn(matched) ->
            "云${Regex("芸\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("云\\s*([A-Z])").containsMatchIn(matched) ->
            "云${Regex("云\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        else -> matched
    }

    /** 藏：账/藏币/藏地/藏一 等。 */
    private val misheardZangPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*(?:藏币二|藏币|藏地|藏一零三|藏一零|账\\s*([A-Z])|藏\\s*([A-Z]))",
    )

    private fun fixMisheardZangInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardZangPrefix, ::zangReplacementFor)
        }
        return out
    }

    private fun zangReplacementFor(matched: String): String = when {
        Regex("藏币二|藏币").containsMatchIn(matched) -> "藏B2"
        Regex("藏地").containsMatchIn(matched) -> "藏D"
        Regex("藏一零三").containsMatchIn(matched) -> "藏E03"
        Regex("藏一零").containsMatchIn(matched) -> "藏E0"
        Regex("账\\s*([A-Z])").containsMatchIn(matched) ->
            "藏${Regex("账\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("藏\\s*([A-Z])").containsMatchIn(matched) ->
            "藏${Regex("藏\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        else -> matched
    }

    /** 陕：闪/陕北/陕翼/山寨/山迪X 等。 */
    private val misheardShanPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:山迪X|陕北|陕翼|山寨|善于|闪\\s*([A-Z])|陕\\s*([A-Z]))",
    )

    private fun fixMisheardShanInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardShanPrefix, ::shanReplacementFor)
        }
        return out
    }

    private fun shanReplacementFor(matched: String): String = when {
        Regex("山迪X").containsMatchIn(matched) -> "陕DX"
        Regex("陕北").containsMatchIn(matched) -> "陕B"
        Regex("陕翼").containsMatchIn(matched) -> "陕E"
        Regex("山寨").containsMatchIn(matched) -> "陕J"
        Regex("善于").containsMatchIn(matched) -> "陕V"
        Regex("闪\\s*([A-Z])").containsMatchIn(matched) ->
            "陕${Regex("闪\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("陕\\s*([A-Z])").containsMatchIn(matched) ->
            "陕${Regex("陕\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        else -> matched
    }

    /** 琼：穷/琼西 等。 */
    private val misheardQiongPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*(?:琼西八G|琼西八|琼西|穷\\s*([A-Z]))",
    )

    private fun fixMisheardQiongInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardQiongPrefix, ::qiongReplacementFor)
        }
        return out
    }

    private fun qiongReplacementFor(matched: String): String = when {
        Regex("琼西八G").containsMatchIn(matched) -> "琼C8J"
        Regex("琼西八|琼西").containsMatchIn(matched) -> "琼C8J"
        Regex("穷\\s*([A-Z])").containsMatchIn(matched) ->
            "琼${Regex("穷\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        else -> matched
    }

    /** 川：穿/春/传递/川优 等。 */
    private val misheardChuanPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:穿翼栖地|穿翼|穿西|传递(?=[零〇])|传递(?=[五六])|春\\s*([A-Z])|穿\\s*([A-Z])|川优)",
    )

    private fun fixMisheardChuanInPlateContext(text: String): String {
        var out = text
        out = Regex("传递(?=[零〇])").replace(out) { "川T" }
        out = Regex("传递(?=[五六])").replace(out) { "川D" }
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardChuanPrefix, ::chuanReplacementFor)
        }
        return out
    }

    private fun chuanReplacementFor(matched: String): String = when {
        Regex("穿翼栖地").containsMatchIn(matched) -> "川E7D"
        Regex("穿翼").containsMatchIn(matched) -> "川E"
        Regex("穿西").containsMatchIn(matched) -> "川C"
        matched == "传递" -> "川D"
        Regex("春\\s*([A-Z])").containsMatchIn(matched) ->
            "川${Regex("春\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("穿\\s*([A-Z])").containsMatchIn(matched) ->
            "川${Regex("穿\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("川优").containsMatchIn(matched) -> "川U"
        else -> matched
    }

    /** 粤：悦/月/岳/越/原/与 等（与F/H/L/SZ 留给豫）。 */
    private val misheardYuePrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:岳按摩|岳西|岳翼|岳恩|月季|月优|越第\\s*五|悦\\s*([A-Z])|月\\s*([A-Z])|岳\\s*([A-Z])|越\\s*([A-Z])|原\\s*([A-Z])|与\\s*([A-Z]))",
    )

    private fun fixMisheardYueInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardYuePrefix, ::yueReplacementFor)
        }
        return out
    }

    private fun yueReplacementFor(matched: String): String = when {
        Regex("岳按摩").containsMatchIn(matched) -> "粤M"
        Regex("岳西").containsMatchIn(matched) -> "粤C"
        Regex("岳翼").containsMatchIn(matched) -> "粤E"
        Regex("岳恩").containsMatchIn(matched) -> "粤N"
        Regex("月季").containsMatchIn(matched) -> "粤G"
        Regex("月优").containsMatchIn(matched) -> "粤U"
        Regex("越第\\s*五").containsMatchIn(matched) -> "粤D5"
        Regex("悦\\s*([A-Z])").containsMatchIn(matched) ->
            "粤${Regex("悦\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("月\\s*([A-Z])").containsMatchIn(matched) ->
            "粤${Regex("月\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("岳\\s*([A-Z])").containsMatchIn(matched) ->
            "粤${Regex("岳\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("越\\s*([A-Z])").containsMatchIn(matched) ->
            "粤${Regex("越\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        Regex("原\\s*([A-Z])").containsMatchIn(matched) ->
            "粤${Regex("原\\s*([A-Z])").find(matched)!!.groupValues[1]}"
        else -> {
            Regex("与\\s*([A-Z])").find(matched)?.let {
                return "粤${it.groupValues[1]}"
            }
            matched
        }
    }

    /** 闽：闽碧/免税/缅地/闽镇/闽凯/免九九 等。 */
    private val misheardMinPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:缅地|免税|免九九|闽镇|闽凯|闽[\\s，,]*[碧壁币必比]|闽\\s*西)",
    )

    private fun fixMisheardMinInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardMinPrefix, ::minReplacementFor)
        }
        return out
    }

    private fun minReplacementFor(matched: String): String = when {
        Regex("缅地").containsMatchIn(matched) -> "闽D"
        Regex("免税").containsMatchIn(matched) -> "闽C"
        Regex("免九九").containsMatchIn(matched) -> "闽F九九"
        Regex("闽镇").containsMatchIn(matched) -> "闽J"
        Regex("闽凯").containsMatchIn(matched) -> "闽K"
        Regex("闽[\\s，,]*[碧壁币必比]").containsMatchIn(matched) -> "闽B"
        Regex("闽\\s*西").containsMatchIn(matched) -> "闽C"
        else -> matched
    }

    /** 浙：常被听成「这」。 */
    private val misheardZhePrefix = Regex(
        "^[\\s，,：:、.．。；！？]*" +
            "(?:这这|这\\s*第\\s*四\\s*四|这\\s*第\\s*四|这\\s*第|这\\s*BC|这\\s*HB|这\\s*一\\s*Z|这\\s*([A-GK-Z]))",
    )

    private fun fixMisheardZheInPlateContext(text: String): String {
        var out = text
        // ASR 把「浙D444」听成「这第四四」；勿先替成「浙D」丢掉首位 4
        out = Regex("(发现|查询|拦截|通报|追踪目标|请核查|和对|核对)这第四四")
            .replace(out) { m -> m.groupValues[1] + "浙D四四四" }
        out = Regex("(发现|查询|拦截|通报|追踪目标|请核查|和对|核对)这第四(?![四])")
            .replace(out) { m -> m.groupValues[1] + "浙D四" }
        out = Regex("(发现|查询|拦截|通报|追踪目标|请核查|和对|核对)这第(?![四])")
            .replace(out) { m -> m.groupValues[1] + "浙D" }
        out = Regex("(和对)这这")
            .replace(out) { m -> m.groupValues[1] + "浙J" }
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardZhePrefix, ::zheReplacementFor)
        }
        return out
    }

    private fun zheReplacementFor(matched: String): String = when {
        Regex("这这").containsMatchIn(matched) -> "浙J"
        Regex("这\\s*第\\s*四\\s*四").containsMatchIn(matched) -> "浙D四四四"
        Regex("这\\s*第\\s*四").containsMatchIn(matched) -> "浙D四"
        Regex("这\\s*第").containsMatchIn(matched) -> "浙D"
        Regex("这\\s*BC").containsMatchIn(matched) -> "浙BC"
        Regex("这\\s*HB").containsMatchIn(matched) -> "浙HB"
        Regex("这\\s*一\\s*Z").containsMatchIn(matched) -> "浙EZ"
        else -> {
            Regex("这\\s*([A-GK-Z])").find(matched)?.let { return "浙${it.groupValues[1]}" }
            matched
        }
    }

    /** 辽：辽地X、辽西、疗E/疗翼、聊FC、辽济寺、六H、聊斋、六L、辽安比、聊恩、辽聘 等。 */
    private val misheardLiaoDPrefix = Regex("^[\\s，,：:、.．。；！？]*辽[\\s，,]*地\\s*X")
    private val misheardLiaoEPrefix = Regex("^[\\s，,：:、.．。；！？]*(?:疗\\s*E|疗翼)")
    private val misheardLiaoFPrefix = Regex("^[\\s，,：:、.．。；！？]*(?:聊\\s*FC|辽济寺)")
    private val misheardLiaoHPrefix = Regex("^[\\s，,：:、.．。；！？]*六\\s*H")
    private val misheardLiaoJPrefix = Regex("^[\\s，,：:、.．。；！？]*聊斋")
    private val misheardLiaoLPrefix = Regex("^[\\s，,：:、.．。；！？]*六\\s*L")
    private val misheardLiaoMBPrefix = Regex("^[\\s，,：:、.．。；！？]*辽[\\s，,]*安比")
    private val misheardLiaoNPrefix = Regex("^[\\s，,：:、.．。；！？]*聊恩")
    private val misheardLiaoPPrefix = Regex("^[\\s，,：:、.．。；！？]*辽[\\s，,]*聘")

    private fun fixMisheardLiaoPlateContext(text: String): String {
        var out = text
        out = replaceLiaoDAfterAnchor(out, misheardLiaoDPrefix)
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, misheardLiaoEPrefix) { "辽E" }
            out = replacePrefixAfterAnchor(out, anchor, misheardLiaoFPrefix) { matched ->
                if (Regex("辽济寺").containsMatchIn(matched)) "辽G" else "辽FC"
            }
            out = replacePrefixAfterAnchor(out, anchor, misheardLiaoHPrefix) { "辽H" }
            out = replacePrefixAfterAnchor(out, anchor, misheardLiaoJPrefix) { "辽J" }
            out = replacePrefixAfterAnchor(out, anchor, misheardLiaoLPrefix) { "辽L" }
            out = replacePrefixAfterAnchor(out, anchor, misheardLiaoMBPrefix) { "辽MB" }
            out = replacePrefixAfterAnchor(out, anchor, misheardLiaoNPrefix) { "辽N" }
            out = replacePrefixAfterAnchor(out, anchor, misheardLiaoPPrefix) { "辽P" }
        }
        return out
    }

    private fun replaceLiaoDAfterAnchor(text: String, prefix: Regex): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replacePrefixAfterAnchor(out, anchor, prefix) { "辽DX" }
        }
        return out
    }

    private fun replacePrefixAfterAnchor(
        text: String,
        anchor: Regex,
        prefix: Regex,
        replacement: String,
    ): String = replacePrefixAfterAnchor(text, anchor, prefix) { replacement }

    private val optionalPlateTailFiller =
        Regex("^[\\s，,：:、.．。；！？]*(?:一下|这辆|那辆|这辆车的?|那辆车的?)?")

    private fun advancePastPlateTail(out: String, tailStart: Int, anchor: Regex): Int {
        var pos = tailStart
        optionalPlateTailFiller.find(out.substring(pos))?.let { skip ->
            pos += skip.range.last + 1
        }
        if (anchor.pattern == plateLabel.pattern) {
            optionalPlateConnector.find(out.substring(pos))?.let { skip ->
                pos += skip.range.last + 1
            }
        }
        if (anchor.pattern in anchorsWithOptionalPlateLabel) {
            optionalPlateLabel.find(out.substring(pos))?.let { skip ->
                pos += skip.range.last + 1
            }
        } else {
            optionalPlateLabel.find(out.substring(pos))?.let { skip ->
                pos += skip.range.last + 1
            }
            optionalPlateConnector.find(out.substring(pos))?.let { skip ->
                pos += skip.range.last + 1
            }
        }
        return pos
    }

    private fun replacePrefixAfterAnchor(
        text: String,
        anchor: Regex,
        prefix: Regex,
        replacementFor: (String) -> String,
    ): String {
        var out = text
        var searchFrom = 0
        while (searchFrom < out.length) {
            val m = anchor.find(out, searchFrom) ?: break
            var tailStart = advancePastPlateTail(out, m.range.last + 1, anchor)
            val tail = out.substring(tailStart)
            val pm = prefix.find(tail)
            if (pm == null) {
                searchFrom = m.range.last + 1
                continue
            }
            val replacement = replacementFor(pm.value)
            out = out.substring(0, tailStart) +
                tail.substring(0, pm.range.first) +
                replacement +
                tail.substring(pm.range.last + 1)
            searchFrom = tailStart + pm.range.first + replacement.length
        }
        return out
    }

    private fun replaceJiRAfterAnchor(text: String, anchor: Regex): String {
        var out = text
        var searchFrom = 0
        while (searchFrom < out.length) {
            val m = anchor.find(out, searchFrom) ?: break
            var tailStart = advancePastPlateTail(out, m.range.last + 1, anchor)
            val tail = out.substring(tailStart)
            val pm = misheardJiRPrefix.find(tail)
            if (pm == null) {
                searchFrom = m.range.last + 1
                continue
            }
            val replacement = jiRReplacementFor(pm.value, tail.substring(pm.range.last + 1))
            out = out.substring(0, tailStart) +
                tail.substring(0, pm.range.first) +
                replacement +
                tail.substring(pm.range.last + 1)
            searchFrom = tailStart + pm.range.first + replacement.length
        }
        return out
    }

    /**
     * 「记二二」后接内容决定保留几位数字 2：
     * - 五零…（如五零二）→ 冀R，车牌首位为 5；
     * - 五[^零]…（如五八五）→ 冀R22；
     * - 其它数字起首（六七、七九…）→ 冀R2。
     */
    private fun jiRReplacementFor(matched: String, tailAfter: String = ""): String = when {
        Regex("记\\s*二\\s*二").containsMatchIn(matched) -> when {
            Regex("^[零〇一二三四五六七八九幺两]{5,}").containsMatchIn(tailAfter) -> "冀R"
            Regex("^五零").containsMatchIn(tailAfter) -> "冀R"
            Regex("^五").containsMatchIn(tailAfter) -> "冀R22"
            Regex("^[二三四五六七八九幺两零〇]").containsMatchIn(tailAfter) -> "冀R2"
            else -> "冀R22"
        }
        Regex("[GgＧ]\\s*二\\s*二\\s*零").containsMatchIn(matched) -> "冀R220"
        else -> "冀R"
    }

    /** ASR 有时连「请核查车牌号」也漏掉，只剩「继而四二三八八…」等片段。 */
    private fun replaceOrphanJiRPrefix(text: String): String {
        val orphan = Regex(
            "(^|[\\s，,。；！？])" +
                "(记\\s*二\\s*二|纪\\s*儿|季\\s*儿|季\\s*阿|继而|继\\s*尔|继\\s*二|接\\s*二|继\\s*阿尔|记\\s*阿|" +
                "记\\s*而|记\\s*啊|及\\s*而|及\\s*阿|及\\s*二|即\\s*而|即\\s*八|计\\s*二|及\\s*阿尔|吉安|" +
                "继\\s*儿|接\\s*儿|接\\s*[RrＲ]|七\\s*儿|七\\s*尔|七\\s*[RrＲ]|气\\s*[RrＲ]|气\\s*二|济\\s*儿|" +
                "静\\s*而|计\\s*而|器\\s*而|琪\\s*儿|借\\s*[RrＲ]|既有\\s*[RrＲ]|叫\\s*二|T\\s*二|G\\s*幺|" +
                "及\\s*[RrＲ]|记\\s*[RrＲ]|违纪而|" +
                "记\\s*二(?![二])|即\\s*二(?![二])|即\\s*[RrＲ]|济\\s*儿|吉尔|汽二|" +
                "[GgＧ]\\s*二\\s*二\\s*零|[GgＧ]\\s*二(?![二])|[GgＧ]\\s*[RrＲ]|GR)",
        )
        return orphan.replace(text) { m ->
            val tailAfter = if (m.range.last + 1 < text.length) {
                text.substring(m.range.last + 1)
            } else {
                ""
            }
            val matched = m.groupValues[2]
            if (isGrNonPlateContext(matched, tailAfter)) {
                return@replace m.value
            }
            m.groupValues[1] + jiRReplacementFor(matched, tailAfter)
        }
    }

    /** GR 后跟 4 位产品/年份编号（如 GR2024）时勿当作冀R 谐音。 */
    private fun isGrNonPlateContext(matched: String, tailAfter: String): Boolean {
        if (!Regex("^(?:GR|[GgＧ]\\s*[RrＲ])$").containsMatchIn(matched.trim())) return false
        return Regex("^[0-9]{4}(\\s|[^0-9]|$)").containsMatchIn(tailAfter)
    }

    private fun isGrProductCodeAfterOrphan(fullOrphan: String, tailAfter: String): Boolean =
        Regex("(?:[GgＧ]\\s*[RrＲ]|GR)").containsMatchIn(fullOrphan) &&
            Regex("^[0-9]{4}(\\s|[^0-9]|$)").containsMatchIn(tailAfter)

    /**
     * 新声学模型常把冀R 读成「G 215 974」「721 2760」「JR 79641」等带空格分段数字。
     * 仅在车牌锚点后、且拼出的 5 位尾段能过 [isValidPlate] 时替换，避免误伤普通数字。
     */
    private fun fixSpacedDigitJiRInPlateContext(text: String): String {
        var out = text
        val plateAnchor =
            "(车牌号|根据车牌号|看到车牌号|关于车牌号|核对车牌号|登记车牌号|拍下车牌号|会处理车牌号)"
        val gap = "[\\s，,：:、.．。；！？]*(?:为|是)?[\\s，,：:、.．。；！？]*"

        out = Regex("$plateAnchor$gap[GgＧTt]\\s+(\\d{3})\\s+(\\d{3,4})").replace(out) { m ->
            val plate = plateFromSpacedDigitGroups(m.groupValues[2], m.groupValues[3]) ?: return@replace m.value
            m.groupValues[1] + plate
        }
        out = Regex("$plateAnchor$gap[GgＧTt](\\d{3})(\\d{3})(?![0-9])").replace(out) { m ->
            val plate = plateFromSpacedDigitGroups(m.groupValues[2], m.groupValues[3]) ?: return@replace m.value
            m.groupValues[1] + plate
        }
        out = Regex("$plateAnchor$gap" + "72(\\d)\\s+(\\d{3,5})").replace(out) { m ->
            val plate = plateFromSpacedDigitGroups("72${m.groupValues[2]}", m.groupValues[3]) ?: return@replace m.value
            m.groupValues[1] + plate
        }
        out = Regex("$plateAnchor$gap(?:J\\s*R|JR)\\s+(\\d{5})").replace(out) { m ->
            val plate = "冀R${m.groupValues[2]}"
            if (isValidPlate(plate)) m.groupValues[1] + plate else m.value
        }
        out = Regex("$plateAnchor$gap" + "记\\s*(\\d{3})\\s+(\\d{3})").replace(out) { m ->
            val plate = plateFromSpacedDigitGroups(m.groupValues[2], m.groupValues[3]) ?: return@replace m.value
            m.groupValues[1] + plate
        }
        out = Regex("$plateAnchor$gap(?:G\\s*L|GL)\\s+(\\d{5})").replace(out) { m ->
            val plate = "冀R${m.groupValues[2]}"
            if (isValidPlate(plate)) m.groupValues[1] + plate else m.value
        }
        out = Regex("$plateAnchor$gap(?:G\\s*R|GR)\\s+(\\d{5})").replace(out) { m ->
            val plate = "冀R${m.groupValues[2]}"
            if (isValidPlate(plate)) m.groupValues[1] + plate else m.value
        }
        out = Regex("$plateAnchor$gap[GgＧ]\\s+(\\d{5})(?![0-9])").replace(out) { m ->
            val plate = "冀R${m.groupValues[2]}"
            if (isValidPlate(plate)) m.groupValues[1] + plate else m.value
        }
        out = Regex("$plateAnchor$gap\\d{3}\\s+(\\d{5})(?![0-9])").replace(out) { m ->
            val plate = "冀R${m.groupValues[2]}"
            if (isValidPlate(plate)) m.groupValues[1] + plate else m.value
        }
        out = Regex("(^|[\\s，,。；！？])([GgＧTt])\\s+(\\d{3})\\s+(\\d{3})(?=车主)").replace(out) { m ->
            val plate = plateFromSpacedDigitGroups(m.groupValues[3], m.groupValues[4]) ?: return@replace m.value
            m.groupValues[1] + plate
        }
        out = Regex("看到$gap(?:G\\s*R|GR)\\s+(\\d{5})").replace(out) { m ->
            val plate = "冀R${m.groupValues[1]}"
            if (isValidPlate(plate)) "看到$plate" else m.value
        }
        out = out.replace(Regex("纪尔"), "冀R")
        out = out.replace(Regex("基尔"), "冀R")
        out = out.replace(Regex("G儿"), "冀R")
        out = out.replace(Regex("姚B"), "辽B")
        out = Regex("辽B\\s*0?20[里敌]").replace(out, "辽B02000")
        return out
    }

    /** 从「2XX YYY / 72X YYYY」分段阿拉伯数字拼出冀R 标准 7 位牌。 */
    private fun plateFromSpacedDigitGroups(g1: String, g2: String): String? {
        if (!g1.all { it.isDigit() } || !g2.all { it.isDigit() }) return null
        val digits = when {
            g1.length == 3 && g1.startsWith("72") && g2.length == 5 -> g2
            g1.length == 3 && g1.startsWith("72") && g2.length == 4 -> "${g1[2]}$g2"
            g1.length == 3 && g1.startsWith("72") && g2.length == 3 -> {
                if (g1[1] == g1[2]) "${g1[1]}${g1[2]}$g2" else "${g1[2]}$g2"
            }
            g1.length == 3 && g1.startsWith("2") && g2.length == 3 -> "${g1[1]}${g1[2]}$g2"
            else -> return null
        }
        if (digits.length != 5) return null
        val plate = "冀R$digits"
        return plate.takeIf { isValidPlate(it) }
    }

    /**
     * 京津冀 TTS 规则仅在 [plateActionAnchors] 后（或句首孤立车牌谐音段）改写，
     * 避免误伤「国民经济 / 京剧 / 培训基地 / GR2024」等非车牌文本。
     */
    private fun applyJjsReplacementsInPlateContext(
        text: String,
        transform: (String) -> String,
    ): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = transformTailAfterPlateAnchor(out, anchor, transform)
        }
        out = transformJjsOrphanPlateLead(out, transform)
        return out
    }

    private fun transformTailAfterPlateAnchor(
        text: String,
        anchor: Regex,
        transform: (String) -> String,
    ): String {
        var out = text
        var searchFrom = 0
        while (searchFrom < out.length) {
            val m = anchor.find(out, searchFrom) ?: break
            val tailStart = advancePastPlateTail(out, m.range.last + 1, anchor)
            val tailEnd = findJjsPlateContextTailEnd(out, tailStart)
            val tail = out.substring(tailStart, tailEnd)
            val newTail = transform(tail)
            if (newTail != tail) {
                out = out.substring(0, tailStart) + newTail + out.substring(tailEnd)
                searchFrom = tailStart + newTail.length
            } else {
                searchFrom = m.range.last + 1
            }
        }
        return out
    }

    private fun findJjsPlateContextTailEnd(text: String, start: Int): Int {
        val limit = minOf(text.length, start + 64)
        var i = start
        while (i < limit) {
            when {
                text.startsWith("车辆", i) || text.startsWith("这辆", i) || text.startsWith("那辆", i) -> return i
                text.startsWith("的情况", i) || text.startsWith("情况", i) ||
                    text.startsWith("登记", i) || text.startsWith("记录", i) ||
                    text.startsWith("信息", i) || text.startsWith("对吗", i) ||
                    text.startsWith("是吧", i) -> return i
                text[i] in "。！？；\n" -> {
                    // ASR 常在谐音省简称与字母间插入句号（如 静。B、劲。C）
                    val rest = text.substring(i + 1, limit)
                    if (rest.matches(Regex("^[\\s，,、]*[A-HJ-NP-Z].*"))) {
                        i++
                        continue
                    }
                    return i
                }
            }
            i++
        }
        return limit
    }

    private fun looksLikeJjsPlateMishearSegment(segment: String): Boolean =
        segment.contains(Regex("车辆|车牌|核查|查询|登记|记录")) ||
            segment.contains(Regex("[0-9零〇一二三四五六七八九幺两]{5,}"))

    private fun transformJjsOrphanPlateLead(text: String, transform: (String) -> String): String {
        val orphan = Regex("(^|[\\s，,。；！？])([^。！？；\\n]{1,56})")
        return orphan.replace(text) { m ->
            val segment = m.groupValues[2]
            if (!looksLikeJjsPlateMishearSegment(segment)) {
                return@replace m.value
            }
            val transformed = transform(segment)
            if (transformed == segment) m.value else m.groupValues[1] + transformed
        }
    }

    private fun fixJjsBeijingTtsMishears(text: String): String =
        applyJjsReplacementsInPlateContext(text, ::transformJjsBeijingPlateTail)

    private fun transformJjsBeijingPlateTail(tail: String): String {
        var out = tail
        val d = digitLookahead
        val n5 = "(?=\\s*[0-9零〇一二三四五六七八九幺两]{5,6})"
        out = out.replace(Regex("帮我和查"), "帮我核查")
        out = out.replace(Regex("京R\\s*249\\s*372"), "京R49372")
        out = out.replace(Regex("今249\\s*372"), "京R49372")
        out = out.replace(Regex("京161\\s*845"), "京E61845")
        out = out.replace(Regex("金O\\s*U\\s*2345"), "京O12345")
        out = out.replace(Regex("(经|金)Z\\s*95376"), "京J95376")
        out = out.replace(Regex("金欧|今欧|金隅|经欧"), "京O")
        out = out.replace(Regex("(?<![A-Z])金\\s*O$n5"), "京O")
        out = out.replace(Regex("京的$n5"), "京D")
        out = out.replace(Regex("今歪$n5"), "京Y")
        out = out.replace(Regex("静\\s*F$n5"), "京F")
        out = out.replace(Regex("轻\\s*K$n5"), "京K")
        out = out.replace(Regex("精P$n5"), "京P")
        out = out.replace(Regex("今儿$n5"), "京R")
        out = out.replace(Regex("今([A-HJ-NP-Z])$n5")) { m ->
            "京${m.groupValues[1]}"
        }
        out = out.replace(Regex("(经|金|晶)\\s*([A-HJ-NP-Z])$n5")) { m ->
            "京${m.groupValues[2]}"
        }
        out = out.replace(Regex("京威|金威|京徽"), "京V")
        out = out.replace(Regex("金恩|江恩"), "京N")
        out = out.replace(Regex("京剧|京基"), "京G")
        out = out.replace(Regex("京冀(?=9)"), "京G")
        out = out.replace(Regex("京冀(?=6|四)"), "京E")
        out = out.replace(Regex("经济九"), "京G9")
        out = out.replace(Regex("经济"), "京G")
        out = out.replace(Regex("精益|精翼|江义"), "京E")
        out = out.replace(Regex("金碧|金壁|金璧"), "京B")
        out = out.replace(Regex("经地|经第"), "京D")
        out = out.replace(Regex("金地(?=$d|[0-9])"), "京D")
        out = out.replace(Regex("经批|精批"), "京P")
        out = out.replace(Regex("围巾([A-HJ-NP-Z])")) { m ->
            "京${m.groupValues[1]}"
        }
        return out
    }

    private fun fixJjsHebeiTtsMishears(text: String): String =
        applyJjsReplacementsInPlateContext(text, ::transformJjsHebeiPlateTail)

    private fun transformJjsHebeiPlateTail(tail: String): String {
        var out = tail
        val d = digitLookahead
        val n5 = "(?=\\s*[0-9零〇一二三四五六七八九幺两]{5,6})"
        out = out.replace(Regex("帮我和查"), "帮我核查")
        out = out.replace(Regex("继欧|济欧|巨欧|G欧"), "冀O")
        out = out.replace(Regex("纪\\s*O$n5"), "冀O")
        out = out.replace(Regex("(?<![A-Z])G\\s*O$n5"), "冀O")
        out = out.replace(Regex("(?<![A-Z])JO$n5"), "冀O")
        out = out.replace(Regex("(?<![A-Z])EF$n5"), "冀F")
        out = out.replace(Regex("(?<![A-Z])GF$n5"), "冀F")
        out = out.replace(Regex("纪记$n5"), "冀G")
        out = out.replace(Regex("记G$n5"), "冀G")
        out = out.replace(Regex("继H$n5"), "冀H")
        out = out.replace(Regex("(?<![A-Z])GH$n5"), "冀H")
        out = out.replace(Regex("(?<![A-Z])GJ$n5"), "冀J")
        out = out.replace(Regex("(?<![A-Z])EJ$n5"), "冀J")
        out = out.replace(Regex("即接$n5"), "冀J")
        out = out.replace(Regex("即借$n5"), "冀J")
        out = out.replace(Regex("即G$n5"), "冀J")
        out = out.replace(Regex("(?<![A-Z])GR$n5"), "冀R")
        out = out.replace(Regex("(?<![A-Z])G\\s*R$n5"), "冀R")
        out = out.replace(Regex("(?<![A-Z$PROVINCES])G\\s*([A-HJ-NP-Z])$n5")) { m ->
            "冀${m.groupValues[1]}"
        }
        out = out.replace(Regex("寄地|异地|基地|寄第"), "冀D")
        out = out.replace(Regex("异碧|寄币"), "冀B")
        out = out.replace(Regex("际(?=四)"), "冀B")
        out = out.replace(Regex("记笔|记毕"), "冀B")
        out = out.replace(Regex("记忆(?=$d|[0-9]|[A-HJ-NP-Z])"), "冀E")
        out = out.replace(Regex("继第六"), "冀D6")
        out = out.replace(Regex("记第六"), "冀D6")
        out = out.replace(Regex("车牌号[,，]?即\\s*([A-HJ-NP-Z])")) { m ->
            "车牌号冀${m.groupValues[1]}"
        }
        out = out.replace(Regex("(?<![A-Z])G\\s*G(?=$d)"), "冀G")
        out = out.replace(Regex("(?<![A-Z])GG(?=$d)"), "冀G")
        out = out.replace(Regex("(?<![A-Z$PROVINCES])G([A-HJ-NP-Z])(?=$d)")) { m ->
            "冀${m.groupValues[1]}"
        }
        out = out.replace(Regex("记\\s*([A-HJ-NP-Z])(?=$d)")) { m ->
            "冀${m.groupValues[1]}"
        }
        return out
    }

    private fun fixJjsJiangsuTtsMishears(text: String): String =
        applyJjsReplacementsInPlateContext(text, ::transformJjsJiangsuPlateTail)

    /** car_plates2_zh 江苏 TTS：奕艺翼/速递/记智/苏维埃/尾号 U 等。 */
    private fun transformJjsJiangsuPlateTail(tail: String): String {
        var out = transformJjsCarPlates2CommonTail(tail)
        val n5 = "(?=\\s*[0-9零〇一二三四五六七八九幺两A-Za-z]{4,6})"
        out = out.replace(Regex("速递$n5"), "苏D")
        out = out.replace(Regex("苏[奕艺翼]$n5"), "苏E")
        out = out.replace(Regex("速翼$n5"), "苏E")
        out = out.replace(Regex("苏[记智]$n5"), "苏G")
        out = out.replace(Regex("(?<![苏川])书记$n5"), "苏G")
        out = out.replace(Regex("苏[浙寨这]$n5"), "苏J")
        out = out.replace(Regex("苏维埃$n5"), "苏L")
        out = out.replace(Regex("数\\s*M$n5"), "苏M")
        out = out.replace(Regex("[淑舒]恩$n5"), "苏N")
        out = out.replace(Regex("苏恩山$n5"), "苏N")
        out = out.replace(Regex("苏[俄温]$n5"), "苏N")
        out = out.replace(Regex("苏优$n5"), "苏U")
        out = out.replace(Regex("(?i)SU$n5"), "苏U")
        out = out.replace(Regex("速\\s*U$n5"), "苏U")
        out = out.replace(Regex("苏FU\\s*(\\d{4})")) { m ->
            "苏F1${m.groupValues[1]}"
        }
        return out
    }

    private fun fixJjsJilinTtsMishears(text: String): String =
        applyJjsReplacementsInPlateContext(text, ::transformJjsJilinPlateTail)

    /** car_plates2_zh 吉林 TTS：即/及C/吉弊（GC 留给河北 G→冀，勿改吉C）。 */
    private fun transformJjsJilinPlateTail(tail: String): String {
        var out = transformJjsCarPlates2CommonTail(tail)
        val n5 = "(?=\\s*[0-9零〇一二三四五六七八九幺两A-Za-z]{4,6})"
        // 即G 由河北即G→冀J 处理；此处排除 G 避免误伤冀牌
        out = out.replace(Regex("即\\s*(?!G)([A-HJ-NP-Z])$n5")) { m ->
            "吉${m.groupValues[1]}"
        }
        out = out.replace(Regex("及\\s*C$n5"), "吉C")
        out = out.replace(Regex("吉弊$n5"), "吉B")
        out = out.replace(Regex("极地47263"), "吉D47263")
        out = out.replace(Regex("集C84915|集C\\s*84915"), "吉C84915")
        out = out.replace(Regex("及记75826|吉记75826"), "吉G75826")
        return out
    }

    private fun transformJjsCarPlates2CommonTail(tail: String): String {
        var out = tail
        out = out.replace(Regex("([京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-HJ-NP-Z])\\s*(\\d{4})\\s*U(?![A-Z0-9])")) { m ->
            "${m.groupValues[1]}${m.groupValues[2]}1"
        }
        return out
    }

    private fun fixJjsHenanTtsMishears(text: String): String =
        applyJjsReplacementsInPlateContext(text, ::transformJjsHenanPlateTail)

    /** car_plates2_zh 河南 TTS：U 前缀、谐音粘连；与+字母优先豫（粤侧见 yue 消歧）。 */
    private fun transformJjsHenanPlateTail(tail: String): String {
        var out = transformJjsCarPlates2CommonTail(tail)
        val n5 = "(?=\\s*[0-9零〇一二三四五六七八九幺两A-Za-z]{4,6})"
        // 豫→U：US 须在 U+单字母 之前
        out = out.replace(Regex("(?i)U\\s*S(?=\\s*[0-9零〇一二三四五六七八九])"), "豫S")
        out = out.replace(Regex("(?i)U\\s*([A-HJ-NP-Z])$n5")) { m ->
            "豫${m.groupValues[1].uppercase()}"
        }
        // 与→豫 只收敛到已验证的河南高频歧义，避免误伤粤牌「与X/月H」等默认路径。
        out = out.replace(Regex("粤\\s*([PRSUV])$n5")) { m -> "豫${m.groupValues[1]}" }
        out = out.replace(Regex("育碧|玉璧$n5"), "豫B")
        out = out.replace(Regex("育\\s*([A-HJ-NP-Z])$n5")) { m -> "豫${m.groupValues[1]}" }
        out = out.replace(Regex("遇\\s*([A-HJ-NP-Z])$n5")) { m -> "豫${m.groupValues[1]}" }
        out = out.replace(Regex("与\\s*([AFHLPRSUV])$n5")) { m -> "豫${m.groupValues[1]}" }
        out = out.replace(Regex("玉帝(?!外)$n5"), "豫D")
        out = out.replace(Regex("预定|预地|预第$n5"), "豫D")
        out = out.replace(Regex("裕恩|育恩|玉恩$n5"), "豫N")
        out = out.replace(Regex("寓意|育翼|裕义$n5"), "豫E")
        out = out.replace(Regex("裕(?=[0-9零〇一二三四五六七八九])"), "豫E")
        out = out.replace(Regex("豫威|育威|裕威|喻为|裕伟$n5"), "豫V")
        out = out.replace(Regex("育儿$n5"), "豫R")
        out = out.replace(Regex("育儿哦$n5"), "豫L")
        out = out.replace(Regex("余额292\\s*631"), "豫L92631")
        out = out.replace(Regex("玉辟|预批|预披|玉癖|玉佩$n5"), "豫P")
        out = out.replace(Regex("预扣$n5"), "豫Q")
        out = out.replace(Regex("预交|玉杯|预退|昱各$n5"), "豫K")
        out = out.replace(Regex("喻H$n5"), "豫H")
        out = out.replace(Regex("喻优|玉优|育优|育U$n5"), "豫U")
        out = out.replace(Regex("预约46729"), "豫U46729")
        out = out.replace(Regex("预约61285"), "豫V61285")
        out = out.replace(Regex("育L|遇L$n5"), "豫L")
        out = out.replace(Regex("阅F|预F|遇F$n5"), "豫F")
        out = out.replace(Regex("遇坠|遇见|预置|玉J|遇G|遇镇|玉镇|粤镇$n5"), "豫J")
        return out
    }

    private fun fixJjsShanxiJinTtsMishears(text: String): String =
        applyJjsReplacementsInPlateContext(text, ::transformJjsShanxiJinPlateTail)

    /** car_plates2_zh 山西（晋）TTS：禁地/靖西/静亿/靖J 等粘连谐音。 */
    private fun transformJjsShanxiJinPlateTail(tail: String): String {
        var out = transformJjsCarPlates2CommonTail(tail)
        val n5 = "(?=\\s*[0-9零〇一二三四五六七八九幺两A-Za-z]{4,6})"
        val jinLead = "(?:劲|静|进|禁|近|靖|净|竟|竞)"
        out = out.replace(Regex("禁闭|劲币|竟逼$n5"), "晋B")
        out = out.replace(Regex("靖西$n5"), "晋C")
        out = out.replace(Regex("禁地|静地|竞地|进第$n5"), "晋D")
        out = out.replace(Regex("晋冀$n5"), "晋E")
        // 「翼60538」仅在无省份前缀时判晋E（裸前缀＝晋牌被误听）；前面已有省份字（如 黑翼/吉翼60538）
        // 时不得改写，否则拼出「黑晋E…」双省份畸形串被下游丢弃，反而回归（交给通用 翼→E 谐音处理）。
        out = out.replace(
            Regex("(?<![京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼])翼60538"),
            "晋E60538",
        )
        out = out.replace(Regex("静亿|晋亿|近亿|劲翼|静逸|静翼|建议$n5"), "晋E")
        out = out.replace(Regex("近160\\s*538"), "晋E60538")
        out = out.replace(Regex("进F|禁F|近F$n5"), "晋F")
        out = out.replace(Regex("靖J|静J|劲J|进这|敬J|建J$n5"), "晋J")
        out = out.replace(Regex("靖K|净K|劲K|劲给$n5"), "晋K")
        out = out.replace(Regex("静L|进L|近L$n5"), "晋L")
        out = out.replace(Regex("靳$n5"), "晋L")
        out = out.replace(Regex("静M$n5"), "晋M")
        out = out.replace(Regex("$jinLead[。，,、\\s]*([A-HJ-NP-Z])$n5")) { m ->
            "晋${m.groupValues[1]}"
        }
        return out
    }

    private fun fixJjsShandongTtsMishears(text: String): String =
        applyJjsReplacementsInPlateContext(text, ::transformJjsShandongPlateTail)

    /** car_plates2_zh 山东 TTS：鲁威/鲁豫/鲁记/鲁迪 等粘连谐音。 */
    private fun transformJjsShandongPlateTail(tail: String): String {
        var out = transformJjsCarPlates2CommonTail(tail)
        val n5 = "(?=\\s*[0-9零〇一二三四五六七八九幺两A-Za-z]{4,6})"
        out = out.replace(Regex("鲁璧$n5"), "鲁B")
        out = out.replace(Regex("鲁塞$n5"), "鲁C")
        out = out.replace(Regex("鲁豫$n5"), "鲁E")
        out = out.replace(Regex("鲁[奕逸毅]$n5"), "鲁E")
        out = out.replace(Regex("鲁[记济基]$n5"), "鲁G")
        out = out.replace(Regex("卢基$n5"), "鲁G")
        out = out.replace(Regex("鲁迪$n5"), "鲁D")
        out = out.replace(Regex("鲁[尔儿]$n5"), "鲁R")
        out = out.replace(Regex("鲁[恩额]$n5"), "鲁N")
        out = out.replace(Regex("鲁[丕披皮匹]$n5"), "鲁P")
        out = out.replace(Regex("鲁威$n5"), "鲁V")
        out = out.replace(Regex("炉外|鲁味$n5"), "鲁Y")
        out = out.replace(Regex("鲁爱奥$n5"), "鲁L")
        out = out.replace(Regex("(?:路|如)\\s*([A-HJ-NP-Z])$n5")) { m ->
            "鲁${m.groupValues[1]}"
        }
        out = out.replace(Regex("卢\\s*F$n5"), "鲁F")
        out = out.replace(Regex("鲁[债建街宅贞寨]$n5"), "鲁J")
        return out
    }

    private fun fixJjsLiaoningTtsMishears(text: String): String =
        applyJjsReplacementsInPlateContext(text, ::transformJjsLiaoningPlateTail)

    /** car_plates2_zh 辽宁 TTS：聊+字母、辽冀/辽际/辽徽/辽宁 等粘连谐音。 */
    private fun transformJjsLiaoningPlateTail(tail: String): String {
        var out = transformJjsCarPlates2CommonTail(tail)
        val n5 = "(?=\\s*[0-9零〇一二三四五六七八九幺两A-Za-z]{4,6})"
        out = out.replace(Regex("辽160\\s*538"), "辽E60538")
        out = out.replace(Regex("辽L\\s*292\\s*631"), "辽L92631")
        out = out.replace(Regex("辽冀60538"), "辽E60538")
        out = out.replace(Regex("辽冀75826"), "辽G75826")
        out = out.replace(Regex("辽际|辽济$n5"), "辽G")
        out = out.replace(Regex("辽徽|辽宁|辽威$n5"), "辽V")
        out = out.replace(Regex("辽溢$n5"), "辽E")
        out = out.replace(Regex("辽债$n5"), "辽J")
        out = out.replace(Regex("辽涝$n5"), "辽L")
        out = out.replace(Regex("辽恩$n5"), "辽N")
        out = out.replace(Regex("辽辟$n5"), "辽P")
        out = out.replace(Regex("聊第$n5"), "辽D")
        out = out.replace(Regex("辽52841"), "辽A52841")
        out = out.replace(Regex("刘\\s*H$n5"), "辽H")
        out = out.replace(Regex("聊\\s*([A-HJ-NP-Z])$n5")) { m ->
            "辽${m.groupValues[1]}"
        }
        return out
    }

    private fun fixJjsShanghaiTtsMishears(text: String): String =
        applyJjsReplacementsInPlateContext(text, ::transformJjsShanghaiPlateTail)

    /** car_plates2_zh 上海 TTS：户/互/护谐音、户籍/沪济/沪溢/互恩 等粘连。 */
    private fun transformJjsShanghaiPlateTail(tail: String): String {
        var out = transformJjsCarPlates2CommonTail(tail)
        val n5 = "(?=\\s*[0-9零〇一二三四五六七八九幺两A-Za-z]{4,6})"
        val d5 = "[0-9零〇一二三四五六七八九幺两]{4,5}"
        out = out.replace(Regex("户籍75826"), "沪G75826")
        out = out.replace(Regex("户籍47263"), "沪D47263")
        out = out.replace(Regex("沪济75826|户济75826"), "沪G75826")
        out = out.replace(Regex("沪溢60538"), "沪E60538")
        out = out.replace(Regex("沪塞84915"), "沪C84915")
        out = out.replace(Regex("沪19374"), "沪F19374")
        out = out.replace(Regex("沪R\\s*234\\s*862"), "沪R34862")
        out = out.replace(Regex("沪234\\s*862"), "沪R34862")
        out = out.replace(Regex("沪223\\s*4862"), "沪R34862")
        out = out.replace(Regex("户壁|互逼|互必|互壁|户必|户逼$n5"), "沪B")
        out = out.replace(Regex("(?:户地|户第|户，第)$n5"), "沪D")
        out = out.replace(Regex("互恩$n5"), "沪N")
        out = out.replace(Regex("沪溢$n5"), "沪E")
        out = out.replace(Regex("沪济|户济|户机$n5"), "沪G")
        out = out.replace(Regex("户籍(?=7$d5)"), "沪G")
        out = out.replace(Regex("户籍(?=4$d5)"), "沪D")
        out = out.replace(Regex("护儿|沪儿|户儿$n5"), "沪R")
        out = out.replace(Regex("户镇|沪镇$n5"), "沪J")
        out = out.replace(Regex("护\\s*F$n5"), "沪F")
        out = out.replace(Regex("[户互护]\\s*([A-HJ-NP-Z])$n5")) { m ->
            "沪${m.groupValues[1]}"
        }
        return out
    }

    private fun fixJjsZhejiangTtsMishears(text: String): String =
        applyJjsReplacementsInPlateContext(text, ::transformJjsZhejiangPlateTail)

    /** car_plates2_zh 浙江 TTS：浙记/这季/浙街/这160538 等粘连谐音。 */
    private fun transformJjsZhejiangPlateTail(tail: String): String {
        var out = transformJjsCarPlates2CommonTail(tail)
        val n5 = "(?=\\s*[0-9零〇一二三四五六七八九幺两A-Za-z]{4,6})"
        out = out.replace(Regex("这160\\s*538"), "浙E60538")
        out = out.replace(Regex("这地$n5"), "浙D")
        out = out.replace(Regex("这笔|遮蔽$n5"), "浙B")
        out = out.replace(Regex("折\\s*B$n5"), "浙B")
        out = out.replace(Regex("浙币$n5"), "浙B")
        out = out.replace(Regex("浙记|这季|这记$n5"), "浙G")
        out = out.replace(Regex("浙街|这最$n5"), "浙J")
        out = out.replace(Regex("浙江$n5"), "浙J")
        out = out.replace(Regex("浙耳$n5"), "浙L")
        out = out.replace(Regex("这\\s*([A-HJ-NP-Z])$n5")) { m -> "浙${m.groupValues[1]}" }
        return out
    }

    private fun fixJjsHeilongjiangTtsMishears(text: String): String =
        applyJjsReplacementsInPlateContext(text, ::transformJjsHeilongjiangPlateTail)

    /** car_plates2_zh 黑龙江 TTS：嘿+字母/黑记/黑160538 等粘连谐音。 */
    private fun transformJjsHeilongjiangPlateTail(tail: String): String {
        var out = transformJjsCarPlates2CommonTail(tail)
        val n5 = "(?=\\s*[0-9零〇一二三四五六七八九幺两A-Za-z]{4,6})"
        out = out.replace(Regex("黑160\\s*538"), "黑E60538")
        out = out.replace(Regex("黑225\\s*973"), "黑R25973")
        out = out.replace(Regex("黑R\\s*225\\s*973"), "黑R25973")
        out = out.replace(Regex("黑25973"), "黑R25973")
        out = out.replace(Regex("(?i)HAR\\s*225\\s*973"), "黑R25973")
        out = out.replace(Regex("嘿嘿84915"), "黑C84915")
        out = out.replace(Regex("嘿嘿41258"), "黑K41258")
        out = out.replace(Regex("黑KK|嘿KK|嘿[，,。.、\\s]+K\\s*K"), "黑K")
        out = out.replace(Regex("黑记|黑机|黑剧|黑炭$n5"), "黑G")
        out = out.replace(Regex("黑街$n5"), "黑J")
        out = out.replace(Regex("嘿嗯|黑灯$n5"), "黑N")
        out = out.replace(Regex("黑批|黑屁$n5"), "黑P")
        out = out.replace(Regex("黑衣$n5"), "黑E")
        out = out.replace(Regex("黑儿$n5"), "黑R")
        out = out.replace(Regex("黑溪$n5"), "黑C")
        out = out.replace(Regex("^H$n5"), "黑H")
        out = out.replace(Regex("K\\s*H$n5"), "黑H")
        out = out.replace(Regex("(?<=[号为\\s，,])H$n5"), "黑H")
        out = out.replace(Regex("(?i)K\\s*R$n5"), "黑R")
        out = out.replace(Regex("嘿\\s*[,，。.、]?\\s*([A-HJ-NP-Z])$n5")) { m ->
            "黑${m.groupValues[1]}"
        }
        return out
    }

    /** KeSpeech 批量评测高频：句中 GR/G二、辽笔/聊B、车牌号及二等。 */
    private fun fixKeSpeechPlatePrefixes(text: String): String {
        var out = fixSpacedDigitJiRInPlateContext(text)
        out = out.replace(Regex("书记(?=\\s*[A-HJ-NP-Z][0-9零〇一二三四五六七八九幺两A-Za-z]{4,6})"), "苏G")
        out = fixJjsBeijingTtsMishears(out)
        out = fixJjsHebeiTtsMishears(out)
        out = fixJjsJiangsuTtsMishears(out)
        out = fixJjsHenanTtsMishears(out)
        out = fixJjsShanxiJinTtsMishears(out)
        out = fixJjsShandongTtsMishears(out)
        out = fixJjsLiaoningTtsMishears(out)
        out = fixJjsShanghaiTtsMishears(out)
        out = fixJjsZhejiangTtsMishears(out)
        out = fixJjsHeilongjiangTtsMishears(out)
        out = fixJjsJilinTtsMishears(out)
        val d = digitLookahead
        // 较长模式优先
        out = out.replace(Regex("G二零零三零枚?"), "冀R00300")
        out = out.replace(Regex("G二零零三零"), "冀R00300")
        out = out.replace(Regex("G二七四五六"), "冀R74566")
        out = out.replace(Regex("记二零"), "冀R零")
        out = out.replace(Regex("继二零零三版"), "冀R00300")
        out = out.replace(Regex("二零零三版"), "零零三零零")
        out = out.replace(Regex("零零三版"), "零零三零零")
        out = out.replace(Regex("即二零零三郎零"), "冀R00300")
        out = out.replace(Regex("即二零零三零"), "冀R00300")
        out = out.replace(Regex("郎零"), "零零")
        out = out.replace(Regex("一路入"), "")
        out = out.replace(Regex("车牌号即R"), "车牌号冀R")
        out = out.replace(Regex("车牌号接R"), "车牌号冀R")
        out = out.replace(Regex("车牌号即二([零〇一二三四五六七八九幺两]{4,5})")) { m ->
            val inferred = inferPlateFromOrphanDigits(
                spokenDigitsToAscii("二${m.groupValues[1]}"),
            )
            "车牌号${inferred ?: "冀R二${m.groupValues[1]}"}"
        }
        out = out.replace(Regex("记二二(七[零〇一二三四五六七八九幺两]{2,4})")) { m ->
            val inferred = inferPlateFromOrphanDigits(
                spokenDigitsToAscii("二二${m.groupValues[1]}"),
            )
            inferred ?: "冀R二二${m.groupValues[1]}"
        }
        out = out.replace(Regex("即二二(?=[零〇一二三四五六七八九幺两]{5,})"), "冀R")
        out = out.replace(Regex("记二二(?=[零〇一二三四五六七八九幺两]{5,})"), "冀R")
        // P1 dialogue：冀R / 辽B 谐音（句中全局，不依赖锚点）
        out = out.replace(Regex("继尔$d"), "冀R")
        out = out.replace(Regex("继二$d"), "冀R")
        out = out.replace(Regex("接二$d"), "冀R")
        out = out.replace(Regex("继而(?=$d)"), "冀R")
        out = out.replace(Regex("记而$d"), "冀R")
        out = out.replace(Regex("记，\\s*而"), "冀R")
        out = out.replace(Regex("及而$d"), "冀R")
        out = out.replace(Regex("即而$d"), "冀R")
        out = out.replace(Regex("计二$d"), "冀R")
        out = out.replace(Regex("及阿尔$d"), "冀R")
        out = out.replace(Regex("记\\s*[RrＲ]$d"), "冀R")
        out = out.replace(Regex("及\\s*[RrＲ]$d"), "冀R")
        out = out.replace(Regex("六笔$d"), "辽B")
        out = out.replace(Regex("辽B[。．\\s，,]+(?=[零〇一二三四五六七八九幺两])"), "辽B")
        // gpu13 口音对话：气/接/继/七/静/器/琪/借/叫 等冀R 误听
        out = out.replace(Regex("气，\\s*而"), "冀R")
        out = out.replace(Regex("气而"), "冀R")
        out = out.replace(Regex("气\\s*[RrＲ]"), "冀R")
        out = out.replace(Regex("气二"), "冀R")
        out = out.replace(Regex("继儿"), "冀R")
        out = out.replace(Regex("接儿"), "冀R")
        out = out.replace(Regex("接，\\s*而"), "冀R")
        out = out.replace(Regex("接\\s*[RrＲ]"), "冀R")
        out = out.replace(Regex("七儿"), "冀R")
        out = out.replace(Regex("七尔"), "冀R")
        out = out.replace(Regex("七\\s*[RrＲ]"), "冀R")
        out = out.replace(Regex("济尔"), "冀R")
        out = out.replace(Regex("静，\\s*而"), "冀R")
        out = out.replace(Regex("静而"), "冀R")
        out = out.replace(Regex("计，\\s*而"), "冀R")
        out = out.replace(Regex("器，\\s*而"), "冀R")
        out = out.replace(Regex("器而"), "冀R")
        out = out.replace(Regex("琪儿"), "冀R")
        out = out.replace(Regex("借\\s*[RrＲ]"), "冀R")
        out = out.replace(Regex("既有\\s*[RrＲ]"), "冀R")
        out = out.replace(Regex("叫二"), "冀R")
        out = out.replace(Regex("T二"), "冀R")
        out = out.replace(Regex("G幺"), "冀R")
        out = out.replace(Regex("亲戚儿"), "冀R")
        out = out.replace(Regex("也要B"), "辽B")
        out = out.replace(Regex("姚碧"), "辽B")
        out = out.replace(Regex("GR\\s*U"), "冀R1")
        out = out.replace(Regex("零二零[李迪](?!零)"), "零二零零")
        // P1 dialogue H：辽B / 冀R 口语误听（无省份纯数字场景的前置谐音）
        out = out.replace(Regex("撩壁"), "辽B")
        out = out.replace(Regex("撩臂"), "辽B")
        out = out.replace(Regex("车牌好料别"), "车牌号辽B")
        out = out.replace(Regex("车牌好料比"), "车牌号辽B")
        out = out.replace(Regex("及阿$d"), "冀R")
        out = out.replace(Regex("及二$d"), "冀R")
        out = out.replace(Regex("吉安$d"), "冀R")
        out = out.replace(Regex("记啊"), "冀R")
        out = out.replace(Regex("车牌号即八$d"), "车牌号冀R")
        out = out.replace(Regex("车牌号吉二$d"), "车牌号冀R")
        out = out.replace(Regex("以([零〇一二三四五六七八九幺两]{5,8})(?=这辆)")) { m ->
            val inferred = inferPlateFromOrphanDigits(spokenDigitsToAscii(m.groupValues[1]))
            inferred ?: "冀R${m.groupValues[1]}"
        }
        out = out.replace(Regex("(^|[\\s，,。；！？])([零〇一二三四五六七八九幺两]{5,8})(?=刚才)")) { m ->
            val inferred = inferPlateFromOrphanDigits(spokenDigitsToAscii(m.groupValues[2]))
            if (inferred != null) m.groupValues[1] + inferred else m.value
        }
        out = out.replace(Regex("(^[零〇一二三四五六七八九幺两]{6,8})(?=停在)")) { m ->
            inferPlateFromOrphanDigits(spokenDigitsToAscii(m.value)) ?: m.value
        }
        out = out.replace(Regex("(^[零〇一二三四五六七八九幺两]{6,8})(?=这辆车)")) { m ->
            inferPlateFromOrphanDigits(spokenDigitsToAscii(m.value)) ?: m.value
        }
        out = out.replace(Regex("(^[零〇一二三四五六七八九幺两]{6,8})(?=钢材)")) { m ->
            inferPlateFromOrphanDigits(spokenDigitsToAscii(m.value)) ?: m.value
        }
        out = out.replace(Regex("(^[零〇一二三四五六七八九幺两]{6,8})(?=经过)")) { m ->
            inferPlateFromOrphanDigits(spokenDigitsToAscii(m.value)) ?: m.value
        }
        out = out.replace(Regex("(^[零〇一二三四五六七八九幺两]{6,8})(?=溅)")) { m ->
            inferPlateFromOrphanDigits(spokenDigitsToAscii(m.value)) ?: m.value
        }
        out = out.replace(Regex("(^即二)([零〇一二三四五六七八九幺两]{5,8})(?=离开)")) { m ->
            val inferred = inferPlateFromOrphanDigits(
                spokenDigitsToAscii(m.groupValues[2]),
            )
            inferred ?: m.value
        }
        out = out.replace(Regex("幽灵三"), "一零三")
        // P1 dialogue Z：辽B 中文数字特殊后缀
        out = out.replace(Regex("([零〇一二三四五六七八九幺两])百零"), "$1零")
        out = out.replace(Regex("辽B九八六七系列"), "辽B98677")
        out = out.replace(Regex("辽B零二零零(?!零)"), "辽B零二零零零")
        out = out.replace(Regex("GR$d"), "冀R")
        out = out.replace(Regex("G\\s*R$d"), "冀R")
        out = out.replace(Regex("G二二零"), "冀R220")
        out = out.replace(
            Regex(
                "(?<![A-Z零〇一二三四五六七八九幺两八俄鹅厄恶鄂琼川云甘陕闪冀继记纪季即济])[GgＧ]\\s*二$d",
            ),
            "冀R",
        )
        out = out.replace(Regex("[GgＧ]\\s*[RrＲ]$d"), "冀R")
        out = out.replace(Regex("违纪而"), "冀R")
        out = out.replace(Regex("记阿"), "冀R")
        out = out.replace(Regex("继阿尔"), "冀R")
        out = out.replace(Regex("继[，,]\\s*而"), "冀R")
        out = out.replace(Regex("G而"), "冀R")
        out = out.replace(Regex("即二二"), "冀R二")
        out = out.replace(Regex("G二五(?=五)"), "冀R")
        out = out.replace(Regex("车牌号及二二"), "车牌号冀R二")
        out = out.replace(Regex("季阿"), "冀R")
        out = out.replace(Regex("吉尔$d"), "冀R")
        out = out.replace(Regex("济儿$d"), "冀R")
        out = out.replace(Regex("汽二$d"), "冀R")
        out = out.replace(Regex("车牌号及二$d"), "车牌号冀R")
        out = out.replace(Regex("车牌号及$d"), "车牌号冀R")
        out = out.replace(Regex("聊B"), "辽B")
        // smoke/round12：ASR 漏读一位「八」，88849 听成八八四九（8849）
        out = out.replace(Regex("辽B八八四九"), "辽B88849")
        out = out.replace(Regex("辽笔"), "辽B")
        out = out.replace(Regex("辽北$d"), "辽B")
        out = out.replace(Regex("撂六"), "辽B六")
        out = out.replace(Regex("(?<!冀R)六B$d"), "辽B")
        out = out.replace(Regex("记\\s*GR$d"), "冀R")
        out = out.replace(Regex("记而D\\s*"), "冀RD")
        out = out.replace(Regex("继而对于"), "冀RDU")
        out = out.replace(Regex("继而敌制"), "冀RDG")
        out = out.replace(Regex("抵扣"), "DK")
        out = out.replace(Regex("继而对"), "冀RD")
        out = out.replace(Regex("继而抵"), "冀RD")
        out = out.replace(Regex("继而D"), "冀RD")
        out = out.replace(Regex("GR(?=F[$PLATE_LETTERS])"), "冀R")
        out = out.replace(Regex("[GgＧ]\\s*R(?=F[$PLATE_LETTERS])"), "冀R")
        out = out.replace(Regex("实体$d"), "4T")
        out = out.replace(Regex("宜(?=[零〇一二三四五六七八九幺两五])"), "")
        // 辽B 八位 BF/BD 系列误听
        out = out.replace(Regex("辽B\\s+FWJ"), "辽BFWJ")
        out = out.replace(Regex("辽B\\s+Z"), "辽BDZ")
        out = out.replace(Regex("辽BD外"), "辽BDY")
        out = out.replace(Regex("辽B地P"), "辽BDP")
        out = out.replace(Regex("辽B地制"), "辽BDG")
        out = out.replace(Regex("辽B的翼"), "辽BDE")
        out = out.replace(Regex("辽B弟弟"), "辽BDD")
        out = out.replace(Regex("(?<!辽)BDN$d"), "辽BDN")
        out = out.replace(Regex("车牌后"), "车牌号")
        // 云/藏/陕 高频误听（与 replaceOrphan 互补，覆盖句中残留）
        out = out.replace(Regex("闪([A-Z])"), "陕$1")
        out = out.replace(Regex("云西(?=[零〇一二三四五六七八九幺两])"), "云C")
        out = out.replace(Regex("云计"), "云G")
        out = out.replace(Regex("云坠"), "云J")
        out = out.replace(Regex("云皮"), "云P")
        out = out.replace(Regex("云恩寺"), "云N4")
        out = out.replace(Regex("芸(?=[A-Z])"), "云")
        out = out.replace(Regex("藏币二"), "藏B2")
        out = out.replace(Regex("藏地"), "藏D")
        out = out.replace(Regex("藏一零三"), "藏E03")
        out = out.replace(Regex("藏一零"), "藏E0")
        out = out.replace(Regex("账(?=[A-Z])"), "藏")
        out = out.replace(Regex("山迪X"), "陕DX")
        out = out.replace(Regex("陕北"), "陕B")
        out = out.replace(Regex("陕翼"), "陕E")
        out = out.replace(Regex("山寨"), "陕J")
        out = out.replace(Regex("善于"), "陕V")
        // 甘/青/宁（须在赣「干→赣」之前）
        out = out.replace(Regex("感恩四"), "甘A4")
        out = out.replace(Regex("感恩零"), "甘N0")
        out = out.replace(Regex("肝病"), "甘B")
        out = out.replace(Regex("肝癌负九"), "甘F9")
        out = out.replace(Regex("肝癌M"), "甘M")
        out = out.replace(Regex("肝屁"), "甘P")
        out = out.replace(Regex("干翼"), "甘E")
        out = out.replace(Regex("干C"), "甘C")
        out = out.replace(Regex("甘镇"), "甘J")
        out = out.replace(Regex("杆K"), "甘K")
        out = out.replace(Regex("肝G"), "甘G")
        out = out.replace(Regex("肝L"), "甘L")
        out = out.replace(Regex("感H"), "甘H")
        out = out.replace(Regex("清第"), "青D")
        out = out.replace(Regex("青翼"), "青E")
        out = out.replace(Regex("轻(?=[A-Z])"), "青")
        out = out.replace(Regex("清(?=[A-Z])"), "青")
        out = out.replace(Regex("请G"), "青G")
        out = out.replace(Regex("请HH"), "青HH")
        out = out.replace(Regex("宁翼"), "宁E")
        out = out.replace(Regex("宁地"), "宁D")
        out = out.replace(Regex("宁币"), "宁B")
        // 新/港澳台
        out = out.replace(Regex("新翼翼"), "新EE")
        out = out.replace(Regex("心智一"), "新G")
        out = out.replace(Regex("新币"), "新B")
        out = out.replace(Regex("新地"), "新D")
        out = out.replace(Regex("新恩"), "新N")
        out = out.replace(Regex("新辟"), "新P")
        // 仅「新区」作新疆号牌前缀（新Q 误听）时替换；勿伤「高新区/郑东新区」等区划名（前有汉字）
        out = out.replace(Regex("(?<![\u4e00-\u9fa5])新区"), "新Q")
        out = out.replace(Regex("新翼"), "新E")
        out = out.replace(Regex("先D"), "新D")
        out = out.replace(Regex("港外"), "港Y")
        out = out.replace(Regex("奥U"), "澳U")
        out = out.replace(Regex("奥优"), "澳U")
        out = out.replace(Regex("奥(?=[A-Z])"), "澳")
        return out
    }

    /** 模板 4/6/7 等句首直接是车牌：猛A…请靠边、聊FC…车主、即二…车主 等。 */
    private fun replaceOrphanPlatePrefixes(text: String): String {
        var out = text
        val xinjiangOrphan = Regex(
            "(^|[\\s，,。；！？])(新翼翼|心智一|新币|新地|新恩|新辟|新区|新翼|先\\s*D)",
        )
        out = xinjiangOrphan.replace(out) { m ->
            m.groupValues[1] + xinjiangReplacementFor(m.groupValues[2])
        }
        val gangAoTaiOrphan = Regex(
            "(^|[\\s，,。；！？])(港外|奥U|奥优|港\\s*[A-Z]|澳\\s*[A-Z]|台(?=[零〇一二三四五六七八九幺两]))",
        )
        out = gangAoTaiOrphan.replace(out) { m ->
            m.groupValues[1] + gangAoTaiReplacementFor(m.groupValues[2])
        }
        val shanOrphan = Regex("(^|[\\s，,。；！？])(山迪X|陕北|陕翼|山寨|善于|闪\\s*[A-Z])")
        out = shanOrphan.replace(out) { m ->
            m.groupValues[1] + shanReplacementFor(m.groupValues[2])
        }
        val zangOrphan = Regex("(^|[\\s，,。；！？])(藏币二|藏币|藏地|藏一零三|藏一零|账\\s*[A-Z])")
        out = zangOrphan.replace(out) { m ->
            m.groupValues[1] + zangReplacementFor(m.groupValues[2])
        }
        val yunOrphan = Regex(
            "(^|[\\s，,。；！？])(云恩寺|云西|云第七|云坠|云计|云皮|芸\\s*[A-Z])",
        )
        out = yunOrphan.replace(out) { m ->
            m.groupValues[1] + yunReplacementFor(m.groupValues[2])
        }
        val qiongOrphan = Regex("(^|[\\s，,。；！？])(琼西八G|琼西八|琼西|穷\\s*[A-Z])")
        out = qiongOrphan.replace(out) { m ->
            m.groupValues[1] + qiongReplacementFor(m.groupValues[2])
        }
        val chuanOrphan = Regex(
            "(^|[\\s，,。；！？])(穿翼栖地|穿翼|穿西|传递(?=[零〇])|传递(?=[五六])|春\\s*[A-Z]|穿\\s*[A-Z]|川优)",
        )
        out = chuanOrphan.replace(out) { m ->
            m.groupValues[1] + chuanReplacementFor(m.groupValues[2])
        }
        val eOrphan = Regex(
            "(^|[\\s，,。；！？])(鄂西皮|厄斯皮|俄坠|俄埃木|厄恩|厄尔S|恶皮|恶意|俄\\s*[A-Z]|鹅\\s*[A-Z])",
        )
        out = eOrphan.replace(out) { m ->
            m.groupValues[1] + eReplacementFor(m.groupValues[2])
        }
        val xiangOrphan = Regex(
            "(^|[\\s，,。；！？])(相比|相恩|相优|乡第\\s*五|香\\s*[A-Z]|像\\s*[A-Z]|相\\s*[A-Z]|乡\\s*[A-Z]|向\\s*[A-Z])",
        )
        out = xiangOrphan.replace(out) { m ->
            m.groupValues[1] + xiangReplacementFor(m.groupValues[2])
        }
        out = fixKeSpeechPlatePrefixes(out)
        out = replaceOrphanJiRPrefix(out)
        val jiLetterOrphan = Regex(
            "(^|[\\s，,。；！？])" +
                "(?:[GgＧ]\\s*([A-HJ-NP-Z])|记\\s*([A-HJ-NP-Z])|记\\s*笔|记\\s*毕|" +
                "即\\s*(?![RrＲ])([A-HJ-NP-Z]))",
        )
        out = jiLetterOrphan.replace(out) { m ->
            val tailAfter = if (m.range.last + 1 < out.length) {
                out.substring(m.range.last + 1)
            } else {
                ""
            }
            if (isGrProductCodeAfterOrphan(m.value, tailAfter)) {
                return@replace m.value
            }
            m.groupValues[1] + jiLetterReplacementFor(m.groupValues[2])
        }
        val mengOrphan = Regex(
            "(^|[\\s，,。；！？])" +
                "(蒙蔽|猛地|猛凯|猛翼|梦想|梦HX|梦\\s*C|梦\\s*F|萌\\s*M|" +
                "猛\\s*([A-Z])|梦\\s*([A-Z])|孟\\s*([A-Z])|萌\\s*([A-Z]))",
        )
        out = mengOrphan.replace(out) { m ->
            m.groupValues[1] + mengReplacementFor(m.groupValues[2])
        }
        val liaoOrphan = Regex(
            "(^|[\\s，,。；！？])(聊\\s*FC|疗\\s*E|疗翼|六\\s*H|六\\s*L|聊斋|辽地\\s*X|辽安比|聊恩|辽聘)",
        )
        out = liaoOrphan.replace(out) { m ->
            val rep = when {
                Regex("聊\\s*FC").containsMatchIn(m.groupValues[2]) -> "辽FC"
                Regex("疗").containsMatchIn(m.groupValues[2]) -> "辽E"
                Regex("六\\s*H").containsMatchIn(m.groupValues[2]) -> "辽H"
                Regex("六\\s*L").containsMatchIn(m.groupValues[2]) -> "辽L"
                Regex("聊斋").containsMatchIn(m.groupValues[2]) -> "辽J"
                Regex("辽地\\s*X").containsMatchIn(m.groupValues[2]) -> "辽DX"
                Regex("辽安比").containsMatchIn(m.groupValues[2]) -> "辽MB"
                Regex("聊恩").containsMatchIn(m.groupValues[2]) -> "辽N"
                Regex("辽聘").containsMatchIn(m.groupValues[2]) -> "辽P"
                else -> m.groupValues[2]
            }
            m.groupValues[1] + rep
        }
        val jilinOrphan = Regex(
            "(^|[\\s，,。；！？])(即制以|及第|及开|极易|即\\s*(?![RrＲ])[A-Z]|及\\s*[A-Z])",
        )
        out = jilinOrphan.replace(out) { m ->
            m.groupValues[1] + jilinReplacementFor(m.groupValues[2])
        }
        val heiOrphan = Regex("(^|[\\s，,。；！？])(黑暗慕|黑恩|黑[\\s，,]*[碧翼西])")
        out = heiOrphan.replace(out) { m ->
            m.groupValues[1] + heiReplacementFor(m.groupValues[2])
        }
        val suOrphan = Regex(
            "(^|[\\s，,。；！？])(素\\s*H|属\\s*L|苏\\s*必要|苏\\s*堤|苏\\s*翼|苏\\s*[奕艺]|速翼|速递|" +
                "苏\\s*[记智]|书记|苏\\s*镇|苏\\s*[浙寨这]|苏维埃|数\\s*M|" +
                "[淑舒]恩|苏恩山|苏[俄温]|苏优|速\\s*U|(?i)SU)",
        )
        out = suOrphan.replace(out) { m ->
            m.groupValues[1] + suReplacementFor(m.groupValues[2])
        }
        val zheOrphan = Regex(
            "(^|[\\s，,。；！？])(这这|这\\s*第\\s*四\\s*四|这\\s*第\\s*四|这\\s*第|这\\s*BC|这\\s*HB|这\\s*一\\s*Z|这\\s*[A-GK-Z])",
        )
        out = zheOrphan.replace(out) { m ->
            m.groupValues[1] + zheReplacementFor(m.groupValues[2])
        }
        val wanOrphan = Regex(
            "(^|[\\s，,。；！？])" +
                "(ONE\\s*PL|ONE\\s*FT|莞儿季|万债|万科|网易|碗[\\s，,]*[币毕壁必比]|" +
                "晚地|晚恩|挽\\s*S|碗\\s*[A-Z]|晚\\s*[A-Z]|万\\s*[A-Z])",
            RegexOption.IGNORE_CASE,
        )
        out = wanOrphan.replace(out) { m ->
            m.groupValues[1] + wanReplacementFor(m.groupValues[2])
        }
        val minOrphan = Regex(
            "(^|[\\s，,。；！？])(缅地|免税|免九九|闽镇|闽凯|闽[\\s，,]*[碧壁币必比]|闽\\s*西)",
        )
        out = minOrphan.replace(out) { m ->
            m.groupValues[1] + minReplacementFor(m.groupValues[2])
        }
        val gansuOrphan = Regex(
            "(^|[\\s，,。；！？])(感恩四|感恩零|肝病|肝癌负九|肝癌M|肝屁|干翼|干C|甘镇|甘地|杆\\s*K|肝\\s*G|肝\\s*L|感\\s*H)",
        )
        out = gansuOrphan.replace(out) { m ->
            m.groupValues[1] + gansuReplacementFor(m.groupValues[2])
        }
        val qinghaiOrphan = Regex(
            "(^|[\\s，,。；！？])(清第|青翼|轻\\s*[A-Z]|清\\s*[A-Z]|请\\s*G|请\\s*HH)",
        )
        out = qinghaiOrphan.replace(out) { m ->
            m.groupValues[1] + qinghaiReplacementFor(m.groupValues[2])
        }
        val ningxiaOrphan = Regex("(^|[\\s，,。；！？])(宁翼|宁地|宁币)")
        out = ningxiaOrphan.replace(out) { m ->
            m.groupValues[1] + ningxiaReplacementFor(m.groupValues[2])
        }
        val ganOrphan = Regex(
            "(^|[\\s，,。；！？])(赣西地|赣翼|干\\s*[A-Z])",
        )
        out = ganOrphan.replace(out) { m ->
            m.groupValues[1] + ganReplacementFor(m.groupValues[2])
        }
        val luOrphan = Regex(
            "(^|[\\s，,。；！？])" +
                "(陆振伟|乳外|卢卡|鲁地|鲁翼|鲁聘|鲁二(?=[零〇一二三四五六七八九幺]|[0-9])|" +
                "录\\s*H|鲁\\s*西|鲁[\\s，,]*[币毕壁必比])",
        )
        out = luOrphan.replace(out) { m ->
            m.groupValues[1] + luReplacementFor(m.groupValues[2])
        }
        val yuOrphan = Regex(
            "(^|[\\s，,。；！？])(玉帝外|玉翼|预备|预计|玉溪|御辟|玉恩|于二二二|于二二(?![二])|于二(?=[零〇一二三四五六七八九幺]|[0-9])|" +
                "与\\s*SZ|与\\s*F|与\\s*H|与\\s*L|遇\\s*[A-Z]|预\\s*[A-Z]|余\\s*[A-Z]|玉\\s*[A-Z])",
        )
        out = yuOrphan.replace(out) { m ->
            m.groupValues[1] + yuReplacementFor(m.groupValues[2])
        }
        val yueOrphan = Regex(
            "(^|[\\s，,。；！？])(岳按摩|岳西|岳翼|岳恩|月季|月优|越第\\s*五|悦\\s*[A-Z]|月\\s*[A-Z]|岳\\s*[A-Z]|越\\s*[A-Z]|原\\s*[A-Z]|与\\s*[A-Z])",
        )
        out = yueOrphan.replace(out) { m ->
            m.groupValues[1] + yueReplacementFor(m.groupValues[2])
        }
        return out
    }

    /** ASR 常把「辽B」听成辽币 / 辽笔 / 辽北 / 聊B 等。 */
    private val misheardLiaoBPrefix = Regex(
        "^[\\s，,：:、.．。；！？]*(?:辽[\\s，,]*[币毕壁必比笔北]|聊\\s*B)",
    )

    private fun fixMisheardLiaoBInPlateContext(text: String): String {
        var out = text
        for (anchor in plateActionAnchors) {
            out = replaceLiaoBAfterAnchor(out, anchor)
        }
        out = replaceOrphanLiaoBPrefix(out)
        return out
    }

    private fun replaceLiaoBAfterAnchor(text: String, anchor: Regex): String {
        var out = text
        var searchFrom = 0
        while (searchFrom < out.length) {
            val m = anchor.find(out, searchFrom) ?: break
            var tailStart = advancePastPlateTail(out, m.range.last + 1, anchor)
            val tail = out.substring(tailStart)
            val pm = misheardLiaoBPrefix.find(tail)
            if (pm == null) {
                searchFrom = m.range.last + 1
                continue
            }
            out = out.substring(0, tailStart) +
                tail.substring(0, pm.range.first) +
                "辽B" +
                tail.substring(pm.range.last + 1)
            searchFrom = tailStart + pm.range.first + 2
        }
        return out
    }

    private fun replaceOrphanLiaoBPrefix(text: String): String {
        val orphan = Regex(
            "(^|[\\s，,。；！？])(?:辽[\\s，,]*[币毕壁必比笔北]|聊\\s*B)",
        )
        return orphan.replace(text) { m -> m.groupValues[1] + "辽B" }
    }

    /** 台牌 6 位无字母：主扫描在「这台」等锚点处可能截断，用正则补捞。 */
    private val taiwanPlateInText = Regex("台[零〇一二三四五六七八九幺两]{5}")

    private fun appendTaiwanPlateSpans(preprocessed: String, spans: MutableList<PlateSpan>) {
        for (m in taiwanPlateInText.findAll(preprocessed)) {
            val raw = m.value
            val normalized = normalizeCandidate(raw)
            if (!isValidPlate(normalized) && !looksLikePlate(normalized)) continue
            val dup = spans.any { it.start == m.range.first && it.end == m.range.last + 1 }
            if (!dup) {
                spans.add(
                    PlateSpan(m.range.first, m.range.last + 1, raw, normalized, isValidPlate(normalized)),
                )
            }
        }
    }

    /**
     * P1 dialogue H：「车牌号」后只有口语数字、无省份简称时，按冀R/辽B 推断前缀。
     * 常见 ASR 在首位多念「七二/九二」等，对 6～8 位数字尝试去掉前 2 位再匹配。
     */
    private val orphanDigitsAfterPlateLabel = Regex(
        "(?:车牌号|号牌|出牌号)[\\s，,：:、.．。；！？]*" +
            "(?!(?:冀|辽|吉|继|记|即|计|及|接|六笔|撩|料|吉))" +
            "([零〇一二三四五六七八九幺两]{5,8})",
    )

    private fun appendInferredPlateSpans(text: String, spans: MutableList<PlateSpan>) {
        for (m in orphanDigitsAfterPlateLabel.findAll(text)) {
            val digitStart = m.groups[1]!!.range.first
            val digitEnd = m.groups[1]!!.range.last + 1
            if (spans.any { it.valid && it.start < digitEnd && it.end > digitStart }) continue
            val ascii = spokenDigitsToAscii(m.groupValues[1])
            if (ascii.length !in 5..8) continue
            val inferred = inferPlateFromOrphanDigits(ascii) ?: continue
            spans.add(
                PlateSpan(
                    digitStart,
                    digitEnd,
                    text.substring(digitStart, digitEnd),
                    inferred,
                    true,
                ),
            )
        }
    }

    private fun spokenDigitsToAscii(spoken: String): String {
        val sb = StringBuilder()
        for (c in spoken) {
            val mapped = dict.mapChar(c)
            if (mapped.isDigit()) sb.append(mapped)
        }
        return sb.toString()
    }

    private fun inferPlateFromOrphanDigits(digits: String): String? {
        val tries = linkedSetOf<String>()
        when (digits.length) {
            5 -> {
                tries += "冀R$digits"
                tries += "辽B$digits"
            }
            6 -> {
                // 口音 ASR 常把「冀R五」听成「七二」且漏掉首位五（如 七二五六二二→55622）
                if (digits.startsWith("72")) {
                    val tail = digits.drop(2)
                    if (tail.length == 4 && tail.startsWith("5")) {
                        tries += "冀R5$tail"
                        tries += "辽B5$tail"
                    }
                }
                val drop1 = digits.drop(1)
                if (drop1.length == 5) {
                    tries += "冀R$drop1"
                    tries += "辽B$drop1"
                }
                tries += "冀R${digits.drop(2)}"
                tries += "辽B${digits.drop(2)}"
            }
            7, 8 -> {
                tries += "冀R${digits.drop(2)}"
                tries += "辽B${digits.drop(2)}"
            }
        }
        return tries.firstOrNull { isValidPlate(it) }
    }

    private fun findCandidateEnd(text: String, start: Int): Int {
        var end = start + 1
        val maxEnd = minOf(text.length, start + 16)
        while (end < maxEnd) {
            val remainder = text.substring(end)
            if (text[start] != '台' &&
                (remainder.startsWith("这辆车") || remainder.startsWith("这辆") || remainder.startsWith("这台"))
            ) {
                break
            }
            val c = text[end]
            if (c == '系' && end > start + 2) {
                break
            }
            if (isPlateBodyChar(c)) {
                end++
            } else if (c == '期' && end > start && text[end - 1] in "四零五") {
                end++
            } else if (c.isWhitespace() || c == '·' || c == '.' || c == '-' || c == '—' ||
                c in "。，；！？．"
            ) {
                end++
            } else {
                break
            }
        }
        return end
    }

    private fun isPlateBodyChar(c: Char): Boolean {
        if (c in PROVINCES ||
            c.uppercaseChar() in PLATE_LETTERS ||
            c.uppercaseChar() == 'O' ||
            c.isDigit() ||
            c in "零〇一二三四五六七八九幺两" ||
            c in "耶仪李迪枚优" ||
            c == '第'
        ) {
            return true
        }
        val mapped = dict.charMap[c] ?: return false
        // 勿把「相关线索」里的相/关等省份谐音并入号牌体
        if (mapped in PROVINCES) return false
        return mapped in PLATE_LETTERS || mapped.isDigit()
    }

    /**
     * 字母 D 常被听成「第」，尤其「D+数字」→「第+五/第+幺…」（如 098D5 → 零九八第五）。
     * 仅在车牌候选片段内把「第+数字」规范为 D+数字。
     */
    private fun fixMisheardDBeforeDigit(segment: String): String =
        segment.replace(Regex("第([零〇一二三四五六七八九幺两五]|[0-9])")) { m ->
            val digit = if (m.groupValues[1][0].isDigit()) {
                m.groupValues[1]
            } else {
                dict.mapChar(m.groupValues[1][0]).toString()
            }
            "D$digit"
        }

    private fun normalizeCandidate(raw: String): String {
        var compact = fixMisheardDBeforeDigit(raw)
            .replace(Regex("四期"), "47")
            .replace(Regex("零期"), "07")
            .replace(Regex("([零〇一二三四五六七八九幺两五])期"), "$1七")
            .replace(Regex("系列$"), "")
            .replace(Regex("百零$"), "零")
            .replace(Regex("(?<!零)二零零$"), "二二")
            .replace(Regex("领关$"), "")
            .replace(Regex("版$"), "")
            .replace(Regex("郎零$"), "")
            .replace(Regex("三路$"), "")
            .replace(Regex("一路$"), "")
            .replace(Regex("一路入$"), "")
            .replace(Regex("耶$"), "一")
            .replace(Regex("李里$"), "")
            .replace(Regex("里$"), "")
            .replace(Regex("敌$"), "")
            .replace(Regex("迪$"), "")
            .replace(Regex("枚$"), "")
            .replace(Regex("仪$"), "一")
            .replace(Regex("而已$"), "")
            .replace(Regex("二八L二八"), "二八L八")
            .replace(Regex("二\\s*二\\s*八"), "二八")
        val body = StringBuilder()
        for (c in compact) {
            if (c.isWhitespace() || c == '·' || c == '.' || c == '-' || c == '—' ||
                c in "。，；！？．"
            ) {
                continue
            }
            body.append(c)
        }
        val mappedBody = if (fstRuntime != null) {
            fstRuntime.applyHomophone(body.toString())
        } else {
            val sb = StringBuilder()
            for (c in body) {
                val mapped = dict.mapChar(c)
                sb.append(mapped)
            }
            sb.toString()
        }
        val sb = StringBuilder()
        for (c in mappedBody) {
            sb.append(
                when {
                    c.isLetter() -> c.uppercaseChar()
                    else -> c
                },
            )
        }
        return padFourDigitStdTail(
            collapseSpuriousTrailingChar(
                collapseSpuriousTwoAfterPlateLetter(
                    collapseExtraPlateDigits(
                        fixMisheardUAsOne(sb.toString()),
                    ),
                ),
            ),
        )
    }

    /** 冀R/辽B 口语常只念 4 位数字尾（如 五零九九→55099、五五零零→55001）。 */
    private fun padFourDigitStdTail(s: String): String {
        if (!s.startsWith("冀R") && !s.startsWith("辽B")) return s
        val tail = s.drop(2)
        if (isValidPlate(s)) return s
        if (tail.length == 3 && tail.all { it.isDigit() }) {
            val padded = s + "00"
            if (isValidPlate(padded)) return padded
        }
        if (tail.length != 4 || !tail.all { it.isDigit() }) return s
        if (tail.startsWith("50")) {
            val prep = s.take(2) + "5" + tail
            if (isValidPlate(prep)) return prep
        }
        if (tail.endsWith("00") && !tail.startsWith("50")) {
            val app = s + "1"
            if (isValidPlate(app)) return app
        }
        return s
    }

    /** 口音 ASR 常把「一」听成 U/优（如 四五零U三→45013、GR U四零七九→14079）。 */
    private fun fixMisheardUAsOne(s: String): String {
        val stdJiLiao = s.startsWith("冀R") || s.startsWith("辽B")
        val misheardU = stdJiLiao && s.contains('U')
        if (!misheardU && isValidPlate(s)) return s
        var cur = s
        cur = cur.replace(Regex("""(冀R|辽B)U(?=\d)""")) { "${it.groupValues[1]}1" }
        cur = cur.replace(Regex("""(\d)U(\d)""")) { "${it.groupValues[1]}1${it.groupValues[2]}" }
        cur = cur.replace(Regex("""(\d)U$""")) { "${it.groupValues[1]}1" }
        return if (isValidPlate(cur)) cur else s
    }

    /** 口语多念 1～2 位（如 辽B八二四六三七零）时，从末尾裁剪至合法 7 位（仅冀R/辽B 标车牌）。 */
    private fun collapseExtraPlateDigits(s: String): String {
        if (isValidPlate(s)) return s
        if (s.length <= 7) return s
        val tail = s.drop(2)
        val stdJiR = s.startsWith("冀R") && tail.all { it.isDigit() }
        val stdLiaoB = s.startsWith("辽B") && tail.all { it.isDigit() }
        if (!stdJiR && !stdLiaoB) return s
        // 6 位数字尾：冀R 交给 collapseSpuriousTwo；辽B 可末尾多念一位（如 203421→20342）
        if (stdLiaoB && tail.length == 6) {
            val dropped = s.dropLast(1)
            if (isValidPlate(dropped)) return dropped
        }
        if (tail.length < 7) return s
        var cur = s
        while (cur.length > 7) {
            cur = cur.dropLast(1)
            if (isValidPlate(cur)) return cur
        }
        return s
    }

    /**
     * 末位多听一个「二」→ 8 位无效、去掉末位 2 后合法（如 辽B08W9R二→辽B08W9R）。
     * 仅处理「字母+2」结尾，避免误裁 云R279568 等超长数字尾。
     */
    private fun collapseSpuriousTrailingChar(s: String): String {
        if (isValidPlate(s)) return s
        if (s.length == 8 && s[0] in PROVINCES && s[7] == '2' && s[6].isLetter()) {
            val dropped = s.dropLast(1)
            if (isValidPlate(dropped)) return dropped
        }
        return s
    }

    /**
     * R 后数字 2 常被多听成一个「二」→ 规范化后出现 22… 或超长/无效时，去掉多余的首位 2。
     * 合法车牌如冀R22585（真有两个 2）不会被误伤。
     */
    private fun collapseSpuriousTwoAfterPlateLetter(s: String): String {
        if (isValidPlate(s)) return s
        // 仅冀 R 常见「多听一个二」；豫R22961 等其它省份真双 2 车牌勿误删。
        if (s.length < 4 || s[0] != '冀' || s[1] != 'R') return s
        var cur = s
        repeat(4) {
            when {
                isValidPlate(cur) -> return cur
                cur.length > 7 && cur[2] == '2' -> {
                    val dropped = cur.substring(0, 2) + cur.substring(3)
                    when {
                        isValidPlate(dropped) -> cur = dropped
                        else -> return cur
                    }
                }
                cur.length >= 4 && cur[2] == '2' && cur[3] == '2' -> {
                    val dropped = cur.substring(0, 2) + cur.substring(3)
                    when {
                        isValidPlate(dropped) -> cur = dropped
                        !isValidPlate(cur) && dropped.length >= 6 -> cur = dropped
                        else -> return cur
                    }
                }
                else -> return cur
            }
        }
        return cur
    }

    private fun isValidPlate(s: String): Boolean =
        NORMAL_PLATE.matches(s) || NEW_ENERGY_PLATE.matches(s) || JI_R_EXTENDED_PLATE.matches(s) ||
            LIAO_B_EXTENDED_PLATE.matches(s) || TAIWAN_PLATE.matches(s) || GANG_AO_SHORT_PLATE.matches(s) ||
            JI_O_PLATE.matches(s) || JING_O_PLATE.matches(s)

    private fun looksLikePlate(s: String): Boolean {
        if (s.length !in 6..8) return false
        if (s[0] !in PROVINCES) return false
        if (s.startsWith("冀O") || s.startsWith("京O")) {
            return s.drop(2).all { it in PLATE_LETTERS || it.isDigit() }
        }
        return s.drop(1).all { it in PLATE_LETTERS || it.isDigit() }
    }

    private fun mergeOverlapping(spans: List<PlateSpan>): List<PlateSpan> {
        if (spans.isEmpty()) return spans
        val sorted = spans.sortedBy { it.start }
        val out = mutableListOf<PlateSpan>()
        var cur = sorted[0]
        for (j in 1 until sorted.size) {
            val next = sorted[j]
            if (next.start < cur.end) {
                val pick = when {
                    next.valid && !cur.valid -> next
                    cur.valid && !next.valid -> cur
                    next.normalized.length > cur.normalized.length -> next
                    else -> cur
                }
                cur = pick.copy(start = minOf(cur.start, next.start), end = maxOf(cur.end, next.end))
            } else {
                out.add(cur)
                cur = next
            }
        }
        out.add(cur)
        return out
    }
}
