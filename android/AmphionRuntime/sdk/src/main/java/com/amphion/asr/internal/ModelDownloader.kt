package com.amphion.asr.internal

import android.content.Context
import com.amphion.asr.AsrError
import com.amphion.asr.AsrErrorCode
import com.amphion.asr.Cancellable
import com.amphion.asr.ModelDescriptor
import com.amphion.asr.ModelDownloadCallback
import com.amphion.asr.ModelFile
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

internal class ModelDownloader(private val appCtx: Context) {

    private val executor = Executors.newSingleThreadExecutor { r ->
        Thread(r, "asr-model-downloader").apply { isDaemon = true }
    }

    fun ensure(manifestUrl: String, callback: ModelDownloadCallback): Cancellable {
        val handle = CancellableImpl()
        executor.submit {
            try {
                doEnsure(manifestUrl, callback, handle)
            } catch (t: Throwable) {
                Logger.e("ensure failed: ${t.message}", t)
                callback.onError(modelIdGuess(manifestUrl),
                    AsrError(AsrErrorCode.IO_FAILED, t.message ?: "unknown", t))
            } finally {
                handle.markDone()
            }
        }
        return handle
    }

    private fun doEnsure(
        manifestUrl: String,
        callback: ModelDownloadCallback,
        handle: CancellableImpl,
    ) {
        Logger.i("download manifest: $manifestUrl")
        val manifestText = httpGetString(manifestUrl)
            ?: return callback.onError(
                modelIdGuess(manifestUrl),
                AsrError(AsrErrorCode.NETWORK_UNAVAILABLE, "fetch manifest failed: $manifestUrl")
            )

        val manifest: ModelDescriptor = try {
            ModelDescriptor.fromJson(manifestText)
        } catch (t: Throwable) {
            return callback.onError(
                modelIdGuess(manifestUrl),
                AsrError(AsrErrorCode.MODEL_MANIFEST_PARSE_ERROR,
                    "invalid manifest.json: ${t.message}", t)
            )
        }

        val modelDir = File(appCtx.filesDir, "asr-models/${manifest.modelId}/${manifest.version}")
        val tmpDir = File(appCtx.filesDir, "asr-models/.tmp/${manifest.modelId}/${manifest.version}")

        if (modelDir.isDirectory && allFilesValid(modelDir, manifest.files)) {
            Logger.i("model already downloaded & valid: $modelDir")
            callback.onCompleted(manifest.modelId, modelDir)
            return
        }

        // 重新下载到 tmpDir，全部校验通过后原子替换
        if (tmpDir.exists()) tmpDir.deleteRecursively()
        if (!tmpDir.mkdirs()) {
            return callback.onError(manifest.modelId,
                AsrError(AsrErrorCode.STORAGE_INSUFFICIENT, "cannot create tmp dir: ${tmpDir.absolutePath}"))
        }

        val total = manifest.files.sumOf { it.sizeBytes }
        var downloaded = 0L

        for (f in manifest.files) {
            if (handle.cancelled) {
                tmpDir.deleteRecursively()
                return callback.onError(manifest.modelId,
                    AsrError(AsrErrorCode.DOWNLOAD_FAILED, "user cancelled"))
            }

            val target = File(tmpDir, f.name)
            try {
                downloadOne(f, target) { delta ->
                    downloaded += delta
                    callback.onProgress(manifest.modelId, downloaded, total)
                    if (handle.cancelled) throw InterruptedException("cancelled")
                }
            } catch (e: InterruptedException) {
                tmpDir.deleteRecursively()
                return callback.onError(manifest.modelId,
                    AsrError(AsrErrorCode.DOWNLOAD_FAILED, "user cancelled"))
            } catch (t: Throwable) {
                tmpDir.deleteRecursively()
                return callback.onError(manifest.modelId,
                    AsrError(AsrErrorCode.DOWNLOAD_FAILED,
                        "download ${f.name} failed: ${t.message}", t))
            }

            if (!Sha256Verifier.matches(target, f.sha256)) {
                tmpDir.deleteRecursively()
                return callback.onError(manifest.modelId,
                    AsrError(AsrErrorCode.SHA256_MISMATCH,
                        "sha256 mismatch on ${f.name}"))
            }
        }

        // 原子替换：先把旧目录改名为 modelDir.bak，把 tmpDir 改名为 modelDir
        val bak = File(modelDir.parentFile, "${modelDir.name}.bak.${System.currentTimeMillis()}")
        if (modelDir.exists() && !modelDir.renameTo(bak)) {
            // 重命名失败，硬删
            modelDir.deleteRecursively()
        }
        if (!tmpDir.renameTo(modelDir)) {
            tmpDir.deleteRecursively()
            if (bak.exists()) bak.renameTo(modelDir)
            return callback.onError(manifest.modelId,
                AsrError(AsrErrorCode.STORAGE_INSUFFICIENT, "cannot move tmp -> final"))
        }
        if (bak.exists()) bak.deleteRecursively()

        // 把 manifest.json 也保存到目录里，方便后续 listLocal / 调试
        File(modelDir, "manifest.json").writeText(manifestText)

        Logger.i("model ready: $modelDir")
        callback.onCompleted(manifest.modelId, modelDir)
    }

