package com.amphion.police.terms

/**
 * 二至三字警务短词的上下文护栏纠正。
 *
 * 短词没有足够上下文，不能进入 V2 的全局模糊层：例如把裸「接触景」全局替换为
 * 「接处警」会误伤「接触景点游客」。这里只接受两类高置信输入：
 * 1. 去掉句末标点后，整句就是已知误识串；
 * 2. 误识串紧邻明确的警务业务锚点。
 */
internal object PoliceTermsShortGuard {

    private val sentenceEndChars = setOf('。', '！', '？', '!', '?', '，', ',', '、', '；', ';', '：', ':')

    private val juchuanVariants = listOf("喻传", "居传", "拒传")
    private val juchuanBeforeAnchors = listOf(
        "办理", "依法", "进行", "执行", "实施", "采取", "决定", "批准", "审批", "申请", "可以",
    )
    private val juchuanAfterAnchors = listOf(
        "到案", "审批", "手续", "措施", "决定", "对象", "期间", "期限", "程序", "执行",
    )

    private val jieChuJingVariants = listOf(
        "接触景", "接触警", "接触井", "接触颈", "接出警", "街处警",
    )
    private val jieChuJingBeforeAnchors = listOf("移动", "指信")
    private val jieChuJingAfterAnchors = listOf(
        "流程", "记录", "规范", "工作", "机制", "系统", "平台", "业务", "要求", "要及时", "已上传",
    )

    /** 图片中「指信接处警」整词被听成「女性接触颈」；只在整句命中时纠正。 */
    private val zhiXinJieChuJingVariants = listOf(
        "女性接触颈", "女性接触景", "女性接触警", "女性接触井",
    )

    fun apply(text: String): String {
        if (text.isEmpty()) return text

        replaceWholeUtterance(text, zhiXinJieChuJingVariants, "指信接处警")?.let { return it }
        replaceWholeUtterance(text, juchuanVariants, "拘传")?.let { return it }
        replaceWholeUtterance(text, jieChuJingVariants, "接处警")?.let { return it }

        var out = replaceWithAnchors(
            text = text,
            variants = juchuanVariants,
            target = "拘传",
            beforeAnchors = juchuanBeforeAnchors,
            afterAnchors = juchuanAfterAnchors,
        )
        out = replaceWithAnchors(
            text = out,
            variants = jieChuJingVariants,
            target = "接处警",
            beforeAnchors = jieChuJingBeforeAnchors,
            afterAnchors = jieChuJingAfterAnchors,
        )
        return out
    }

    private fun replaceWholeUtterance(text: String, variants: List<String>, target: String): String? {
        val trimmedStart = text.indexOfFirst { !it.isWhitespace() }.takeIf { it >= 0 } ?: return null
        var coreEnd = text.length
        while (coreEnd > trimmedStart) {
            val c = text[coreEnd - 1]
            if (!c.isWhitespace() && c !in sentenceEndChars) break
            coreEnd--
        }
        if (coreEnd <= trimmedStart) return null
        val core = text.substring(trimmedStart, coreEnd)
        if (core !in variants) return null
        return text.replaceRange(trimmedStart, coreEnd, target)
    }

    private fun replaceWithAnchors(
        text: String,
        variants: List<String>,
        target: String,
        beforeAnchors: List<String>,
        afterAnchors: List<String>,
    ): String {
        var out = text
        for (variant in variants) {
            var from = 0
            while (from < out.length) {
                val index = out.indexOf(variant, from)
                if (index < 0) break
                val end = index + variant.length
                val before = out.substring(0, index)
                val after = out.substring(end)
                val accepted = beforeAnchors.any { before.endsWith(it) } ||
                    afterAnchors.any { after.startsWith(it) }
                if (accepted) {
                    out = out.replaceRange(index, end, target)
                    from = index + target.length
                } else {
                    from = end
                }
            }
        }
        return out
    }
}
