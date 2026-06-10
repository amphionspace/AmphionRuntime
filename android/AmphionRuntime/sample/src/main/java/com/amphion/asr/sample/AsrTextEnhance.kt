package com.amphion.asr.sample

import com.amphion.asr.sample.plate.PlateEnhance
import com.amphion.asr.sample.plate.PlateNormalizeResult
import com.amphion.asr.sample.plate.PlateNormalizer
import com.amphion.asr.sample.police_station.PoliceStationEnhance
import com.amphion.asr.sample.police_station.PoliceStationNormalizeResult
import com.amphion.asr.sample.police_station.PoliceStationNormalizer
import com.amphion.asr.sample.police_terms.PoliceTermsEnhance
import com.amphion.asr.sample.police_terms.PoliceTermsNormalizeResult
import com.amphion.asr.sample.police_terms.PoliceTermsNormalizer

/**
 * 麦克风 / 批量共用：ASR final → 警务术语 → 车牌 → 派出所后处理。
 */
object AsrTextEnhance {

    data class Result(
        val text: String,
        val terms: PoliceTermsNormalizeResult,
        val plate: PlateNormalizeResult,
        val station: PoliceStationNormalizeResult,
    )

    fun apply(
        asrFinalText: String,
        termsNormalizer: PoliceTermsNormalizer,
        termsNormalizeEnabled: Boolean,
        plateNormalizer: PlateNormalizer,
        plateNormalizeEnabled: Boolean,
        stationNormalizer: PoliceStationNormalizer,
        stationNormalizeEnabled: Boolean,
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
}
