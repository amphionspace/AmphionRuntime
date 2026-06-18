package com.amphion.police.plate

import android.content.Context
import java.io.File

/**
 * 车牌场景 FST 资源（PC 编译产物，见 plate_fst_experiment）。
 *
 * 方案 A：仅谐音表走 FST；省别锚点 / 冀R / 辽B / 校验仍在 [PlateNormalizer] 宿主。
 */
object PlateFstAssets {

    const val DIR = "plate"
    const val HOMOPHONE_FST = "$DIR/plate_homophone.fst"
    const val HOMOPHONE_META = "$DIR/plate_homophone_meta.json"

    val ALL_FST = listOf(HOMOPHONE_FST)

    fun cacheDir(context: Context): File =
        File(context.filesDir, "plate_fst").apply { mkdirs() }

    fun ensureCached(context: Context): List<File> {
        val outDir = cacheDir(context)
        return ALL_FST.map { assetPath ->
            val name = assetPath.substringAfterLast('/')
            val out = File(outDir, name)
            if (!out.isFile || out.length() == 0L) {
                context.assets.open(assetPath).use { input ->
                    out.outputStream().use { output -> input.copyTo(output) }
                }
            }
            out
        }
    }

    fun allPresent(context: Context): Boolean =
        ALL_FST.all { path ->
            runCatching {
                context.assets.open(path).use { it.read() }
                true
            }.getOrDefault(false)
        }
}
