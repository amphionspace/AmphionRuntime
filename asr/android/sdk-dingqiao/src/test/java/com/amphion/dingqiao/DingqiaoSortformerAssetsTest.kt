package com.amphion.dingqiao

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/**
 * 钉住资产就绪判定按**精确大小**比对。
 *
 * 这条不是假设出来的：改图后新旧 `spkcache_update` 只差 151 字节，旧文件反而更大，原先"不小于
 * 下限"的判定把旧的厂商图当成已就绪、从不替换，于是设备上一直跑旧图，排查了很久。
 */
class DingqiaoSortformerAssetsTest {
    @get:Rule val folder = TemporaryFolder()

    private fun write(dir: File, name: String, size: Int) {
        File(dir, name).apply { parentFile?.mkdirs() }.writeBytes(ByteArray(size))
    }

    @Test
    fun readinessRequiresEveryAssetAtItsExactSize() {
        val work = folder.newFolder("work")
        val dir = File(work, "sortformer-66M-4spk")
        val expected = sortformerExpectedSizes()
        for ((name, size) in expected) write(dir, name, size.toInt())
        assertTrue("all assets at their exact size", DingqiaoSpeakerModelAssets.isSortformerReady(work))

        // 比期望大一个字节也必须判未就绪：模型换版时新旧大小可能相近
        val (name, size) = expected.first()
        write(dir, name, size.toInt() + 1)
        assertFalse("a differently sized asset is not ready", DingqiaoSpeakerModelAssets.isSortformerReady(work))

        // 少一个字节同样不行
        write(dir, name, size.toInt() - 1)
        assertFalse("a truncated asset is not ready", DingqiaoSpeakerModelAssets.isSortformerReady(work))
    }

    @Test
    fun aMissingAssetIsNotReady() {
        val work = folder.newFolder("work")
        val dir = File(work, "sortformer-66M-4spk")
        val expected = sortformerExpectedSizes()
        for ((name, size) in expected.drop(1)) write(dir, name, size.toInt())
        assertFalse("one asset missing", DingqiaoSpeakerModelAssets.isSortformerReady(work))
    }

    /** 从被测对象自己读期望大小，避免测试里再抄一份清单。 */
    private fun sortformerExpectedSizes(): List<Pair<String, Long>> {
        val field = DingqiaoSpeakerModelAssets::class.java.getDeclaredField("SORTFORMER_ASSETS")
        field.isAccessible = true
        @Suppress("UNCHECKED_CAST")
        return field.get(DingqiaoSpeakerModelAssets) as List<Pair<String, Long>>
    }
}
