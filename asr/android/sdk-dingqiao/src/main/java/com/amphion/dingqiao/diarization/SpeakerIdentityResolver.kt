package com.amphion.dingqiao.diarization

import com.amphion.asr.internal.SpeakerIdentityAssigner
import kotlin.math.min

/** 给一段 16 kHz 单声道音频算声纹嵌入；算不出时返回 null。 */
internal typealias SpeakerEmbedFn = (samples: FloatArray) -> FloatArray?

/**
 * 把 Sortformer 的发言段换成声纹身份：取回该段音频 -> 算嵌入 -> 增量分配。
 * 与鸿蒙 `SpeakerIdentityResolver.ets` 同一套规则与常量。
 *
 * 嵌入函数是**注入**的，不在这里加载模型：既让本文件能在没有声纹模型的环境下完整单测，
 * 也让调用方决定 extractor 的生命周期（引擎级共享，模型只加载一次）。
 *
 * 时序约束：嵌入必须在**会话期间**逐段算完（块提交回调里），提交与收尾路径只做分配器那几
 * 微秒的算术——收尾路径余量很小，把嵌入堆在 finish 会顶破它。
 */
internal class SpeakerIdentityResolver(
    sampleRate: Int,
    maxSpeakers: Int,
    private val embed: SpeakerEmbedFn,
    retainSeconds: Double = DiarizationPcmWindow.RETAIN_SECONDS,
) {
    private val window = DiarizationPcmWindow(sampleRate, retainSeconds)
    private val assigner = SpeakerIdentityAssigner(maxSpeakers)
    /** 取不到音频的段数，用于诊断：持续非零说明保留窗太短或轨道报得太晚。 */
    var audioMissCount: Int = 0
        private set
    /** 嵌入失败的段数。 */
    var embedFailureCount: Int = 0
        private set

    /** 分流一份近期 PCM。必须与喂给推理客户端的是同一批字节、同一顺序。 */
    fun appendAudio(pcm: ByteArray) = window.append(pcm)

    /**
     * 给一批 final 轨道定身份，返回与入参**同序**的身份数组。
     *
     * 轨道内部按起始时间排序后再分配：分配器是增量的，顺序会影响编号，而 Sortformer 是按
     * 槽位报 runs 的（槽位 0 的全部、再槽位 1 的……），不排序会把到达顺序弄乱。
     *
     * 取不到音频或嵌入失败的段返回 [UNRESOLVED]，不猜。
     */
    fun resolve(tracks: List<SortformerTrack>): IntArray {
        val identities = IntArray(tracks.size) { UNRESOLVED }
        for (index in tracks.indices.sortedBy { tracks[it].beginTime }) {
            val track = tracks[index]
            // 只取 EMBED_MAX_SECONDS 秒：嵌入几秒即饱和，截断同时降内存与原生算力。
            // 取**中间**而不是开头：Sortformer 报的 run 起点常早于实际语音，从开头切会取到静音，
            // 嵌入与同人其它段相似度趋近 0，于是把一个人拆成多个身份（缺陷 #77）。
            val durationMs = (track.endTime - track.beginTime).coerceAtLeast(0L)
            val embedMs = min(durationMs, EMBED_MAX_SECONDS * 1000L)
            val begin = track.beginTime + (durationMs - embedMs) / 2
            val samples = window.slice(begin, begin + embedMs)
            if (samples == null) {
                audioMissCount += 1
                continue
            }
            val embedding = embed(samples)
            if (embedding == null || embedding.isEmpty()) {
                embedFailureCount += 1
                continue
            }
            identities[index] = assigner.assign(embedding, (track.endTime - track.beginTime) / 1000.0).identity
        }
        return identities
    }

    /** 已开出的身份数。 */
    fun identityCount(): Int = assigner.identityCount()

    /** 会话结束时清空。**不要**按 120 s 公共提交周期调用，否则身份每周期重新编号。 */
    fun reset() {
        window.reset()
        assigner.reset()
        audioMissCount = 0
        embedFailureCount = 0
    }

    companion object {
        /** 未赋身份。与公开 speakerIndex 的"不确定"取值一致。 */
        const val UNRESOLVED = -1

        /**
         * 每段最多送多少秒音频去算嵌入。
         *
         * 声纹嵌入几秒就饱和，不需要整段。鸿蒙实测（丁桥 4 条、143 个发言段）：不截断 34/34
         * 判对、送入 506 s 音频；截到 3 s 仍是 34/34，送入降到 327 s、嵌入耗时降约 37%；
         * 截到 1 s 才掉到 32/34。取 3 s 是在"2 s 仍满分"之上留一档余量，也压掉了每段切出
         * 整段音频带来的内存尖峰。
         */
        const val EMBED_MAX_SECONDS = 3
    }
}
