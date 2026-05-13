package com.amphion.asr.sample

import android.content.Context
import android.util.Log
import java.io.File

/**
 * Sample-only：把 `externalFilesDir/asr-models-import/<id>/<v>/` 一次性导入到
 * `filesDir/asr-models/<id>/<v>/`，使 SDK 的 ModelManager.listLocal() 能找到它。
 *
 * 设计为给 demo / 调试用：你只需要 adb push 模型到外部存储，重启 app 就生效。
 * 这一类逻辑不放在 SDK 里，避免污染公开 API。
 */
class ModelImporter(private val context: Context) {

    private val tag = "AsrSampleImporter"

    /** 返回这次新 import 的目录列表（绝对路径）。同名目录已存在则跳过该 (id, version)。 */
    fun importIfPresent(): List<File> {
        val srcRoot = File(context.getExternalFilesDir(null), "asr-models-import")
        if (!srcRoot.isDirectory) return emptyList()

        val dstRoot = File(context.filesDir, "asr-models")
        val imported = mutableListOf<File>()

        for (modelDir in srcRoot.listFiles().orEmpty()) {
            if (!modelDir.isDirectory) continue
            for (versionDir in modelDir.listFiles().orEmpty()) {
                if (!versionDir.isDirectory) continue

                val dst = File(dstRoot, "${modelDir.name}/${versionDir.name}")
                if (dst.isDirectory && File(dst, "tokens.txt").isFile) {
                    Log.i(tag, "skip existing $dst")
                    continue
                }

                Log.i(tag, "importing ${versionDir.absolutePath} -> $dst")
                dst.parentFile?.mkdirs()
                if (dst.exists()) dst.deleteRecursively()
                versionDir.copyRecursively(dst, overwrite = true)
                imported.add(dst)
            }
        }

        // 全部成功后清理外部目录，避免下次启动重复 import
        if (imported.isNotEmpty()) {
            Log.i(tag, "cleanup $srcRoot")
            srcRoot.deleteRecursively()
        }
        return imported
    }
}
