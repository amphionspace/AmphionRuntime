package com.amphion.asr.internal

import android.content.Context
import com.amphion.asr.AsrConfig
import com.amphion.asr.AsrErrorCode
import com.amphion.asr.AsrLanguage
import com.amphion.asr.BuildConfig
import com.amphion.asr.Cancellable
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 把 APK 内置 assets 解包到 [Context.getFilesDir]/[AssetRegistry.INSTALL_ROOT]/。
 *
 * 工作流程：
 * 1. 计算需要哪些 bundle（[ensureInstalled]: 当前 language + 业务开关；[preInstallAll]: 全部）
 * 2. 检查 install.flag 是否与当前 SDK_VERSION 匹配；不匹配则清空 install root 重新解包
 * 3. 流式从 AssetManager 拷贝到 internal 路径，每 64KB 累加进度
 * 4. 全部成功后写 install.flag = SDK_VERSION
 *
 * # 设计考虑
 *
 * - 不做单文件 sha256：APK 内的资产是只读的，只要 SDK_VERSION 一致就保证内容一致；
 *   sha256 只作为 [PackSdkAssets] 脚本生成 manifest.json 时的一次性校验，运行期不再校验
 * - 解包失败时不留半成品：任何一步出错都把 install root 整个清空，避免下次启动用到坏文件
 * - 以 SDK_VERSION 为单位整体 invalidate：任何一份模型变了都强制重新解包；
 *   省得为了少量改动写复杂 diff 逻辑
 */
internal object AssetInstaller {

    /**
     * 同步把当前 [language] + [config] 真正需要的全部 bundle 解包好，返回内部路径布局。
     * 已经安装且 SDK_VERSION 一致时本调用是 O(1) 的（[InstallStats.installMs] = 0）。
     */
    @Throws(IllegalStateException::class)
    fun ensureInstalled(
        ctx: Context,
        language: AsrLanguage,
        config: AsrConfig,
    ): InstalledLayout {
        val bundles = mutableListOf(AssetRegistry.asrBundle(language))
        if (config.punctuation) bundles += AssetRegistry.punctuationBundle()
        if (config.itn && AssetRegistry.itnEnabledFor(language)) bundles += AssetRegistry.itnBundle()
        if (config.vad) bundles += AssetRegistry.vadBundle()

        val stats = installAll(ctx, bundles, onProgress = null, cancelFlag = AtomicBoolean(false))
        return InstalledLayout.of(ctx, language, config, stats)
    }

    /**
     * 异步解包 [AssetRegistry.allBundles] 全部资产；返回的 [Cancellable] 可在中途取消。
     *
     * 进度回调单调递增 0..100，最后一个值一定是 100；调用线程 = 调用 [Cancellable] 的线程。
     * 解包过程在 SDK 自己的后台线程执行；onProgress 在该线程触发。
     */
    fun preInstallAll(ctx: Context, onProgress: ((Int) -> Unit)?): Cancellable {
        val cancelFlag = AtomicBoolean(false)
        val handle = CancellableImpl(cancelFlag)
        val thread = Thread({
            try {
                installAll(ctx, AssetRegistry.allBundles(), onProgress, cancelFlag)
            } catch (t: Throwable) {
                Logger.e("preInstallAll failed: ${t.message}", t)
            } finally {
                handle.markDone()
            }
        }, "amphion-preinstall").apply { isDaemon = true }
        thread.start()
        return handle
    }

    /**
     * 不带进度回调的同步全量预安装入口（生产线在 splash / first-launch 主线程外调用）。
     */
    @Throws(IllegalStateException::class)
    fun preInstallAllSync(ctx: Context, onProgress: ((Int) -> Unit)? = null): InstallStats {
        return installAll(ctx, AssetRegistry.allBundles(), onProgress, AtomicBoolean(false))
    }

    /** 描述一次 installAll 的副作用：耗时 + 拷贝字节数（已经 short-circuit 时全 0）。 */
    internal data class InstallStats(
        val installMs: Long,
        val installBytes: Long,
    ) {
        internal companion object {
            val ZERO = InstallStats(installMs = 0L, installBytes = 0L)
        }
    }

