package com.amphion.asr.sample

import android.app.Application
import android.util.Log
import com.amphion.asr.AmphionLogLevel
import com.amphion.asr.AmphionOptions
import com.amphion.asr.AmphionRuntime
import com.amphion.asr.AsrConfig
import com.amphion.asr.AsrLanguage
import com.amphion.asr.sample.plate.PlateEnhancePrefs
import com.amphion.asr.sample.police_station.PoliceStationEnhancePrefs
import com.amphion.asr.sample.police_terms.PoliceTermsEnhancePrefs

/**
 * Sample 入口：SDK 全局 init + 多语言并行预加载。
 *
 * 业务方推荐的接入路径：
 * 1. [AmphionRuntime.init] 必须，建立全局上下文 / 日志级别
 * 2. [AmphionRuntime.preload] 强烈建议，在 splash / onboarding 阶段调一次，
 *    把全部要用到的语言一次性加载到 ASR 池里；之后 [AmphionRuntime.create] 命中池
 *    O(ms) 返回，用户切换语言不再有等待
 *
 * 这里 sample 选了「中英 + 粤英」两个语言；实际业务方按需调整 list。
 */
class AmphionApp : Application() {

    /** 暴露给 [MainActivity] 让 UI 在 splash 期间观察 preload 进度。 */
    @Volatile
    var preloadStage: String = "init"

    @Volatile
    var preloadPercent: Int = 0

    @Volatile
    var preloadDone: Boolean = false

    /**
     * preload 时是否注入了占位热词。值在 [onCreate] 内一次性决定：
     * 任一语言有 active 热词即 true。MainActivity 根据它决定运行时是否补占位词，
     * 保证池命中（详见 `MainActivity.HOTWORD_POOL_PLACEHOLDER` 注释）。
     */
    var hotwordsArmed: Boolean = false
        private set

    override fun onCreate() {
        super.onCreate()

        AmphionRuntime.init(
            this,
            AmphionOptions(logLevel = AmphionLogLevel.INFO),
        )

        // 演示授权状态查询：未武装构建（SDK 公钥为空）下为 DEV_UNLICENSED，不校验、不影响使用；
        // 武装交付构建放入 .lic 后会是 LICENSED（接入与排障见 docs/INTEGRATION.md §14）。
        val lic = AmphionRuntime.licenseStatus()
        Log.i(TAG, "license state=${lic.state} customer=${lic.customer} expiresAt=${lic.expiresAt}")

        // 决定本次启动池子要不要带占位热词。读 prefs 是 ~ms 级 I/O，可接受。
        // 一旦决定就不会在运行期改变；用户在 app 内首次开关热词的边界场景会让
        // 后续 create 不命中池一次（同步加载 ~1-3 秒），可接受。
        val platePrefs = PlateEnhancePrefs(this)
        val stationPrefs = PoliceStationEnhancePrefs(this)
        val termsPrefs = PoliceTermsEnhancePrefs(this)
        hotwordsArmed = HotwordsPrefs(this).anyLangHasActive() ||
            platePrefs.plateHotwordsEnabled ||
            stationPrefs.stationHotwordsEnabled ||
            termsPrefs.termsHotwordsEnabled

        // 整个 SDK 默认配置：punct + itn + vad + endpoint 全开
        val configBuilder = AsrConfig.Builder()
            .numThreads(2)
            .punctuation(true)
            .itn(true)
            .vad(true)
            .endpoint(true)
        if (hotwordsArmed) {
            val preloadWords = if (!HotwordsPrefs(this).anyLangHasActive()) {
                SceneAsrConfig.effectiveHotwords(
                    this,
                    AsrLanguage.ZH_EN,
                    platePrefs.plateHotwordsEnabled,
                    stationPrefs.stationHotwordsEnabled,
                    termsPrefs.termsHotwordsEnabled,
                ).filter { it != MainActivity.HOTWORD_POOL_PLACEHOLDER }
                    .ifEmpty { listOf(POOL_HOTWORDS_PLACEHOLDER) }
            } else {
                listOf(POOL_HOTWORDS_PLACEHOLDER)
            }
            configBuilder.hotwords(preloadWords, MainActivity.HOTWORDS_SCORE)
        }
        val config = configBuilder.build()

        // preload 本身是非阻塞的（内部派发到自己的工作线程），onProgress 是判定完成的唯一来源。
        // 这里在所有 stage 都到 100 后才把 preloadDone = true。
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
                Log.i(TAG, "preload stage=$stage percent=$percent% hotwordsArmed=$hotwordsArmed")
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
        private const val TAG = "AmphionApp"

        /** 与 [MainActivity.HOTWORD_POOL_PLACEHOLDER] 同步；池占位词，避免业务相关性。 */
        private const val POOL_HOTWORDS_PLACEHOLDER: String = "__placeholder__"
    }
}
