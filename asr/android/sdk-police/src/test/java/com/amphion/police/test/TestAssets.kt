package com.amphion.police.test

import java.io.File

object TestAssets {

    fun resolve(relativePath: String): File {
        val relPaths = listOf(
            "src/main/assets/$relativePath",
            "sdk-police/src/main/assets/$relativePath",
            "sample/src/main/assets/$relativePath",
        )
        var dir: File? = File(System.getProperty("user.dir") ?: ".")
        repeat(10) {
            val base = dir ?: return@repeat
            for (rel in relPaths) {
                val f = File(base, rel)
                if (f.isFile) return f
            }
            dir = base.parentFile
        }
        error("asset not found: $relativePath")
    }
}
