import Foundation

/// WeText ITN 不可变资源配置。
///
/// WeTextProcessing 中文 ITN 走「tagger.fst + verbalizer.fst 两段式」：
///
/// - ``taggerFst`` 解析输入并产出结构化 token（`tokens { decimal { integer_part: "2" ... } }`）
/// - ``verbalizerFst`` 把结构化 token 序列化回正规化文本
///
/// 预期的 native 层会按 ``taggerFst`` 文件名识别语言/方向（默认 `zh_itn`）：
/// - `zh_itn_tagger.fst` -> 中文 ITN
/// - `zh_tn_tagger.fst` -> 中文 TN
/// - `en_tn_tagger.fst` -> 英文 TN
/// - `ja_tn_tagger.fst` -> 日文 TN
///
/// 两个 fst 文件通常由 [WeTextProcessing](https://github.com/wenet-e2e/WeTextProcessing)
/// 编译产出（中文 ITN 总和约 2–4 MB）。它们必须随客户交付包提供并经过来源校验。
public struct WeitnConfig {

    /// WeTextProcessing tagger FST 路径（如 `zh_itn_tagger.fst`）。
    public let taggerFst: URL

    /// WeTextProcessing verbalizer FST 路径（如 `zh_itn_verbalizer.fst`）。
    public let verbalizerFst: URL

    /// 是否打开 native 内部 debug 日志（仅排查时使用）。
    public let debug: Bool

    /// 构造时校验两个 fst 文件都存在。
    public init(taggerFst: URL, verbalizerFst: URL, debug: Bool = false) throws {
        let fm = FileManager.default
        if !fm.fileExists(atPath: taggerFst.path) {
            throw AsrError(
                code: .modelFileMissing,
                message: "WeText tagger fst not found: \(taggerFst.path)"
            )
        }
        if !fm.fileExists(atPath: verbalizerFst.path) {
            throw AsrError(
                code: .modelFileMissing,
                message: "WeText verbalizer fst not found: \(verbalizerFst.path)"
            )
        }
        self.taggerFst = taggerFst
        self.verbalizerFst = verbalizerFst
        self.debug = debug
    }
}
