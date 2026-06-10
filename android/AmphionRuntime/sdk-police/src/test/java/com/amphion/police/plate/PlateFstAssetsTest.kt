package com.amphion.police.plate

import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** 验证车牌谐音 FST 已打入 assets。 */
class PlateFstAssetsTest {

    @Test
    fun fstAssets_existAndNonEmpty() {
        for (path in PlateFstAssets.ALL_FST) {
            val f = resolveAsset(path)
            assertTrue("missing $path", f.isFile)
            assertTrue("$path empty", f.length() > 0L)
        }
        for (path in listOf(PlateFstAssets.HOMOPHONE_META)) {
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
