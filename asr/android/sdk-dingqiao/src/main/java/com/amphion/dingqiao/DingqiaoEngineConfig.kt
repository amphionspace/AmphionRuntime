package com.amphion.dingqiao

import com.amphion.asr.AsrConfig
import com.amphion.asr.AsrLanguage
import com.amphion.asr.EndpointRules
import com.amphion.asr.SessionConfig
import com.amphion.asr.SpeakerVadConfig
import com.amphion.asr.TargetSpeakerConfig
import com.amphion.asr.VadConfig
import com.amphion.police.PoliceEngineConfig
import com.amphion.police.PoliceHotwordProfile
import java.io.File

internal object DingqiaoEngineConfig {

    /** 门控阈值设为 -1，保证始终走 onFinal 路径但仍计算 speakerScore。 */
    private const val SCORE_ONLY_THRESHOLD = -1.0f
    private const val DEFAULT_ASR_NUM_THREADS = 4
    private const val DEFAULT_VAD_END_MS = 800
    private const val MIN_VAD_END_MS = 500
    private const val MAX_VAD_END_MS = 10_000
    private const val MIN_VAD_BEGIN_MS = 500
    private const val MAX_VAD_BEGIN_MS = 10_000
    private const val MAX_AUDIO_DURATION_MS = 28_800_000L
    private const val DEFAULT_SPEAKER_VAD_THRESHOLD = 0.40f
    private const val DEFAULT_SPEAKER_VAD_WINDOW_MS = 1000
    private const val DEFAULT_SPEAKER_VAD_HOP_MS = 300
    private const val DEFAULT_SPEAKER_VAD_CONSECUTIVE_BELOW = 2

    fun mapLanguage(language: String): AsrLanguage = when (language) {
        "zh-CN", "zh-en", "zh_en" -> AsrLanguage.ZH_EN
        "zh-yue", "zh_yue" -> AsrLanguage.YUE_EN
        else -> throw IllegalArgumentException("unsupported language: $language")
    }

    fun buildAsrConfig(
        params: CreateEngineParams,
        speakerModelPath: String?,
        startParams: StartParams? = null,
    ): AsrConfig {
        require(params.online == DingqiaoOnlineMode.OFFLINE) {
            "only offline mode is supported"
        }
        validateRecognizerMode(params)
        @Suppress("UNCHECKED_CAST")
        val sysLexicon = params.extraParams["sysGeneralLexicon"] as? List<String>
            ?: (params.extraParams["sysGeneralLexicon"] as? List<*>)?.mapNotNull { it?.toString() }
            ?: emptyList()
        val userHotwords = sysLexicon.map { it.trim() }.filter { it.isNotEmpty() }
        val hotwordProfile = PoliceHotwordProfile.parse(
            params.extraParams[PoliceHotwordProfile.EXPERIMENTAL_PARAM],
        )
        val hotwords = PoliceEngineConfig.effectiveHotwordsForProfile(
            userHotwords = userHotwords,
            profile = hotwordProfile,
            plateHotwords = true,
            stationHotwords = true,
            termsHotwords = true,
        )

        val builder = AsrConfig.Builder()
            .numThreads(DEFAULT_ASR_NUM_THREADS)
            .punctuation(true)
            .itn(true)
            .vad(true)
            .vadConfig(VadConfig(activeEndpointSilenceMs = vadEndMs(startParams)))
            .endpoint(true)
            .endpointRules(EndpointRules(rule2MinTrailingSilenceSec = 2.0f))
            .disablePrepack(compatibleBoolean(params.extraParams["disablePrepack"], true))
        if (hotwords.isNotEmpty()) {
            builder.hotwords(hotwords, PoliceEngineConfig.HOTWORDS_SCORE_DEFAULT)
        }
        if (!speakerModelPath.isNullOrBlank() && File(speakerModelPath).isFile) {
            builder.targetSpeaker(
                TargetSpeakerConfig(
                    modelPath = speakerModelPath,
                    threshold = SCORE_ONLY_THRESHOLD,
                    minSegSec = 0f,
                    preload = true,
                    enabledByDefault = false,
                    speakerVad = speakerVadConfig(startParams),
                ),
            )
        }
        return builder.build()
    }

