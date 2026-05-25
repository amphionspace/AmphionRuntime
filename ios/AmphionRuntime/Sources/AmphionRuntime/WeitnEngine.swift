import Foundation
import SherpaOnnxBridge

/// 中文 ITN 引擎：把 ASR 识别得到的「口语化中文」正规化为「书面化中文」，覆盖
/// 数字、小数、单位、日期、时间、货币、百分比、电话、身份证等场景。
///
/// ```
/// 两点五八万 -> 2.58万
/// 幺三五七零八四 -> 1357084
/// 二零二六年五月十五日 -> 2026年5月15日
/// 三点五公里 -> 3.5公里
/// ```
///
/// 底层封装我们 fork 的 sherpa-onnx 里 vendored 的 [WeTextProcessing](https://github.com/wenet-e2e/WeTextProcessing)
/// 三段式 runtime（tagger.fst → token reorder → verbalizer.fst）。
///
/// # 资源占用
///
/// - 中文 ITN tagger + verbalizer fst 总和约 2–4 MB；加载后常驻 native 堆
/// - 一段几十字的 [normalize] 大约 1–10 ms（端侧 CPU），通常可放在 ASR final 之后串行调用
///
/// # 使用模式
///
/// 跟未来的 PunctuationEngine 一样，ITN 是「文本到文本」的纯函数式 API，独立于
/// [AsrEngine]，由业务方按需 lazy 创建：
///
/// ```swift
/// let cfg = try WeitnConfig(taggerFst: taggerURL, verbalizerFst: verbalizerURL)
/// let itn = try WeitnEngine(config: cfg)
/// let out = itn.normalize("两点五八万") // -> "2.58万"
/// // app 退出时：
/// itn.close()
/// ```
///
/// # 线程安全
///
/// - [normalize] 可以从多个线程并发调用，但每次调用都是同步阻塞，建议串行排队避免抢占
///   native FST Compose 资源
/// - [close] 是幂等的；close 后再调用 [normalize] 返回原文本
public final class WeitnEngine {

    public let config: WeitnConfig
    private var wrapper: SherpaOnnxWetextItnWrapper?
    private let lock = NSLock()
    private var closed = false

    /// 加载两个 fst；失败时抛 [AsrError] (code = .modelLoadFailed)。
    public init(config: WeitnConfig) throws {
        self.config = config

        var raw = sherpaOnnxWetextItnConfig(
            taggerFst: config.taggerFst.path,
            verbalizerFst: config.verbalizerFst.path,
            debug: config.debug ? 1 : 0
        )
        let w: SherpaOnnxWetextItnWrapper? = withUnsafePointer(to: &raw) { p in
            let w = SherpaOnnxWetextItnWrapper(config: p)
            return w.isValid ? w : nil
        }
        guard let valid = w else {
            throw AsrError(
                code: .modelLoadFailed,
                message: "Failed to load WeText ITN fsts (" +
                    "tagger=\(config.taggerFst.path), " +
                    "verbalizer=\(config.verbalizerFst.path))"
            )
        }
        self.wrapper = valid
        Log.i("WeitnEngine loaded tagger=\(config.taggerFst.path) verbalizer=\(config.verbalizerFst.path)")
    }

    /// 引擎是否已经 [close]。
    public var isClosed: Bool {
        lock.lock(); defer { lock.unlock() }
        return closed
    }

    /// 对 [text] 做 ITN。
    ///
    /// - 入参为空：原样返回（不调 native）
    /// - native 抛出 / 引擎已关闭：原样返回 [text]，错误打 Log
    public func normalize(_ text: String) -> String {
        if text.isEmpty { return text }
        lock.lock(); defer { lock.unlock() }
        if closed || wrapper == nil {
            Log.w("WeitnEngine.normalize called after close; returning input as-is")
            return text
        }
        let result = NativeGuard.run("WeitnEngine.normalize") {
            wrapper?.normalize(text: text) ?? text
        }
        return result ?? text
    }

    /// 释放底层 native 资源。幂等：多次调用安全。
    public func close() {
        lock.lock(); defer { lock.unlock() }
        if closed { return }
        closed = true
        wrapper = nil
        Log.i("WeitnEngine closed")
    }

    deinit {
        close()
    }
}
