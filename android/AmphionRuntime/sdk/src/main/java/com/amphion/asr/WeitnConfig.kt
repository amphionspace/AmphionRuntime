package com.amphion.asr

import java.io.File

/**
 * WeText ITN 引擎配置（不可变）。
 *
 * 通过 [Builder] 构造；构造完成后字段不可改。如需更换 FST 必须新建一个 [WeitnEngine]。
 *
 * # 关于 FST
 *
 * WeTextProcessing 的中文 ITN 走「tagger.fst + verbalizer.fst 两段式」：
 *
 * - [taggerPath] 解析输入并产出结构化 token（`tokens { decimal { integer_part: "2" ... } }`）
 * - [verbalizerPath] 把结构化 token 序列化回正规化文本
 *
 * Native 层会按 [taggerPath] 文件名识别语言/方向（默认 `zh_itn`）：
 * - `zh_itn_tagger.fst` -> 中文 ITN
 * - `zh_tn_tagger.fst` -> 中文 TN
 * - `en_tn_tagger.fst` -> 英文 TN
 * - `ja_tn_tagger.fst` -> 日文 TN
 *
 * 两个 fst 文件通常由 [WeTextProcessing](https://github.com/wenet-e2e/WeTextProcessing)
 * 编译产出（中文 ITN 总和约 2–4 MB），不在 APK 内，必须运行期分发到 [File]。
 *
 * 详见 [docs/INTEGRATION.md](../../../../../../../../../../docs/INTEGRATION.md) §12.6。
 */
public class WeitnConfig private constructor(
    /** WeTextProcessing tagger FST 路径（如 `zh_itn_tagger.fst`）。 */
    public val taggerPath: File,
    /** WeTextProcessing verbalizer FST 路径（如 `zh_itn_verbalizer.fst`）。 */
    public val verbalizerPath: File,
    /** 是否打开 native 内部 debug 日志（仅排查时使用）。 */
    public val debug: Boolean,
) {

    /**
     * Builder：链式构造 [WeitnConfig]。
     *
     * 必填：tagger + verbalizer 两个 fst 文件路径，均需存在。
     *
     * ```
     * val config = WeitnConfig.Builder(
     *     File(filesDir, "asr-weitn/zh_itn_tagger.fst"),
     *     File(filesDir, "asr-weitn/zh_itn_verbalizer.fst"),
     * ).build()
     * val itn = WeitnEngine(config)
     * val out = itn.normalize("两点五八万") // -> "2.58万"
     * itn.close()
     * ```
     */
    public class Builder(
        private val taggerPath: File,
        private val verbalizerPath: File,
    ) {

        private var debug: Boolean = false

        /** 打开 native 内部 debug 日志（默认关）。 */
        public fun debug(value: Boolean): Builder = apply {
            this.debug = value
        }

        public fun build(): WeitnConfig {
            require(taggerPath.isFile) {
                "WeText tagger fst not found: ${taggerPath.absolutePath}"
            }
            require(verbalizerPath.isFile) {
                "WeText verbalizer fst not found: ${verbalizerPath.absolutePath}"
            }
            return WeitnConfig(
                taggerPath = taggerPath,
                verbalizerPath = verbalizerPath,
                debug = debug,
            )
        }
    }
}
