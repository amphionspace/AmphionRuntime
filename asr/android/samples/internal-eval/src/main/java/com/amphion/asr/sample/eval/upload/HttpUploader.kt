package com.amphion.asr.sample.eval.upload

import android.util.Log
import com.amphion.asr.sample.eval.data.RecordingStore
import com.amphion.asr.sample.eval.data.UploadSettings
import com.amphion.asr.sample.eval.model.RecordingMeta
import com.amphion.asr.sample.eval.model.UploadMeta
import okhttp3.Headers
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.TimeUnit

/**
 * 把一条录音 POST 到云端 eval-collector 服务（详见 docs/eval/SERVER_SPEC.md）。
 *
 * 协议要点：
 * - POST /v1/recordings/{recording_id}
 * - multipart/form-data：meta(application/json) + audio(audio/wav) + hypothesis(text/plain optional)
 * - Authorization: Bearer <token>
 *
 * 响应分类：
 * - 200 status=stored / status=duplicate => 成功
 * - 4xx => 永久失败（state=FAILED）
 * - 5xx / 网络异常 => 临时失败（state=RETRY），等下次扫描
 *
 * 重试与退避由 [UploadScanner] 编排；本类只做"单次尝试"。
 * 失败时返回 [Result.Failure]，由调用方更新 meta.json，不在本类做磁盘 IO。
 */
