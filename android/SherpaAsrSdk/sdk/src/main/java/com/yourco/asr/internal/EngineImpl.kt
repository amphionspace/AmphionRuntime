package com.yourco.asr.internal

import com.k2fsa.sherpa.onnx.EndpointConfig
import com.k2fsa.sherpa.onnx.EndpointRule
import com.k2fsa.sherpa.onnx.FeatureConfig
import com.k2fsa.sherpa.onnx.HomophoneReplacerConfig
import com.k2fsa.sherpa.onnx.OnlineLMConfig
import com.k2fsa.sherpa.onnx.OnlineModelConfig
import com.k2fsa.sherpa.onnx.OnlineNeMoCtcModelConfig
import com.k2fsa.sherpa.onnx.OnlineParaformerModelConfig
import com.k2fsa.sherpa.onnx.OnlineRecognizer
import com.k2fsa.sherpa.onnx.OnlineRecognizerConfig
import com.k2fsa.sherpa.onnx.OnlineTransducerModelConfig
import com.k2fsa.sherpa.onnx.OnlineZipformer2CtcModelConfig
import com.k2fsa.sherpa.onnx.SileroVadModelConfig
import com.k2fsa.sherpa.onnx.Vad
import com.k2fsa.sherpa.onnx.VadModelConfig
import com.yourco.asr.AsrCallback
import com.yourco.asr.AsrConfig
import com.yourco.asr.AsrError
import com.yourco.asr.AsrErrorCode
import com.yourco.asr.DecodingMethod
import com.yourco.asr.ModelType
import org.json.JSONObject
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/** EngineImpl：包装官方 [OnlineRecognizer]，对上为 [com.yourco.asr.AsrEngine] 提供 newSession 工厂。 */
internal class EngineImpl(private val config: AsrConfig) {

    private val recognizer: OnlineRecognizer
    private val vad: Vad?
    private val closed = AtomicBoolean(false)
    private val sessionsLock = ReentrantLock()
    private val sessions: MutableSet<SessionImpl> = HashSet()
    private val sessionCounter = AtomicInteger(0)

    /** 内部传给 SessionImpl 用：在 createStream 时把热词作为 string 注入 */
    @Volatile
    internal var engineHotwords: String = ""
        private set

    /** 内部传给 SessionImpl 用：调用方 updateHotwords 时校验 score 一致性，便于诊断 */
    internal val engineHotwordsScore: Float
        get() = config.hotwordsScore

    init {
        engineHotwords = config.hotwords.joinToString("\n")
        recognizer = when (val r = NativeGuard.run("OnlineRecognizer.<init>") {
            OnlineRecognizer(
                assetManager = null,
                config = buildOnlineRecognizerConfig(config),
            )
        }) {
            is NativeResult.Ok -> {
                Logger.i("OnlineRecognizer loaded from ${config.modelDir.absolutePath}")
                r.value
            }
            is NativeResult.Err -> {
                throw IllegalStateException(
                    "Failed to load model from ${config.modelDir.absolutePath}: ${r.error.message}",
                    r.error.cause
                )
            }
        }

        vad = if (config.enableVad && config.vadModelPath != null) {
            NativeGuard.runQuietly("Vad.<init>") {
                Vad(
                    assetManager = null,
                    config = VadModelConfig(
                        sileroVadModelConfig = SileroVadModelConfig(
                            model = config.vadModelPath.absolutePath,
                            threshold = 0.5f,
                            minSilenceDuration = 0.25f,
                            minSpeechDuration = 0.25f,
                            windowSize = 512,
                        ),
                        sampleRate = config.sampleRate,
                        numThreads = 1,
                        provider = "cpu",
                    )
                )
            }
        } else null
    }

    val isClosed: Boolean
        get() = closed.get()

    fun newSession(callback: AsrCallback): SessionImpl {
        check(!closed.get()) { "Engine is closed" }
        val id = sessionCounter.incrementAndGet()
        val session = SessionImpl(
            engineImpl = this,
            recognizer = recognizer,
            vad = vad,
            sampleRate = config.sampleRate,
            callback = callback,
            sessionId = id,
        )
        sessionsLock.withLock { sessions.add(session) }
        return session
    }

    /** 由 SessionImpl.close() 反向调用，从注册表移除。 */
    internal fun unregister(s: SessionImpl) {
        sessionsLock.withLock { sessions.remove(s) }
    }

    fun close() {
        if (!closed.compareAndSet(false, true)) return

        // 关闭所有未关闭的 session（拷贝一份避免并发修改）
        val toClose = sessionsLock.withLock { sessions.toList().also { sessions.clear() } }
        for (s in toClose) {
            try {
                s.close()
            } catch (t: Throwable) {
                Logger.w("close session failed: ${t.message}")
            }
        }

        NativeGuard.runQuietly("recognizer.release") { recognizer.release() }
        NativeGuard.runQuietly("vad.release") { vad?.release() }
        Logger.i("Engine closed")
    }

