package com.yourco.asr

/**
 * 错误：错误码 + 简明 message + 可选原始异常。
 *
 * SDK 不会让 native crash 透传给业务方；任何 native 抛出都会被捕获并归一为 [AsrErrorCode.NATIVE_CRASH]。
 */
public data class AsrError(
    public val code: Int,
    public val message: String,
    public val cause: Throwable? = null,
) {
    public override fun toString(): String =
        "AsrError(code=$code, message=$message${cause?.let { ", cause=${it.javaClass.simpleName}: ${it.message}" } ?: ""})"
}

/**
 * 全部错误码常量，与 [shared/api-spec/errcodes.yaml](../../../../../../../../../../../shared/api-spec/errcodes.yaml)
 * 完全一一对齐（同时与 iOS [AsrErrorCode] 对齐）。
 *
 * 区段：
 * - 1xxx 配置类
 * - 2xxx 模型类
 * - 3xxx 运行时
 * - 4xxx 网络
 * - 5xxx 系统
 * - 9xxx native 兜底
 *
 * 新增/废弃错误码必须先改 errcodes.yaml，再同步 Android / iOS / server。
 */
public object AsrErrorCode {

    public const val OK: Int = 0

    public const val INVALID_ARGUMENT: Int = 1001
    public const val INVALID_SAMPLE_RATE: Int = 1002
    public const val SDK_NOT_INITIALIZED: Int = 1003

    public const val MODEL_DIR_INVALID: Int = 2001
    public const val MODEL_FILE_MISSING: Int = 2002
    public const val MODEL_LOAD_FAILED: Int = 2003
    public const val MODEL_MANIFEST_PARSE_ERROR: Int = 2004

    public const val SESSION_ALREADY_CLOSED: Int = 3001
    public const val SAMPLE_RATE_MISMATCH: Int = 3002
    public const val DECODE_FAILED: Int = 3003

    public const val NETWORK_UNAVAILABLE: Int = 4001
    public const val DOWNLOAD_FAILED: Int = 4002
    public const val SHA256_MISMATCH: Int = 4003

    public const val IO_FAILED: Int = 5001
    public const val STORAGE_INSUFFICIENT: Int = 5002

    public const val NATIVE_CRASH: Int = 9001
}
