package com.amphion.asr.internal

import java.io.File

/**
 * 从 /proc/self/status 读当前进程的 VmRSS（resident set size），返回 MB。
 *
 * VmRSS 包含了应用 native 堆 + JVM 堆 + so 文件 mmap + Zygote 共享部分；不是「纯 SDK
 * 内存占用」，但是是衡量 native 模型加载前后差量最可靠、最简单的指标，与 Linux/Android
 * 工具链（dumpsys meminfo / showmap）口径一致。
 *
 * 失败返回 -1（业务方需要按 sentinel 处理）。
 */
internal object ProcessRssReader {

    fun readNativeRssMb(): Int {
        return try {
            val text = File("/proc/self/status").readText()
            val line = text.lineSequence().firstOrNull { it.startsWith("VmRSS:") } ?: return -1
            // 形如 "VmRSS:   123456 kB"
            val kb = line
                .substringAfter("VmRSS:")
                .trim()
                .split(Regex("\\s+"))
                .firstOrNull { it.toLongOrNull() != null }
                ?.toLongOrNull()
                ?: return -1
            (kb / 1024L).toInt()
        } catch (_: Throwable) {
            -1
        }
    }
}
