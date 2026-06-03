package com.amphion.asr.mini

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.CheckBox
import android.widget.ImageButton
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView

/**
 * 单语言热词列表的 Adapter；每行 [CheckBox] + 词面 + 删除按钮。
 *
 * Adapter 不持有任何引擎 / SDK 状态；列表数据由 [HotwordsActivity] 在本地的可变 list 中维护，
 * 用户的勾选与删除通过 [onEnabledChanged] / [onDelete] 回上去；提交时机由 Activity 决定
 * （onPause / setResult 之前一次性 save）。
 */
internal class HotwordsAdapter(
    private val items: MutableList<HotwordEntry>,
    private val onEnabledChanged: (index: Int, enabled: Boolean) -> Unit,
    private val onDelete: (index: Int) -> Unit,
) : RecyclerView.Adapter<HotwordsAdapter.VH>() {

    inner class VH(view: View) : RecyclerView.ViewHolder(view) {
        val cb: CheckBox = view.findViewById(R.id.cb_enabled)
        val tv: TextView = view.findViewById(R.id.tv_text)
        val btnDelete: ImageButton = view.findViewById(R.id.btn_delete)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val v = LayoutInflater.from(parent.context).inflate(R.layout.item_hotword, parent, false)
        return VH(v)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val entry = items[position]
        holder.tv.text = entry.text
        // 解绑旧 listener 再设值，避免 ViewHolder 复用时 setChecked 反向触发回调
        holder.cb.setOnCheckedChangeListener(null)
        holder.cb.isChecked = entry.enabled
        holder.cb.setOnCheckedChangeListener { _, isChecked ->
            val idx = holder.bindingAdapterPosition
            if (idx == RecyclerView.NO_POSITION) return@setOnCheckedChangeListener
            onEnabledChanged(idx, isChecked)
        }
        holder.btnDelete.setOnClickListener {
            val idx = holder.bindingAdapterPosition
            if (idx == RecyclerView.NO_POSITION) return@setOnClickListener
            onDelete(idx)
        }
    }

    override fun getItemCount(): Int = items.size
}
