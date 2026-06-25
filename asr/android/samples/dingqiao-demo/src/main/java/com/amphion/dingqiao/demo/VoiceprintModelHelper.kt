package com.amphion.dingqiao.demo

import com.amphion.dingqiao.DINGQIAO_SPEAKER_MODEL_FILENAME
import java.io.File

/** Demo 声纹模型就绪检测；模型由 SDK 内置并自动解包到工作目录。 */
object VoiceprintModelHelper {

    private const val MIN_BYTES = 30L * 1024 * 1024

    fun modelFile(workPath: String): File = File(workPath, DINGQIAO_SPEAKER_MODEL_FILENAME)

    fun isReady(file: File): Boolean =
        file.isFile && file.canRead() && file.length() >= MIN_BYTES
}
