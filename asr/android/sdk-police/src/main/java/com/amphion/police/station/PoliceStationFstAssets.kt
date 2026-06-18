package com.amphion.police.station

import android.content.Context
import java.io.File

/**
 * 派出所场景 FST 资源（PC 编译产物，见 police_station_fst_experiment）。
 *
 * 方案 A：global + polish 走 FST；gazetteer 谐音与最长匹配仍在宿主。
 * 运行时加载需 kaldifst TextNormalizer JNI（与 sherpa rule_fsts 同类），尚未接入时回退 Kotlin 规则。
 */
object PoliceStationFstAssets {

    const val DIR = "police_station"
    const val GLOBAL_FST = "$DIR/station_global.fst"
    const val POLISH_FST = "$DIR/station_polish.fst"
    const val GAZETTEER_FST = "$DIR/station_gazetteer.fst"

    const val GLOBAL_META = "$DIR/station_global_meta.json"
    const val POLISH_META = "$DIR/station_polish_meta.json"
    const val GAZETTEER_META = "$DIR/station_gazetteer_meta.json"

    val ALL_FST = listOf(GLOBAL_FST, POLISH_FST, GAZETTEER_FST)

    fun cacheDir(context: Context): File =
        File(context.filesDir, "police_station_fst").apply { mkdirs() }

    /** 将 assets 中的 FST 解压到 filesDir，供后续 native TextNormalizer 加载。 */
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
