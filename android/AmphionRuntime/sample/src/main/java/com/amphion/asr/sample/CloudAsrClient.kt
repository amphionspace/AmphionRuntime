package com.amphion.asr.sample

import android.util.Base64
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 云端流式 ASR 客户端：对接 Amphion 开放平台「增强型流式 ASR」WebSocket
 * （wss://amphion.top/asr/v1/clean-stream）。
 *
 * 一个实例对应一次录音会话，**不可复用**：[start] 一次，期间持续 [sendPcm]，结束 [stop]，
 * 销毁 [close]。所有回调都在 okhttp 的派发线程触发，UI 更新需调用方自行 post 回主线程。
 *
 * 协议时序（与平台文档一致）：
 * 1. 连接成功后服务端先发 `session.created`；客户端随即发送一次 `session.update`
 *    （language / cleanup / hotwords），并必须等到 `session.updated` 才能推音频；
 *    其间若收到 `session.waiting` 则保持连接继续等。
 * 2. 音频为 PCM int16 / 16k / mono，**base64 后**装进 `input_audio_buffer.append` 的 `audio`
 *    字段发送（文本帧，不是二进制帧）。ready 前把 PCM 缓冲起来，ready 时整块 base64 flush。
 * 3. 结束时发 `input_audio_buffer.commit` 且 `final=true`；服务端做完最终清洗后回
 *    `transcription.done`。发完 commit 后保留连接 [STOP_GRACE_MS] 收尾再关。
 * 4. 增量事件 `transcription.delta` / `postprocess.delta` 的 `text` 是累积文本 → onPartial；
 *    `transcription.done` 的 `cleaned_text`（无则 `text`）为最终结果 → onFinal。
 *
 * 鉴权走 `Authorization: Bearer <apiKey>` 请求头，不拼进 URL，避免 key 落到日志/状态栏。
 *
 * 失败域隔离：云端任何异常都只走 [Listener.onError] / [Listener.onStatus]，绝不抛回录音线程，
 * 因此端侧 SDK 识别完全不受影响。
 */
