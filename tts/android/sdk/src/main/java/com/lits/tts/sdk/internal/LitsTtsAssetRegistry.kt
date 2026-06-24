package com.lits.tts.sdk.internal

internal object LitsTtsAssetRegistry {
    const val ASSET_ROOT: String = "lits-models"
    const val MODEL_ROOT: String = "tts"
    const val MODEL_ID: String = "lits_delivery_16k_hifigan_streaming_proto"
    const val MODEL_VERSION: String = "0.1.1"

    const val MANIFEST: String = "manifest.json"
    const val ACOUSTIC_MODEL: String = "lits_acoustic.onnx"
    const val HIDDEN_ENCODER_MODEL: String = "lits_hidden_encoder.onnx"
    const val STREAM_DECODER_CHUNK_MODEL: String = "lits_stream_decoder_chunk.onnx"
    const val STREAM_DECODER_FINAL_MODEL: String = "lits_stream_decoder_final.onnx"
    const val VOCODER_MODEL: String = "hifigan_vocoder_int8.onnx"
    const val FRONTEND_GOLDEN: String = "frontend_golden.json"
    const val CHINESE_LEXICON: String = "chinese_lexicon.txt"
    const val CHINESE_LEXICON_BIN: String = "chinese_lexicon.bin"
    const val CMUDICT: String = "cmudict.txt"
    const val CMUDICT_BIN: String = "cmudict.bin"
    const val PINYIN_TO_BPMF: String = "pinyin_2_bpmf.txt"
    const val POLYCHAR: String = "polychar.txt"
    const val SYMBOLS: String = "zh_en_symbols.json"
    const val PINYIN_TO_TOKENS: String = "pinyin_to_tokens.json"
    const val ARPABET_TO_TOKENS: String = "arpabet_to_tokens.json"

    val files: List<String> = listOf(
        MANIFEST,
        HIDDEN_ENCODER_MODEL,
        STREAM_DECODER_CHUNK_MODEL,
        VOCODER_MODEL,
        FRONTEND_GOLDEN,
        CHINESE_LEXICON,
        CHINESE_LEXICON_BIN,
        CMUDICT,
        CMUDICT_BIN,
        PINYIN_TO_BPMF,
        POLYCHAR,
        SYMBOLS,
        PINYIN_TO_TOKENS,
        ARPABET_TO_TOKENS,
    )

    val assetSubPath: String = "$MODEL_ROOT/$MODEL_ID/$MODEL_VERSION"
}
