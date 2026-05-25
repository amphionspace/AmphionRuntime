package com.amphion.asr.sample.eval.export

import android.content.Context
import com.amphion.asr.sample.eval.data.RecordingStore

/**
 * 录音批量导出的抽象。当前有 [ZipExporter]（离线分享）；
 * 未来如果要把零散的多个 attempt 一次性 HTTP 上传，可以加 BatchHttpExporter。
 */
interface RecordingExporter {

    /**
     * 导出符合 [filter] 的所有 attempt。
     *
     * @return 导出结果（如 zip 文件 Uri 或上传统计），具体由实现定义；失败抛异常
     */
    fun export(
        ctx: Context,
        store: RecordingStore,
        filter: ExportFilter,
    ): ExportResult

    /** 过滤器：决定哪些 attempt 进入本次导出。 */
    data class ExportFilter(
        val testerId: String?,
        val sentenceIdPrefix: String?,
        val onlyNotUploaded: Boolean,
    ) {
        companion object {
            fun allOfTester(testerId: String): ExportFilter =
                ExportFilter(testerId = testerId, sentenceIdPrefix = null, onlyNotUploaded = false)

            fun notUploadedOfTester(testerId: String): ExportFilter =
                ExportFilter(testerId = testerId, sentenceIdPrefix = null, onlyNotUploaded = true)
        }
    }

    /** 导出结果。zipUri 可用 Intent.ACTION_SEND 直接 share。 */
    data class ExportResult(
        val itemCount: Int,
        val zipFile: java.io.File?,
        val totalBytes: Long,
    )
}
