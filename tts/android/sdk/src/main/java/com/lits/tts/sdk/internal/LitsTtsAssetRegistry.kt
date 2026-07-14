package com.lits.tts.sdk.internal

internal object LitsTtsAssetRegistry {
    const val ASSET_ROOT: String = "lits-models"
    const val MODEL_ROOT: String = "tts"
    const val MODEL_ID: String = "dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop"
    const val MODEL_VERSION: String = "0.1.0"
    const val ASSET_SIGNATURE_VERSION: String = "20260701-chunk50-polyphone-v1"

    const val MANIFEST: String = "manifest.json"
    const val ACOUSTIC_MODEL: String = "lits_acoustic.onnx"
    const val HIDDEN_ENCODER_MODEL: String = "lits_hidden_encoder.onnx"
    const val STREAM_CONDITION_CHUNK_MODEL: String = "lits_stream_condition_chunk.onnx"
    const val STREAM_CONDITION_FINAL_MODEL: String = "lits_stream_condition_final.onnx"
    const val STREAM_DECODER_STEP_MODEL: String = "lits_stream_decoder_step.onnx"
    const val VOCODER_MODEL: String = "vocos_vocoder.onnx"
    const val FRONTEND_GOLDEN: String = "frontend_golden.json"
    const val FRONTEND_RULES: String = "frontend_rules.json"
    const val CHINESE_LEXICON: String = "chinese_lexicon.txt"
    const val CHINESE_LEXICON_BIN: String = "chinese_lexicon.bin"
    const val POLYPHONE_CONTEXT: String = "polyphone_context.txt"
    const val POLYPHONE_PHRASES: String = "polyphone_phrases.txt"
    const val CHINESE_SURNAME_LEXICON: String = "chinese_surname_lexicon.txt"
    const val CMUDICT: String = "cmudict.txt"
    const val CMUDICT_BIN: String = "cmudict.bin"
    const val SUPPLEMENT_LEXICON: String = "supplement_lexicon.json"
    const val PINYIN_TO_BPMF: String = "pinyin_2_bpmf.txt"
    const val POLYCHAR: String = "polychar.txt"
    const val SYMBOLS: String = "zh_en_symbols.json"
    const val PINYIN_TO_TOKENS: String = "pinyin_to_tokens.json"
    const val ARPABET_TO_TOKENS: String = "arpabet_to_tokens.json"
    const val TN_ZH_TTS: String = "tn-bin/arm64-v8a/zh_tts"
    const val TN_EN_TTS: String = "tn-bin/arm64-v8a/en_tts"
    const val TN_RULES_ZH: String = "rules/zh.json"
    const val TN_RULES_EN: String = "rules/en.json"
    const val TN_RULES_ZH_PINYIN: String = "rules_v2/zh_pinyin.json"
    const val TN_RULES_V2_ZH: String = "rules_v2/zh.full.json"
    const val TN_RULES_V2_EN: String = "rules_v2/en.full.json"

    val files: List<String> = listOf(
        MANIFEST,
        HIDDEN_ENCODER_MODEL,
        STREAM_CONDITION_CHUNK_MODEL,
        STREAM_DECODER_STEP_MODEL,
        VOCODER_MODEL,
        FRONTEND_GOLDEN,
        FRONTEND_RULES,
        CHINESE_LEXICON,
        CHINESE_LEXICON_BIN,
        POLYPHONE_CONTEXT,
        POLYPHONE_PHRASES,
        CHINESE_SURNAME_LEXICON,
        CMUDICT,
        CMUDICT_BIN,
        SUPPLEMENT_LEXICON,
        PINYIN_TO_BPMF,
        POLYCHAR,
        SYMBOLS,
        PINYIN_TO_TOKENS,
        ARPABET_TO_TOKENS,
        TN_ZH_TTS,
        TN_EN_TTS,
        TN_RULES_ZH,
        TN_RULES_EN,
        TN_RULES_ZH_PINYIN,
        TN_RULES_V2_ZH,
        TN_RULES_V2_EN,
    )

    val tnBinaryFiles: List<String> = listOf(
        TN_ZH_TTS,
        TN_EN_TTS,
    )

    val assetSubPath: String = "$MODEL_ROOT/$MODEL_ID/$MODEL_VERSION"
}