    /**
     * 会话级覆盖参数：vadEnd 与 speaker VAD 窗口都是运行时阈值，逐会话直接生效，不触发引擎重建。
     * speakerModelPath 为空时不下发 speakerVad（engine 未配置声纹能力）。
     */
    fun buildSessionConfig(
        startParams: StartParams,
        speakerModelPath: String?,
        voiceprintCapabilityProvisioned: Boolean = false,
    ): SessionConfig {
        val speakerVad = if (!speakerModelPath.isNullOrBlank()) {
            speakerVadConfig(startParams)
        } else {
            null
        }
        return SessionConfig(
            endpointSilenceMs = vadEndMs(startParams),
            initialSilenceTimeoutMs = vadBeginMs(startParams),
            initialSilenceConfirmationGraceMs = voiceprintConfirmationGraceMs(
                startParams,
                speakerModelPath,
                voiceprintCapabilityProvisioned,
            ),
            speakerVad = speakerVad,
        )
    }

    private fun voiceprintConfirmationGraceMs(
        startParams: StartParams,
        speakerModelPath: String?,
        voiceprintCapabilityProvisioned: Boolean,
    ): Int? {
        val needsVoiceprintAudio = enableVoiceprintVerification(startParams) ||
            enableSpeakerVad(startParams) ||
            voiceprintCapabilityProvisioned
        if (!needsVoiceprintAudio || speakerModelPath.isNullOrBlank()) return null

        return (TargetSpeakerConfig(speakerModelPath).minSegSec * 1000).toInt()
    }

    fun vadBeginMs(startParams: StartParams): Int? {
        if (!startParams.extraParams.containsKey("vadBegin")) return null
        val value = finiteLong(startParams.extraParams["vadBegin"]) ?: return null
        return value.coerceIn(MIN_VAD_BEGIN_MS.toLong(), MAX_VAD_BEGIN_MS.toLong()).toInt()
    }

    fun vadEndMs(startParams: StartParams?): Int {
        val raw = startParams?.extraParams?.get("vadEnd") ?: return DEFAULT_VAD_END_MS
        val value = finiteDouble(raw) ?: return DEFAULT_VAD_END_MS
        return value.toInt().coerceIn(MIN_VAD_END_MS, MAX_VAD_END_MS)
    }

    fun maxAudioDurationMs(startParams: StartParams): Long {
        val value = finiteDouble(startParams.extraParams["maxAudioDuration"]) ?: return 0L
        if (value <= 0.0) return 0L
        return value.coerceAtMost(MAX_AUDIO_DURATION_MS.toDouble()).toLong().coerceAtLeast(1L)
    }

    fun validateRecognitionMode(startParams: StartParams) {
        val raw = startParams.extraParams["recognitionMode"] ?: DingqiaoRecognitionMode.STREAM
        val mode = finiteDouble(raw)
        require(mode == DingqiaoRecognitionMode.STREAM.toDouble()) {
            "only recognitionMode=1 (external audio stream) is supported"
        }
    }

    fun isSupportedAudioFrameBytes(byteSize: Int): Boolean =
        byteSize == DINGQIAO_AUDIO_FRAME_BYTES

    fun enablePartialResult(startParams: StartParams): Boolean {
        val v = startParams.extraParams["enablePartialResult"]
        return when (v) {
            is Boolean -> v
            else -> true
        }
    }

    /** Police text normalization is enabled by default for delivery compatibility. */
    fun enablePoliceEnhancement(startParams: StartParams): Boolean {
        return startParams.extraParams["enablePoliceEnhancement"] as? Boolean ?: true
    }

    fun enableVoiceprintVerification(startParams: StartParams): Boolean {
        return startParams.extraParams["enableVoiceprintVerification"] == true
    }

