package com.amphion.asr.sample.eval.model

import org.json.JSONObject

/**
 * 评估测试集顶层 manifest，与 assets/eval-set/sentences.json 一一对应。
 *
 * 解析失败时抛 IllegalStateException；调用方应捕获并降级到内置 fallback 或显示错误。
 */
data class SentenceManifest(
    val schemaVersion: Int,
    val manifestVersion: String,
    val lang: String,
    val description: String,
    val categories: List<Category>,
) {

    val sentenceCount: Int get() = categories.sumOf { it.sentences.size }

    /** 全量句子拍平迭代，保留 category 顺序。 */
    fun allSentences(): Sequence<Sentence> = sequence {
        for (c in categories) for (s in c.sentences) yield(s)
    }

    fun findSentence(sentenceId: String): Sentence? =
        allSentences().firstOrNull { it.id == sentenceId }

    fun findCategoryOf(sentenceId: String): Category? =
        categories.firstOrNull { c -> c.sentences.any { it.id == sentenceId } }

    companion object {

        /** schema_version 当前支持的版本号。manifest 中更高的版本视为不兼容，拒绝加载。 */
        const val SUPPORTED_SCHEMA_VERSION: Int = 1

        fun fromJson(text: String): SentenceManifest {
            val root = JSONObject(text)
            val sv = root.optInt("schema_version", 0)
            check(sv == SUPPORTED_SCHEMA_VERSION) {
                "sentences manifest schema_version=$sv not supported (expected $SUPPORTED_SCHEMA_VERSION)"
            }
            val cats = root.getJSONArray("categories")
            val categories = ArrayList<Category>(cats.length())
            for (i in 0 until cats.length()) {
                val co = cats.getJSONObject(i)
                val sa = co.getJSONArray("sentences")
                val list = ArrayList<Sentence>(sa.length())
                for (j in 0 until sa.length()) {
                    val so = sa.getJSONObject(j)
                    list.add(
                        Sentence(
                            id = so.getString("id"),
                            text = so.getString("text"),
                            categoryId = co.getString("id"),
                        )
                    )
                }
                categories.add(
                    Category(
                        id = co.getString("id"),
                        label = co.getString("label"),
                        description = co.optString("description", ""),
                        sentences = list,
                    )
                )
            }
            return SentenceManifest(
                schemaVersion = sv,
                manifestVersion = root.optString("manifest_version", "0.0.0"),
                lang = root.optString("lang", "zh-en"),
                description = root.optString("description", ""),
                categories = categories,
            )
        }
    }
}

/** 测试集分类（如「日常对话」/「数字与日期」），每个 category 下有若干 [Sentence]。 */
data class Category(
    val id: String,
    val label: String,
    val description: String,
    val sentences: List<Sentence>,
)

/** 一条参考句子。`text` 是测试员需要朗读的参考文本，也是后台 WER 计算的 reference。 */
data class Sentence(
    val id: String,
    val text: String,
    val categoryId: String,
)