    /** 已安装资产的真实 [File] 路径，按业务关心的字段聚合，传给 [EngineImpl]。 */
    internal class InstalledLayout(
        val asrEncoder: File,
        val asrDecoder: File,
        val asrJoiner: File,
        val asrTokens: File,
        /**
         * 两列文本 BPE 词表（每行 `<piece> <score>`），sherpa-onnx 自带的 ssentencepiece
         * 库专用格式；不是 Google SentencePiece protobuf `.model`。
         *
         * byte-level BPE 模型（modeling_unit=bbpe）启用 hotwords 时必备：bpe_encoder_
         * 构造时拿这个路径去 darts trie build，文件不存在 / 格式不对都会 segfault。
         * 如果手头只有 `.model`，用 `asr/tools/09_export_bbpe_vocab.py` 转换。
         */
        val asrBpeVocab: File,
        val punctuationModel: File?,
        val itnTaggerFst: File?,
        val itnVerbalizerFst: File?,
        val vadModel: File?,
        val installStats: InstallStats,
    ) {
        companion object {
            fun of(
                ctx: Context,
                language: AsrLanguage,
                config: AsrConfig,
                installStats: InstallStats = InstallStats.ZERO,
            ): InstalledLayout {
                val root = installRoot(ctx)
                val asrDir = File(root, AssetRegistry.asrBundle(language).installSubDir)
                val punctDir = File(root, AssetRegistry.punctuationBundle().installSubDir)
                val itnDir = File(root, AssetRegistry.itnBundle().installSubDir)
                val vadDir = File(root, AssetRegistry.vadBundle().installSubDir)
                val itnUsed = config.itn && AssetRegistry.itnEnabledFor(language)
                return InstalledLayout(
                    asrEncoder = File(asrDir, "encoder.int8.ort"),
                    asrDecoder = File(asrDir, "decoder.ort"),
                    asrJoiner = File(asrDir, "joiner.int8.ort"),
                    asrTokens = File(asrDir, "tokens.txt"),
                    asrBpeVocab = File(asrDir, "bbpe.vocab"),
                    punctuationModel = if (config.punctuation) File(punctDir, "model.int8.ort") else null,
                    itnTaggerFst = if (itnUsed) File(itnDir, "zh_itn_tagger.fst") else null,
                    itnVerbalizerFst = if (itnUsed) File(itnDir, "zh_itn_verbalizer.fst") else null,
                    vadModel = if (config.vad) File(vadDir, "silero_vad.onnx") else null,
                    installStats = installStats,
                )
            }
        }
    }

    // -------- 内部实现 --------

    private fun installRoot(ctx: Context): File =
        File(ctx.filesDir, AssetRegistry.INSTALL_ROOT)

