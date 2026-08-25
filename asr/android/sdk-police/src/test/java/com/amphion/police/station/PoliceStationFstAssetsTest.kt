package com.amphion.police.station

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.File
import java.nio.file.Files

/** P3：验证 FST 资源已打入 assets（PC P0–P3 通过后 sync_fsts_to_sample.sh 同步）。 */
class PoliceStationFstAssetsTest {

    @Test
    fun fstAssets_existAndNonEmpty() {
        for (path in PoliceStationFstAssets.ALL_FST) {
            val f = resolveAsset(path)
            assertTrue("missing $path", f.isFile)
            assertTrue("$path empty", f.length() > 0L)
        }
        for (path in listOf(
                PoliceStationFstAssets.GLOBAL_META,
                PoliceStationFstAssets.POLISH_META,
                PoliceStationFstAssets.GAZETTEER_META,
            )) {
            val f = resolveAsset(path)
            assertTrue("missing $path", f.isFile)
            assertTrue("$path empty", f.length() > 0L)
        }
    }

    @Test
    fun cachedAsset_isRefreshedWhenPackagedBytesChange() {
        val dir = Files.createTempDirectory("station-fst-cache").toFile()
        try {
            val out = File(dir, "station_global.fst")
            out.writeText("old", Charsets.UTF_8)
            PoliceStationFstAssets.installIfChanged(
                ByteArrayInputStream("new-fst".toByteArray(Charsets.UTF_8)),
                out,
            )
            assertEquals("new-fst", out.readText(Charsets.UTF_8))
        } finally {
            dir.deleteRecursively()
        }
    }

    private fun resolveAsset(rel: String): File {
        val roots = listOf("src/main/assets", "sample/src/main/assets")
        val cwd = File(System.getProperty("user.dir") ?: ".")
        for (base in listOfNotNull(cwd, cwd.parentFile)) {
            for (r in roots) {
                val f = File(base, "$r/$rel")
                if (f.isFile) return f
            }
        }
        error("asset not found: $rel")
    }
}
