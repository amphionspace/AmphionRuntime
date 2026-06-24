package com.amphion.dingqiao

import com.amphion.asr.AsrConfig
import com.amphion.asr.AsrLanguage
import com.amphion.asr.EndpointRules
import com.amphion.asr.SpeakerVadConfig
import com.amphion.asr.TargetSpeakerConfig
import com.amphion.asr.VadConfig
import com.amphion.police.PoliceEngineConfig
import java.io.File

internal object DingqiaoEngineConfig {

    /** 门控阈值设为 -1，保证始终走 onFinal 路径但仍计算 speakerScore。 */
    private const val SCORE_ONLY_THRESHOLD = -1.0f
    private const val DEFAULT_VAD_END_MS = 800
    private const val MIN_VAD_END_MS = 500
    private const val MAX_VAD_END_MS = 10_000
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
        @Suppress("UNCHECKED_CAST")
        val sysLexicon = params.extraParams["sysGeneralLexicon"] as? List<String>
            ?: (params.extraParams["sysGeneralLexicon"] as? List<*>)?.mapNotNull { it?.toString() }
            ?: emptyList()
        val userHotwords = sysLexicon.map { it.trim() }.filter { it.isNotEmpty() }
        val hotwords = PoliceEngineConfig.effectiveHotwords(
            userHotwords = userHotwords,
            plateHotwords = true,
            stationHotwords = true,
            termsHotwords = true,
        )

        val builder = AsrConfig.Builder()
            .numThreads(2)
            .punctuation(true)
            .itn(true)
            .vad(true)
            .vadConfig(VadConfig(activeEndpointSilenceMs = vadEndMs(startParams)))
            .endpoint(true)
            .endpointRules(EndpointRules(rule2MinTrailingSilenceSec = 2.0f))
        if (hotwords.isNotEmpty()) {
            builder.hotwords(hotwords, PoliceEngineConfig.HOTWORDS_SCORE_DEFAULT)
        }
        if (!speakerModelPath.isNullOrBlank() && File(speakerModelPath).isFile) {
            builder.targetSpeaker(
                TargetSpeakerConfig(
                    modelPath = speakerModelPath,
                    threshold = SCORE_ONLY_THRESHOLD,
                    preload = true,
                    enabledByDefault = false,
                    speakerVad = speakerVadConfig(startParams),
                ),
            )
        }
        return builder.build()
    }

    fun vadEndMs(startParams: StartParams?): Int {
        val raw = startParams?.extraParams?.get("vadEnd") ?: return DEFAULT_VAD_END_MS
        return when (raw) {
            is Number -> raw.toInt()
            is String -> raw.toIntOrNull() ?: DEFAULT_VAD_END_MS
            else -> DEFAULT_VAD_END_MS
        }.coerceIn(MIN_VAD_END_MS, MAX_VAD_END_MS)
    }

    fun maxAudioDurationMs(startParams: StartParams): Long {
        val v = startParams.extraParams["maxAudioDuration"] as? Number
        return v?.toLong()?.coerceAtLeast(20_000L) ?: 20_000L
    }

    fun isSupportedAudioFrameBytes(byteSize: Int): Boolean =
        byteSize == DINGQIAO_AUDIO_FRAME_BYTES || byteSize == DINGQIAO_AUDIO_FRAME_BYTES_40MS

    fun enablePartialResult(startParams: StartParams): Boolean {
        val v = startParams.extraParams["enablePartialResult"]
        return when (v) {
            is Boolean -> v
            else -> true
        }
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

    private fun asInt(raw: Any?, defaultValue: Int): Int = when (raw) {
        is Number -> raw.toInt()
        is String -> raw.toIntOrNull() ?: defaultValue
        else -> defaultValue
    }

    private fun asFloat(raw: Any?, defaultValue: Float): Float = when (raw) {
        is Number -> raw.toFloat()
        is String -> raw.toFloatOrNull() ?: defaultValue
        else -> defaultValue
    }
}
