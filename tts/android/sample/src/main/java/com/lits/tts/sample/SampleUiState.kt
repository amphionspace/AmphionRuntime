package com.lits.tts.sample

internal data class SampleInput(
    val text: String = SampleTexts.forLanguage("zh-en"),
    val language: String = "zh-en",
    val chunkSize: String = "",
    val pcmQueueCapacity: String = "32",
    val speed: String = "1.0",
)

internal data class SampleUiState(
    val status: String = "",
    val metrics: String = "",
    val log: String = "",
    val busy: Boolean = false,
    val canPlay: Boolean = false,
    val canStop: Boolean = false,
    val memory: ProcessMemory? = null,
)