    // -------- 把 AsrConfig 翻译成 sherpa-onnx 官方 OnlineRecognizerConfig --------
    private fun buildOnlineRecognizerConfig(c: AsrConfig): OnlineRecognizerConfig {
        // 一次性读 manifest，把可被覆盖的字段全拿出来（不在则留 null，走 Builder/默认）
        val overrides = readManifestOverrides(c.modelDir)

        // 决定 model_type：优先 manifest，其次 Builder 默认（TRANSDUCER）
        val modelType: ModelType = overrides?.modelType
            ?.let(ModelType::fromManifestString)
            ?: ModelType.TRANSDUCER

        // 解析模型文件路径：按 model_type 不同期望不同（int8 优先）
        val (resolved, errMsg) = ModelLayout.resolve(c.modelDir, modelType)
        if (resolved == null) {
            throw IllegalStateException("MODEL_FILE_MISSING (code=${AsrErrorCode.MODEL_FILE_MISSING}): $errMsg")
        }
        Logger.i(
            "model layout: type=$modelType " +
            "encoder=${resolved.encoder?.name} decoder=${resolved.decoder?.name} " +
            "joiner=${resolved.joiner?.name} model=${resolved.model?.name}"
        )

        val tokens = resolved.tokens.absolutePath

        // 优先级：调用方 Builder 显式设置 > manifest.json > Builder 默认值
        var effectiveDecoding: DecodingMethod = when {
            c.decodingMethodIsExplicit -> c.decodingMethod
            overrides?.decodingMethod != null -> overrides.decodingMethod
            else -> c.decodingMethod
        }
        val effectiveMaxActivePaths: Int = when {
            c.maxActivePathsIsExplicit -> c.maxActivePaths
            overrides?.maxActivePaths != null -> overrides.maxActivePaths
            else -> c.maxActivePaths
        }

        // 兜底：如果 hotwords 非空但 effective decoding 仍然是 greedy_search（极端情况：调用方在
        // Builder 里没传热词，但通过 updateHotwords 等运行时路径注入，或 manifest 把 explicit
        // modified_beam_search 之外的 builder 默认覆盖回 greedy），强制切到 modified_beam_search。
        // 这与 AsrConfig.Builder.build() 的协商保持一致，并防止 native LOGE。
        if (c.hotwords.isNotEmpty() && effectiveDecoding != DecodingMethod.MODIFIED_BEAM_SEARCH) {
            Logger.w(
                "hotwords non-empty but effective decoding=$effectiveDecoding; forcing MODIFIED_BEAM_SEARCH " +
                "(sherpa-onnx requires it for hotwords to take effect)."
            )
            effectiveDecoding = DecodingMethod.MODIFIED_BEAM_SEARCH
        }

        if (overrides != null) {
            Logger.i(
                "manifest overrides: model_type=${overrides.modelType ?: "(none)"} -> $modelType, " +
                "decoding_method=${overrides.decodingMethod ?: "(none)"}, " +
                "max_active_paths=${overrides.maxActivePaths ?: "(none)"}"
            )
        }
        Logger.i(
            "effective decoding=$effectiveDecoding maxActivePaths=$effectiveMaxActivePaths " +
            "(decodingExplicit=${c.decodingMethodIsExplicit}, " +
            "maxActiveExplicit=${c.maxActivePathsIsExplicit})"
        )

        // sherpa-onnx 的 OnlineModelConfig.modelType 是字符串字段；按实际选用的网络类型填回
        val modelTypeStr = modelTypeToManifestString(modelType, overrides?.modelType)

        val modelConfig = when (modelType) {
            ModelType.TRANSDUCER -> OnlineModelConfig(
                transducer = OnlineTransducerModelConfig(
                    encoder = resolved.encoder!!.absolutePath,
                    decoder = resolved.decoder!!.absolutePath,
                    joiner = resolved.joiner!!.absolutePath,
                ),
                tokens = tokens,
                numThreads = c.numThreads,
                debug = false,
                provider = "cpu",
                modelType = modelTypeStr,
            )
            ModelType.PARAFORMER -> OnlineModelConfig(
                paraformer = OnlineParaformerModelConfig(
                    encoder = resolved.encoder!!.absolutePath,
                    decoder = resolved.decoder!!.absolutePath,
                ),
                tokens = tokens,
                numThreads = c.numThreads,
                debug = false,
                provider = "cpu",
                modelType = modelTypeStr,
            )
            ModelType.ZIPFORMER2_CTC -> OnlineModelConfig(
                zipformer2Ctc = OnlineZipformer2CtcModelConfig(
                    model = resolved.model!!.absolutePath,
                ),
                tokens = tokens,
                numThreads = c.numThreads,
                debug = false,
                provider = "cpu",
                modelType = modelTypeStr,
            )
            ModelType.NEMO_CTC -> OnlineModelConfig(
                neMoCtc = OnlineNeMoCtcModelConfig(
                    model = resolved.model!!.absolutePath,
                ),
                tokens = tokens,
                numThreads = c.numThreads,
                debug = false,
                provider = "cpu",
                modelType = modelTypeStr,
            )
        }

        val featureConfig = FeatureConfig(
            sampleRate = c.sampleRate,
            featureDim = c.featureDim,
        )

        val endpointConfig = EndpointConfig(
            rule1 = EndpointRule(false, c.endpointRules.rule1MinTrailingSilenceSec, 0f),
            rule2 = EndpointRule(true,  c.endpointRules.rule2MinTrailingSilenceSec, 0f),
            rule3 = EndpointRule(false, 0f, c.endpointRules.rule3MinUtteranceLengthSec),
        )

        // 高级特性：HomophoneReplacer / ITN rule_fsts / LM rescoring
        val hr = if (c.homophoneLexiconPath != null && c.homophoneRuleFstsPath != null) {
            HomophoneReplacerConfig(
                lexicon = c.homophoneLexiconPath.absolutePath,
                ruleFsts = c.homophoneRuleFstsPath.absolutePath,
            )
        } else {
            HomophoneReplacerConfig()
        }
        val ruleFsts = c.itnRuleFstsPaths.joinToString(",") { it.absolutePath }
        val lmConfig = if (c.lmModelPath != null) {
            // 仅在 modified_beam_search 下生效；上面已经做过协商
            OnlineLMConfig(model = c.lmModelPath.absolutePath, scale = c.lmScale)
        } else {
            OnlineLMConfig()
        }

        // 热词通过 createStream(hotwords=...) 注入（见 SessionImpl），这里 hotwordsFile 留空
        return OnlineRecognizerConfig(
            featConfig = featureConfig,
            modelConfig = modelConfig,
            lmConfig = lmConfig,
            hr = hr,
            endpointConfig = endpointConfig,
            enableEndpoint = c.enableEndpoint,
            decodingMethod = when (effectiveDecoding) {
                DecodingMethod.GREEDY_SEARCH -> "greedy_search"
                DecodingMethod.MODIFIED_BEAM_SEARCH -> "modified_beam_search"
            },
            maxActivePaths = effectiveMaxActivePaths,
            hotwordsFile = "",
            hotwordsScore = c.hotwordsScore,
            ruleFsts = ruleFsts,
        )
    }

