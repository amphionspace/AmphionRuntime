package com.amphion.asr.internal

import android.content.res.AssetManager
import com.amphion.asr.AsrCallback
import com.amphion.asr.AsrConfig
import com.amphion.asr.AsrErrorCode
import com.amphion.asr.AsrLanguage
import com.amphion.asr.EndpointRules
import com.amphion.asr.SessionConfig
import com.amphion.asr.VadConfig
import com.amphion.asr.TargetSpeakerConfig
import com.amphion.asr.VadModelType
import com.k2fsa.sherpa.onnx.EndpointConfig
import com.k2fsa.sherpa.onnx.EndpointRule
import com.k2fsa.sherpa.onnx.FeatureConfig
import com.k2fsa.sherpa.onnx.HomophoneReplacerConfig
import com.k2fsa.sherpa.onnx.OnlineLMConfig
import com.k2fsa.sherpa.onnx.OnlineModelConfig
import com.k2fsa.sherpa.onnx.OnlineRecognizer
import com.k2fsa.sherpa.onnx.OnlineRecognizerConfig
import com.k2fsa.sherpa.onnx.OnlineTransducerModelConfig
import com.k2fsa.sherpa.onnx.SileroVadModelConfig
import com.k2fsa.sherpa.onnx.SpeakerEmbeddingExtractor
import com.k2fsa.sherpa.onnx.SpeakerEmbeddingExtractorConfig
import com.k2fsa.sherpa.onnx.Vad
import com.k2fsa.sherpa.onnx.VadModelConfig
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/**
 * SDK 的 ASR 引擎实现：包装一份 [OnlineRecognizer]（可能来自 [AmphionRuntime] 的池）+
 * per-engine 的 [Vad]，以及对 [SharedPostProcessor] 的引用。
 *
 * 业务方拿到的 [com.amphion.asr.AsrEngine] 只是 EngineImpl 的薄壳。
 * 1 个 EngineImpl ↔ N 个 [SessionImpl]：recognizer / vad / 共享 punct / 共享 itn 都是
 * Engine 级别共享资源，session 之间不互相影响。
 *
 * 关于 [ownsRecognizer]：true 时 close 会真的 release recognizer；false 时表示
 * recognizer 来自 [AmphionRuntime.asrPool]，close 仅释放 sessions 与 vad，recognizer
 * 留在池里供下次 create 复用。
 */
