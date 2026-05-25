package com.amphion.asr

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * 覆盖 [PunctuationConfig.Builder] 的参数校验：
 *  - modelPath 不存在 / 是目录 → IllegalArgumentException
 *  - numThreads 越界 → IllegalArgumentException
 *  - 正常 build 返回字段一致的 immutable config
 *
 * 不覆盖 [PunctuationEngine] 自身：构造需要 native .so 与 ONNX 模型，应放到设备 instrumented test。
 */
class PunctuationConfigTest {

    @get:Rule
    val tmp: TemporaryFolder = TemporaryFolder()

    private fun newModelFile(): File {
        val f = tmp.newFile("model.int8.onnx")
        f.writeBytes(ByteArray(16))
        return f
    }

    @Test
    fun build_withValidFile_succeeds() {
        val f = newModelFile()
        val cfg = PunctuationConfig.Builder(f).build()
        assertEquals(f.absolutePath, cfg.modelPath.absolutePath)
        assertEquals(1, cfg.numThreads)
        assertFalse(cfg.debug)
    }

    @Test
    fun build_withCustomNumThreadsAndDebug_takesEffect() {
        val f = newModelFile()
        val cfg = PunctuationConfig.Builder(f)
            .numThreads(4)
            .debug(true)
            .build()
        assertEquals(4, cfg.numThreads)
        assertEquals(true, cfg.debug)
    }

    @Test
    fun build_modelPathMissing_throws() {
        val missing = File(tmp.root, "does-not-exist.onnx")
        val ex = assertThrows(IllegalArgumentException::class.java) {
            PunctuationConfig.Builder(missing).build()
        }
        assertEquals(true, ex.message?.contains("punctuation model not found"))
    }

    @Test
    fun build_modelPathIsDirectory_throws() {
        val dir = tmp.newFolder("not-a-file")
        val ex = assertThrows(IllegalArgumentException::class.java) {
            PunctuationConfig.Builder(dir).build()
        }
        assertEquals(true, ex.message?.contains("punctuation model not found"))
    }

    @Test
    fun numThreads_outOfRange_throws() {
        val f = newModelFile()
        assertThrows(IllegalArgumentException::class.java) {
            PunctuationConfig.Builder(f).numThreads(0)
        }
        assertThrows(IllegalArgumentException::class.java) {
            PunctuationConfig.Builder(f).numThreads(9)
        }
    }
}
