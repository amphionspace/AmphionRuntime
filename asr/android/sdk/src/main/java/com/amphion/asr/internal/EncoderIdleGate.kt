package com.amphion.asr.internal

/**
 * 静音段不送 encoder 的门控（decoder 线程私有，无锁）。
 *
 * 为什么要它：流式 ASR 原本把全部 PCM（含静音）送进 encoder，静音时 encoder 照样满速跑；
 * 更糟的是纯静音流每隔 rule1 的尾静音阈值（2.4 s）就触发一次空端点 → 硬重启 stream →
 * 再喂 0.8 s 静音预热，客户锁屏场景约一半时间是静音，这部分算力全是白烧的。
 *
 * 两个状态：
 * - ACTIVE：与过去完全一致，PCM 全量进 ASR；
 * - IDLE：PCM 只进 VAD 和这里的预滚环，不碰 encoder。VAD 一看到 speech 窗口就 [resume]，
 *   把预滚（最近 [preRollMs] 毫秒）连同当前 chunk 一次性送进 encoder。
 *
 * 只在 stream 边界（端点后重启 / 软复位）进入 IDLE：那时 VAD 刚被 reset、stream 为空，
 * 不会有半句话悬在 encoder 里。预滚要盖住 silero 的起音确认延迟（minSpeechDuration 0.25 s
 * + 若干 32 ms 窗口）再留出 encoder 的左上下文，所以默认 1 s。
 *
 * 不负责判断"能不能门控"：目标说话人 / speaker VAD 等需要 stream 持有全部音频的模式，
 * 由调用方决定不进入 IDLE。
 */
internal class EncoderIdleGate(sampleRate: Int, preRollMs: Int) {
    private val capacity = (sampleRate.toLong() * preRollMs / 1000L).toInt().coerceAtLeast(1)
    private val ring = FloatArray(capacity)
    private var head = 0
    private var size = 0

    /** 当前是否处于 IDLE（PCM 不进 encoder）。 */
    var idle: Boolean = false
        private set

    /** 诊断计数：进入 IDLE 的次数、IDLE 期间跳过 encoder 的样本数、恢复次数。 */
    var idleEntries: Int = 0
        private set
    var idleSamples: Long = 0L
        private set
    var resumes: Int = 0
        private set

    /** 预滚环里当前保存的样本数（≤ 容量）。 */
    val bufferedSamples: Int get() = size

    fun enterIdle() {
        if (idle) return
        idle = true
        head = 0
        size = 0
        idleEntries += 1
    }

    /** IDLE 期间每个 chunk 调一次：样本进预滚环（满了丢最旧的），不送 encoder。 */
    fun observe(processed: FloatArray) {
        check(idle) { "observe() only while idle" }
        idleSamples += processed.size
        if (processed.size >= capacity) {
            System.arraycopy(processed, processed.size - capacity, ring, 0, capacity)
            head = 0
            size = capacity
            return
        }
        var i = 0
        while (i < processed.size) {
            val pos = (head + size) % capacity
            ring[pos] = processed[i]
            if (size < capacity) size += 1 else head = (head + 1) % capacity
            i += 1
        }
    }

    /** 退出 IDLE，返回按时间顺序排好的预滚样本（可能为空），调用方一次性送进 encoder。 */
    fun resume(): FloatArray {
        check(idle) { "resume() only while idle" }
        idle = false
        resumes += 1
        val out = FloatArray(size)
        var i = 0
        while (i < size) {
            out[i] = ring[(head + i) % capacity]
            i += 1
        }
        head = 0
        size = 0
        return out
    }

    /** 会话 stop/close：丢掉状态，但保留计数供收尾日志。 */
    fun reset() {
        idle = false
        head = 0
        size = 0
    }
}
