package com.amphion.police.station

import android.content.Context
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.security.DigestInputStream
import java.security.MessageDigest

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
            context.assets.open(assetPath).use { input ->
                installIfChanged(input, out)
            }
            out
        }
    }

    /** 覆盖安装后若包内 FST 已变化，按内容哈希刷新旧缓存，再交给 native 加载。 */
    internal fun installIfChanged(input: InputStream, out: File) {
        out.parentFile?.mkdirs()
        val temp = File(out.parentFile, ".${out.name}.tmp-${System.nanoTime()}")
        try {
            val assetDigest = MessageDigest.getInstance("SHA-256")
            FileOutputStream(temp).use { output ->
                DigestInputStream(input, assetDigest).use { source -> source.copyTo(output) }
                output.fd.sync()
            }
            val same = out.isFile && out.length() == temp.length() &&
                MessageDigest.isEqual(assetDigest.digest(), sha256(out))
            if (same) return

            // POSIX/Android 通常可原子替换；极少数文件系统不支持时再退化为删除后重命名。
            if (!temp.renameTo(out)) {
                if (out.exists()) require(out.delete()) { "cannot replace cached FST: $out" }
                require(temp.renameTo(out)) { "cannot install cached FST: $out" }
            }
        } finally {
            if (temp.exists()) temp.delete()
        }
    }

    private fun sha256(file: File): ByteArray {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                if (read > 0) digest.update(buffer, 0, read)
            }
        }
        return digest.digest()
    }

    fun allPresent(context: Context): Boolean =
        ALL_FST.all { path ->
            runCatching {
                context.assets.open(path).use { it.read() }
                true
            }.getOrDefault(false)
        }
}
