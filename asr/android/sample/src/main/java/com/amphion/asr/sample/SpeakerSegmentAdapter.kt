package com.amphion.asr.sample

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageButton
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import java.io.File

/** 一段注册录音的展示项：文件 + 已格式化的标签（序号 · 时长）。 */
internal data class SegmentItem(
    val file: File,
    val label: String,
)

/**
 * 注册录音列表 Adapter；每行 播放按钮 + 标签 + 删除按钮。
 *
 * 不持有任何 SDK / 存储状态；播放与删除通过 [onPlay] / [onDelete] 回到 Activity，
 * 由 Activity 统一操作 [SpeakerProfileStore] 并刷新列表。
 */
internal class SpeakerSegmentAdapter(
    private val items: MutableList<SegmentItem>,
    private val onPlay: (index: Int) -> Unit,
    private val onDelete: (index: Int) -> Unit,
) : RecyclerView.Adapter<SpeakerSegmentAdapter.VH>() {

    inner class VH(view: View) : RecyclerView.ViewHolder(view) {
        val btnPlay: ImageButton = view.findViewById(R.id.btn_play)
        val tvLabel: TextView = view.findViewById(R.id.tv_seg_label)
        val btnDelete: ImageButton = view.findViewById(R.id.btn_delete)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val v = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_speaker_segment, parent, false)
        return VH(v)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        holder.tvLabel.text = items[position].label
        holder.btnPlay.setOnClickListener {
            val idx = holder.bindingAdapterPosition
            if (idx != RecyclerView.NO_POSITION) onPlay(idx)
        }
        holder.btnDelete.setOnClickListener {
            val idx = holder.bindingAdapterPosition
            if (idx != RecyclerView.NO_POSITION) onDelete(idx)
        }
    }

    override fun getItemCount(): Int = items.size
}
