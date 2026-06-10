package com.amphion.asr.sample.plate

import java.io.File

/** 单条批量评测用例（metadata.jsonl 一行）。 */
data class BatchEvalCase(
    val uttId: String,
    val origUttId: String,
    val refText: String,
    val expectedPlate: String,
    val wavFile: File,
)
