package com.amphion.asr.sample

import com.amphion.police.PoliceEnhancePipeline
import com.amphion.police.plate.PlateNormalizer
import com.amphion.police.station.PoliceStationNormalizer
import com.amphion.police.terms.PoliceTermsNormalizer

/**
 * Sample 层后处理入口，委托 [PoliceEnhancePipeline]。
 */
object AsrTextEnhance {

    fun apply(
        asrFinalText: String,
        termsNormalizer: PoliceTermsNormalizer,
        termsNormalizeEnabled: Boolean,
        plateNormalizer: PlateNormalizer,
        plateNormalizeEnabled: Boolean,
        stationNormalizer: PoliceStationNormalizer,
        stationNormalizeEnabled: Boolean,
    ): PoliceEnhancePipeline.Result = PoliceEnhancePipeline.apply(
        asrFinalText = asrFinalText,
        termsNormalizer = termsNormalizer,
        termsNormalizeEnabled = termsNormalizeEnabled,
        plateNormalizer = plateNormalizer,
        plateNormalizeEnabled = plateNormalizeEnabled,
        stationNormalizer = stationNormalizer,
        stationNormalizeEnabled = stationNormalizeEnabled,
    )
}
