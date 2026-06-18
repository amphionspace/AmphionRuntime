package com.amphion.asr.sample

import android.content.Context
import android.content.SharedPreferences
import com.amphion.asr.AsrLanguage
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

/**
 * 热词的本地存储：按 [AsrLanguage] 分组维护，每条热词带 enabled 开关 + 顶层 master 开关。
 *
 * 数据模型：
 * - 每个 [AsrLanguage] 一份 [HotwordEntry] 列表（增删都按语言独立）
 * - 每个 [AsrLanguage] 一个 master 开关，关闭时即使 entry.enabled=true 也不激活
 * - "激活" = master=true 且 entry.enabled=true；通过 [activeWords] 一步算出
 *
 * 持久化：单文件 [SharedPreferences]，按 language 用不同 key 隔离。JSON 字符串存储
 * （无 GSON 依赖），entry 长度由 UI 层校验（建议 ≤ 30 字符）。
 *
 * 线程：SharedPreferences 自身在主线程同步可用；本类的 setter 都用 apply()，
 * 不阻塞主线程。多线程读取 100% 安全。
 */
internal class HotwordsPrefs(ctx: Context) {

    private val sp: SharedPreferences =
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    /** 当前语言下保存的全部热词条目。 */
    fun load(lang: AsrLanguage): List<HotwordEntry> {
        val raw = sp.getString(listKey(lang), null) ?: return emptyList()
        return try {
            val arr = JSONArray(raw)
            val out = ArrayList<HotwordEntry>(arr.length())
            for (i in 0 until arr.length()) {
                val obj = arr.optJSONObject(i) ?: continue
                val text = obj.optString(KEY_TEXT, "").trim()
                if (text.isEmpty()) continue
                out.add(HotwordEntry(text = text, enabled = obj.optBoolean(KEY_ENABLED, true)))
            }
            out
        } catch (_: JSONException) {
            emptyList()
        }
    }

    /** 覆盖保存当前语言下的全部热词条目；调用方自己负责去重与字段清洗。 */
    fun save(lang: AsrLanguage, list: List<HotwordEntry>) {
        val arr = JSONArray()
        for (e in list) {
            val cleaned = e.text.trim()
            if (cleaned.isEmpty()) continue
            arr.put(JSONObject().put(KEY_TEXT, cleaned).put(KEY_ENABLED, e.enabled))
        }
        sp.edit().putString(listKey(lang), arr.toString()).apply()
    }

    /** 当前语言的总开关；默认 true（即不显式关闭就视为允许激活）。 */
    fun masterEnabled(lang: AsrLanguage): Boolean =
        sp.getBoolean(masterKey(lang), true)

    fun setMasterEnabled(lang: AsrLanguage, value: Boolean) {
        sp.edit().putBoolean(masterKey(lang), value).apply()
    }

    /**
     * 当前语言要真正传给 [com.amphion.asr.AsrConfig.Builder.hotwords] 的词列表：
     * master 开关 + 各 entry enabled 都为 true 才入列；trim 后排重；保留原插入顺序。
     */
    fun activeWords(lang: AsrLanguage): List<String> {
        if (!masterEnabled(lang)) return emptyList()
        val seen = LinkedHashSet<String>()
        for (e in load(lang)) {
            if (!e.enabled) continue
            val t = e.text.trim()
            if (t.isEmpty()) continue
            seen.add(t)
        }
        return seen.toList()
    }

    /**
     * 是否任一已知语言存在激活热词。`AmphionApp` 用它决定 preload 时是否注入占位词，
     * 让池保持 modified_beam_search 解码方法，运行时 create 才能命中池。
     */
    fun anyLangHasActive(): Boolean =
        AsrLanguage.values().any { activeWords(it).isNotEmpty() }

    private fun listKey(lang: AsrLanguage): String = "list_${lang.name}"
    private fun masterKey(lang: AsrLanguage): String = "master_${lang.name}"

    companion object {
        private const val NAME = "amphion_hotwords"
        private const val KEY_TEXT = "text"
        private const val KEY_ENABLED = "enabled"

        /** UI 层向用户呈现的"建议长度上限"；data 层不强制，超过也存。 */
        const val SUGGESTED_MAX_LEN = 30
    }
}

/**
 * 持久化用的热词条目。
 *
 * @property text 词面文字；trim 后存
 * @property enabled 是否参与激活；false 表示用户暂时禁用此条但保留入口（区别于删除）
 */
internal data class HotwordEntry(
    val text: String,
    val enabled: Boolean,
)
