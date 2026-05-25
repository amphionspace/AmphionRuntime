package com.amphion.asr.internal

import java.io.File
import java.io.RandomAccessFile

/**
 * 通过扫描 encoder ONNX 文件头部的 metadata 区段，判断流式 zipformer 大版本（zipformer1 vs zipformer2）。
 *
 * 之所以需要这一层校验：sherpa-onnx 的 zipformer1 / zipformer2 走两套不同的 InitEncoder 代码路径，
 * 各自要从 ONNX `metadata_props` 读取的 key 不同：
 *
 * - `online-zipformer-transducer-model.cc:InitEncoder` 读 `attention_dims`
 * - `online-zipformer2-transducer-model.cc:InitEncoder` 读 `query_head_dims` / `value_head_dims`
 *
 * 当 manifest.json 的 `model_type` 写错（例如 zipformer2 模型写成 zipformer），sherpa-onnx 会走错路径
 * 找不到字段，C++ 直接 abort 整个进程，Java try/catch 接不住。所以在调 OnlineRecognizer 构造之前
 * 做一次轻量字节扫描校验，发现不一致直接抛 [com.amphion.asr.AsrErrorCode.MODEL_TYPE_MISMATCH]
 * fail-fast，避免 native abort。
 *
 * 实现原则：零依赖（不引 protobuf / onnxruntime jar），只读 encoder.onnx 末尾若干 KB 字节，
 * 在字节流里 ASCII 子串匹配特征 metadata key。ONNX 的 `metadata_props` 是 ModelProto 较高 field
 * 号的 repeated StringStringEntryProto，protobuf 序列化时排在 graph weights 之后，因此实测
 * (icefall export-onnx-streaming.py 输出) metadata 都在文件最末尾几百字节内。读末尾 256KB 足以覆盖。
 */
internal object ZipformerSignature {

    /** 字节扫描读取的最大字节数；ONNX 的 metadata 区段一般在文件末尾的 KB 级范围内。 */
    private const val MAX_BYTES_TO_READ: Int = 256 * 1024

    /** zipformer1 才有的 metadata key（`online-zipformer-transducer-model.cc:InitEncoder`）。 */
    private val ZIPFORMER1_KEY: ByteArray = "attention_dims".toByteArray(Charsets.US_ASCII)

    /** zipformer2 才有的 metadata key（`online-zipformer2-transducer-model.cc:InitEncoder`）。 */
    private val ZIPFORMER2_KEY: ByteArray = "query_head_dims".toByteArray(Charsets.US_ASCII)

    /** 检测结果。 */
    internal enum class Detected { ZIPFORMER1, ZIPFORMER2, UNKNOWN }

    /**
     * 扫描 encoder.onnx 末尾区段，返回检测到的 zipformer 大版本。
     *
     * 任何 IO / 解析异常都吞掉返回 [Detected.UNKNOWN]，让校验逻辑选择"宽松通过"，
     * 避免我们自己的检测器有 bug 时把原本能加载的模型 reject 掉。
     */
    fun detect(encoderFile: File): Detected {
        return try {
            val fileLen = encoderFile.length()
            val readLen = minOf(fileLen, MAX_BYTES_TO_READ.toLong()).toInt()
            if (readLen <= 0) return Detected.UNKNOWN
            val offset = fileLen - readLen
            val buf = ByteArray(readLen)
            RandomAccessFile(encoderFile, "r").use {
                it.seek(offset)
                it.readFully(buf, 0, readLen)
            }
            val hasZ2 = indexOfBytes(buf, ZIPFORMER2_KEY) >= 0
            val hasZ1 = indexOfBytes(buf, ZIPFORMER1_KEY) >= 0
            // 两个都命中时按 zipformer2 算（实际上两者互斥；若同现，新模型的可能性更大）
            when {
                hasZ2 -> Detected.ZIPFORMER2
                hasZ1 -> Detected.ZIPFORMER1
                else -> Detected.UNKNOWN
            }
        } catch (_: Throwable) {
            Detected.UNKNOWN
        }
    }

    /** 朴素子串查找；needle 通常 < 32 字节，O(n*m) 完全够用。 */
    private fun indexOfBytes(haystack: ByteArray, needle: ByteArray): Int {
        if (needle.isEmpty()) return 0
        val end = haystack.size - needle.size
        outer@ for (i in 0..end) {
            for (j in needle.indices) {
                if (haystack[i + j] != needle[j]) continue@outer
            }
            return i
        }
        return -1
    }
}