class CloudAsrClient(
    private val url: String,
    private val apiKey: String,
    private val language: String?,
    private val hotwords: List<String>,
    private val listener: Listener,
) {

    enum class Status { CONNECTING, READY, STOPPING, CLOSED }

    interface Listener {
        fun onStatus(status: Status, detail: String?)
        fun onPartial(text: String)
        fun onFinal(text: String, durationSec: Double?)
        fun onError(message: String)
    }

    private val lock = Any()

    /** 收到 `session.updated` 后才允许直接发音频；之前先缓冲。 */
    private var ready = false

    /** ready 前的 PCM 缓冲；ready 时整块 base64 flush。超过 [MAX_PENDING_BYTES] 丢弃新帧。 */
    private val pending = ByteArrayOutputStream()

    @Volatile
    private var webSocket: WebSocket? = null

    private val closed = AtomicBoolean(false)

    /** CLOSED 状态只对外发一次（onClosed/onFailure 与主动 close 可能都想发）。 */
    private val closedEmitted = AtomicBoolean(false)

    private val scheduler: ScheduledExecutorService =
        Executors.newSingleThreadScheduledExecutor { r ->
            Thread(r, "cloud-asr-close").apply { isDaemon = true }
        }
    private var closeFuture: ScheduledFuture<*>? = null

    fun start() {
        listener.onStatus(Status.CONNECTING, url)
        val request = try {
            Request.Builder()
                .url(url)
                .addHeader("Authorization", "Bearer $apiKey")
                .build()
        } catch (t: Throwable) {
            listener.onError("invalid url: ${t.message}")
            emitClosed(t.message)
            return
        }
        webSocket = sharedClient.newWebSocket(request, SocketListener())
    }

    /**
     * 投递一帧 PCM（16k、mono、s16le，与录音线程同源）。线程安全：可从录音线程直接调用。
     * ready 前缓冲、ready 后立即 base64 发送；[close] 后静默丢弃。
     */
    fun sendPcm(samples: ShortArray) {
        if (closed.get() || samples.isEmpty()) return
        val bytes = shortsToLeBytes(samples)
        val sendNow: Boolean
        synchronized(lock) {
            sendNow = ready
            if (!ready && pending.size() + bytes.size <= MAX_PENDING_BYTES) {
                pending.write(bytes)
            }
        }
        if (sendNow) webSocket?.send(appendMessage(bytes))
    }

    /** 结束输入：发 commit(final=true)，保留连接 [STOP_GRACE_MS] 收 `transcription.done` 后自动 [close]。 */
    fun stop() {
        if (closed.get()) return
        val ws = webSocket
        if (ws != null && ready) {
            ws.send(
                JSONObject()
                    .put("type", "input_audio_buffer.commit")
                    .put("final", true)
                    .toString()
            )
        }
        listener.onStatus(Status.STOPPING, null)
        synchronized(lock) {
            if (closed.get()) return
            closeFuture?.cancel(false)
            closeFuture = try {
                scheduler.schedule({ close() }, STOP_GRACE_MS, TimeUnit.MILLISECONDS)
            } catch (_: Throwable) {
                null
            }
        }
    }

    /** 立即关闭并释放；多次调用幂等。 */
    fun close() {
        if (!closed.compareAndSet(false, true)) return
        synchronized(lock) { closeFuture?.cancel(false) }
        val ws = webSocket
        webSocket = null
        try {
            ws?.close(NORMAL_CLOSE, "client closing")
        } catch (_: Throwable) {
        }
        // 没连上就 close 时不会有 onClosed 回调，这里兜底发一次 CLOSED。
        if (ws == null) emitClosed(null)
        scheduler.shutdown()
    }

    /** 收到 session.created：发送唯一一次 session.update（此时仍未 ready，音频继续缓冲）。 */
    private fun onSessionCreated() {
        synchronized(lock) {
            webSocket?.send(buildSessionUpdate())
        }
    }

    /** 收到 session.updated：进入 ready，整块 flush 已缓冲音频。 */
    private fun onReady() {
        val flush: ByteArray
        synchronized(lock) {
            if (ready) return
            ready = true
            flush = pending.toByteArray()
            pending.reset()
        }
        if (flush.isNotEmpty()) webSocket?.send(appendMessage(flush))
        listener.onStatus(Status.READY, null)
    }

    private fun buildSessionUpdate(): String {
        val o = JSONObject()
        o.put("type", "session.update")
        o.put("language", if (language.isNullOrBlank()) "auto" else language)
        o.put("translate_mode", false)
        o.put("cleanup", JSONObject().put("level", "light"))
        if (hotwords.isNotEmpty()) {
            o.put("hotwords", JSONObject().put("custom", JSONArray(hotwords)))
        }
        return o.toString()
    }

    private fun appendMessage(pcm: ByteArray): String {
        val b64 = Base64.encodeToString(pcm, Base64.NO_WRAP)
        return JSONObject()
            .put("type", "input_audio_buffer.append")
            .put("audio", b64)
            .toString()
    }

    private fun handleMessage(text: String) {
        val obj = try {
            JSONObject(text)
        } catch (t: Throwable) {
            Log.w(TAG, "non-JSON message dropped: ${t.message}")
            return
        }
        when (obj.optString("type")) {
            "session.created" -> onSessionCreated()
            "session.updated" -> onReady()
            "session.waiting" -> listener.onStatus(Status.CONNECTING, "waiting")
            "transcription.delta", "postprocess.delta" ->
                listener.onPartial(obj.optString("text"))
            "transcription.done" -> {
                val finalText = obj.optString("cleaned_text").ifBlank { obj.optString("text") }
                val dur = obj.optJSONObject("usage")
                    ?.optDouble("seconds")
                    ?.takeIf { !it.isNaN() }
                listener.onFinal(finalText, dur)
            }
            "error" -> listener.onError(obj.optString("message", "unknown error"))
            else -> Log.d(TAG, "ignored message type=${obj.optString("type")}")
        }
    }

    private fun emitClosed(detail: String?) {
        if (closedEmitted.compareAndSet(false, true)) {
            listener.onStatus(Status.CLOSED, detail)
        }
    }

    private inner class SocketListener : WebSocketListener() {
        override fun onMessage(webSocket: WebSocket, text: String) {
            if (closed.get()) return
            handleMessage(text)
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            // 平台用 4001/4002/4003 等业务关闭码表达鉴权/余额问题，转成可读错误。
            if (code in 4000..4999 && !closed.get()) {
                listener.onError(closeCodeMessage(code, reason))
            }
            try {
                webSocket.close(NORMAL_CLOSE, null)
            } catch (_: Throwable) {
            }
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            closed.set(true)
            emitClosed(reason.takeIf { it.isNotBlank() })
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            if (!closed.get()) {
                listener.onError(t.message ?: "websocket failure")
            }
            closed.set(true)
            emitClosed(t.message)
        }
    }

    private fun closeCodeMessage(code: Int, reason: String): String = when (code) {
        4001 -> "缺少 API Key"
        4002 -> "余额不足"
        4003 -> "鉴权失败（API Key 无效）"
        else -> reason.ifBlank { "服务端关闭（$code）" }
    }

    companion object {
        private const val TAG = "CloudAsrClient"
        private const val NORMAL_CLOSE = 1000

        /** commit 后保留连接收 `transcription.done` 的等待窗口（最终清洗可能耗时）。 */
        private const val STOP_GRACE_MS = 10000L

        /**
         * ready 前的 PCM 缓冲上限 ≈ 4 秒（16000 * 2 * 4）。
         * 服务端对未消费 buffer 有 5 秒上限（超出回 input_audio_rate_exceeded），故 flush 量须 < 5s；
         * 正常建连 + session 协商在 1~2 秒内完成，4 秒缓冲足够覆盖且留安全余量。
         */
        private const val MAX_PENDING_BYTES = 16000 * 2 * 4

        /** 进程内共享：流式连接 readTimeout 关掉，pingInterval 保活。 */
        private val sharedClient: OkHttpClient by lazy {
            OkHttpClient.Builder()
                .pingInterval(20, TimeUnit.SECONDS)
                .readTimeout(0, TimeUnit.SECONDS)
                .build()
        }

        private fun shortsToLeBytes(samples: ShortArray): ByteArray {
            val out = ByteArray(samples.size * 2)
            var i = 0
            var j = 0
            while (i < samples.size) {
                val s = samples[i].toInt()
                out[j] = (s and 0xFF).toByte()
                out[j + 1] = ((s shr 8) and 0xFF).toByte()
                i++
                j += 2
            }
            return out
        }
    }
}