    /**
     * 把 [ModelType] 翻成 sherpa-onnx native 期望的 modelType 字符串。
     * 如果 manifest 里已经写了 zipformer / zipformer2 这种"细分 type"，优先保留原始字符串。
     */
    private fun modelTypeToManifestString(t: ModelType, manifestRaw: String?): String {
        if (!manifestRaw.isNullOrBlank()) return manifestRaw
        return when (t) {
            ModelType.TRANSDUCER -> "zipformer2"   // 公司主推 streaming zipformer2
            ModelType.PARAFORMER -> "paraformer"
            ModelType.ZIPFORMER2_CTC -> "zipformer2_ctc"
            ModelType.NEMO_CTC -> "nemo_ctc"
        }
    }

    /** 把内部异常包成 AsrError 上报。 */
    internal fun asAsrError(t: Throwable, fallbackCode: Int = AsrErrorCode.NATIVE_CRASH): AsrError =
        AsrError(
            code = fallbackCode,
            message = t.message ?: t.javaClass.simpleName,
            cause = t,
        )

    /**
     * manifest.json 中 SDK 关心的可覆盖字段。任意字段缺省都允许（返回 null 表示没有覆盖）。
     * 优先级低于 Builder 显式调用，高于 Builder 默认值。
     */
    private data class ManifestOverrides(
        val modelType: String?,
        val decodingMethod: DecodingMethod?,
        val maxActivePaths: Int?,
    )

    /** 读 modelDir/manifest.json 中允许覆盖运行时配置的字段；不存在/解析失败返回 null。 */
    private fun readManifestOverrides(modelDir: File): ManifestOverrides? {
        return try {
            val mf = File(modelDir, "manifest.json")
            if (!mf.isFile) return null
            val o = JSONObject(mf.readText())
            val modelType = o.optString("model_type", "").takeIf { it.isNotBlank() }
            val decodingMethod = o.optString("decoding_method", "").takeIf { it.isNotBlank() }
                ?.let(::parseDecodingMethod)
            val maxActivePaths = if (o.has("max_active_paths")) o.optInt("max_active_paths", -1)
                .takeIf { it in 1..32 } else null
            ManifestOverrides(modelType, decodingMethod, maxActivePaths)
        } catch (t: Throwable) {
            Logger.w("readManifestOverrides failed: ${t.message}")
            null
        }
    }

    /** 把 manifest 里的字符串映射到 [DecodingMethod]；未知值返回 null（走 Builder 默认）。 */
    private fun parseDecodingMethod(value: String): DecodingMethod? = when (value.trim()) {
        "greedy_search" -> DecodingMethod.GREEDY_SEARCH
        "modified_beam_search" -> DecodingMethod.MODIFIED_BEAM_SEARCH
        else -> {
            Logger.w("manifest.decoding_method='$value' unknown, ignored")
            null
        }
    }
}
