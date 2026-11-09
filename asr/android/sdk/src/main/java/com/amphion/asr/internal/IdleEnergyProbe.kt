package com.amphion.asr.internal

import kotlin.math.log10
import kotlin.math.max
import kotlin.math.sqrt

/**
 * encoder IDLE 期间的能量兜底唤醒。
 *
 * 门控的唤醒不能只靠 silero 的二值状态：真机上出现过同一段音频、同一构建下 silero 迟了约 25 s 才报
 * 起音，IDLE 期间 encoder 不跑，这 25 s 的话就整段丢了（对照臂的 ASR 自己是能认出来的）。
 * 这里在 IDLE 期间跟踪原始 PCM 的噪声底（慢升快降的最小值），任一 chunk 的 RMS 高出噪声底
 * [riseDb] 以上就要求唤醒。唤醒错了只是多跑一次 encoder、2.4 s 后端点再回到 IDLE，方向安全；
 * 漏唤醒才会丢字，所以宁可敏感。
 */
internal class IdleEnergyProbe(
    private val sampleRate: Int,
    private val riseDb: Float = 10f,
    private val floorRiseDbPerSec: Float = 1.0f,
    private val absoluteMinDb: Float = -60f,
) {
    private var floorDb = Float.NaN
    private var armed = false

    /** 进入 IDLE 时调用：噪声底从头学，前 [WARMUP_CHUNKS] 个 chunk 只学不判。 */
    fun arm() {
        floorDb = Float.NaN
        warmupLeft = WARMUP_CHUNKS
        armed = true
    }

    fun disarm() {
        armed = false
    }

    private var warmupLeft = 0

    /** IDLE 期间每个 chunk 调一次；返回 true 表示能量明显高于噪声底，应当唤醒。 */
    fun observe(raw: FloatArray): Boolean {
        if (!armed || raw.isEmpty()) return false
        val db = rmsDb(raw)
        val seconds = raw.size.toFloat() / sampleRate
        if (floorDb.isNaN()) {
            floorDb = db
        } else if (db < floorDb) {
            floorDb = db                                  // 快降
        } else {
            floorDb = minOf(db, floorDb + floorRiseDbPerSec * seconds)   // 慢升
        }
        if (warmupLeft > 0) {
            warmupLeft -= 1
            return false
        }
        return db >= max(floorDb + riseDb, absoluteMinDb)
    }

    private fun rmsDb(x: FloatArray): Float {
        var acc = 0.0
        for (v in x) acc += v.toDouble() * v
        val rms = sqrt(acc / x.size)
        return if (rms <= 1e-7) -140f else (20.0 * log10(rms)).toFloat()
    }

    private companion object {
        const val WARMUP_CHUNKS = 2
    }
}
