package com.amphion.dingqiao

import com.amphion.asr.AsrConfig
import com.amphion.asr.AsrLanguage
import com.amphion.asr.EndpointRules
import com.amphion.asr.TargetSpeakerConfig
import com.amphion.asr.VadConfig
import com.amphion.police.PoliceEngineConfig
import java.io.File

internal object DingqiaoEngineConfig {

    /** 门控阈值设为 -1，保证始终走 onFinal 路径但仍计算 speakerScore。 */
    private const val SCORE_ONLY_THRESHOLD = -1.0f
    private const val DEFAULT_VAD_END_MS = 500

    fun mapLanguage(language: String): AsrLanguage = when (language) {
        "zh-CN", "zh-en", "zh_en" -> AsrLanguage.ZH_EN
        "zh-yue", "zh_yue" -> AsrLanguage.YUE_EN
        else -> throw IllegalArgumentException("unsupported language: $language")
    }

    fun buildAsrConfig(
        params: CreateEngineParams,
        speakerModelPath: String?,
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
            .vadConfig(VadConfig(activeEndpointSilenceMs = vadEndMs(params)))
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
                ),
            )
        }
        return builder.build()
    }

    fun vadEndMs(params: CreateEngineParams): Int {
        val raw = params.extraParams["vadEnd"] ?: return DEFAULT_VAD_END_MS
        return when (raw) {
            is Number -> raw.toInt()
            is String -> raw.toIntOrNull() ?: DEFAULT_VAD_END_MS
            else -> DEFAULT_VAD_END_MS
        }.coerceAtLeast(0)
    }

    fun maxAudioDurationMs(startParams: StartParams): Long {
        val v = startParams.extraParams["maxAudioDuration"] as? Number
        return v?.toLong()?.coerceAtLeast(20_000L) ?: 20_000L
    }

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

    @Suppress("UNCHECKED_CAST")
    fun voiceprintIds(startParams: StartParams): List<String> {
        val raw = startParams.extraParams["voiceprintIds"] as? List<*>
        return raw?.mapNotNull { it?.toString()?.trim()?.takeIf { id -> id.isNotEmpty() } }
            ?: emptyList()
    }
}
