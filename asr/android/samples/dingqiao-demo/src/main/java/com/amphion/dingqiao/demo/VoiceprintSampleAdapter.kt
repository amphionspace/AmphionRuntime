package com.amphion.dingqiao.demo

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageButton
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import java.io.File
import java.util.Locale

class VoiceprintSampleAdapter(
    private val items: MutableList<File>,
    private val onPlay: (Int) -> Unit,
    private val onDelete: (Int) -> Unit,
) : RecyclerView.Adapter<VoiceprintSampleAdapter.Holder>() {

    class Holder(v: View) : RecyclerView.ViewHolder(v) {
        val label: TextView = v.findViewById(R.id.tv_label)
        val play: ImageButton = v.findViewById(R.id.btn_play)
        val delete: ImageButton = v.findViewById(R.id.btn_delete)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder {
        val v = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_voiceprint_sample, parent, false)
        return Holder(v)
    }

    override fun onBindViewHolder(holder: Holder, position: Int) {
        val file = items[position]
        holder.label.text = holder.itemView.context.getString(
            R.string.enroll_seg_label_with_duration,
            position + 1,
            file.name,
            formatDuration(file),
        )
        holder.play.setOnClickListener { onPlay(holder.bindingAdapterPosition) }
        holder.delete.setOnClickListener { onDelete(holder.bindingAdapterPosition) }
    }

    override fun getItemCount(): Int = items.size

    private fun formatDuration(file: File): String {
        val seconds = file.length().coerceAtLeast(0L).toDouble() / BYTES_PER_SECOND
        return String.format(Locale.getDefault(), "%.1fs", seconds)
    }

    private companion object {
        private const val SAMPLE_RATE = 16_000
        private const val BYTES_PER_SAMPLE = 2
        private const val BYTES_PER_SECOND = SAMPLE_RATE * BYTES_PER_SAMPLE.toDouble()
    }
}
