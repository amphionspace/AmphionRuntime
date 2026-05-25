package com.amphion.asr.sample

import android.content.Context
import android.util.Log
import java.io.File
import java.io.FileOutputStream

/**
 * Sample-only：把 `externalFilesDir/asr-punct-import/model.int8.onnx` 一次性搬到
 * `filesDir/asr-punct/model.int8.onnx`，提供给 SDK 的 [com.amphion.asr.PunctuationEngine]。
 *
 * 资源约定：
 *  - 用户通过 [tools/asr/00_push_punct_model.sh](../../../../../../../../../../../tools/asr/00_push_punct_model.sh)
 *    把官方 INT8 模型推到 external `asr-punct-import/` 目录
 *  - sample 启动时调用 [installOrLocate]，把模型搬到 internal filesDir 让 native 可读
 *  - 搬完后清理 external 源文件，避免下次启动重复 import
 *  - 之后即使 external 被清空，模型仍常驻 internal，直到调用方主动删除
 *
 * 设计与 [WeitnAssetInstaller] / [ModelImporter] 同款：所有 IO 异常都吞掉返回 null，
 * 让上层 UI 通过 Switch 灰禁 + 状态提示分支兜底，不抛崩 app。
 *
 * 不做 sha256 校验：tools/asr/00_push_punct_model.sh 已经在 push 前算过 sha256，
 * 运行期 size 兜底即可；标点模型从未由 SDK 主动篡改，无需重复校验。
 */
class PunctModelInstaller(private val context: Context) {

    private val tag = "AsrSamplePunct"

    /**
     * 优先：external 有则搬到 internal；否则查 internal 是否已有上一次搬过的副本。
     *
     * 返回值：成功时返回 internal 路径；都没有 / 拷贝失败时返回 null。
     */
    fun installOrLocate(): File? {
        val dstDir = File(context.filesDir, INTERNAL_SUBDIR).apply { mkdirs() }
        val dst = File(dstDir, MODEL_FILENAME)

        val external = context.getExternalFilesDir(null)
        val src = external?.let { File(it, "$EXTERNAL_SUBDIR/$MODEL_FILENAME") }

        if (src != null && src.isFile) {
            val needCopy = !dst.isFile || dst.length() != src.length()
            if (needCopy) {
                Log.i(tag, "importing ${src.absolutePath} -> ${dst.absolutePath}")
                if (!copyTo(src, dst)) {
                    return null
                }
            } else {
                Log.i(tag, "skip existing ${dst.absolutePath} (size=${dst.length()})")
            }
            // 清空 external 源（包括 import 目录），避免下次启动重复 import
            try {
                src.delete()
                src.parentFile?.takeIf { it.exists() }?.deleteRecursively()
            } catch (t: Throwable) {
                Log.w(tag, "cleanup external failed: ${t.message}")
            }
            return dst
        }

        // external 里没有：看 internal 是不是上次已经搬过
        return if (dst.isFile) {
            Log.i(tag, "located existing ${dst.absolutePath} (size=${dst.length()})")
            dst
        } else {
            Log.i(
                tag,
                "no punct model found (external=${src?.absolutePath} internal=${dst.absolutePath})"
            )
            null
        }
    }

    private fun copyTo(src: File, dst: File): Boolean = try {
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

    private companion object {
        const val EXTERNAL_SUBDIR = "asr-punct-import"
        const val INTERNAL_SUBDIR = "asr-punct"
        const val MODEL_FILENAME = "model.int8.onnx"
    }
}
