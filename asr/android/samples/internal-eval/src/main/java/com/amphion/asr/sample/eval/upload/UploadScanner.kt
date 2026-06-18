package com.amphion.asr.sample.eval.upload

import android.util.Log
import com.amphion.asr.sample.eval.data.RecordingStore
import com.amphion.asr.sample.eval.data.UploadSettings
import com.amphion.asr.sample.eval.model.RecordingMeta
import com.amphion.asr.sample.eval.model.UploadMeta
import java.io.File
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.pow
import kotlin.random.Random

/**
 * 扫描 RecordingStore 中所有 pending / retry 状态的录音，串行上传。
 *
 * 触发时机（由 EvalActivity 编排）：
 * - 应用启动 / EvalActivity onResume
 * - 录音保存后立刻一次（轻量化触发，复用同一队列）
 * - 用户点击「立即同步」（含 failed 状态强制重试）
 *
 * 设计要点：
 * - 单线程串行：避免多个 HTTP 请求并发耗光手机内存与服务端连接
 * - 一次 scan 拿到所有候选 → 排序（recordedAt 升序）→ 串行 upload → 更新 meta
 * - 同一时间最多一个 scan 在跑（runFlag），重复调用直接合并到当前
 * - 进度通过 [Listener] 暴露给 UI（UploadStatusBar）
 */
