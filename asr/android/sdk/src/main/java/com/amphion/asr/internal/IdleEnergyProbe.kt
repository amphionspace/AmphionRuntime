package com.amphion.asr.internal

import kotlin.math.log10
import kotlin.math.sqrt

/**
 * encoder IDLE 期间的保守能量唤醒；调用方传入即将送给 ASR 的 PCM，VAD 仍使用原始 PCM。
 *
 * 每 20 ms 音频判断一次，跨调用保留未满一窗的能量，不让调用分帧改变噪声底或稀释短起音。
 * 达到 [absoluteMinDb] 或比噪声底高 [riseDb] 任一条件即唤醒；进入 IDLE 后的第一窗同样生效。
 * 能量不能可靠区分稳定环境声和持续讲话，因此可闻环境声也允许保守唤醒。
 */
internal class IdleEnergyProbe(
    private val sampleRate: Int,
    private val riseDb: Float = 10f,
    private val floorRiseDbPerSec: Float = 1.0f,
    private val absoluteMinDb: Float = -60f,
) {
    private val windowSamples = (sampleRate / DECISIONS_PER_SECOND).coerceAtLeast(1)
    private var floorDb = Float.NaN
    private var armed = false
    private var pendingSamples = 0
    private var pendingEnergy = 0.0

    init {
        require(sampleRate > 0) { "sampleRate must be positive" }
    }

    /** 调用方在 IDLE 中据此切片，在决定唤醒前不继续覆盖预滚音频。 */
    val samplesUntilNextDecision: Int
        get() = windowSamples - pendingSamples

    fun arm() {
        floorDb = Float.NaN
        pendingSamples = 0
        pendingEnergy = 0.0
        armed = true
    }

    fun disarm() {
        armed = false
        pendingSamples = 0
        pendingEnergy = 0.0
    }

    /** 消费所有输入，任一完整音频窗需要唤醒即返回 true。 */
    fun observe(samples: FloatArray): Boolean {
        if (!armed || samples.isEmpty()) return false
        var wake = false
        for (sample in samples) {
            pendingEnergy += sample.toDouble() * sample
            pendingSamples += 1
            if (pendingSamples == windowSamples) {
                if (observeWindow()) wake = true
                pendingSamples = 0
                pendingEnergy = 0.0
            }
        }
        return wake
    }

    private fun observeWindow(): Boolean {
        val rms = sqrt(pendingEnergy / windowSamples)
        val db = if (rms <= 1e-7) -140f else (20.0 * log10(rms)).toFloat()
        val relativeWake = !floorDb.isNaN() && db >= floorDb + riseDb
        floorDb = when {
            floorDb.isNaN() || db < floorDb -> db
            else -> minOf(db, floorDb + floorRiseDbPerSec * windowSamples / sampleRate)
        }
        return db >= absoluteMinDb || relativeWake
    }

    private companion object {
        const val DECISIONS_PER_SECOND = 50
    }
}