    @Throws(IllegalStateException::class)
    @Synchronized
    private fun installAll(
        ctx: Context,
        bundles: List<AssetRegistry.Bundle>,
        onProgress: ((Int) -> Unit)?,
        cancelFlag: AtomicBoolean,
    ): InstallStats {
        val installStartElapsed = android.os.SystemClock.elapsedRealtime()
        val root = installRoot(ctx)
        val flagFile = File(root, AssetRegistry.INSTALL_FLAG)

        // 已安装且 SDK_VERSION 匹配：检查目标文件是否齐全；齐全直接 short-circuit
        if (flagFile.isFile && flagFile.readTextSafely() == BuildConfig.SDK_VERSION) {
            val allReady = bundles.all { bundle ->
                val dir = File(root, bundle.installSubDir)
                bundle.files.all { File(dir, it).isFile }
            }
            if (allReady) {
                onProgress?.invoke(100)
                Logger.i("AssetInstaller: bundles already installed for SDK ${BuildConfig.SDK_VERSION}")
                return InstallStats.ZERO
            }
            Logger.w("AssetInstaller: install.flag matches but files missing, re-installing")
        }

        // 任意不匹配 / 缺文件 -> 清空 root 重新走流程
        if (root.exists() && !root.deleteRecursively()) {
            throw illegalState(
                AsrErrorCode.STORAGE_INSUFFICIENT,
                "cannot clean install root: ${root.absolutePath}",
            )
        }
        if (!root.mkdirs()) {
            throw illegalState(
                AsrErrorCode.STORAGE_INSUFFICIENT,
                "cannot create install root: ${root.absolutePath}",
            )
        }

        // 估算总字节数（用 AssetManager 的 length()），用于做进度
        val assetManager = ctx.assets
        val totalBytes = bundles.sumOf { bundle ->
            bundle.files.sumOf { name ->
                val assetPath = "${AssetRegistry.ASSET_ROOT}/${bundle.assetSubPath}/$name"
                openAssetLengthOrThrow(ctx, assetPath)
            }
        }
        var copied = 0L
        // 进度去重：同一整数百分比只回调一次，避免业务方在 64KB 粒度上被刷屏。
        var lastReportedPercent = -1

        for (bundle in bundles) {
            if (cancelFlag.get()) {
                root.deleteRecursively()
                throw illegalState(
                    AsrErrorCode.ASSET_INSTALL_FAILED,
                    "preInstall cancelled",
                )
            }
            val dstDir = File(root, bundle.installSubDir)
            if (!dstDir.mkdirs() && !dstDir.isDirectory) {
                throw illegalState(
                    AsrErrorCode.STORAGE_INSUFFICIENT,
                    "cannot create ${dstDir.absolutePath}",
                )
            }
            for (name in bundle.files) {
                if (cancelFlag.get()) {
                    root.deleteRecursively()
                    throw illegalState(
                        AsrErrorCode.ASSET_INSTALL_FAILED,
                        "preInstall cancelled",
                    )
                }
                val assetPath = "${AssetRegistry.ASSET_ROOT}/${bundle.assetSubPath}/$name"
                val dstFile = File(dstDir, name)
                try {
                    assetManager.open(assetPath).use { input ->
                        FileOutputStream(dstFile).use { output ->
                            val buf = ByteArray(64 * 1024)
                            while (true) {
                                if (cancelFlag.get()) {
                                    throw IOException("cancelled")
                                }
                                val n = input.read(buf)
                                if (n <= 0) break
                                output.write(buf, 0, n)
                                copied += n.toLong()
                                if (onProgress != null && totalBytes > 0) {
                                    val p = ((copied * 100L) / totalBytes).toInt().coerceIn(0, 99)
                                    if (p > lastReportedPercent) {
                                        lastReportedPercent = p
                                        onProgress(p)
                                    }
                                }
                            }
                            output.fd.sync()
                        }
                    }
                } catch (t: Throwable) {
                    root.deleteRecursively()
                    throw illegalState(
                        AsrErrorCode.ASSET_INSTALL_FAILED,
                        "copy asset failed: $assetPath -> ${dstFile.absolutePath}: ${t.message}",
                        t,
                    )
                }
            }
        }

        try {
            flagFile.writeText(BuildConfig.SDK_VERSION)
        } catch (t: Throwable) {
            root.deleteRecursively()
            throw illegalState(
                AsrErrorCode.STORAGE_INSUFFICIENT,
                "cannot write install.flag: ${t.message}",
                t,
            )
        }
        onProgress?.invoke(100)
        val installMs = android.os.SystemClock.elapsedRealtime() - installStartElapsed
        Logger.i(
            "AssetInstaller: ${bundles.size} bundle(s) installed for SDK ${BuildConfig.SDK_VERSION}, " +
                "totalBytes=$copied installMs=$installMs at ${root.absolutePath}",
        )
        return InstallStats(installMs = installMs, installBytes = copied)
    }

    private fun openAssetLengthOrThrow(ctx: Context, path: String): Long {
        return try {
            ctx.assets.openFd(path).use { afd -> afd.length }
        } catch (_: IOException) {
            // .ort / .onnx / .fst 是 noCompress 的，理论上必然能 openFd；此处兜底走 InputStream
            ctx.assets.open(path).use { input ->
                var total = 0L
                val buf = ByteArray(64 * 1024)
                while (true) {
                    val n = input.read(buf)
                    if (n <= 0) break
                    total += n.toLong()
                }
                total
            }
        }
    }

    private fun File.readTextSafely(): String? = try { readText().trim() } catch (_: Throwable) { null }

    private fun illegalState(code: Int, message: String, cause: Throwable? = null): IllegalStateException {
        val tagged = "code=$code: $message"
        return if (cause != null) IllegalStateException(tagged, cause) else IllegalStateException(tagged)
    }

    private class CancellableImpl(private val flag: AtomicBoolean) : Cancellable {
        @Volatile
        private var done: Boolean = false

        override fun cancel() {
            flag.set(true)
        }

        override val isDone: Boolean
            get() = done

        fun markDone() {
            done = true
        }
    }
}