    fun enableSpeakerVad(startParams: StartParams): Boolean {
        return asBoolean(startParams.extraParams["enableSpeakerVad"])
    }

    private fun speakerVadConfig(startParams: StartParams?): SpeakerVadConfig {
        return SpeakerVadConfig(
            threshold = startParams?.let { speakerVadThreshold(it) } ?: DEFAULT_SPEAKER_VAD_THRESHOLD,
            winSec = (startParams?.let { speakerVadWindowMs(it) } ?: DEFAULT_SPEAKER_VAD_WINDOW_MS) / 1000f,
            hopSec = (startParams?.let { speakerVadHopMs(it) } ?: DEFAULT_SPEAKER_VAD_HOP_MS) / 1000f,
            consecutiveBelow = startParams?.let { speakerVadConsecutiveBelow(it) }
                ?: DEFAULT_SPEAKER_VAD_CONSECUTIVE_BELOW,
            enabledByDefault = false,
        )
    }

    private fun speakerVadThreshold(startParams: StartParams): Float {
        return asFloat(startParams.extraParams["speakerVadThreshold"], DEFAULT_SPEAKER_VAD_THRESHOLD)
            .coerceIn(-1.0f, 1.0f)
    }

    private fun speakerVadWindowMs(startParams: StartParams): Int {
        return asInt(startParams.extraParams["speakerVadWindowMs"], DEFAULT_SPEAKER_VAD_WINDOW_MS)
            .coerceIn(500, 5000)
    }

    private fun speakerVadHopMs(startParams: StartParams): Int {
        return asInt(startParams.extraParams["speakerVadHopMs"], DEFAULT_SPEAKER_VAD_HOP_MS)
            .coerceIn(100, 2000)
    }

    private fun speakerVadConsecutiveBelow(startParams: StartParams): Int {
        return asInt(
            startParams.extraParams["speakerVadConsecutiveBelow"],
            DEFAULT_SPEAKER_VAD_CONSECUTIVE_BELOW,
        ).coerceIn(1, 5)
    }

    @Suppress("UNCHECKED_CAST")
    fun voiceprintIds(startParams: StartParams): List<String> {
        val raw = startParams.extraParams["voiceprintIds"] as? List<*>
        return raw?.mapNotNull { it?.toString()?.trim()?.takeIf { id -> id.isNotEmpty() } }
            ?: emptyList()
    }

    private fun asBoolean(raw: Any?): Boolean = when (raw) {
        is Boolean -> raw
        is String -> raw.equals("true", ignoreCase = true) || raw == "1"
        is Number -> raw.toInt() != 0
        else -> false
    }

    /** Mirrors Harmony's tolerant host-parameter policy without changing strict capability flags. */
    private fun compatibleBoolean(raw: Any?, defaultValue: Boolean): Boolean = when (raw) {
        is Boolean -> raw
        is Number -> raw.toDouble().takeIf { it.isFinite() }?.let { it != 0.0 } ?: defaultValue
        is String -> raw.trim().equals("true", ignoreCase = true) || raw.trim() == "1"
        else -> defaultValue
    }

    private fun asInt(raw: Any?, defaultValue: Int): Int =
        finiteDouble(raw)?.toInt() ?: defaultValue

    private fun asFloat(raw: Any?, defaultValue: Float): Float =
        finiteDouble(raw)?.toFloat() ?: defaultValue

    private fun validateRecognizerMode(params: CreateEngineParams) {
        val raw = params.extraParams["recognizerMode"] ?: return
        val mode = raw.toString().trim().lowercase()
        require(mode == "short" || mode == "long") {
            "recognizerMode must be short or long"
        }
    }

    private fun finiteLong(raw: Any?): Long? = finiteDouble(raw)?.toLong()

    private fun finiteDouble(raw: Any?): Double? = when (raw) {
        is Number -> raw.toDouble().takeIf { it.isFinite() }
        is String -> raw.toDoubleOrNull()?.takeIf { it.isFinite() }
        else -> null
    }
}
