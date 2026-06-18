package com.amphion.asr.sample.eval.data

import android.content.Context
import android.util.Log
import com.amphion.asr.sample.eval.model.RecordingMeta
import java.io.File
import java.io.IOException

/**
 * 录音的本地持久化层。目录布局：
 * ```
 * <externalFilesDir>/asr-eval/
 *   _temp/<recording_id>/           ← 写入中（包含未 finalized 的 meta.json + audio.wav）
 *   <tester_id>/
 *     <sentence_id>/
 *       <recording_id>/             ← finalize 后 atomic rename 到此
 *         audio.wav
 *         meta.json
 *         hypothesis.txt            ← 可选
 * ```
 *
 * 核心不变量：
 * - finalize() 通过 [File.renameTo] 做 atomic 目录搬迁；rename 成功才视为有效样本
 * - 后台与 UploadScanner 仅看 finalized 目录，_temp 永远忽略
 * - 删除 attempt 必须先检查 upload.state，禁止删除已上传或正在上传的
 *
 * 线程安全：所有方法可在任意线程调用；同一 [recordingId] 必须串行操作（由调用方保证）。
 */
class RecordingStore(ctx: Context) {

    val rootDir: File = run {
        val base = ctx.getExternalFilesDir(null) ?: ctx.filesDir
        File(base, ROOT_NAME).apply { if (!isDirectory) mkdirs() }
    }

    val tempDir: File = File(rootDir, TEMP_NAME).apply { if (!isDirectory) mkdirs() }

    /** 为新录音分配一个 _temp/<recording_id>/ 子目录。 */
    fun newTempDir(recordingId: String): File {
        val d = File(tempDir, recordingId)
        if (d.isDirectory) {
            d.deleteRecursively()
        }
        d.mkdirs()
        return d
    }

    /**
     * 把 _temp 中的录音 atomic rename 到正式目录。失败返回 null（调用方应清理并提示）。
     *
     * 流程：
     * 1. 在 _temp 中写完整 meta.json（finalized=true）+ audio.wav
     * 2. 调用本方法，rename 到 `<tester_id>/<sentence_id>/<recording_id>/`
     * 3. rename 是 atomic（POSIX 同设备 rename 是原子的），中途断电不会留半成品
     */
    fun finalize(
        tempDir: File,
        testerId: String,
        sentenceId: String,
        recordingId: String,
    ): File? {
        require(tempDir.parentFile == this.tempDir) {
            "tempDir must be a child of ${this.tempDir.absolutePath}"
        }
        val target = recordingDir(testerId, sentenceId, recordingId)
        if (target.exists()) {
            Log.w(TAG, "target already exists: ${target.absolutePath}, cleaning before rename")
            target.deleteRecursively()
        }
        target.parentFile?.mkdirs()
        return if (tempDir.renameTo(target)) {
            target
        } else {
            Log.w(TAG, "rename ${tempDir.absolutePath} -> ${target.absolutePath} failed")
            null
        }
    }

    /** 取某条 attempt 的 meta.json 文件路径（不保证文件存在）。 */
    fun metaFile(testerId: String, sentenceId: String, recordingId: String): File =
        File(recordingDir(testerId, sentenceId, recordingId), META_FILE)

    fun audioFile(testerId: String, sentenceId: String, recordingId: String): File =
        File(recordingDir(testerId, sentenceId, recordingId), AUDIO_FILE)

    fun hypothesisFile(testerId: String, sentenceId: String, recordingId: String): File =
        File(recordingDir(testerId, sentenceId, recordingId), HYPOTHESIS_FILE)

    fun recordingDir(testerId: String, sentenceId: String, recordingId: String): File =
        File(File(File(rootDir, testerId), sentenceId), recordingId)

    /**
     * 列举某测试员某句的全部 attempts，按 recordedAt 升序。
     * 损坏的 meta.json 自动跳过并 log warn，不抛出。
     */
    fun listAttempts(testerId: String, sentenceId: String): List<RecordingMeta> {
        val sentenceDir = File(File(rootDir, testerId), sentenceId)
        if (!sentenceDir.isDirectory) return emptyList()
        val out = ArrayList<RecordingMeta>()
        sentenceDir.listFiles()?.forEach { recDir ->
            if (!recDir.isDirectory) return@forEach
            val meta = File(recDir, META_FILE)
            if (!meta.isFile) return@forEach
            val parsed = try {
                RecordingMeta.fromJson(meta.readText(Charsets.UTF_8))
            } catch (t: Throwable) {
                Log.w(TAG, "skip corrupted meta ${meta.absolutePath}: ${t.message}")
                null
            }
            if (parsed != null && parsed.finalized) out.add(parsed)
        }
        out.sortBy { it.recordedAt }
        return out
    }

