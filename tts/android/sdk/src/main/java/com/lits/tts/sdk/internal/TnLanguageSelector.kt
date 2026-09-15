package com.lits.tts.sdk.internal

internal object TnLanguageSelector {
    // The caller has already applied NFKC, so full-width digits are ASCII here.
    // Keep ASCII words/codes on the English route; number-only utterances use
    // Chinese in mixed mode, including decimal/sign characters and punctuation.
    private val numericPunctuation = ".,!?;:，。！？；：、…+-−()（）[]【】\"'“”‘’"

    fun select(text: String, isEnglishContext: Boolean): String {
        if (isEnglishContext) return "en"
        if (text.any { it in '\u4e00'..'\u9fff' }) return "zh"
        val numericOnly = text.any { it in '0'..'9' } && text.all {
            it in '0'..'9' || it.isWhitespace() || it in numericPunctuation
        }
        return if (numericOnly) "zh" else "en"
    }
}
