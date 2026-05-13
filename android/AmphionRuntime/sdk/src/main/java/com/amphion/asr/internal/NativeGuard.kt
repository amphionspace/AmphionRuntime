package com.amphion.asr.internal

import com.amphion.asr.AsrError
import com.amphion.asr.AsrErrorCode

/**
 * 把对 native（JNI）层的调用包装到统一的"不让进程崩溃"路径中。
 *
 * 设计目标：
 *
 * - 进程级保护：JNI 抛出的 [Error]（含 LinkageError/UnsatisfiedLinkError/OutOfMemoryError/
 *   StackOverflowError 等 Throwable 子类）一律捕获，不让 Java 调用栈直接崩溃；只有真正的
 *   native segfault / abort 才会绕过 JVM，那是 OS 级问题，归 ANR/Tombstone 处理
 * - 错误码归一：所有捕获的异常都映射到 [AsrErrorCode.NATIVE_CRASH]（9001），调用方只需要
 *   一个错误码就能处理"native 出问题，应当 close session 重建"的场景
 * - 区分业务错误：业务级错误（如采样率不匹配）应该走 [AsrErrorCode.SAMPLE_RATE_MISMATCH] 等
 *   独立错误码，不要套这个 helper
 *
 * 使用：
 *
 * ```
 * val r = NativeGuard.run("decode") { recognizer.decode(stream) }
 * when (r) {
 *     is NativeResult.Ok -> ... r.value
 *     is NativeResult.Err -> postError(r.error)
 * }
 * ```
 */
internal object NativeGuard {

    /**
     * 执行 [block]；任何 [Throwable]（包括 [Error]）都捕获并以 [NativeResult.Err] 形式返回。
     */
    inline fun <R> run(opName: String, block: () -> R): NativeResult<R> {
        return try {
            NativeResult.Ok(block())
        } catch (t: Throwable) {
            // Catch Throwable 是有意为之：UnsatisfiedLinkError 等是 Error 的子类
            Logger.e("[NativeGuard] $opName threw: ${t.javaClass.simpleName}: ${t.message}", t)
            NativeResult.Err(
                AsrError(
                    code = AsrErrorCode.NATIVE_CRASH,
                    message = "$opName failed: ${t.message ?: t.javaClass.simpleName}",
                    cause = t,
                )
            )
        }
    }

    /**
     * 执行 [block]；任何异常都吞掉只打日志，返回 null。用于 close / release 之类不能再向上报错的路径。
     */
    inline fun <R> runQuietly(opName: String, block: () -> R): R? {
        return try {
            block()
        } catch (t: Throwable) {
            Logger.w("[NativeGuard] $opName failed (ignored in quiet mode): ${t.message}")
            null
        }
    }
}

/** 包装 native 调用结果。Kotlin 没有 union type，自己造一个。 */
internal sealed class NativeResult<out R> {
    data class Ok<R>(val value: R) : NativeResult<R>()
    data class Err(val error: AsrError) : NativeResult<Nothing>()
}
