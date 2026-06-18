package com.amphion.asr.sample.eval.model

import java.security.MessageDigest

/**
 * 测试员自定义参考文本（不在 sentences.json 内置集中）的 sentence_id 派生与识别。
 *
 * 设计要点：
 * - sentence_id = `custom_<sha1(normalize(text))[:12]>`：相同 text 在不同设备 / tester 间稳定派生同一 id，
 *   后台脚本天然可做「同一 custom 文本跨人 WER 对比」，比随机 UUID 信息密度更高
 * - normalize：去首尾空白 + 合并多空格；ref text 末尾误多个空格不会派生出新 id
 * - 不维护单独的 CustomSentenceStore：reference_text 已经是 meta.json 中的强制字段，
 *   EvalActivity 列表通过扫描 RecordingStore 中 `custom_` 前缀的录音即可还原出全部 custom 句子
 *   （减少冗余表 = 减少状态机维护负担，符合"单一事实源"原则）
 *
 * 与内置 sentence 的关系：
 * - 共用 [Sentence] 数据类型；category_id 固定为 [CUSTOM_CATEGORY_ID]
 * - RecordSentenceActivity / SentenceDetailActivity 不需要分情况判断；统一按 Sentence 走
 *
 * 修改 text 的语义：text 一改 → sentence_id 立即变 → 等于新建一个 custom 句子。
 * 这是有意为之的不变量，禁止"原地编辑 reference text"破坏历史录音聚合。
 */
object CustomSentence {

    /** custom 句子统一的 category_id；与内置 6 个 category 隔离。 */
    const val CUSTOM_CATEGORY_ID: String = "custom"

    /** sentence_id 的固定前缀。 */
    const val ID_PREFIX: String = "custom_"

    /** sha1 hex 截断长度（与 TesterPrefs.deriveTesterId 保持一致，48 bit 足够避碰）。 */
    private const val ID_HEX_LEN: Int = 12

    fun isCustomSentenceId(id: String?): Boolean =
        id != null && id.startsWith(ID_PREFIX)

    /** 按规范化 text 派生 sentence_id。text 不能为空白。 */
    fun deriveId(text: String): String {
        val n = normalize(text)
        require(n.isNotEmpty()) { "custom sentence text cannot be blank" }
        val md = MessageDigest.getInstance("SHA-1")
        val hex = md.digest(n.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
        return ID_PREFIX + hex.substring(0, ID_HEX_LEN)
    }

    /** 构造 ad-hoc [Sentence] —— 用作 RecordSentenceActivity 的输入。 */
    fun adHoc(text: String): Sentence {
        val n = normalize(text)
        return Sentence(
            id = deriveId(n),
            text = n,
            categoryId = CUSTOM_CATEGORY_ID,
        )
    }

    /**
     * 规范化 text：去首尾空白 + 合并连续空格。
     * 不做大小写折叠（英文大小写在 ASR 里可能有真实差异），也不去标点
     * （中文标点会影响 ITN / WER）。意图：只清理"显然不该影响 id"的格式差异。
     */
    fun normalize(text: String): String =
        text.trim().split(Regex("\\s+")).joinToString(" ").trim()
}
