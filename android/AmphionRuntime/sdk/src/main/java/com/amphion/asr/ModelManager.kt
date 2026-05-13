package com.amphion.asr

import android.content.Context
import com.amphion.asr.internal.ModelDownloader
import java.io.File

/**
 * 模型下载、本地存储、版本管理。
 *
 * 存储位置：`<filesDir>/asr-models/<modelId>/<version>/`，与 APK 解耦。
 *
 * 不引入 OkHttp / Retrofit，使用 [java.net.HttpURLConnection]，对客户依赖零侵入。
 *
 * 线程安全：所有方法可任意线程调用；[ensure] 内部使用单线程下载队列。
 */
public class ModelManager(context: Context) {

    private val appCtx: Context = context.applicationContext ?: context
    private val downloader: ModelDownloader = ModelDownloader(appCtx)

    /** 列出当前 filesDir 下已存在的模型版本。 */
    public fun listLocal(): List<LocalModel> {
        val root = rootDir()
        if (!root.isDirectory) return emptyList()
        return buildList {
            for (modelDir in root.listFiles().orEmpty()) {
                if (!modelDir.isDirectory) continue
                for (versionDir in modelDir.listFiles().orEmpty()) {
                    if (versionDir.isDirectory) {
                        add(LocalModel(modelDir.name, versionDir.name, versionDir))
                    }
                }
            }
        }
    }

    /**
     * 确保模型已经在本地。流程：
     * 1. 拉取 manifest.json
     * 2. 检查本地目录是否已存在该 (model_id, version)，且全部文件 SHA256 都一致 → 跳过下载
     * 3. 否则把缺失或损坏的文件下载到临时目录，校验通过后原子替换到目标目录
     *
     * 调用方可以保留返回值用 [Cancellable.cancel] 取消任务。
     *
     * @param manifestUrl 你的服务端 manifest.json 的 HTTPS 地址
     * @param callback 下载进度 / 完成 / 错误回调
     * @return 可取消句柄
     */
    public fun ensure(manifestUrl: String, callback: ModelDownloadCallback): Cancellable {
        return downloader.ensure(manifestUrl, callback)
    }

    /**
     * 删除本地某个版本的模型。
     *
     * @return true 如果存在并删除成功，false 如果原本就不存在
     */
    public fun delete(modelId: String, version: String): Boolean {
        val dir = File(rootDir(), "$modelId/$version")
        if (!dir.exists()) return false
        return dir.deleteRecursively()
    }

    /**
     * 返回某个 (model_id, version) 在本地的目录路径，如果不存在返回 null。
     */
    public fun localPath(modelId: String, version: String): File? {
        val dir = File(rootDir(), "$modelId/$version")
        return if (dir.isDirectory) dir else null
    }

    private fun rootDir(): File = File(appCtx.filesDir, "asr-models")
}

/** 模型下载回调。所有方法都在 SDK 下载线程触发，不要做长耗时操作。 */
public interface ModelDownloadCallback {
    /**
     * 下载进度。
     *
     * @param modelId 当前下载的 model_id
     * @param downloadedBytes 已下载字节数（聚合所有文件）
     * @param totalBytes 全部文件总字节数
     */
    public fun onProgress(modelId: String, downloadedBytes: Long, totalBytes: Long) {}

    /**
     * 下载并校验全部完成。
     *
     * @param modelId 当前 model_id
     * @param modelDir 本地最终目录，可以直接传给 [AsrConfig.Builder]
     */
    public fun onCompleted(modelId: String, modelDir: java.io.File) {}

    /** 出错时调用。错误码见 [AsrErrorCode]。 */
    public fun onError(modelId: String, error: AsrError) {}
}

/** 可取消句柄。 */
public interface Cancellable {
    /** 取消（多次调用幂等）。 */
    public fun cancel()
    /** 是否已取消或已经结束。 */
    public val isDone: Boolean
}
