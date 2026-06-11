package com.amphion.police

import android.content.Context
import com.amphion.police.plate.PlateEnhance
import com.amphion.police.plate.PlateEnhancePrefs
import com.amphion.police.plate.PlateNormalizeResult
import com.amphion.police.plate.PlateNormalizer
import com.amphion.police.station.PoliceStationEnhance
import com.amphion.police.station.PoliceStationEnhancePrefs
import com.amphion.police.station.PoliceStationNormalizeResult
import com.amphion.police.station.PoliceStationNormalizer
import com.amphion.police.terms.PoliceTermsEnhance
import com.amphion.police.terms.PoliceTermsEnhancePrefs
import com.amphion.police.terms.PoliceTermsNormalizeResult
import com.amphion.police.terms.PoliceTermsNormalizer

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
        val terms = PoliceTermsEnhance.apply(
            asrFinalText,
            termsNormalizer,
            termsNormalizeEnabled,
        )
        val plate = PlateEnhance.apply(terms.text, plateNormalizer, plateNormalizeEnabled)
        val station = PoliceStationEnhance.apply(
            plate.text,
            stationNormalizer,
            stationNormalizeEnabled,
        )
        return Result(
            text = station.text,
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
        ): PoliceEnhancePipeline = PoliceEnhancePipeline(
            termsNormalizer = PoliceTermsNormalizer.create(context, useFst = termsUseFst),
            plateNormalizer = PlateNormalizer.create(context, useFst = plateUseFst),
            stationNormalizer = PoliceStationNormalizer.create(context, useFst = stationUseFst),
            termsNormalizeEnabled = termsNormalizeEnabled,
            plateNormalizeEnabled = plateNormalizeEnabled,
            stationNormalizeEnabled = stationNormalizeEnabled,
        )
    }
}
