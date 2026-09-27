package com.amphion.dingqiao.demo

import org.junit.Assert.*
import org.junit.Test
import java.io.File

class WavFileInputTest {
    @Test
    fun fileInputKeepsActualPcmAndRejectsUnsupportedRateOrPartialFrame() {
        val file = File.createTempFile("demo-input", ".wav")
        try {
            val pcm = ByteArray(1280) { (it % 127).toByte() }
            WavIo.writePcmBytes(file, pcm)
            assertArrayEquals(pcm, WavIo.readDemoInput(file))
            WavIo.writePcmBytes(file, pcm, 8000)
            assertThrows(IllegalArgumentException::class.java) { WavIo.readDemoInput(file) }
            WavIo.writePcmBytes(file, pcm.copyOf(1278))
            assertThrows(IllegalArgumentException::class.java) { WavIo.readDemoInput(file) }
            file.writeBytes(byteArrayOf(1, 2, 3))
            assertThrows(IllegalArgumentException::class.java) { WavIo.readDemoInput(file) }
        } finally { file.delete() }
    }
}
