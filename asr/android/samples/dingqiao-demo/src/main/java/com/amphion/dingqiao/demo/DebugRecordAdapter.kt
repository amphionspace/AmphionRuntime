package com.amphion.dingqiao.demo

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageButton
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

internal class DebugRecordAdapter(
    private val items: MutableList<DebugRecordSummary>,
    private val onPlay: (Int) -> Unit,
) : RecyclerView.Adapter<DebugRecordAdapter.Holder>() {

    var playingBaseName: String? = null

    class Holder(v: View) : RecyclerView.ViewHolder(v) {
        val title: TextView = v.findViewById(R.id.tv_title)
        val meta: TextView = v.findViewById(R.id.tv_meta)
        val text: TextView = v.findViewById(R.id.tv_text)
        val play: ImageButton = v.findViewById(R.id.btn_play)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder {
        val v = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_debug_record, parent, false)
        return Holder(v)
    }

    override fun onBindViewHolder(holder: Holder, position: Int) {
        val item = items[position]
        val context = holder.itemView.context
        val playing = item.baseName == playingBaseName
        holder.title.text = TIME_FORMAT.format(Date(item.startTimeMs))
        holder.meta.text = context.getString(
            R.string.debug_record_meta,
            formatDuration(item.durationMs),
            statusLabel(item),
        )
        holder.text.text = item.finalText
            .ifBlank { item.lastPartial }
            .ifBlank { context.getString(R.string.debug_record_no_text) }
        holder.play.setImageResource(if (playing) R.drawable.ic_mic_stop else R.drawable.ic_mic)
        holder.play.contentDescription = context.getString(
            if (playing) R.string.debug_record_stop_desc else R.string.debug_record_play_desc,
        )
        holder.play.setOnClickListener {
            val index = holder.bindingAdapterPosition
            if (index != RecyclerView.NO_POSITION) onPlay(index)
        }
    }

    override fun getItemCount(): Int = items.size

    private fun statusLabel(item: DebugRecordSummary): String =
        when (item.status) {
            DebugRecordStore.STATUS_ERROR -> item.errorMessage?.let { "错误：$it" } ?: "错误"
            DebugRecordStore.STATUS_ABORTED -> "已中断"
            else -> "完成"
        }

    private fun formatDuration(durationMs: Long): String =
        String.format(Locale.getDefault(), "%.1fs", durationMs / 1000.0)

    private companion object {
        val TIME_FORMAT = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault())
    }
}
