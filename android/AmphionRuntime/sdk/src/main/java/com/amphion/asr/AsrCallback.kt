package com.amphion.asr

/**
 * 识别回调。所有方法都在 SDK 专用回调线程触发，不要在回调里做长耗时操作；
 * 如果需要更新 UI，自行 post 到主线程。
 *
 * 实现可以只覆盖关心的方法；默认实现做 no-op（结果回调中带 [AsrResult] 的版本默认会降级到旧文本签名）。
 *
 * 调用方按需选择以下两种粒度：
 *
 * - 文本只关心模式：覆盖 [onPartial] / [onFinal]（旧签名），SDK 会自动降级派发
 * - 完整结果模式：覆盖 [onPartial]([AsrResult]) / [onFinal]([AsrResult])，可拿到 token / 时间戳 / 逐 token 置信度
 *
 * 如果两种都覆盖，SDK 只会调用 [AsrResult] 版本，旧版不会被自动二次派发。
 */
public interface AsrCallback {

    /**
     * 部分识别结果（流式增量）。文本-only 模式入口。
     *
     * 注意：SDK 不保证 [text] 严格单调；当出现 LM 重打分或 context-aware 替换时，
     * partial 可能被回退/重写。集成方在 UI 层应该直接覆盖显示，不要拼接。
     *
     * @param text 当前累计的文本
     */
    public fun onPartial(text: String) {}

    /**
     * 部分识别结果（流式增量）。完整结果模式入口。
     *
     * 默认实现把 [result] 拆成 [text] 调用旧 [onPartial] 签名，保证旧实现不需要任何改动。
     *
     * @param result 见 [AsrResult]，包含 text / 置信度 / tokens / timestamps
     */
    public fun onPartial(result: AsrResult) {
        onPartial(result.text)
    }

    /**
     * 最终识别结果（一段话已确认）。文本-only 模式入口。
     *
     * 触发条件：
     * - 引擎判定 endpoint
     * - 调用方主动 [AsrSession.stop]
     *
     * @param text 一段话的最终文本
     * @param confidence 置信度，[0.0, 1.0]；若引擎不支持则恒为 1.0
     */
    public fun onFinal(text: String, confidence: Float) {}

    /**
     * 最终识别结果。完整结果模式入口。
     *
     * 默认实现把 [result] 拆开调用旧 [onFinal](text, confidence) 签名。
     *
     * @param result 见 [AsrResult]
     */
    public fun onFinal(result: AsrResult) {
        onFinal(result.text, result.confidence)
    }

    /**
     * 端点检测：检测到一段话结束。
     *
     * 这个事件会在 [onFinal] 之前触发，便于业务方做 UI 状态切换（比如把"正在识别…"切成"等待下一句"）。
     */
    public fun onEndpoint() {}

    /**
     * 错误回调。错误发生后，session 会自动进入"已停止"状态，集成方可以直接 [AsrSession.close]。
     *
     * @param error 错误码 + 错误信息
     */
    public fun onError(error: AsrError) {}

    /** Session 已经准备好接收音频；可选监听。 */
    public fun onSessionStarted() {}

    /** Session 已经停止接收音频（[AsrSession.stop] 之后或 [AsrSession.close] 之后）。 */
    public fun onSessionStopped() {}
}