internal class EngineImpl(
    private val language: AsrLanguage,
    private val config: AsrConfig,
    private val recognizer: OnlineRecognizer,
    private val ownsRecognizer: Boolean,
    layout: AssetInstaller.InstalledLayout,
    private val createStartElapsedMs: Long,
    private val assetInstallMs: Long,
    private val assetTotalBytes: Long,
) {

    private val vad: Vad?

    // 目标说话人声纹 extractor（engine 级，可选）：preload 时 init 即建，否则首次开关开启懒加载。
    private val speakerLock = ReentrantLock()

    @Volatile
    private var speakerExtractor: SpeakerEmbeddingExtractor? = null

    private val closed = AtomicBoolean(false)
    private val sessionsLock = ReentrantLock()
    private val sessions: MutableSet<SessionImpl> = HashSet()
    private val closingSessions = ClosingSessionBarrier<SessionImpl>(
        awaitQuiescent = { session, timeoutMs -> session.awaitDecoderQuit(timeoutMs) },
    )
    private val sessionCounter = AtomicInteger(0)

    /** engine ready 时刻（init 完成）的 SystemClock.elapsedRealtime；MetricsCollector 需要。 */
    val engineReadyElapsedMs: Long
    val engineReadyMs: Long
    val nativeRssMbAtReady: Int

    @Volatile
    internal var engineHotwords: String = ""
        private set

    internal val engineHotwordsScore: Float
        get() = config.hotwordsScore

    /** 用于让 SessionImpl 通过 SharedPostProcessor 串入后处理；可能为 null。 */
    internal val sharedPunctuation: InternalPunctuationEngine?
        get() = if (config.punctuation) SharedPostProcessor.punctuation() else null

    internal val sharedItn: InternalWeitnEngine?
        get() = if (config.itn && AssetRegistry.itnEnabledFor(language)) SharedPostProcessor.itn() else null

    internal val asrLanguage: AsrLanguage
        get() = language

    /** 给 [SessionImpl] 读 VAD 主动 endpoint 阈值等参数；与 [vad] 是否非空解耦。 */
    internal val vadConfig: VadConfig
        get() = config.vadConfig

    internal val endpointRules: EndpointRules
        get() = config.endpointRules

    /** 目标说话人能力配置；null 表示未启用。 */
    internal val targetSpeakerConfig: TargetSpeakerConfig?
        get() = config.targetSpeaker

    init {
        engineHotwords = config.hotwords.joinToString("\n")

        // VAD：可选，per-engine（sherpa-onnx VAD 是 stateful，不能跨 session 共享）
        // 0.2.x 起 SessionImpl 真正接入了 VAD 管线（Gate + 主动 endpoint）
        vad = if (config.vad && layout.vadModel != null) {
            buildVad(config.vadConfig, layout.vadModel, layout.assetManager)
        } else {
            null
        }

        // 目标说话人：preload=true 时随 engine 创建即加载声纹模型，让运行时开关只切标志位（秒级生效）。
        config.targetSpeaker?.let { if (it.preload) obtainSpeakerExtractor() }

        engineReadyElapsedMs = android.os.SystemClock.elapsedRealtime()
        engineReadyMs = engineReadyElapsedMs - createStartElapsedMs
        nativeRssMbAtReady = ProcessRssReader.readNativeRssMb()
        Logger.i(
            "Engine ready: language=$language ownsRecognizer=$ownsRecognizer " +
                "engineReadyMs=$engineReadyMs nativeRssMbAtReady=$nativeRssMbAtReady",
        )
    }

    val isClosed: Boolean
        get() = closed.get()

    fun newSession(callback: AsrCallback, sessionConfig: SessionConfig? = null): SessionImpl {
        check(!closed.get()) { "Engine is closed (code=${AsrErrorCode.SESSION_ALREADY_CLOSED})" }
        check(closingSessions.awaitAll(SESSION_REUSE_DRAIN_TIMEOUT_MS)) {
            "Previous session decoder did not quiesce in ${SESSION_REUSE_DRAIN_TIMEOUT_MS}ms"
        }
        val id = sessionCounter.incrementAndGet()
        val isFirstSession = id == 1
        val startupBundle = if (isFirstSession) {
            EngineStartupBundle(
                assetInstallMs = assetInstallMs,
                assetTotalBytes = assetTotalBytes,
                engineReadyMs = engineReadyMs,
                nativeRssMbAtReady = nativeRssMbAtReady,
            )
        } else {
            null
        }
        val session = SessionImpl(
            engineImpl = this,
            recognizer = recognizer,
            vad = vad,
            sampleRate = SAMPLE_RATE,
            callback = callback,
            sessionId = id,
            startupBundle = startupBundle,
            sessionConfig = sessionConfig,
        )
        sessionsLock.withLock { sessions.add(session) }
        return session
    }

    /** 由 SessionImpl.close() 反向调用。 */
    internal fun unregister(s: SessionImpl) {
        sessionsLock.withLock { sessions.remove(s) }
        closingSessions.track(s)
    }

    /**
     * 懒加载 / 预加载 engine 级声纹 extractor。
     *
     * [config].targetSpeaker 为 null 时返回 null；模型加载失败时记 warn 并返回 null——目标说话人
     * 是可选增量能力，加载失败只让门控降级（放行全部），不影响 ASR 主链路。
     * 由 init（preload）或 SessionImpl 的 decoder 线程调用，内部用 [speakerLock] 保证只建一次。
     */
    internal fun obtainSpeakerExtractor(): SpeakerEmbeddingExtractor? {
        val tsc = config.targetSpeaker ?: return null
        speakerExtractor?.let { return it }
        return speakerLock.withLock {
            speakerExtractor ?: buildSpeakerExtractor(tsc)?.also { speakerExtractor = it }
        }
    }

    private fun buildSpeakerExtractor(tsc: TargetSpeakerConfig): SpeakerEmbeddingExtractor? {
        val cfg = SpeakerEmbeddingExtractorConfig(
            model = tsc.modelPath,
            numThreads = tsc.numThreads,
            debug = false,
            provider = "cpu",
        )
        return when (
            val r = NativeGuard.run("SpeakerEmbeddingExtractor.<init>") {
                SpeakerEmbeddingExtractor(assetManager = null, config = cfg)
            }
        ) {
            is NativeResult.Ok -> {
                Logger.i("Speaker extractor loaded: model=${tsc.modelPath} dim=${r.value.dim()}")
                r.value
            }
            is NativeResult.Err -> {
                Logger.w(
                    "Speaker model load failed, target-speaker gating will pass through: ${r.error.message}",
                )
                null
            }
        }
    }

    fun close() {
        if (!closed.compareAndSet(false, true)) return

        val toClose = sessionsLock.withLock { sessions.toList().also { sessions.clear() } }
        for (s in toClose) {
            try { s.close() } catch (t: Throwable) { Logger.w("close session failed: ${t.message}") }
        }

        // session.close 只是 post 任务给各自的 decoder handler，不阻塞；但接下来要
        // release per-engine vad，必须等 decoder 线程上「当前正在执行的 feedAndDecode」
        // 退出，否则那个 task 里的 v.isSpeechDetected() 会拿到已释放的 native pointer
        // 直接 SIGSEGV（见 SessionImpl.awaitDecoderQuit 的说明）。
        // 同一个 barrier 也覆盖此前已经 close、但仍在异步退出的 session。
        if (!closingSessions.awaitAll(ENGINE_CLOSE_DRAIN_TIMEOUT_MS)) {
            Logger.w(
                "Engine close: session decoder didn't quit in " +
                    "${ENGINE_CLOSE_DRAIN_TIMEOUT_MS}ms, proceeding anyway",
            )
        }

        if (ownsRecognizer) {
            NativeGuard.runQuietly("recognizer.release") { recognizer.release() }
        }
        NativeGuard.runQuietly("vad.release") { vad?.release() }
        NativeGuard.runQuietly("speakerExtractor.release") { speakerExtractor?.release() }
        Logger.i("Engine closed (ownsRecognizer=$ownsRecognizer)")
    }

    internal companion object {
        private const val SESSION_REUSE_DRAIN_TIMEOUT_MS = 5_000L
        private const val ENGINE_CLOSE_DRAIN_TIMEOUT_MS = 500L

        /** SDK 锁定的采样率，与训练时一致。 */
        const val SAMPLE_RATE: Int = 16000

        /** fbank 特征维度，与训练时一致。 */
        const val FEATURE_DIM: Int = 80

        /**
         * 按 [VadConfig.modelType] 构造一份新的 [Vad]。
         *
         * 当前 AAR 只打包了 silero VAD 资产；选择 [VadModelType.TEN_VAD] 会抛
         * [UnsupportedOperationException]。资产打包好后这里只需要分支多加 modelPath 与
         * `TenVadModelConfig` 即可。
         */
        @Throws(UnsupportedOperationException::class)
        fun buildVad(
            vadConfig: VadConfig,
            modelPath: String,
            assetManager: AssetManager,
        ): Vad? {
            val sherpaConfig = when (vadConfig.modelType) {
                VadModelType.SILERO -> VadModelConfig(
                    sileroVadModelConfig = SileroVadModelConfig(
                        model = modelPath,
                        threshold = vadConfig.threshold,
                        minSilenceDuration = vadConfig.minSilenceDurationSec,
                        minSpeechDuration = vadConfig.minSpeechDurationSec,
                        windowSize = 512,
                        maxSpeechDuration = vadConfig.maxSpeechDurationSec,
                    ),
                    sampleRate = SAMPLE_RATE,
                    numThreads = 1,
                    provider = "cpu",
                )
                VadModelType.TEN_VAD -> throw UnsupportedOperationException(
                    "ten-vad is not packaged in this AAR yet; " +
                        "use VadModelType.SILERO or rebuild SDK with ten-vad.onnx",
                )
            }
            return NativeGuard.runQuietly("Vad.<init>") {
                Vad(assetManager = assetManager, config = sherpaConfig)
            }
        }

        /**
         * 构造一份新的 [OnlineRecognizer]。失败抛 [IllegalStateException]（含 ASSET_INSTALL_FAILED 错误码）。
         */
        fun buildRecognizer(
            layout: AssetInstaller.InstalledLayout,
            config: AsrConfig,
            language: AsrLanguage,
        ): OnlineRecognizer {
            val recognizerConfig = buildOnlineRecognizerConfig(layout, config)
            return when (val r = NativeGuard.run("OnlineRecognizer.<init>") {
                OnlineRecognizer(assetManager = layout.assetManager, config = recognizerConfig)
            }) {
                is NativeResult.Ok -> {
                    // 显式把热词链路的关键参数打出来；同音字纠错效果不达预期时直接看这一行
                    Logger.i(
                        "OnlineRecognizer loaded for $language: " +
                            "decoding=${recognizerConfig.decodingMethod} " +
                            "maxActivePaths=${recognizerConfig.maxActivePaths} " +
                            "modelingUnit=${recognizerConfig.modelConfig.modelingUnit} " +
                            "hotwordsCount=${config.hotwords.size} " +
                            "hotwordsScore=${config.hotwordsScore} " +
                            "disablePrepack=${config.disablePrepack}",
                    )
                    r.value
                }
                is NativeResult.Err -> throw IllegalStateException(
                    "code=${AsrErrorCode.ASSET_INSTALL_FAILED}: " +
                        "failed to load ASR model for $language: ${r.error.message}",
                    r.error.cause,
                )
            }
        }

        /**
         * 判断 [other] 是否能直接复用以 [pool] 为模板创建的 OnlineRecognizer。
         * 比对 recognizer 级别字段：numThreads / endpoint / hasHotwords。
         * hotwordsScore / hotwords 内容本身在 createStream 阶段才生效，不影响。
         */
        fun isRecognizerConfigCompatible(pool: AsrConfig, other: AsrConfig): Boolean {
            if (pool.numThreads != other.numThreads) return false
            if (pool.endpoint != other.endpoint) return false
            if (pool.endpointRules != other.endpointRules) return false
            if (pool.disablePrepack != other.disablePrepack) return false
            // decodingMethod 在 buildOnlineRecognizerConfig 内由 hotwords 是否为空决定
            val poolHasHotwords = pool.hotwords.isNotEmpty()
            val otherHasHotwords = other.hotwords.isNotEmpty()
            if (poolHasHotwords != otherHasHotwords) return false
            return true
        }

        // -------- 把 AsrConfig + InstalledLayout 翻译成 sherpa-onnx 的 OnlineRecognizerConfig --------
        private fun buildOnlineRecognizerConfig(
            layout: AssetInstaller.InstalledLayout,
            c: AsrConfig,
        ): OnlineRecognizerConfig {
            // 模型族固定 zipformer2 transducer：业务方在 SDK 边界看不到 model_type 这一层
            val modelConfig = OnlineModelConfig(
                transducer = OnlineTransducerModelConfig(
                    encoder = layout.asrEncoder,
                    decoder = layout.asrDecoder,
                    joiner = layout.asrJoiner,
                ),
                tokens = layout.asrTokens,
                numThreads = c.numThreads,
                debug = false,
                provider = if (c.disablePrepack) "cpu;DisablePrepacking=1" else "cpu",
                modelType = "zipformer2",
                // 我们的 zipformer2 是 byte-level BPE，tokens.txt 没有独立汉字/字母 token；
                // 必须用 bbpe：sherpa-onnx 内部先把每个 byte 转成 byte-level 符号，再用
                // bpeVocab 指向的两列文本词表做 BPE encode，让热词编出与 ASR 输出一致的
                // token ID 序列。注意：bpeVocab 是 sherpa-onnx ssentencepiece 的文本词表
                // 格式（每行 `<piece> <score>`），不是 Google SentencePiece protobuf。
                // 空 modeling_unit 会触发 SHERPA_ONNX_EXIT(-1)；vocab 文件格式不对会让
                // ssentencepiece::Build 的 darts trie 构造 segfault；都是直接 native 退出
                modelingUnit = "bbpe",
                bpeVocab = layout.asrBpeVocab,
            )

            val featureConfig = FeatureConfig(
                sampleRate = SAMPLE_RATE,
                featureDim = FEATURE_DIM,
            )

            val endpointConfig = EndpointConfig(
                rule1 = EndpointRule(false, c.endpointRules.rule1MinTrailingSilenceSec, 0f),
                rule2 = EndpointRule(true, c.endpointRules.rule2MinTrailingSilenceSec, 0f),
                rule3 = EndpointRule(false, 0f, c.endpointRules.rule3MinUtteranceLengthSec),
            )

            // 解码方式：默认 greedy_search；hotwords 非空时自动切到 modified_beam_search
            // （sherpa-onnx 强制要求；与旧 SDK 行为一致）
            val decodingMethod = if (c.hotwords.isEmpty()) "greedy_search" else "modified_beam_search"

            // beam width 跟着 decodingMethod 走：
            // - greedy_search 时其实只取 top-1，maxActivePaths 没意义；保留 4 是历史默认
            // - modified_beam_search 时这是 beam 宽度，直接决定「正确假设能不能在 boost
            //   生效之前活下来」。同音字（如「余明洞」/「余铭栋」）声学概率几乎相同，
            //   AM 给出的 top-1 通常是更常见的「明洞」，「铭栋」要靠 hotwords boost 翻盘；
            //   beam 太窄（4）会让「铭栋」候选还没拿到完整路径 boost 就被 prune 掉。
            //   8 是 sherpa-onnx 文档里的中文场景推荐值，多 4 条路径的解码代价约 +20% CPU
            val maxActivePaths = if (decodingMethod == "modified_beam_search") 8 else 4

            return OnlineRecognizerConfig(
                featConfig = featureConfig,
                modelConfig = modelConfig,
                lmConfig = OnlineLMConfig(),
                hr = HomophoneReplacerConfig(),
                endpointConfig = endpointConfig,
                enableEndpoint = c.endpoint,
                decodingMethod = decodingMethod,
                maxActivePaths = maxActivePaths,
                hotwordsFile = "",
                hotwordsScore = c.hotwordsScore,
                ruleFsts = "",
            )
        }
    }
}

/** 引擎启动期信息，附带在第一段 utterance 的 metrics 上。 */
internal data class EngineStartupBundle(
    val assetInstallMs: Long,
    val assetTotalBytes: Long,
    val engineReadyMs: Long,
    val nativeRssMbAtReady: Int,
)