class HttpUploader(
    private val settings: UploadSettings,
    private val client: OkHttpClient = defaultClient,
) {

    sealed class Result {
        /** 成功（包含 duplicate）。 */
        data class Success(val duplicate: Boolean) : Result()

        /** 永久失败（4xx），不应重试。 */
        data class Failure(val httpCode: Int, val errorCode: String?, val message: String) : Result()

        /** 临时失败（5xx / 网络异常），下次扫描重试。 */
        data class Retry(val message: String) : Result()
    }

    /**
     * 上传一条录音。调用方提前保证：
     * - settings.isConfigured() == true
     * - item.audio 与 item.metaFile 文件存在
     * - meta.upload.state in {pending, retry, failed}
     *
     * 本方法不修改 meta.json，由调用方根据 Result 决定如何 persist。
     */
    fun uploadOnce(item: RecordingStore.ScanItem): Result {
        val baseUrl = settings.serverUrl()?.trimEnd('/')
            ?: return Result.Failure(0, "NOT_CONFIGURED", "server_url 未配置")
        val token = settings.bearerToken()
            ?: return Result.Failure(0, "NOT_CONFIGURED", "bearer_token 未配置")

        val url = "$baseUrl/v1/recordings/${item.meta.recordingId}"

        val multipart = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addPart(
                Headers.headersOf(
                    "Content-Disposition",
                    """form-data; name="meta"; filename="meta.json""""
                ),
                item.metaFile.asRequestBody("application/json".toMediaType()),
            )
            .addPart(
                Headers.headersOf(
                    "Content-Disposition",
                    """form-data; name="audio"; filename="audio.wav""""
                ),
                item.audio.asRequestBody("audio/wav".toMediaType()),
            )
            .apply {
                if (item.hypothesis.isFile) {
                    addPart(
                        Headers.headersOf(
                            "Content-Disposition",
                            """form-data; name="hypothesis"; filename="hypothesis.txt""""
                        ),
                        item.hypothesis.asRequestBody("text/plain".toMediaType()),
                    )
                }
            }
            .build()

        val request = Request.Builder()
            .url(url)
            .post(multipart)
            .header("Authorization", "Bearer $token")
            .header("X-Amphion-Schema-Version", item.meta.schemaVersion.toString())
            .build()

        return try {
            client.newCall(request).execute().use { resp ->
                val code = resp.code
                val body = try { resp.body?.string() ?: "" } catch (_: Throwable) { "" }
                classify(code, body)
            }
        } catch (e: IOException) {
            Result.Retry("网络错误: ${e.javaClass.simpleName} ${e.message ?: ""}")
        } catch (t: Throwable) {
            Log.w(TAG, "uploadOnce uncaught: ${t.message}")
            Result.Retry("上传异常: ${t.message}")
        }
    }

    companion object {
        private const val TAG = "HttpUploader"

        /**
         * 永久失败的 body.code 列表（来自 SERVER_SPEC §1.6）。
         * 在此列表中的错误，客户端不应重试 —— 重试也只会得到同样的错。
         * 不在此列表（如 RATE_LIMITED / STORAGE_FULL）一律视为重试。
         */
        internal val PERMANENT_CODES: Set<String> = setOf(
            "SCHEMA_MISMATCH",
            "INVALID_AUDIO",
            "RECORDING_ID_MISMATCH",
            "UNAUTHORIZED",
            "FORBIDDEN",
            "PAYLOAD_TOO_LARGE",
            "UNSUPPORTED_MEDIA_TYPE",
        )

        /**
         * 服务端没返回 body.code 时的 HTTP code → 标准 code 回退表。
         * 仅用于推断永久性（这些 HTTP code 本身语义足够强）。
         */
        private val HTTP_CODE_FALLBACK: Map<Int, String> = mapOf(
            401 to "UNAUTHORIZED",
            403 to "FORBIDDEN",
            413 to "PAYLOAD_TOO_LARGE",
            415 to "UNSUPPORTED_MEDIA_TYPE",
        )

        /**
         * 按 SERVER_SPEC §1.6 / CLIENT_INTEGRATION §6.2 分类响应。
         *
         * 关键原则：**按 body.code 而非 HTTP code 判定永久 / 重试**。
         *
         * - 2xx → 成功（含 duplicate）
         * - 4xx + body.code ∈ PERMANENT_CODES → Failure（不再重试）
         * - 4xx + body.code 缺失 → 按 HTTP code 推断（401/403/413/415 也归永久）
         * - 4xx + body.code 不在永久列表（如 RATE_LIMITED 429）→ Retry
         * - 5xx / 网络异常 → Retry
         *
         * 设计取舍：早期实现"凡 4xx 都 Failure"，但 spec 6.2 明确把 RATE_LIMITED 归到重试。
         * 凡 4xx 永久会让"短时连发→撞 429→永久丢弃"成为数据丢失级 bug。
         *
         * 提为 companion 静态方法以便纯 JVM 单测（不需 Context）。
         */
        internal fun classify(code: Int, body: String): Result {
            if (code in 200..299) return parseSuccessBody(body)
            val (bodyCode, message) = parseErrorBody(body)
            if (code in 400..499) {
                val effective = bodyCode ?: HTTP_CODE_FALLBACK[code]
                val msg = message.ifBlank { effective ?: "HTTP $code" }
                return if (effective != null && effective in PERMANENT_CODES) {
                    Result.Failure(code, effective, msg)
                } else {
                    Result.Retry("HTTP $code ${effective ?: ""}: $msg".trim())
                }
            }
            if (code in 500..599) {
                return Result.Retry(
                    "HTTP $code ${bodyCode ?: ""}: ${message.ifBlank { "服务器错误" }}".trim()
                )
            }
            return Result.Retry("未知 HTTP $code")
        }

        private fun parseSuccessBody(body: String): Result {
            if (body.isBlank()) return Result.Success(duplicate = false)
            return try {
                val o = JSONObject(body)
                val status = o.optString("status", "stored")
                Result.Success(duplicate = status == "duplicate")
            } catch (_: Throwable) {
                Log.w(TAG, "non-JSON success body: ${body.take(80)}")
                Result.Success(duplicate = false)
            }
        }

        private fun parseErrorBody(body: String): Pair<String?, String> {
            if (body.isBlank()) return null to ""
            return try {
                val o = JSONObject(body)
                val code = if (o.has("code") && !o.isNull("code")) {
                    o.optString("code", "").takeUnless { it.isEmpty() }
                } else null
                code to o.optString("message", body)
            } catch (_: Throwable) {
                null to body.take(200)
            }
        }

        /**
         * 共享 OkHttpClient，超时按 SERVER_SPEC.md 建议设置：
         * - connect 15s（弱网下握手可能慢）
         * - read 60s（5MB 音频在 1Mbps 上传约需 40s）
         * - write 60s
         * 不开 retryOnConnectionFailure（由 UploadScanner 编排重试）
         */
        val defaultClient: OkHttpClient by lazy {
            OkHttpClient.Builder()
                .connectTimeout(15, TimeUnit.SECONDS)
                .readTimeout(60, TimeUnit.SECONDS)
                .writeTimeout(60, TimeUnit.SECONDS)
                .retryOnConnectionFailure(false)
                .build()
        }

        /** ISO8601 时间戳（UTC）。 */
        fun nowIso(): String {
            val fmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US)
            fmt.timeZone = TimeZone.getTimeZone("UTC")
            return fmt.format(Date())
        }

        /**
         * 根据 [Result] 把 meta.upload 状态机推进到下一态。
         * 不做磁盘写盘，由调用方拿到新 meta 后再 [RecordingStore.writeMeta]。
         */
        fun advance(meta: RecordingMeta, serverUrl: String?, result: Result): RecordingMeta {
            val now = nowIso()
            val newUpload = when (result) {
                is Result.Success -> meta.upload.copy(
                    state = UploadMeta.State.UPLOADED,
                    uploadedAt = now,
                    attempts = meta.upload.attempts + 1,
                    lastAttemptAt = now,
                    lastError = null,
                    serverUrl = serverUrl,
                )
                is Result.Failure -> meta.upload.copy(
                    state = UploadMeta.State.FAILED,
                    attempts = meta.upload.attempts + 1,
                    lastAttemptAt = now,
                    lastError = "[${result.errorCode ?: "?"}] HTTP ${result.httpCode}: ${result.message}",
                )
                is Result.Retry -> meta.upload.copy(
                    state = UploadMeta.State.RETRY,
                    attempts = meta.upload.attempts + 1,
                    lastAttemptAt = now,
                    lastError = result.message,
                )
            }
            return meta.withUpload(newUpload)
        }
    }
}

@Suppress("unused")
private fun emptyBody(): RequestBody = "".toRequestBody("text/plain".toMediaType())
