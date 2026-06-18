package com.amphion.asr

/**
 * 端侧 ASR 标准指标。Android 与未来鸿蒙端按同一份 schema 输出，业务方可
 * 通过 logcat（tag = AmphionMetrics）或者 [AsrCallback.onMetrics] 拿到。
 *
 * 派发时机：
 * - [AmphionMetricsKind.UTTERANCE]：每段话 onFinal 同帧派发；第一段会附带 engine 启动期字段
 *   （[assetInstallMs] / [engineReadyMs] / [nativeRssMbAtReady]），后续段为 -1
 * - [AmphionMetricsKind.SESSION]：[AsrEngine.close] 时派发一次，汇总该 engine 生命周期内
 *   所有 utterance 的统计
 *
 * 时间戳基准为 [android.os.SystemClock.elapsedRealtime]（不受系统挂起影响）。
 * 长度未知或不适用的字段统一用 -1（数值字段）/ -1f（浮点字段）/ 空字符串（文本字段）作 sentinel。
 */
public data class AmphionMetrics(
    /** 区分本次派发是 utterance 维度还是 session 总结。 */
    public val kind: AmphionMetricsKind,
    /** 当前 engine 绑定的语言。 */
    public val language: AsrLanguage,
    /** 触发本次派发的 session id（session 维度时是该 engine 最后一个 session）。 */
    public val sessionId: Int,

    // -------- 启动期（仅 UTTERANCE 类型的第一段 metrics 上非默认值） --------

    /** 本次 create / preload 触发的资产解包累计耗时；已 cache 时为 0；非首段时为 -1。 */
    public val assetInstallMs: Long = -1L,
    /** 解包字节数；非首段时为 -1。 */
    public val assetTotalBytes: Long = -1L,
    /** 从 [AmphionRuntime.create] / [AmphionRuntime.preload] 调用入口到 engine ready 的耗时；非首段为 -1。 */
    public val engineReadyMs: Long = -1L,
    /** engine ready 时刻的 native VmRSS（MB）；非首段为 -1。 */
    public val nativeRssMbAtReady: Int = -1,

    // -------- utterance 维度（仅 UTTERANCE 类型有效） --------

    /** 该 engine 上 utterance 序号，从 1 开始；SESSION 类型为 -1。 */
    public val utteranceIndex: Int = -1,
    /** 本段音频时长（pcmBytes / sampleRate / bytesPerSample）。 */
    public val utteranceDurationMs: Long = -1L,
    /** 第一帧 PCM accept → raw final 出来；不含后处理。 */
    public val decodeDurationMs: Long = -1L,
    /** ITN + 标点合计耗时。 */
    public val postProcessMs: Long = -1L,
    /** 第一帧 PCM accept → 第一个 partial 派发；本段无 partial 时为 -1。 */
    public val firstPartialLatencyMs: Long = -1L,
    /** endpoint 命中 → onFinal 派发；非 endpoint 触发的 final 为 -1。 */
    public val endpointToFinalLatencyMs: Long = -1L,
    /** 第一帧 PCM accept → onFinal 派发。 */
    public val utteranceE2eLatencyMs: Long = -1L,
    /** decodeDurationMs / utteranceDurationMs；< 1 才能流式跟上实时。 */
    public val rtf: Float = -1f,
    /** 本段处理期间 native RSS 增量（MB）；用于看是否泄漏。 */
    public val nativeRssMbDelta: Int = 0,
    /** 本段结束时刻读到的 native VmRSS 绝对值（MB）；UI 显示推荐用这个。 */
    public val nativeRssMb: Int = -1,
    /** 本段累计接收 PCM 字节数。 */
    public val pcmBytesAccepted: Long = -1L,

    // -------- session 维度（仅 SESSION 类型有效） --------

    /** 该 engine 生命周期内识别的 utterance 总数。 */
    public val totalUtterances: Int = -1,
    /** 该 engine 生命周期内累计接收的 PCM 字节数。 */
    public val totalPcmBytes: Long = -1L,
    /** RTF 算术平均；样本不足时为 -1f。 */
    public val avgRtf: Float = -1f,
    /** RTF p95 分位数；样本数 < 5 时退化为最大值；样本 0 时为 -1f。 */
    public val p95Rtf: Float = -1f,
    /** 该 engine 生命周期内的 native RSS 峰值（MB）。 */
    public val peakNativeRssMb: Int = -1,
) {

    /**
     * 序列化成一行 KV 文本，跟 logcat 输出格式一致（tag 由 Logger 自己加）。
     * KV 之间用空格分隔，字符串字段不会出现空格，方便直接 grep / awk。
     */
    public fun toLogLine(): String {
        val sb = StringBuilder(256)
        sb.append("kind=").append(kind.name)
        sb.append(" language=").append(language.name)
        sb.append(" sessionId=").append(sessionId)
        when (kind) {
            AmphionMetricsKind.UTTERANCE -> {
                sb.append(" utteranceIndex=").append(utteranceIndex)
                sb.append(" utteranceDurationMs=").append(utteranceDurationMs)
                sb.append(" decodeDurationMs=").append(decodeDurationMs)
                sb.append(" postProcessMs=").append(postProcessMs)
                sb.append(" firstPartialLatencyMs=").append(firstPartialLatencyMs)
                sb.append(" endpointToFinalLatencyMs=").append(endpointToFinalLatencyMs)
                sb.append(" utteranceE2eLatencyMs=").append(utteranceE2eLatencyMs)
                sb.append(" rtf=").append(formatFloat(rtf))
                sb.append(" nativeRssMb=").append(nativeRssMb)
                sb.append(" nativeRssMbDelta=").append(nativeRssMbDelta)
                sb.append(" pcmBytesAccepted=").append(pcmBytesAccepted)
                if (assetInstallMs >= 0L) {
                    sb.append(" assetInstallMs=").append(assetInstallMs)
                    sb.append(" assetTotalBytes=").append(assetTotalBytes)
                    sb.append(" engineReadyMs=").append(engineReadyMs)
                    sb.append(" nativeRssMbAtReady=").append(nativeRssMbAtReady)
                }
            }
            AmphionMetricsKind.SESSION -> {
                sb.append(" totalUtterances=").append(totalUtterances)
                sb.append(" totalPcmBytes=").append(totalPcmBytes)
                sb.append(" avgRtf=").append(formatFloat(avgRtf))
                sb.append(" p95Rtf=").append(formatFloat(p95Rtf))
                sb.append(" peakNativeRssMb=").append(peakNativeRssMb)
                sb.append(" nativeRssMb=").append(nativeRssMb)
            }
        }
        return sb.toString()
    }

    private fun formatFloat(f: Float): String =
        if (f < 0f) "-1" else String.format(java.util.Locale.ROOT, "%.3f", f)
}

/** [AmphionMetrics] 派发类型。 */
public enum class AmphionMetricsKind {
    /** 每段话 onFinal 同帧派发。 */
    UTTERANCE,

    /** [AsrEngine.close] 时派发一次，汇总该 engine 生命周期。 */
    SESSION,
}
