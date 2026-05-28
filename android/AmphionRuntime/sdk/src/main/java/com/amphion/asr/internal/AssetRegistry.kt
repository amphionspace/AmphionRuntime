package com.amphion.asr.internal

import com.amphion.asr.AsrLanguage

/**
 * SDK 内部资产清单：每一类资产（ASR 模型 / 标点 / ITN / VAD）都在 APK assets 下有
 * 固定的相对路径。
 *
 * 任何「业务方需不需要这份资产」「资产对应哪几个文件」都收敛到本类，[AssetInstaller]
 * 据此驱动解包，[EngineImpl] 据此构造 native config。这样新增/替换模型时只改本文件。
 *
 * # 路径约定
 *
 * 所有资产都在 `assets/amphion-models/<bundleId>/<version>/<files...>`：
 *
 * - bundleId 与 version 共同决定资产的"逻辑唯一标识"
 * - SDK 自身版本（[com.amphion.asr.BuildConfig.SDK_VERSION]）决定 install.flag 的内容；
 *   SDK 升级后会强制重新解包，避免 APK 内资产换了但 filesDir 还是旧版的对齐问题
 */
internal object AssetRegistry {

    /** assets 内的资产根目录。 */
    const val ASSET_ROOT: String = "amphion-models"

    /** 解包到 internal storage 的根目录（位于 [android.content.Context.getFilesDir]）。 */
    const val INSTALL_ROOT: String = "amphion-runtime"

    /** 安装完成后写入的 flag 文件名；内容为 SDK_VERSION。 */
    const val INSTALL_FLAG: String = "install.flag"

    /** 单份资产 bundle 的元数据：assets 子路径 + 内部文件清单。 */
    internal data class Bundle(
        val bundleId: String,
        val assetSubPath: String,
        val files: List<String>,
    ) {
        val installSubDir: String get() = bundleId
    }

    /**
     * ASR 主模型 bundle。
     *
     * `bbpe.vocab` 是 sherpa-onnx ssentencepiece 库期望的「token + score」两列文本词表
     * （**不是** Google SentencePiece protobuf .model）。byte-level BPE 模型（tokens.txt
     * 里出现 `▁THE` / `ƎĽĥ` 这种条目）配合 hotwords 时必备：sherpa-onnx 用它把热词字符串
     * 切成 BPE token，让 ContextGraph 能匹配模型实际输出的 token 序列。缺这个文件，
     * `modeling_unit=bbpe` + `bpeVocab=""` 在构造 bpe_encoder_ 时直接 segfault。
     */
    internal fun asrBundle(language: AsrLanguage): Bundle = when (language) {
        AsrLanguage.ZH_EN -> Bundle(
            bundleId = "zh-en/v1",
            assetSubPath = "zh-en/v1",
            files = listOf(
                "encoder.int8.onnx",
                "decoder.onnx",
                "joiner.int8.onnx",
                "tokens.txt",
                "bbpe.vocab",
            ),
        )
        AsrLanguage.YUE_EN -> Bundle(
            bundleId = "yue-en/v1",
            assetSubPath = "yue-en/v1",
            files = listOf(
                "encoder.int8.onnx",
                "decoder.onnx",
                "joiner.int8.onnx",
                "tokens.txt",
                "bbpe.vocab",
            ),
        )
    }

    /** 标点模型 bundle（中英 CT-Transformer，跨语言共用）。 */
    internal fun punctuationBundle(): Bundle = Bundle(
        bundleId = "punct-zhen/v1",
        assetSubPath = "punct-zhen/v1",
        files = listOf("model.int8.onnx"),
    )

    /** 中文 ITN bundle（仅 ZH_EN 启用）。 */
    internal fun itnBundle(): Bundle = Bundle(
        bundleId = "itn-zh/v1",
        assetSubPath = "itn-zh/v1",
        files = listOf("zh_itn_tagger.fst", "zh_itn_verbalizer.fst"),
    )

    /** silero VAD bundle。 */
    internal fun vadBundle(): Bundle = Bundle(
        bundleId = "vad/v1",
        assetSubPath = "vad/v1",
        files = listOf("silero_vad.onnx"),
    )

    /** 是否对当前语言启用 ITN（粤英不启用）。 */
    internal fun itnEnabledFor(language: AsrLanguage): Boolean = when (language) {
        AsrLanguage.ZH_EN -> true
        AsrLanguage.YUE_EN -> false
    }

    /** 全部 bundle（preInstall 用）。 */
    internal fun allBundles(): List<Bundle> = listOf(
        asrBundle(AsrLanguage.ZH_EN),
        asrBundle(AsrLanguage.YUE_EN),
        punctuationBundle(),
        itnBundle(),
        vadBundle(),
    )
}
