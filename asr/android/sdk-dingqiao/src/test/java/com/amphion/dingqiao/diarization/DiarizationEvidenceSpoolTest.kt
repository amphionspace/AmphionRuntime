package com.amphion.dingqiao.diarization

import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files

class DiarizationEvidenceSpoolTest {
    private fun window(seed: Float, runs: Int) = CommunityDiarizationWindow(
        FloatArray(589 * 3) { seed + it }, FloatArray(768) { seed - it }, 0.0, 0.0, 0.0,
        FloatArray(runs * 256) { seed * 10 + it }, FloatArray(runs * 4) { if (it % 4 == 0) 0f else it.toFloat() },
        FloatArray(runs) { seed + it / 10f })

    @Test fun prefixReadsKeepEveryWindowAndRenumberRunWindows() {
        val directory = Files.createTempDirectory("evidence-spool").toFile()
        try {
            val spool = DiarizationEvidenceSpool(directory)
            val windows = listOf(window(1f, 2), window(2f, 0), window(3f, 1))
            windows.forEach { spool.append(it.segments, it.embeddings, it.runEmbeddings, it.runRanges, it.runRms) }
            val all = spool.read(3)
            assertArrayEquals(windows.flatMap { it.segments.toList() }.toFloatArray(), all.segments, 0f)
            assertArrayEquals(windows.flatMap { it.embeddings.toList() }.toFloatArray(), all.embeddings, 0f)
            assertArrayEquals(windows.flatMap { it.runEmbeddings.toList() }.toFloatArray(), all.runEmbeddings, 0f)
            assertArrayEquals(windows.flatMap { it.runRms.toList() }.toFloatArray(), all.runRms, 0f)
            // Run ranges carry the position of their window inside this snapshot.
            assertEquals(listOf(0f, 0f, 2f), (0 until 3).map { all.runRanges[it * 4] })
            assertEquals(windows[2].runRanges.drop(1), all.runRanges.drop(9).toList())
            val prefix = spool.read(2)
            assertEquals(2 * 589 * 3, prefix.segments.size)
            assertEquals(2 * 256, prefix.runEmbeddings.size)
            assertEquals(listOf(0f, 0f), listOf(prefix.runRanges[0], prefix.runRanges[4]))
            assertThrows(IllegalArgumentException::class.java) { spool.read(4) }
            assertThrows(IllegalArgumentException::class.java) {
                spool.append(FloatArray(10), FloatArray(768))
            }
            assertThrows(IllegalArgumentException::class.java) {
                spool.append(FloatArray(589 * 3), FloatArray(768), FloatArray(256), FloatArray(4), FloatArray(0))
            }
            assertEquals(3, spool.windows)
            spool.remove()
            assertTrue(directory.listFiles().isNullOrEmpty())
        } finally { directory.deleteRecursively() }
    }
}
