package com.amphion.asr.sample.eval

import android.text.format.DateUtils
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.RecyclerView
import com.amphion.asr.sample.R
import com.amphion.asr.sample.eval.model.RecordingMeta
import com.amphion.asr.sample.eval.model.UploadMeta
import java.text.SimpleDateFormat
import java.util.Locale

/**
 * 句子详情页的 attempts 列表。
 *
 * 每个 item 展示：
 * - 标题：第 N 次 · 时间 · 估算 WER
 * - hypothesis 行（character diff vs reference）
 * - env 摘要（地点 / 噪声等级 / 备注）
 * - 状态徽章（未上传 / 上传中 / 已上传 / 失败）
 * - 播放 + 删除按钮（已上传禁删）
 */
class AttemptListAdapter(
    private val reference: String,
    private val onPlay: (RecordingMeta) -> Unit,
    private val onDelete: (RecordingMeta) -> Unit,
) : RecyclerView.Adapter<AttemptListAdapter.VH>() {

    private val items: MutableList<RecordingMeta> = ArrayList()

    fun refresh(list: List<RecordingMeta>) {
        items.clear()
        items.addAll(list)
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val v = LayoutInflater.from(parent.context).inflate(R.layout.item_attempt, parent, false)
        return VH(v)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        holder.bind(items[position], reference, onPlay, onDelete)
    }

    override fun getItemCount(): Int = items.size

    class VH(view: View) : RecyclerView.ViewHolder(view) {
        private val tvTitle: TextView = view.findViewById(R.id.tv_title)
        private val tvState: TextView = view.findViewById(R.id.tv_state)
        private val tvDiffHyp: TextView = view.findViewById(R.id.tv_diff_hyp)
        private val tvEnv: TextView = view.findViewById(R.id.tv_env)
        private val btnPlay: Button = view.findViewById(R.id.btn_play)
        private val btnDelete: Button = view.findViewById(R.id.btn_delete)

        fun bind(
            meta: RecordingMeta,
            reference: String,
            onPlay: (RecordingMeta) -> Unit,
            onDelete: (RecordingMeta) -> Unit,
        ) {
            val ctx = itemView.context

            val werStr = meta.onDeviceWerEstimate?.let { DeviceWerEstimator.formatPercent(it) } ?: "—"
            val ts = parseTs(meta.recordedAt)
            val tsStr = DateUtils.getRelativeTimeSpanString(
                ts, System.currentTimeMillis(), DateUtils.SECOND_IN_MILLIS
            )
            tvTitle.text = ctx.getString(R.string.eval_detail_attempt_fmt, meta.attemptIndex, tsStr, werStr)

            val hyp = meta.onDeviceHypothesis.orEmpty()
            if (hyp.isEmpty()) {
                tvDiffHyp.text = "—"
            } else {
                tvDiffHyp.text = DiffRenderer.renderHypothesis(ctx, reference, hyp)
            }

            tvEnv.text = buildEnvSummary(meta)

            renderStateBadge(ctx, tvState, meta.upload)

            btnPlay.setOnClickListener { onPlay(meta) }
            btnDelete.setOnClickListener { onDelete(meta) }
            btnDelete.isEnabled = !meta.upload.isUploaded && !meta.upload.isInflight
        }

        private fun buildEnvSummary(meta: RecordingMeta): String {
            val parts = ArrayList<String>(3)
            if (meta.env.location.isNotEmpty()) parts.add(meta.env.location)
            val noise = com.amphion.asr.sample.eval.model.NoiseLevel.fromToken(meta.env.noiseLevel)
            if (noise != com.amphion.asr.sample.eval.model.NoiseLevel.UNSPECIFIED) {
                parts.add(itemView.context.getString(noise.displayResId))
            }
            if (meta.env.notes.isNotEmpty()) parts.add(meta.env.notes)
            return if (parts.isEmpty()) "" else parts.joinToString(" · ")
        }

        private fun renderStateBadge(
            ctx: android.content.Context,
            view: TextView,
            upload: UploadMeta,
        ) {
            val (textRes, colorRes) = when (upload.state) {
                UploadMeta.State.UPLOADED -> R.string.eval_detail_upload_uploaded to R.color.eval_state_uploaded
                UploadMeta.State.UPLOADING -> R.string.eval_detail_upload_uploading to R.color.eval_state_pending
                UploadMeta.State.PENDING -> R.string.eval_detail_upload_pending to R.color.eval_state_pending
                UploadMeta.State.RETRY -> R.string.eval_detail_upload_retry to R.color.eval_state_pending
                UploadMeta.State.FAILED -> R.string.eval_detail_upload_failed to R.color.eval_state_failed
                else -> R.string.eval_detail_upload_pending to R.color.eval_state_pending
            }
            view.text = ctx.getString(textRes)
            view.setTextColor(ContextCompat.getColor(ctx, colorRes))
        }

        private fun parseTs(iso: String): Long = try {
            ISO_FMT.parse(iso)?.time ?: 0L
        } catch (_: Throwable) {
            0L
        }
    }

    companion object {
        private val ISO_FMT = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).apply {
            timeZone = java.util.TimeZone.getTimeZone("UTC")
        }
    }
}
