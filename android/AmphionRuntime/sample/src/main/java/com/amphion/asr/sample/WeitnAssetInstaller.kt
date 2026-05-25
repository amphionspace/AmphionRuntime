package com.amphion.asr.sample

import android.content.Context
import android.util.Log
import java.io.File
import java.io.FileOutputStream

/**
 * Sample-only：把 `externalFilesDir/asr-weitn-import/{zh_itn_tagger.fst,zh_itn_verbalizer.fst}`
 * 一次性搬到 `filesDir/asr-weitn/`，提供给 SDK 的 [com.amphion.asr.WeitnEngine]。
 *
 * 资源约定：
 *  - 用户通过 [tools/asr/00_push_weitn_fsts.sh](../../../../../../../../../../../tools/asr/00_push_weitn_fsts.sh)
 *    把 WeTextProcessing 编出的两份 fst push 到 external `asr-weitn-import/` 目录
 *  - sample 启动时调用 [installOrLocate]，把 fst 搬到 internal filesDir 让 native 可读
 *  - 搬完后清理 external 源文件，避免下次启动重复 import
 *  - 之后即使 external 被清空，fst 仍常驻 internal，直到调用方主动删除
 *
 * 设计跟 [PunctModelInstaller] 同款：所有 IO 异常都吞掉返回 null，让上层 UI
 * 通过 Switch 灰禁 + 状态提示分支兜底，不抛崩 app。
 *
 * 不做 sha256 校验：tools/asr/00_push_weitn_fsts.sh 已经在 push 前算过 sha256
 * （或由 pip build 流程把版本锁死），运行期 size 兜底即可。
 */
class WeitnAssetInstaller(private val context: Context) {

    private val tag = "AsrSampleWeitn"

    /** 同时返回 tagger 与 verbalizer 两个文件；任何一份缺失都返回 null。 */
    data class Installed(val tagger: File, val verbalizer: File)

    /**
     * 优先：external 有则搬到 internal；否则查 internal 是否已有上一次搬过的副本。
     *
     * 返回值：成功时返回两个 internal 路径；任何一份缺失 / 拷贝失败时返回 null。
     */
    fun installOrLocate(): Installed? {
        val dstDir = File(context.filesDir, INTERNAL_SUBDIR).apply { mkdirs() }
        val dstTagger = File(dstDir, TAGGER_FILENAME)
        val dstVerbalizer = File(dstDir, VERBALIZER_FILENAME)

        val external = context.getExternalFilesDir(null)
        val srcDir = external?.let { File(it, EXTERNAL_SUBDIR) }
        val srcTagger = srcDir?.let { File(it, TAGGER_FILENAME) }
        val srcVerbalizer = srcDir?.let { File(it, VERBALIZER_FILENAME) }

        if (srcTagger != null && srcVerbalizer != null &&
            srcTagger.isFile && srcVerbalizer.isFile
        ) {
            if (!copyIfNeeded(srcTagger, dstTagger)) return null
            if (!copyIfNeeded(srcVerbalizer, dstVerbalizer)) return null
            // 清空 external 源目录，避免下次启动重复 import
            try {
                srcDir.deleteRecursively()
            } catch (t: Throwable) {
                Log.w(tag, "cleanup external failed: ${t.message}")
            }
            return Installed(dstTagger, dstVerbalizer)
        }

        return if (dstTagger.isFile && dstVerbalizer.isFile) {
            Log.i(
                tag,
                "located existing tagger=${dstTagger.absolutePath} (${dstTagger.length()}B) " +
                    "verbalizer=${dstVerbalizer.absolutePath} (${dstVerbalizer.length()}B)",
            )
            Installed(dstTagger, dstVerbalizer)
        } else {
            Log.i(
                tag,
                "no weitn fsts found (external=${srcDir?.absolutePath} " +
                    "internalTagger=${dstTagger.absolutePath} " +
                    "internalVerbalizer=${dstVerbalizer.absolutePath})",
            )
            null
        }
    }

    private fun copyIfNeeded(src: File, dst: File): Boolean {
        val needCopy = !dst.isFile || dst.length() != src.length()
        if (!needCopy) {
            Log.i(tag, "skip existing ${dst.absolutePath} (size=${dst.length()})")
            return true
        }
        Log.i(tag, "importing ${src.absolutePath} -> ${dst.absolutePath}")
        return try {
            src.inputStream().use { input ->
                FileOutputStream(dst).use { output -> input.copyTo(output) }
            }
            Log.i(tag, "installed ${dst.absolutePath} size=${dst.length()}")
            true
        } catch (t: Throwable) {
            Log.w(tag, "copy ${src.name} to ${dst.absolutePath} failed: ${t.message}")
            dst.delete()
            false
        }
    }

    private companion object {
        const val EXTERNAL_SUBDIR = "asr-weitn-import"
        const val INTERNAL_SUBDIR = "asr-weitn"
        const val TAGGER_FILENAME = "zh_itn_tagger.fst"
        const val VERBALIZER_FILENAME = "zh_itn_verbalizer.fst"
    }
}
