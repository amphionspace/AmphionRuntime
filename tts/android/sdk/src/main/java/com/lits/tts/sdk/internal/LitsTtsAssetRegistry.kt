package com.lits.tts.sdk.internal

internal object LitsTtsAssetRegistry {
    const val ASSET_ROOT: String = "lits-models"
    const val MODEL_ROOT: String = "tts"
    const val MODEL_ID: String = "lits_delivery_16k_hifigan"
    const val MODEL_VERSION: String = "1.0.0"

    const val MANIFEST: String = "manifest.json"
    const val ACOUSTIC_MODEL: String = "lits_acoustic.onnx"
    const val VOCODER_MODEL: String = "hifigan_vocoder.onnx"
    const val FRONTEND_GOLDEN: String = "frontend_golden.json"
    const val CHINESE_LEXICON: String = "chinese_lexicon.txt"
    const val CMUDICT: String = "cmudict.txt"
    const val PINYIN_TO_BPMF: String = "pinyin_2_bpmf.txt"
    const val POLYCHAR: String = "polychar.txt"
    const val SYMBOLS: String = "zh_en_symbols.json"
    const val PINYIN_TO_TOKENS: String = "pinyin_to_tokens.json"
    const val ARPABET_TO_TOKENS: String = "arpabet_to_tokens.json"

    val files: List<String> = listOf(
        MANIFEST,
        ACOUSTIC_MODEL,
        VOCODER_MODEL,
        FRONTEND_GOLDEN,
        CHINESE_LEXICON,
        CMUDICT,
        PINYIN_TO_BPMF,
        POLYCHAR,
        SYMBOLS,
        PINYIN_TO_TOKENS,
        ARPABET_TO_TOKENS,
    )

    val assetSubPath: String = "$MODEL_ROOT/$MODEL_ID/$MODEL_VERSION"
}
