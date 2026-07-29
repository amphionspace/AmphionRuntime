package com.amphion.police

import android.content.Context
import com.amphion.police.plate.PlateEnhance
import com.amphion.police.plate.PlateEnhancePrefs
import com.amphion.police.plate.PlateNormalizeResult
import com.amphion.police.plate.PlateNormalizer
import com.amphion.police.plate.PlateNormalizerV2
import com.amphion.police.station.PoliceStationEnhance
import com.amphion.police.station.PoliceStationEnhancePrefs
import com.amphion.police.station.PoliceStationNormalizeResult
import com.amphion.police.station.PoliceStationNormalizer
import com.amphion.police.station.PoliceStationNormalizerV2
import com.amphion.police.terms.PoliceTermsEnhance
import com.amphion.police.terms.PoliceTermsEnhancePrefs
import com.amphion.police.terms.PoliceTermsNormalizeResult
import com.amphion.police.terms.PoliceTermsNormalizer
import com.amphion.police.terms.PoliceTermsNormalizerV2

/**
 * 警务三场景后处理流水线：ASR final → 术语 → 车牌 → 派出所。
 *
 * v0.1 交付默认全开 normalize；FST 开关来自各 [EnhancePrefs]（默认关）。
 */
class PoliceEnhancePipeline private constructor(
    val termsNormalizer: PoliceTermsNormalizer,
    val plateNormalizer: PlateNormalizer,
    val stationNormalizer: PoliceStationNormalizer,
    private val termsNormalizeEnabled: Boolean,
    private val plateNormalizeEnabled: Boolean,
    private val stationNormalizeEnabled: Boolean,
    /** V2 车牌后处理（面向全国）；null 表示未启用，走老方案 [plateNormalizer]。 */
    val plateNormalizerV2: PlateNormalizerV2? = null,
    /** V2 派出所后处理（字级候选格 + gazetteer 校验器）；null 表示未启用，走老方案 [stationNormalizer]。 */
    val stationNormalizerV2: PoliceStationNormalizerV2? = null,
    /** V2 术语后处理（全局谐音 + 保守模糊层）；null 表示未启用，走老方案 [termsNormalizer]。 */
    val termsNormalizerV2: PoliceTermsNormalizerV2? = null,
) : AutoCloseable {

    data class Result(
        val text: String,
        val terms: PoliceTermsNormalizeResult,
        val plate: PlateNormalizeResult,
        val station: PoliceStationNormalizeResult,
    )

    /** 默认全开三场景后处理（鼎桥交付 v0.1）。 */
    fun enhance(asrFinalText: String): Result = apply(
        asrFinalText = asrFinalText,
        termsNormalizeEnabled = termsNormalizeEnabled,
        plateNormalizeEnabled = plateNormalizeEnabled,
        stationNormalizeEnabled = stationNormalizeEnabled,
    )

    fun apply(
        asrFinalText: String,
        termsNormalizeEnabled: Boolean = this.termsNormalizeEnabled,
        plateNormalizeEnabled: Boolean = this.plateNormalizeEnabled,
        stationNormalizeEnabled: Boolean = this.stationNormalizeEnabled,
    ): Result {
        val termsV2 = termsNormalizerV2
        val terms = when {
            !termsNormalizeEnabled -> PoliceTermsNormalizeResult(asrFinalText, emptyList())
            termsV2 != null -> termsV2.normalize(asrFinalText)
            else -> PoliceTermsEnhance.apply(asrFinalText, termsNormalizer, termsNormalizeEnabled)
        }
        val v2 = plateNormalizerV2
        val plate = when {
            !plateNormalizeEnabled -> PlateNormalizeResult(terms.text, emptyList())
            v2 != null -> v2.normalize(terms.text)
            else -> PlateEnhance.apply(terms.text, plateNormalizer, plateNormalizeEnabled)
        }
        val stationV2 = stationNormalizerV2
        val station = when {
            !stationNormalizeEnabled -> PoliceStationNormalizeResult(plate.text, emptyList())
            stationV2 != null -> stationV2.normalize(plate.text)
            else -> PoliceStationEnhance.apply(plate.text, stationNormalizer, stationNormalizeEnabled)
        }
        // 车牌后处理会把「川A F60080」收成「川AF60080」等；术语末润色再拉回语音指令书写。
        val finalText = when {
            !termsNormalizeEnabled -> station.text
            termsV2 != null -> termsV2.polish(station.text)
            else -> station.text
        }
        return Result(
            text = finalText,
            terms = terms,
            plate = plate,
            station = station,
        )
    }

    override fun close() {
        try {
            termsNormalizer.close()
        } catch (_: Throwable) {}
        try {
            plateNormalizer.close()
        } catch (_: Throwable) {}
        try {
            plateNormalizerV2?.close()
        } catch (_: Throwable) {}
        try {
            stationNormalizer.close()
        } catch (_: Throwable) {}
    }

    companion object {
        /** 单次后处理（不持有 normalizer 生命周期）。 */
        fun apply(
            asrFinalText: String,
            termsNormalizer: PoliceTermsNormalizer,
            termsNormalizeEnabled: Boolean,
            plateNormalizer: PlateNormalizer,
            plateNormalizeEnabled: Boolean,
            stationNormalizer: PoliceStationNormalizer,
            stationNormalizeEnabled: Boolean,
        ): Result = PoliceEnhancePipeline(
            termsNormalizer = termsNormalizer,
            plateNormalizer = plateNormalizer,
            stationNormalizer = stationNormalizer,
            termsNormalizeEnabled = termsNormalizeEnabled,
            plateNormalizeEnabled = plateNormalizeEnabled,
            stationNormalizeEnabled = stationNormalizeEnabled,
        ).apply(
            asrFinalText = asrFinalText,
            termsNormalizeEnabled = termsNormalizeEnabled,
            plateNormalizeEnabled = plateNormalizeEnabled,
            stationNormalizeEnabled = stationNormalizeEnabled,
        )

        /** 从 [Context] 与 prefs 构建；normalize 默认全开，FST 由 prefs 控制。 */
        fun create(context: Context): PoliceEnhancePipeline {
            val app = context.applicationContext
            val platePrefs = PlateEnhancePrefs(app)
            val stationPrefs = PoliceStationEnhancePrefs(app)
            val termsPrefs = PoliceTermsEnhancePrefs(app)
            return create(
                context = app,
                plateUseFst = platePrefs.plateFstEnabled,
                stationUseFst = stationPrefs.stationFstEnabled,
                termsUseFst = termsPrefs.termsFstEnabled,
                plateNormalizeEnabled = platePrefs.plateNormalizeEnabled,
                stationNormalizeEnabled = stationPrefs.stationNormalizeEnabled,
                termsNormalizeEnabled = termsPrefs.termsNormalizeEnabled,
                plateV2Enabled = platePrefs.plateV2Enabled,
                stationV2Enabled = stationPrefs.stationV2Enabled,
                termsV2Enabled = termsPrefs.termsV2Enabled,
            )
        }

        fun create(
            context: Context,
            plateUseFst: Boolean = false,
            stationUseFst: Boolean = false,
            termsUseFst: Boolean = false,
            plateNormalizeEnabled: Boolean = true,
            stationNormalizeEnabled: Boolean = true,
            termsNormalizeEnabled: Boolean = true,
            plateV2Enabled: Boolean = false,
            stationV2Enabled: Boolean = false,
            termsV2Enabled: Boolean = false,
            /**
             * V2 部署辖区省份先验。本项目警用设备部署在河北雄安，甲方点名冀R/辽B 为重点牌，
             * 故默认 ['冀','辽']：省份同音歧义平局时偏向辖区省（如 及/即→吉|冀 取冀），
             * 同时丢省份兜底也以此为候选。注意它只是 tie-break，绝不覆盖已识别清楚的外地牌，
             * 故全国其他省份覆盖不受影响。如需纯全国中立可传 emptyList()。
             */
            plateContextProvinces: List<Char> = listOf('冀', '辽'),
        ): PoliceEnhancePipeline = PoliceEnhancePipeline(
            termsNormalizer = PoliceTermsNormalizer.create(context, useFst = termsUseFst),
            plateNormalizer = PlateNormalizer.create(context, useFst = plateUseFst),
            stationNormalizer = PoliceStationNormalizer.create(context, useFst = stationUseFst),
            termsNormalizeEnabled = termsNormalizeEnabled,
            plateNormalizeEnabled = plateNormalizeEnabled,
            stationNormalizeEnabled = stationNormalizeEnabled,
            // 仅在开关开启时构建 V2（含资产加载），关闭时零开销、零行为变化。
            plateNormalizerV2 = if (plateV2Enabled) {
                PlateNormalizerV2.create(context, plateContextProvinces)
            } else {
                null
            },
            stationNormalizerV2 = if (stationV2Enabled) {
                PoliceStationNormalizerV2.create(context)
            } else {
                null
            },
            termsNormalizerV2 = if (termsV2Enabled) {
                PoliceTermsNormalizerV2.create(context)
            } else {
                null
            },
        )
    }
}
