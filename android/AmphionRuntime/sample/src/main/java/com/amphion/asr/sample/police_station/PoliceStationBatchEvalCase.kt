package com.amphion.asr.sample.police_station

import java.io.File

/** 单条派出所批量评测用例。 */
data class PoliceStationBatchEvalCase(
    val uttId: String,
    val origUttId: String,
    val refText: String,
    val expectedStation: String,
    val wavFile: File,
)
