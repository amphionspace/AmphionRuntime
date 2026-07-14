package com.amphion.asr

/**
 * 识别回调。所有方法都在 SDK 专用回调线程触发，不要在回调里做长耗时操作；
 * 如果需要更新 UI，自行 post 到主线程。
 *
 * 回调到达顺序（每段话一次）：
 *
 * ```
 * onSessionStarted
 *   ↓ 反复
 * onPartial(text)         ← 流式增量；可能被回退/重写，UI 应该直接覆盖显示，不要拼接
 *   ↓
 * onEndpoint              ← 仅当 AsrConfig.endpoint=true 时触发
 *   ↓
 * onFinal(result)         ← 已包含 ITN + 标点处理（按 AsrConfig 配置），单次出
 *                            ↓ 进入下一段话或者
 *                            stop() / close()
 * onSessionStopped
 * ```
 *
 * 实现可以只覆盖关心的方法；默认实现都做 no-op。
 */
public interface AsrCallback {

    /** VAD 检测到一段语音真正开始。 */
    public fun onSpeechBegin() {}

    /** 会话配置的首段静音时限已到，且尚未检测到任何语音。 */
    public fun onInitialSilenceTimeout() {}

    /**
     * 部分识别结果（流式增量）。
     *
     * SDK 不保证 [text] 严格单调；当出现重打分或 context-aware 替换时，partial 可能被回退/重写。
     * 集成方在 UI 层应该直接覆盖显示，不要拼接。
     *
     * @param text 当前累计的文本（未做 ITN / 标点）
     */
    public fun onPartial(text: String) {}

    /** 部分识别结果（带置信度 / token / 时间戳的完整版）。默认实现委托给 [onPartial]。 */
    public fun onPartial(result: AsrResult) {
        onPartial(result.text)
    }

    /**
     * 最终识别结果。一段话结束时只触发一次。
     *
     * 文本已经过 SDK 内部串联好的后处理：
     * - 若 [AsrConfig.itn] = true 且语言为 [AsrLanguage.ZH_EN]：ITN 已经做过
     * - 若 [AsrConfig.punctuation] = true：标点已经加过
     *
     * 触发条件：
     * - 引擎判定 endpoint
     * - 调用方主动 [AsrSession.stop]
     *
     * @param text 一段话的最终文本（含标点 / 已 ITN）
     * @param confidence 置信度，[0.0, 1.0]；模型不支持时恒为 1.0
     */
    public fun onFinal(text: String, confidence: Float) {}

    /** 最终识别结果（带 token / 时间戳的完整版）。默认实现委托给 [onFinal]。 */
    public fun onFinal(result: AsrResult) {
        onFinal(result.text, result.confidence)
    }

    /**
     * 一段话结束、但被目标说话人开关判定为"非目标"而过滤掉时触发（替代该段的 [onFinal]）。
     *
     * 仅在目标说话人开关开启、已注册目标、且该段被判为非目标时调用；此时不会再触发 [onFinal]。
     * [result] 携带被过滤段的文本与 [AsrResult.speakerScore]，便于业务自定义呈现（如灰显 / 折叠）。
     * 默认 no-op：默认行为即"丢弃非目标段"。
     */
    public fun onFinalRejected(result: AsrResult) {}

    /**
     * 端点检测：检测到一段话结束。
     *
     * 该事件在 [onFinal] 之前触发，便于 UI 切状态（"正在识别…" -> "等待下一句"）。
     */
    public fun onEndpoint() {}

    /**
     * 调试事件。用于 demo / 集成期观察内部状态，不承诺稳定格式；生产业务可忽略。
     */
    public fun onDebug(message: String) {}

    /**
     * 错误回调。错误发生后 session 自动进入"已停止"状态，集成方可以直接 [AsrSession.close]。
     *
     * @param error 错误码 + 错误信息；详见 [AsrErrorCode]
     */
    public fun onError(error: AsrError) {}

    /** Session 已经准备好接收音频；可选监听。 */
    public fun onSessionStarted() {}

    /** Session 已经停止接收音频（[AsrSession.stop] 之后或 [AsrSession.close] 之后）。 */
    public fun onSessionStopped() {}

    /**
     * 端侧标准指标回调。
     *
     * 时机：
     * - [AmphionMetricsKind.UTTERANCE]：每段话 [onFinal] 同帧派发；engine 第一段会附带启动期字段
     *   （assetInstallMs / engineReadyMs / nativeRssMbAtReady）
     * - [AmphionMetricsKind.SESSION]：[AsrEngine.close] 时派发一次，汇总该 engine 生命周期
     *
     * 业务方不实现也可以；指标始终会通过 logcat (tag = AmphionMetrics) 输出，方便事后排查。
     */
    public fun onMetrics(metrics: AmphionMetrics) {}
}
