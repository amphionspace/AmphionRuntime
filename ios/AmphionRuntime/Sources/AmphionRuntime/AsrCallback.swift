import Foundation

/// 识别回调；与 Android `AsrCallback` 接口一一对应。
///
/// SDK 在专用的 callback 队列上派发，调用方按需要 dispatch 到主线程刷新 UI。
///
/// 与 Android 一致的"两种粒度"：
/// - 文本-only：只实现 `onPartial(text:)` / `onFinal(text:confidence:)`
/// - 完整结果：实现 `onPartial(result:)` / `onFinal(result:)` 拿到 token / 时间戳
public protocol AsrCallback: AnyObject {
    func onPartial(text: String)
    func onPartial(result: AsrResult)
    func onFinal(text: String, confidence: Float)
    func onFinal(result: AsrResult)
    func onEndpoint()
    func onError(_ error: AsrError)
    func onSessionStarted()
    func onSessionStopped()
}

/// 默认实现：所有方法 no-op；带 `result:` 的版本默认拆开调用旧签名以兼容。
public extension AsrCallback {
    func onPartial(text: String) {}
    func onPartial(result: AsrResult) {
        onPartial(text: result.text)
    }
    func onFinal(text: String, confidence: Float) {}
    func onFinal(result: AsrResult) {
        onFinal(text: result.text, confidence: result.confidence)
    }
    func onEndpoint() {}
    func onError(_ error: AsrError) {}
    func onSessionStarted() {}
    func onSessionStopped() {}
}
