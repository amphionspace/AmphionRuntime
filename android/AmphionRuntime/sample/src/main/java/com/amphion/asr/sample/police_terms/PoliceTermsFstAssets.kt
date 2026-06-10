package com.amphion.asr.sample.police_terms

import android.content.Context
import java.io.File

/**
 * 警务术语场景 FST 资源（PC 编译产物，见 police_terms_fst_experiment）。
 *
 * 方案 A：global FST 替代 [PoliceTermsHomophoneDict.applyPhrases]；gazetteer 仍在宿主。
 */
object PoliceTermsFstAssets {

    const val DIR = "police_terms"
    const val GLOBAL_FST = "$DIR/terms_global.fst"
    const val GLOBAL_META = "$DIR/terms_global_meta.json"

    val ALL_FST = listOf(GLOBAL_FST)

    fun cacheDir(context: Context): File =
        File(context.filesDir, "police_terms_fst").apply { mkdirs() }

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
