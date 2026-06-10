package com.amphion.asr.sample.police_terms

import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** 验证警务术语 global FST 已打入 assets。 */
class PoliceTermsFstAssetsTest {

    @Test
    fun fstAssets_existAndNonEmpty() {
        for (path in PoliceTermsFstAssets.ALL_FST) {
            val f = resolveAsset(path)
            assertTrue("missing $path", f.isFile)
            assertTrue("$path empty", f.length() > 0L)
        }
        for (path in listOf(PoliceTermsFstAssets.GLOBAL_META)) {
            val f = resolveAsset(path)
            assertTrue("missing $path", f.isFile)
            assertTrue("$path empty", f.length() > 0L)
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