    /**
     * 扫描整个 rootDir 下所有"已 finalized + 满足 [predicate]"的录音。
     * 用于 UploadScanner 找出 pending/retry 状态的录音。
     */
    fun scanAll(predicate: (RecordingMeta) -> Boolean): List<ScanItem> {
        val out = ArrayList<ScanItem>()
        rootDir.listFiles()?.forEach tester@{ testerDir ->
            if (!testerDir.isDirectory || testerDir.name == TEMP_NAME) return@tester
            testerDir.listFiles()?.forEach sentence@{ sentenceDir ->
                if (!sentenceDir.isDirectory) return@sentence
                sentenceDir.listFiles()?.forEach rec@{ recDir ->
                    if (!recDir.isDirectory) return@rec
                    val metaFile = File(recDir, META_FILE)
                    if (!metaFile.isFile) return@rec
                    val meta = try {
                        RecordingMeta.fromJson(metaFile.readText(Charsets.UTF_8))
                    } catch (t: Throwable) {
                        Log.w(TAG, "skip corrupted meta ${metaFile.absolutePath}: ${t.message}")
                        return@rec
                    }
                    if (meta.finalized && predicate(meta)) {
                        out.add(ScanItem(meta = meta, dir = recDir))
                    }
                }
            }
        }
        return out
    }

    /**
     * 原子覆盖 meta.json（先写 tmp 再 rename）。失败返回 false。
     * 用于 UploadScanner 在上传成功后更新 upload state 字段。
     */
    fun writeMeta(dir: File, meta: RecordingMeta): Boolean {
        val target = File(dir, META_FILE)
        val tmp = File(dir, META_FILE_TMP)
        return try {
            tmp.writeText(meta.toJsonString(), Charsets.UTF_8)
            if (target.exists()) target.delete()
            tmp.renameTo(target)
        } catch (t: IOException) {
            Log.w(TAG, "writeMeta failed at ${dir.absolutePath}: ${t.message}")
            try { tmp.delete() } catch (_: Throwable) {}
            false
        }
    }

    /**
     * 删除一条 attempt。仅允许删除未上传（state in {pending, retry, failed}）的；
     * 已上传（uploaded）或上传中（uploading）禁止删除，返回 false。
     */
    fun deleteAttempt(testerId: String, sentenceId: String, recordingId: String): Boolean {
        val dir = recordingDir(testerId, sentenceId, recordingId)
        val meta = metaFile(testerId, sentenceId, recordingId)
        if (!dir.isDirectory) return false
        if (meta.isFile) {
            try {
                val m = RecordingMeta.fromJson(meta.readText(Charsets.UTF_8))
                if (m.upload.isUploaded || m.upload.isInflight) {
                    Log.w(TAG, "refuse delete ${m.recordingId}: state=${m.upload.state}")
                    return false
                }
            } catch (t: Throwable) {
                Log.w(TAG, "delete: ignoring corrupted meta ${meta.absolutePath}")
            }
        }
        return dir.deleteRecursively()
    }

    /** 删除一个 _temp 目录（录音中途丢弃时使用）。 */
    fun discardTemp(tempDir: File) {
        if (tempDir.parentFile == this.tempDir) {
            tempDir.deleteRecursively()
        }
    }

    /** 包装一条扫描到的录音（meta + 物理目录）。 */
    data class ScanItem(val meta: RecordingMeta, val dir: File) {
        val audio: File get() = File(dir, AUDIO_FILE)
        val metaFile: File get() = File(dir, META_FILE)
        val hypothesis: File get() = File(dir, HYPOTHESIS_FILE)
    }

    companion object {
        private const val TAG = "RecordingStore"
        private const val ROOT_NAME = "asr-eval"
        private const val TEMP_NAME = "_temp"
        const val AUDIO_FILE = "audio.wav"
        const val META_FILE = "meta.json"
        const val HYPOTHESIS_FILE = "hypothesis.txt"
        private const val META_FILE_TMP = "meta.json.tmp"
    }
}
