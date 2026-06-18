package com.amphion.asr.sample.police_terms

import java.io.File

/** 单条警务术语批量评测用例。 */
data class PoliceTermsBatchEvalCase(
    val uttId: String,
    val origUttId: String,
    val refText: String,
    val expectedTerms: List<String>,
    val wavFile: File,
)
