package com.amphion.asr.sample

import android.app.Application
import android.util.Log
import com.amphion.asr.AmphionLogLevel
import com.amphion.asr.AmphionOptions
import com.amphion.asr.AmphionRuntime
import com.amphion.asr.AsrConfig
import com.amphion.asr.AsrLanguage

/**
 * 评测版（:sample-eval）的 Application 入口：
 *
 * 0.2.0 起所有模型已经打进 SDK AAR；不再需要 ModelImporter / WeitnAssetInstaller /
 * PunctModelInstaller 把外部 push 的资产搬到 internal storage。
 *
 * 这里做两件事：
 * 1. [AmphionRuntime.init]：必须；建立 SDK 全局上下文 / 日志级别
 * 2. 异步 [AmphionRuntime.preload]：把中英 + 粤英两个语言一次性加载进 ASR 池，
 *    后续 RecordSentenceActivity 调 [AmphionRuntime.create] 命中池 0 延迟
 *
 * Activity 在录音前 poll [preloadDone]，避免 splash 期开始录音时引擎没就绪。
 */
class AmphionApp : Application() {

    @Volatile
    var preloadStage: String = "init"

    @Volatile
    var preloadPercent: Int = 0

    @Volatile
    var preloadDone: Boolean = false

    override fun onCreate() {
        super.onCreate()

        AmphionRuntime.init(
            this,
            AmphionOptions(logLevel = AmphionLogLevel.INFO),
        )

        val config = AsrConfig.Builder()
            .numThreads(2)
            .punctuation(true)
            .itn(true)
            .vad(true)
            .endpoint(true)
            .build()

        // preload 内部走专用线程；onProgress 是判定每个 stage 完成的唯一来源
        val finishedStages = mutableSetOf<String>()
        val expectedStages = setOf("asr-ZH_EN", "asr-YUE_EN")
        try {
            AmphionRuntime.preload(
                this,
                languages = listOf(AsrLanguage.ZH_EN, AsrLanguage.YUE_EN),
                config = config,
            ) { stage, percent ->
                preloadStage = stage
                preloadPercent = percent
                Log.i(TAG, "preload stage=$stage percent=$percent%")
                if (percent >= 100) {
                    synchronized(finishedStages) {
                        finishedStages.add(stage)
                        if (finishedStages.containsAll(expectedStages)) {
                            preloadDone = true
                            Log.i(TAG, "preload pipeline finished, ASR pool ready")
                        }
                    }
                }
            }
        } catch (t: Throwable) {
            Log.w(TAG, "preload kickoff failed: ${t.message}")
        }
    }

    companion object {
        private const val TAG = "AmphionApp(eval)"
    }
}