class UploadScanner(
    private val store: RecordingStore,
    private val settings: UploadSettings,
    private val uploader: HttpUploader = HttpUploader(settings),
    private val executor: ExecutorService = Executors.newSingleThreadExecutor { r ->
        Thread(r, "eval-uploader").apply { isDaemon = true }
    },
) {

    interface Listener {
        fun onScanStarted(total: Int)
        fun onItemDone(meta: RecordingMeta, result: HttpUploader.Result, remaining: Int)
        fun onScanFinished(stats: Stats)
    }

    data class Stats(
        val attempted: Int,
        val uploaded: Int,
        val duplicates: Int,
        val retried: Int,
        val failed: Int,
    )

    /** UI 状态快照，供 UploadStatusBar 渲染。 */
    data class Snapshot(
        val pending: Int,
        val uploaded: Int,
        val failed: Int,
        val isRunning: Boolean,
    ) {
        val total: Int get() = pending + uploaded + failed
    }

    private val runFlag = AtomicBoolean(false)
    private val listener = AtomicReference<Listener?>(null)

    fun setListener(l: Listener?) {
        listener.set(l)
    }

    /**
     * 拿到当前 store 中所有 attempt 的状态分布快照（O(N) 遍历，但 < 50ms）。
     * 用于 UI 顶部状态条显示。
     */
    fun snapshot(): Snapshot {
        var p = 0
        var u = 0
        var f = 0
        store.scanAll { meta ->
            when (meta.upload.state) {
                UploadMeta.State.UPLOADED -> u++
                UploadMeta.State.FAILED -> f++
                UploadMeta.State.PENDING,
                UploadMeta.State.RETRY,
                UploadMeta.State.UPLOADING -> p++
            }
            false // 我们只是想用副作用计数，不收集结果
        }
        return Snapshot(p, u, f, runFlag.get())
    }

    /**
     * 触发一轮扫描 + 上传。如果当前已有一轮在跑，直接 no-op。
     *
     * @param includeFailed 是否把 state=FAILED 的也加入重试（用户点「立即同步」时为 true）
     * @param ignoreBackoff 是否绕过指数退避到点判定。用户主动「立即同步」应为 true；
     *                     自动触发（onResume / 录音保存）保持 false，避免无效请求打服务端
     */
    fun trigger(includeFailed: Boolean = false, ignoreBackoff: Boolean = false) {
        if (!settings.isConfigured()) {
            Log.i(TAG, "settings not configured, skip")
            return
        }
        if (!runFlag.compareAndSet(false, true)) {
            Log.i(TAG, "scan already running, skip")
            return
        }
        executor.execute {
            try {
                runScan(includeFailed, ignoreBackoff)
            } catch (t: Throwable) {
                Log.w(TAG, "scan uncaught: ${t.message}")
            } finally {
                runFlag.set(false)
            }
        }
    }

    fun shutdown() {
        executor.shutdownNow()
    }

    private fun runScan(includeFailed: Boolean, ignoreBackoff: Boolean) {
        val nowMs = System.currentTimeMillis()
        val candidates = store.scanAll { meta ->
            when (meta.upload.state) {
                UploadMeta.State.PENDING,
                UploadMeta.State.RETRY,
                UploadMeta.State.UPLOADING -> true
                UploadMeta.State.FAILED -> includeFailed
                UploadMeta.State.UPLOADED -> false
                else -> false
            }
        }.filter { ignoreBackoff || shouldRetryNow(it.meta, nowMs) }
            .sortedBy { it.meta.recordedAt }

        val total = candidates.size
        val l = listener.get()
        l?.onScanStarted(total)

        if (total == 0) {
            l?.onScanFinished(Stats(0, 0, 0, 0, 0))
            return
        }

        var uploaded = 0
        var duplicates = 0
        var retried = 0
        var failed = 0

        candidates.forEachIndexed { idx, item ->
            // 自我限速：保证两次 upload 起始之间至少间隔 MIN_INTERVAL_MS。
            // 服务端默认 1 req/s burst 3；客户端不利用 burst，简化为严格 1 req/s。
            // 大多数情况单条 upload 本身就 > 1s（cosfs 落盘 ~6s），sleep=0；
            // 仅在 4xx 快速返回 / 本地缓存命中等场景生效。
            val startMs = System.currentTimeMillis()
            val result = uploader.uploadOnce(item)
            val newMeta = HttpUploader.advance(item.meta, settings.serverUrl(), result)
            val ok = store.writeMeta(item.dir, newMeta)
            if (!ok) {
                Log.w(TAG, "writeMeta failed at ${item.dir.absolutePath}; result was $result")
            }
            when (result) {
                is HttpUploader.Result.Success -> {
                    if (result.duplicate) duplicates++ else uploaded++
                }
                is HttpUploader.Result.Failure -> failed++
                is HttpUploader.Result.Retry -> retried++
            }
            l?.onItemDone(newMeta, result, total - idx - 1)

            if (idx < total - 1) {
                val elapsed = System.currentTimeMillis() - startMs
                val sleepMs = (MIN_INTERVAL_MS - elapsed).coerceAtLeast(0L)
                if (sleepMs > 0) {
                    try {
                        Thread.sleep(sleepMs)
                    } catch (_: InterruptedException) {
                        Log.i(TAG, "scan interrupted, abort")
                        Thread.currentThread().interrupt()
                        l?.onScanFinished(Stats(idx + 1, uploaded, duplicates, retried, failed))
                        return
                    }
                }
            }
        }

        l?.onScanFinished(Stats(total, uploaded, duplicates, retried, failed))
    }

    companion object {
        private const val TAG = "UploadScanner"

        /** 自我限速：两次上传起始时间最小间隔（毫秒）。对齐服务端 1 req/s 配额。 */
        internal const val MIN_INTERVAL_MS: Long = 1_000L

        /** 退避基数：第一次 Retry 后等待 2s（spec 6.3 base）。 */
        internal const val BACKOFF_BASE_MS: Long = 2_000L

        /** 退避增长因子：每次失败延时翻倍。 */
        internal const val BACKOFF_FACTOR: Double = 2.0

        /** 退避上限：5 分钟（避免单条永远轮询服务端）。 */
        internal const val BACKOFF_MAX_MS: Long = 5L * 60_000L

        /** Jitter 幅度：±20%，避免多 tester 同时启动 app 时的"惊群"重试。 */
        private const val JITTER_RATIO: Double = 0.2

        private val ISO_PARSER = ThreadLocal.withInitial {
            SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).apply {
                timeZone = TimeZone.getTimeZone("UTC")
            }
        }

        /**
         * 计算给定 attempts 后下一次允许重试的最小延时（毫秒）。
         *
         * 公式（spec 6.3）：`min(MAX, BASE * FACTOR^(attempts-1)) * (1 ± JITTER)`
         *
         * - attempts=1：~2s（首次失败后）
         * - attempts=2：~4s
         * - attempts=3：~8s
         * - …
         * - attempts>=9：~5min（上限）
         *
         * Jitter 在 BackoffMax 的 ±20% 范围内随机，避免多 tester 同 onResume 撞服务端。
         */
        internal fun backoffMs(attempts: Int, random: Random = Random.Default): Long {
            val n = attempts.coerceAtLeast(1)
            val raw = (BACKOFF_BASE_MS * BACKOFF_FACTOR.pow((n - 1).toDouble())).toLong()
            val capped = raw.coerceAtMost(BACKOFF_MAX_MS)
            val jitter = 1.0 + (random.nextDouble() * 2.0 - 1.0) * JITTER_RATIO
            return (capped * jitter).toLong().coerceAtLeast(0L)
        }

        /**
         * 判断一条录音此刻是否到了允许（重新）尝试上传的时间点。
         *
         * - PENDING（从未尝试过）：永远 true
         * - RETRY / UPLOADING / FAILED 等已尝试过：必须距 lastAttemptAt 至少 backoff(attempts)
         * - lastAttemptAt 解析失败：保守 true，避免老 meta 永不重传
         */
        internal fun shouldRetryNow(meta: RecordingMeta, nowMs: Long): Boolean {
            if (meta.upload.attempts <= 0) return true
            val lastAt = parseIsoOrNull(meta.upload.lastAttemptAt) ?: return true
            return (nowMs - lastAt) >= backoffMs(meta.upload.attempts)
        }

        private fun parseIsoOrNull(iso: String?): Long? {
            if (iso.isNullOrBlank()) return null
            return try {
                ISO_PARSER.get()?.parse(iso)?.time
            } catch (_: Throwable) {
                null
            }
        }
    }
}

/** 占位避免 lint：未来如果加 WorkManager 后台任务可在这里挂钩，本期暂用空函数。 */
@Suppress("unused", "UNUSED_PARAMETER")
private fun reserveBackgroundHook(dir: File) {}
