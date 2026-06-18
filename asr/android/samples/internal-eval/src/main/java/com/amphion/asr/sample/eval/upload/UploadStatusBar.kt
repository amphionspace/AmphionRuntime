package com.amphion.asr.sample.eval.upload

import android.content.Context
import android.util.AttributeSet
import android.view.LayoutInflater
import android.widget.LinearLayout
import android.widget.TextView
import com.amphion.asr.sample.R

/**
 * EvalActivity 顶部的一条状态视图：`待上传 N · 已上传 M · 失败 K [立即同步]`。
 *
 * 持有引用关系：由 EvalActivity 创建 → 注入 UploadScanner → 实现 Listener 回调。
 * 本视图不持有 scanner 或 store，避免 leak；所有状态由 EvalActivity 主动推过来。
 */
class UploadStatusBar @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyle: Int = 0,
) : LinearLayout(context, attrs, defStyle) {

    private val tvSummary: TextView
    private val tvAction: TextView

    var onActionClick: (() -> Unit)? = null

    init {
        LayoutInflater.from(context).inflate(R.layout.view_upload_status_bar, this, true)
        orientation = HORIZONTAL
        tvSummary = findViewById(R.id.tv_upload_summary)
        tvAction = findViewById(R.id.tv_upload_action)
        tvAction.setOnClickListener { onActionClick?.invoke() }
    }

    fun render(snapshot: UploadScanner.Snapshot, hasConfig: Boolean) {
        val s = snapshot
        if (!hasConfig) {
            tvSummary.text = context.getString(R.string.eval_upload_summary_not_configured)
            tvAction.text = context.getString(R.string.eval_upload_action_configure)
            tvAction.isEnabled = true
            return
        }
        tvSummary.text = context.getString(
            R.string.eval_upload_summary_fmt,
            s.pending, s.uploaded, s.failed
        )
        tvAction.text = if (s.isRunning) {
            context.getString(R.string.eval_upload_action_running)
        } else {
            context.getString(R.string.eval_upload_action_sync_now)
        }
        tvAction.isEnabled = !s.isRunning
    }
}
