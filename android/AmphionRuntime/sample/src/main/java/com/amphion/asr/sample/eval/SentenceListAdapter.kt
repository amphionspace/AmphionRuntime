package com.amphion.asr.sample.eval

import android.text.format.DateUtils
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.amphion.asr.sample.R
import com.amphion.asr.sample.eval.model.RecordingMeta
import com.amphion.asr.sample.eval.model.Sentence
import com.amphion.asr.sample.eval.model.SentenceManifest
import java.text.SimpleDateFormat
import java.util.Locale

/**
 * 句子列表（按 category 分组的 RecyclerView Adapter）。
 *
 * 数据模型：把 manifest 摊平成 [Row] 列表，header 与 sentence 各占一行；
 * 每次 EvalActivity 注入新 manifest / attempts 索引时调用 [refresh] 重算。
 *
 * attempts 索引由 EvalActivity 在 onResume 时扫一遍 RecordingStore 算出来，
 * 传进来即可，不要让 adapter 持有 store（避免每次 bind 都 scan 磁盘）。
 */
class SentenceListAdapter(
    private val onClickSentence: (Sentence) -> Unit,
    private val onClickNewCustom: () -> Unit,
) : RecyclerView.Adapter<RecyclerView.ViewHolder>() {

    sealed class Row {
        /** Custom section 顶部的「+ 录入自定义文本」按钮卡片，永远展示。 */
        object CustomEntry : Row()

        /** 内置 6 个 category 的 header；custom section 的 header 也复用此类型。 */
        data class Header(val title: String, val description: String, val count: Int) : Row()

        data class Item(val sentence: Sentence, val attempts: List<RecordingMeta>) : Row()
    }

    private val rows: MutableList<Row> = ArrayList()

    /**
     * @param customSentences 已经存在的 custom 句子（按调用方期望的展示顺序，通常是最近一次录制 desc）。
     *                       attempts 已包含在 [attemptsBySentence] 内。
     * @param customSectionTitle / customSectionDesc 自由文本 section header 文案，由调用方从
     *                       strings.xml 取出（adapter 不直接吃 R.string，便于做单测）。
     */
    fun refresh(
        manifest: SentenceManifest,
        attemptsBySentence: Map<String, List<RecordingMeta>>,
        customSentences: List<Sentence>,
        customSectionTitle: String,
        customSectionDesc: String,
    ) {
        rows.clear()
        // 1) Custom section 永远放最上面，体现「自由文本是 first-class 公民」
        rows.add(Row.CustomEntry)
        rows.add(
            Row.Header(
                title = customSectionTitle,
                description = customSectionDesc,
                count = customSentences.size,
            )
        )
        for (s in customSentences) {
            rows.add(Row.Item(s, attemptsBySentence[s.id].orEmpty()))
        }

        // 2) 内置 6 类
        for (cat in manifest.categories) {
            rows.add(Row.Header(cat.label, cat.description, cat.sentences.size))
            for (s in cat.sentences) {
                rows.add(Row.Item(s, attemptsBySentence[s.id].orEmpty()))
            }
        }
        notifyDataSetChanged()
    }

    override fun getItemViewType(position: Int): Int = when (rows[position]) {
        is Row.CustomEntry -> TYPE_CUSTOM_ENTRY
        is Row.Header -> TYPE_HEADER
        is Row.Item -> TYPE_ITEM
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): RecyclerView.ViewHolder {
        val inf = LayoutInflater.from(parent.context)
        return when (viewType) {
            TYPE_CUSTOM_ENTRY -> CustomEntryVH(inf.inflate(R.layout.item_custom_entry, parent, false))
            TYPE_HEADER -> HeaderVH(inf.inflate(R.layout.item_category_header, parent, false))
            TYPE_ITEM -> ItemVH(inf.inflate(R.layout.item_sentence, parent, false))
            else -> error("unknown viewType $viewType")
        }
    }

    override fun onBindViewHolder(holder: RecyclerView.ViewHolder, position: Int) {
        when (val row = rows[position]) {
            is Row.CustomEntry -> (holder as CustomEntryVH).bind(onClickNewCustom)
            is Row.Header -> (holder as HeaderVH).bind(row)
            is Row.Item -> (holder as ItemVH).bind(row.sentence, row.attempts, onClickSentence)
        }
    }

    override fun getItemCount(): Int = rows.size

    private class HeaderVH(view: View) : RecyclerView.ViewHolder(view) {
        private val tvLabel: TextView = view.findViewById(R.id.tv_category_label)
        private val tvDesc: TextView = view.findViewById(R.id.tv_category_desc)
        fun bind(h: Row.Header) {
            tvLabel.text = if (h.count > 0) "${h.title}（${h.count} 句）" else h.title
            tvDesc.text = h.description
            tvDesc.visibility = if (h.description.isEmpty()) View.GONE else View.VISIBLE
        }
    }

    private class CustomEntryVH(view: View) : RecyclerView.ViewHolder(view) {
        fun bind(onClick: () -> Unit) {
            itemView.setOnClickListener { onClick() }
        }
    }

    private class ItemVH(view: View) : RecyclerView.ViewHolder(view) {
        private val tvText: TextView = view.findViewById(R.id.tv_text)
        private val tvStat: TextView = view.findViewById(R.id.tv_stat)
        private val tvLast: TextView = view.findViewById(R.id.tv_last)

        fun bind(s: Sentence, attempts: List<RecordingMeta>, onClick: (Sentence) -> Unit) {
            tvText.text = s.text
            val ctx = itemView.context
            // 未录的句子也展示「已录 0 次」而非「还没录」：
            // 让句子保持「参考」的中性语气，不暗示「这是个必须完成的任务」
            if (attempts.isEmpty()) {
                tvStat.text = ctx.getString(R.string.eval_item_stat_zero)
                tvLast.text = ""
            } else {
                val bestEstimate = attempts.mapNotNull { it.onDeviceWerEstimate }.minOrNull()
                val estimateStr = bestEstimate?.let { DeviceWerEstimator.formatPercent(it) }
                    ?: ctx.getString(R.string.eval_item_estimate_unknown)
                val uploaded = attempts.count { it.upload.isUploaded }
                tvStat.text = ctx.getString(
                    R.string.eval_item_stat_fmt,
                    attempts.size, estimateStr, uploaded, attempts.size,
                )
                val lastTs = attempts.maxOf { parseTs(it.recordedAt) }
                tvLast.text = ctx.getString(
                    R.string.eval_item_last_fmt,
                    DateUtils.getRelativeTimeSpanString(
                        lastTs,
                        System.currentTimeMillis(),
                        DateUtils.SECOND_IN_MILLIS,
                    )
                )
            }
            itemView.setOnClickListener { onClick(s) }
        }

        private fun parseTs(iso: String): Long = try {
            ISO_FMT.parse(iso)?.time ?: 0L
        } catch (_: Throwable) {
            0L
        }
    }

    companion object {
        private const val TYPE_HEADER = 0
        private const val TYPE_ITEM = 1
        private const val TYPE_CUSTOM_ENTRY = 2
        private val ISO_FMT = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).apply {
            timeZone = java.util.TimeZone.getTimeZone("UTC")
        }
    }
}
