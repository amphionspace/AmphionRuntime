package com.amphion.asr

/**
 * SDK 通用错误。出现错误时 SDK 不会让 native 崩溃透传，所有 native 异常都会被捕获
 * 并归一为 [AsrErrorCode.NATIVE_CRASH]。
 *
 * @property code 错误码，取自 [AsrErrorCode]
 * @property message 简明描述，可直接打日志/上报
 * @property cause 底层异常，可能为 null
 */
public data class AsrError(
    public val code: Int,
    public val message: String,
    public val cause: Throwable? = null,
) {
    public override fun toString(): String =
        "AsrError(code=$code, message=$message" +
            (cause?.let { ", cause=${it.javaClass.simpleName}: ${it.message}" } ?: "") + ")"
}

/**
 * SDK 错误码常量。
 *
 * 分段：
 * - 1xxx 调用约定（参数 / 状态）
 * - 2xxx 资源（首次安装失败）
 * - 3xxx 运行时（识别 / 后处理）
 * - 9xxx native 兜底
 *
 * 业务方一般只需要关心：
 * - [SDK_NOT_INITIALIZED]：忘了 [AmphionRuntime.init]
 * - [LANGUAGE_UNAVAILABLE]：传入的 [AsrLanguage] 在当前 SDK 版本不可用
 * - [ASSET_INSTALL_FAILED]：首次解包失败（多半是磁盘空间不足）
 * - [SESSION_ALREADY_CLOSED]：用了已 close 的 session
 * - 其他错误码视为「重启 session 重试」即可
 */
public object AsrErrorCode {

    public const val OK: Int = 0

    public const val INVALID_ARGUMENT: Int = 1001
    public const val SDK_NOT_INITIALIZED: Int = 1002
    public const val SESSION_ALREADY_CLOSED: Int = 1003

    public const val LANGUAGE_UNAVAILABLE: Int = 2001
    public const val ASSET_INSTALL_FAILED: Int = 2002
    public const val STORAGE_INSUFFICIENT: Int = 2003

    public const val DECODE_FAILED: Int = 3001
    public const val POSTPROCESS_FAILED: Int = 3002

    public const val NATIVE_CRASH: Int = 9001
}