    private fun allFilesValid(dir: File, files: List<ModelFile>): Boolean {
        for (f in files) {
            val local = File(dir, f.name)
            if (!local.isFile) return false
            if (local.length() != f.sizeBytes) return false
            if (!Sha256Verifier.matches(local, f.sha256)) return false
        }
        return true
    }

    private fun downloadOne(file: ModelFile, dst: File, onProgress: (Long) -> Unit) {
        val timeout = Logger.httpTimeoutMs
        val conn = (URL(file.url).openConnection() as HttpURLConnection).apply {
            connectTimeout = timeout
            readTimeout = timeout
            requestMethod = "GET"
            instanceFollowRedirects = true
            setRequestProperty("Accept", "*/*")
            setRequestProperty("User-Agent", "AsrSdk/${com.amphion.asr.BuildConfig.SDK_VERSION}")
        }

        try {
            val code = conn.responseCode
            if (code !in 200..299) {
                throw RuntimeException("HTTP $code on ${file.url}")
            }
            conn.inputStream.use { input ->
                FileOutputStream(dst).use { out ->
                    val buf = ByteArray(64 * 1024)
                    while (true) {
                        val n = input.read(buf)
                        if (n <= 0) break
                        out.write(buf, 0, n)
                        onProgress(n.toLong())
                    }
                    out.fd.sync()
                }
            }
        } finally {
            conn.disconnect()
        }
    }

    private fun httpGetString(url: String): String? {
        val timeout = Logger.httpTimeoutMs
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = timeout
            readTimeout = timeout
            requestMethod = "GET"
            instanceFollowRedirects = true
        }
        return try {
            val code = conn.responseCode
            if (code !in 200..299) null else conn.inputStream.bufferedReader().use { it.readText() }
        } catch (t: Throwable) {
            Logger.e("httpGetString $url failed: ${t.message}", t)
            null
        } finally {
            conn.disconnect()
        }
    }

    private fun modelIdGuess(manifestUrl: String): String {
        return try {
            URL(manifestUrl).path.trimEnd('/').substringBeforeLast('/')
                .substringAfterLast('/')
                .ifEmpty { "<unknown>" }
        } catch (_: Throwable) {
            "<unknown>"
        }
    }

    private class CancellableImpl : Cancellable {
        @Volatile
        var cancelled: Boolean = false
            private set
        private val done = AtomicBoolean(false)

        override fun cancel() {
            cancelled = true
        }

        override val isDone: Boolean
            get() = done.get()

        fun markDone() {
            done.set(true)
        }
    }
}
