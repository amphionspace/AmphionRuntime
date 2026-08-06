package com.lits.tts.sdk.internal

import android.util.Log
import java.io.File

internal object NativeTnNormalizer {
    private const val TAG = "LitsTnNative"

    private val isAvailable: Boolean by lazy {
        try {
            System.loadLibrary("lits_tn")
            Log.i(TAG, "native TN library loaded name=lits_tn")
            true
        } catch (error: Throwable) {
            Log.w(TAG, "native TN library is unavailable", error)
            false
        }
    }
    private val lastCallProfileByThread = ThreadLocal<CallProfile?>()
    private val lastBatchCallProfileByThread = ThreadLocal<BatchCallProfile?>()

    data class CallProfile(
        val availabilityMs: Long,
        val jniMs: Long,
    )

    data class BatchCallProfile(
        val wallMs: Long,
        val availabilityMs: Long,
        val jniMs: Long,
        val itemCount: Int,
    )

    fun normalize(rootDir: File, lang: String, text: String): String? {
        val availabilityStartedAt = System.nanoTime()
        if (!isAvailable) {
            lastCallProfileByThread.set(CallProfile(elapsedMs(availabilityStartedAt), 0L))
            return null
        }
        val availabilityMs = elapsedMs(availabilityStartedAt)
        Log.i(TAG, "native TN normalize start lang=$lang root=${rootDir.absolutePath} input=${text.takeForLog()}")
        val jniStartedAt = System.nanoTime()
        return normalizeNative(rootDir.absolutePath, lang, text).also { normalized ->
            lastCallProfileByThread.set(CallProfile(availabilityMs, elapsedMs(jniStartedAt)))
            Log.i(TAG, "native TN normalize success lang=$lang output=${normalized.takeForLog()}")
        }
    }

    fun lastCallProfile(): CallProfile? = lastCallProfileByThread.get()

    fun normalizeBatch(rootDir: File, langs: Array<String>, texts: Array<String>): Array<String>? {
        require(langs.size == texts.size) { "TN batch languages/texts size mismatch" }
        val startedAt = System.nanoTime()
        val availabilityStartedAt = System.nanoTime()
        if (!isAvailable) {
            lastBatchCallProfileByThread.set(
                BatchCallProfile(
                    wallMs = elapsedMs(startedAt),
                    availabilityMs = elapsedMs(availabilityStartedAt),
                    jniMs = 0L,
                    itemCount = texts.size,
                ),
            )
            return null
        }
        val availabilityMs = elapsedMs(availabilityStartedAt)
        val jniStartedAt = System.nanoTime()
        return normalizeBatchNative(rootDir.absolutePath, langs, texts).also {
            lastBatchCallProfileByThread.set(
                BatchCallProfile(
                    wallMs = elapsedMs(startedAt),
                    availabilityMs = availabilityMs,
                    jniMs = elapsedMs(jniStartedAt),
                    itemCount = texts.size,
                ),
            )
        }
    }

    fun lastBatchCallProfile(): BatchCallProfile? = lastBatchCallProfileByThread.get()

    fun clear(rootDir: File) {
        if (!isAvailable) return
        runCatching { clearCacheNative(rootDir.absolutePath) }
    }

    private external fun normalizeNative(rulesRoot: String, lang: String, text: String): String

    private external fun normalizeBatchNative(
        rulesRoot: String,
        langs: Array<String>,
        texts: Array<String>,
    ): Array<String>

    private external fun clearCacheNative(rulesRoot: String)

    private fun String.takeForLog(maxLength: Int = 160): String =
        if (length <= maxLength) this else take(maxLength) + "...(len=$length)"

    private fun elapsedMs(startedAt: Long): Long = (System.nanoTime() - startedAt) / 1_000_000L
}
