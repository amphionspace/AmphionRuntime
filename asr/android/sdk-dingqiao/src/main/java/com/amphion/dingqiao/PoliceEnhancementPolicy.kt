package com.amphion.dingqiao

/** Selects final text without letting a disabled session invoke the enhancement pipeline. */
internal object PoliceEnhancementPolicy {
    fun finalText(
        rawText: String,
        enabled: Boolean,
        enhance: (String) -> String,
    ): String = if (enabled) enhance(rawText) else rawText
}
