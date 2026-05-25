package com.amphion.asr

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * 覆盖 [WeitnConfig.Builder] 的参数校验：
 *  - tagger / verbalizer 路径不存在 / 是目录 → IllegalArgumentException
 *  - 正常 build 返回字段一致的 immutable config
 *  - debug 开关生效
 *
 * 不覆盖 [WeitnEngine] 自身：构造需要 native .so 与真实 OpenFST 文件，
 * 这部分留给设备 instrumented test。
 */
class WeitnConfigTest {

    @get:Rule
    val tmp: TemporaryFolder = TemporaryFolder()

    private fun newFstFile(name: String): File {
        val f = tmp.newFile(name)
        f.writeBytes(ByteArray(64))
        return f
    }

    @Test
    fun build_withValidFiles_succeeds() {
        val tagger = newFstFile("zh_itn_tagger.fst")
        val verbalizer = newFstFile("zh_itn_verbalizer.fst")
        val cfg = WeitnConfig.Builder(tagger, verbalizer).build()
        assertEquals(tagger.absolutePath, cfg.taggerPath.absolutePath)
        assertEquals(verbalizer.absolutePath, cfg.verbalizerPath.absolutePath)
        assertFalse(cfg.debug)
    }

    @Test
    fun debug_takesEffect() {
        val tagger = newFstFile("zh_itn_tagger.fst")
        val verbalizer = newFstFile("zh_itn_verbalizer.fst")
        val cfg = WeitnConfig.Builder(tagger, verbalizer).debug(true).build()
        assertTrue(cfg.debug)
    }

    @Test
    fun build_taggerMissing_throws() {
        val missing = File(tmp.root, "missing_tagger.fst")
        val verbalizer = newFstFile("zh_itn_verbalizer.fst")
        val ex = assertThrows(IllegalArgumentException::class.java) {
            WeitnConfig.Builder(missing, verbalizer).build()
        }
        assertTrue(ex.message?.contains("tagger fst not found") == true)
    }

    @Test
    fun build_verbalizerMissing_throws() {
        val tagger = newFstFile("zh_itn_tagger.fst")
        val missing = File(tmp.root, "missing_verbalizer.fst")
        val ex = assertThrows(IllegalArgumentException::class.java) {
            WeitnConfig.Builder(tagger, missing).build()
        }
        assertTrue(ex.message?.contains("verbalizer fst not found") == true)
    }

    @Test
    fun build_taggerIsDirectory_throws() {
        val dir = tmp.newFolder("tagger-dir")
        val verbalizer = newFstFile("zh_itn_verbalizer.fst")
        val ex = assertThrows(IllegalArgumentException::class.java) {
            WeitnConfig.Builder(dir, verbalizer).build()
        }
        assertTrue(ex.message?.contains("tagger fst not found") == true)
    }
}
