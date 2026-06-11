package com.amphion.asr.sample

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Menu
import android.view.MenuItem
import android.widget.Button
import android.widget.ProgressBar
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.Toolbar
import androidx.core.content.ContextCompat
import com.amphion.asr.AmphionMetrics
import com.amphion.asr.AmphionMetricsKind
import com.amphion.asr.AmphionRuntime
import com.amphion.asr.AsrCallback
import com.amphion.asr.AsrConfig
import com.amphion.asr.AsrEngine
import com.amphion.asr.AsrError
import com.amphion.asr.AsrLanguage
import com.amphion.asr.AsrSession
import android.graphics.Color
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.text.style.StrikethroughSpan
import androidx.appcompat.widget.SwitchCompat
import com.amphion.asr.AsrResult
import com.amphion.asr.TargetSpeakerConfig
import com.amphion.asr.sample.plate.PlateBatchEvalActivity
import com.amphion.asr.sample.plate.PlateEvalRecorder
import com.amphion.asr.sample.police_station.PoliceStationBatchEvalActivity
import com.amphion.asr.sample.police_station.PoliceStationEvalRecorder
import com.amphion.asr.sample.police_terms.PoliceTermsBatchEvalActivity
import com.amphion.asr.sample.police_terms.PoliceTermsEvalRecorder
import com.amphion.police.PoliceEnhancePipeline
import com.amphion.police.plate.PlateEnhancePrefs
import com.amphion.police.plate.PlateHotwords
import com.amphion.police.plate.PlateNormalizer
import com.amphion.police.station.PoliceStationEnhancePrefs
import com.amphion.police.station.PoliceStationHotwords
import com.amphion.police.station.PoliceStationNormalizer
import com.amphion.police.terms.PoliceTermsEnhancePrefs
import com.amphion.police.terms.PoliceTermsHotwords
import com.amphion.police.terms.PoliceTermsNormalizer
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger
import kotlin.math.abs
import kotlin.math.max

/**
 * 单 Activity Sample：演示 SDK 的最小接入。
 *
 * UI 元素：
 * - 顶部 RadioGroup：在 中英 / 粤英 之间切换；切换走 [AmphionRuntime] 的 ASR 池，0 延迟
 * - 中部状态/波形/部分结果/最终结果四个区域
 * - Final 卡底部一行 metrics：E2E / 首字 / RTF / RSS（来自 SDK 的 onMetrics 回调）
 * - 底部按钮：录音/停止
 */
class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "AmphionSample"
        private const val WAVEFORM_FRAMES_PER_BATCH = 4

        /**
         * 热词加权分数。
         *
         * 1.5 是 sherpa-onnx 英文 BPE 默认值；中文 byte-level BPE 路径长（每个汉字 3
         * byte → 3 token + ▁ 前缀，3 字词约 10 token），单步累加完同音字
         * 一般也只多 ~30 分。AM 的隐式 LM 对训练语料里高频共现的词（如「明洞」、
         * 「北京」）已经内化强 prior；浅融合要击败这个 prior，λ 必须大到能补偿
         * prior gap，**否则属于浅融合的结构性短板**（不是参数没调对）。
         *
         * 当前置 5.0：SDK 允许的上限（[com.amphion.asr.AsrConfig.Builder.hotwords] 写死
         * [0.0, 5.0]），用来测试「在 boost 能力的天花板上，常见词 prior 是否还能撬动」。
         * 如果 5.0 仍撬不动「余明洞」→「余铭栋」这类对抗，应转向后处理同音字典替换
         * （deterministic mapping，本就不该用概率模型解决）。
         *
         * 被 [AmphionApp] 在 preload 时同样使用，保证 pool 命中。
         */
        const val HOTWORDS_SCORE = 5.0f

        /**
         * 占位热词：仅当 [AmphionApp.hotwordsArmed] 为 true 但当前语言无 active 热词时使用，
         * 让 cfg.hotwords 始终非空，与池配置（preload 时也注入了占位词）保持一致，命中池。
         * 选 ASCII 双下划线包裹的字符串：tokenize 后不会出现在自然语音的 token 序列里，
         * 不会影响识别结果。
         */
        const val HOTWORD_POOL_PLACEHOLDER = "__placeholder__"

        /** 声纹模型文件名；放在 app external files dir，由 adb push 进去。 */
        const val SPEAKER_MODEL_FILENAME = "eres2net.onnx"
    }

    private lateinit var btnTalk: Button
    private lateinit var tvPartial: TextView
    private lateinit var tvFinal: TextView
    private lateinit var tvStatus: TextView
    private lateinit var tvLoadingHint: TextView
    private lateinit var tvMetrics: TextView
    private lateinit var progress: ProgressBar
    private lateinit var rgLang: RadioGroup
    private lateinit var rbZhEn: RadioButton
    private lateinit var rbYueEn: RadioButton
    private lateinit var waveform: WaveformView

    // -------- 云端（WebSocket /clean-stream）相关视图 --------
    private lateinit var swCloud: SwitchCompat
    private lateinit var tvCloudState: TextView
    private lateinit var cardCloud: android.view.View
    private lateinit var colCloud: android.view.View
    private lateinit var svCloud: android.widget.ScrollView
    private lateinit var tvCloudFinal: TextView
    private lateinit var tvCloudStatus: TextView

    private lateinit var cardPlateEnhance: android.view.View
    private lateinit var swPlateHotwords: SwitchCompat
    private lateinit var swPlateNormalize: SwitchCompat
    private lateinit var tvPlatePipeline: TextView
    private lateinit var plateEnhancePrefs: PlateEnhancePrefs
    private lateinit var cardStationEnhance: android.view.View
    private lateinit var swStationHotwords: SwitchCompat
    private lateinit var swStationNormalize: SwitchCompat
    private lateinit var tvStationPipeline: TextView
    private lateinit var stationEnhancePrefs: PoliceStationEnhancePrefs
    private lateinit var cardTermsEnhance: android.view.View
    private lateinit var swTermsHotwords: SwitchCompat
    private lateinit var swTermsNormalize: SwitchCompat
    private lateinit var tvTermsPipeline: TextView
    private lateinit var termsEnhancePrefs: PoliceTermsEnhancePrefs

    private val mainHandler: Handler by lazy { Handler(Looper.getMainLooper()) }

    /**
     * 串行 ASR engine 加载/关闭 executor。
     * 池命中时只是 ~100ms 的 VAD 加载，但依旧放在后台避免主线程偶发抖动。
     */
    private val asrLoadExec: ExecutorService = Executors.newSingleThreadExecutor { r ->
        Thread(r, "amphion-asr-load").apply { isDaemon = true }
    }

    /**
     * 每次「切换/加载 engine」递增；后台加载完成后用它判断结果是否仍然有效。
     */
    private val asrLoadGeneration = AtomicInteger(0)

    private var engine: AsrEngine? = null
    private var session: AsrSession? = null
    private var recorder: AudioRecorder? = null
    private var currentLang: AsrLanguage = AsrLanguage.ZH_EN

    /**
     * 当前 engine 实际生效的热词列表（**不含占位词**，与用户在热词页看到的一致）。
     * 用来判断 [onHotwordsChanged] 时该走「重建 engine」还是「热更新 session」。
     */
    private var currentHotwordsApplied: List<String> = emptyList()

    @Volatile
    private var listening: Boolean = false

    // -------- 目标说话人状态 --------
    private val speakerStore: SpeakerProfileStore by lazy { SpeakerProfileStore(applicationContext) }

    /**
     * 当前 engine 的 TargetSpeakerConfig 实际生效的判定阈值。声纹页改阈值后，onResume 比对此值
     * （NaN=尚未建过带阈值的 engine）决定是否静默重建 engine 使新阈值生效。
     */
    private var currentThresholdApplied: Float = Float.NaN

    @Volatile
    private var targetEmbedding: FloatArray? = null
    private val finalBuilder = SpannableStringBuilder()

    // -------- 云端状态 --------
    private val cloudPrefs: CloudAsrPrefs by lazy { CloudAsrPrefs(applicationContext) }

    @Volatile
    private var cloudClient: CloudAsrClient? = null

    private val cloudGeneration = AtomicInteger(0)
    private val cloudFinalBuilder = StringBuilder()
    private var cloudCurrentPartial: String = ""

    private lateinit var plateNormalizer: PlateNormalizer
    private lateinit var plateEvalRecorder: PlateEvalRecorder
    private lateinit var stationNormalizer: PoliceStationNormalizer
    private lateinit var stationEvalRecorder: PoliceStationEvalRecorder
    private lateinit var termsNormalizer: PoliceTermsNormalizer
    private lateinit var termsEvalRecorder: PoliceTermsEvalRecorder

    private val recordPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) {
            loadEngineForLang(currentLang)
        } else {
            toast(getString(R.string.status_no_permission))
        }
    }

    /** 跳到 [HotwordsActivity] 并接收"是否变更"的回执；变更时走 [onHotwordsChanged]。 */
    private val hotwordsLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        val changed = result.data
            ?.getBooleanExtra(HotwordsActivity.EXTRA_HOTWORDS_CHANGED, false)
            ?: false
        if (changed) onHotwordsChanged()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        setSupportActionBar(findViewById<Toolbar>(R.id.toolbar))
        supportActionBar?.setDisplayShowTitleEnabled(false)

        btnTalk = findViewById(R.id.btn_talk)
        tvPartial = findViewById(R.id.tv_partial)
        tvFinal = findViewById(R.id.tv_final)
        tvStatus = findViewById(R.id.tv_status)
        tvLoadingHint = findViewById(R.id.tv_loading_hint)
        tvMetrics = findViewById(R.id.tv_metrics)
        progress = findViewById(R.id.progress)
        rgLang = findViewById(R.id.rg_lang)
        rbZhEn = findViewById(R.id.rb_zh_en)
        rbYueEn = findViewById(R.id.rb_yue_en)
        waveform = findViewById(R.id.waveform)

        swCloud = findViewById(R.id.sw_cloud)
        tvCloudState = findViewById(R.id.tv_cloud_state)
        cardCloud = findViewById(R.id.card_cloud)
        colCloud = findViewById(R.id.col_cloud)
        svCloud = findViewById(R.id.sv_cloud)
        tvCloudFinal = findViewById(R.id.tv_cloud_final)
        tvCloudStatus = findViewById(R.id.tv_cloud_status)
        cardCloud.setOnClickListener { swCloud.toggle() }

        plateEnhancePrefs = PlateEnhancePrefs(this)
        stationEnhancePrefs = PoliceStationEnhancePrefs(this)
        termsEnhancePrefs = PoliceTermsEnhancePrefs(this)
        plateNormalizer = PlateNormalizer.create(
            this,
            useFst = plateEnhancePrefs.plateFstEnabled,
        )
        stationNormalizer = PoliceStationNormalizer.create(
            this,
            useFst = stationEnhancePrefs.stationFstEnabled,
        )
        termsNormalizer = PoliceTermsNormalizer.create(
            this,
            useFst = termsEnhancePrefs.termsFstEnabled,
        )
        plateEvalRecorder = PlateEvalRecorder(this)
        stationEvalRecorder = PoliceStationEvalRecorder(this)
        termsEvalRecorder = PoliceTermsEvalRecorder(this)
        Log.i(TAG, "plate-eval TSV: ${plateEvalRecorder.filePath()}")
        Log.i(TAG, PlateEvalRecorder.pullHint())
        Log.i(TAG, "police-station-eval TSV: ${stationEvalRecorder.filePath()}")
        Log.i(TAG, PoliceStationEvalRecorder.pullHint())
        Log.i(TAG, "police-terms-eval TSV: ${termsEvalRecorder.filePath()}")
        Log.i(TAG, PoliceTermsEvalRecorder.pullHint())

        cardPlateEnhance = findViewById(R.id.card_plate_enhance)
        swPlateHotwords = findViewById(R.id.sw_plate_hotwords)
        swPlateNormalize = findViewById(R.id.sw_plate_normalize)
        tvPlatePipeline = findViewById(R.id.tv_plate_pipeline)
        swPlateHotwords.setOnCheckedChangeListener { _, on ->
            onPlateHotwordsToggle(on)
        }
        swPlateNormalize.setOnCheckedChangeListener { _, on ->
            plateEnhancePrefs.plateNormalizeEnabled = on
            refreshPlateEnhanceCard()
        }
        refreshPlateEnhanceCard()

        cardStationEnhance = findViewById(R.id.card_station_enhance)
        swStationHotwords = findViewById(R.id.sw_station_hotwords)
        swStationNormalize = findViewById(R.id.sw_station_normalize)
        tvStationPipeline = findViewById(R.id.tv_station_pipeline)
        swStationHotwords.setOnCheckedChangeListener { _, on ->
            onStationHotwordsToggle(on)
        }
        swStationNormalize.setOnCheckedChangeListener { _, on ->
            stationEnhancePrefs.stationNormalizeEnabled = on
            refreshStationEnhanceCard()
        }
        refreshStationEnhanceCard()

        cardTermsEnhance = findViewById(R.id.card_terms_enhance)
        swTermsHotwords = findViewById(R.id.sw_terms_hotwords)
        swTermsNormalize = findViewById(R.id.sw_terms_normalize)
        tvTermsPipeline = findViewById(R.id.tv_terms_pipeline)
        swTermsHotwords.setOnCheckedChangeListener { _, on ->
            onTermsHotwordsToggle(on)
        }
        swTermsNormalize.setOnCheckedChangeListener { _, on ->
            termsEnhancePrefs.termsNormalizeEnabled = on
            refreshTermsEnhanceCard()
        }
        refreshTermsEnhanceCard()

        btnTalk.isEnabled = false
        setTalkButtonRecording(false)
        btnTalk.setOnClickListener { onTalkButtonClick() }

        rgLang.check(R.id.rb_zh_en)
        rgLang.setOnCheckedChangeListener { _, checkedId ->
            val newLang = when (checkedId) {
                R.id.rb_zh_en -> AsrLanguage.ZH_EN
                R.id.rb_yue_en -> AsrLanguage.YUE_EN
                else -> return@setOnCheckedChangeListener
            }
            if (newLang == currentLang) return@setOnCheckedChangeListener
            currentLang = newLang
            stopListeningForSwitch()
            clearTexts()
            refreshPlateEnhanceCard()
            refreshStationEnhanceCard()
            refreshTermsEnhanceCard()
            loadEngineForLang(newLang)
        }

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            recordPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        } else {
            loadEngineForLang(currentLang)
        }
    }

    override fun onResume() {
        super.onResume()
        reloadTargetSpeaker()
        refreshCloudCard()
        refreshPlateEnhanceCard()
        refreshStationEnhanceCard()
        refreshTermsEnhanceCard()
        maybeReloadThreshold()
    }

    override fun onDestroy() {
        super.onDestroy()
        stopListening()
        cloudGeneration.incrementAndGet()
        cloudClient?.close()
        cloudClient = null
        asrLoadGeneration.incrementAndGet()
        asrLoadExec.shutdownNow()
        engine?.close()
        engine = null
        try {
            stationNormalizer.close()
        } catch (_: Throwable) {}
        try {
            plateNormalizer.close()
        } catch (_: Throwable) {}
        try {
            termsNormalizer.close()
        } catch (_: Throwable) {}
        // 不调 AmphionRuntime.release()：保留池给下次 Activity 用，避免重复加载
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.menu_main, menu)
        return true
    }

    override fun onPrepareOptionsMenu(menu: Menu): Boolean {
        menu.findItem(R.id.action_hotwords)?.isEnabled = !listening
        menu.findItem(R.id.action_speaker)?.isEnabled = !listening
        return super.onPrepareOptionsMenu(menu)
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        return when (item.itemId) {
            R.id.action_speaker -> {
                startActivity(Intent(this, SpeakerEnrollActivity::class.java))
                true
            }
            R.id.action_hotwords -> {
                hotwordsLauncher.launch(Intent(this, HotwordsActivity::class.java))
                true
            }
            R.id.action_batch_eval -> {
                startActivity(Intent(this, PlateBatchEvalActivity::class.java))
                true
            }
            R.id.action_station_batch_eval -> {
                startActivity(Intent(this, PoliceStationBatchEvalActivity::class.java))
                true
            }
            R.id.action_terms_batch_eval -> {
                startActivity(Intent(this, PoliceTermsBatchEvalActivity::class.java))
                true
            }
            else -> super.onOptionsItemSelected(item)
        }
    }

    // ----------- 热词变更回路 -----------

    /**
     * 用户在 [HotwordsActivity] 改完返回。
     *
     * 三类情况：
     * 1. 当前语言的 activeWords 没变 → 静默无操作
     * 2. 仅"内容"变了（emptyness 不变）→ 用 [AsrSession.updateHotwords] 热更新（不在录音中
     *    时无 session，下次 startListening 时 newSession 会走 buildOnlineRecognizerConfig
     *    自动拿到新热词，所以也无需做事）
     * 3. emptyness 变了（true→false 或 false→true）→ 走 recognizer 池的 hasHotwords 维度，
     *    与 cfg 不兼容；必须重建 engine。占位词机制下大部分时候不会落入此分支
     */
    private fun onHotwordsChanged() {
        val newActive = HotwordsPrefs(applicationContext).activeWords(currentLang)
        val old = currentHotwordsApplied
        if (newActive == old) return

        val oldEmpty = old.isEmpty()
        val newEmpty = newActive.isEmpty()
        // 池兼容性维度（占位词补齐前）：池 armed 时 emptyness 始终一致，多数情况下进 else
        val poolDimensionFlipped = oldEmpty != newEmpty &&
            !(application as AmphionApp).hotwordsArmed
        if (poolDimensionFlipped) {
            Log.i(TAG, "hotwords pool dimension flipped, rebuild engine")
            loadEngineForLang(currentLang)
            return
        }

        currentHotwordsApplied = newActive
        val s = session
        if (s != null) {
            try {
                val merged = SceneAsrConfig.effectiveHotwords(
                    applicationContext,
                    currentLang,
                    plateEnhancePrefs.plateHotwordsEnabled,
                    stationEnhancePrefs.stationHotwordsEnabled,
                    termsEnhancePrefs.termsHotwordsEnabled,
                ).filter { it != HOTWORD_POOL_PLACEHOLDER }
                s.updateHotwords(merged, HOTWORDS_SCORE)
            } catch (t: Throwable) {
                Log.w(TAG, "updateHotwords failed: ${t.message}")
            }
        } else {
            // 没在录音时，下次 startListening 会用现有 engine 的 newSession——但 engine 的
            // cfg.hotwords 是 loadEngineForLang 当时的值，session 的 currentHotwords 也来自那
            // 一份。这里同步重建 engine 一次（命中池仍 O(ms)），让 cfg 与 prefs 对齐。
            loadEngineForLang(currentLang)
        }
    }

    // ----------- 云端能力卡 -----------

    private fun refreshCloudCard() {
        val enabled = cloudPrefs.isEnabled()
        swCloud.setOnCheckedChangeListener(null)
        swCloud.isChecked = enabled
        swCloud.setOnCheckedChangeListener { _, isChecked -> onCloudToggle(isChecked) }
        tvCloudState.text = if (enabled) {
            getString(R.string.cap_cloud_on)
        } else {
            getString(R.string.cap_cloud_off)
        }
        colCloud.visibility = if (enabled) android.view.View.VISIBLE else android.view.View.GONE
        if (!enabled) {
            cloudFinalBuilder.setLength(0)
            cloudCurrentPartial = ""
            renderCloud()
            setCloudStatus(getString(R.string.cloud_status_idle))
        }
    }

    private fun onCloudToggle(enabled: Boolean) {
        cloudPrefs.setEnabled(enabled)
        refreshCloudCard()
        if (!enabled) {
            cloudGeneration.incrementAndGet()
            cloudClient?.close()
            cloudClient = null
        } else if (listening) {
            startCloudForCurrentSession()
        }
    }

    private fun startCloudForCurrentSession() {
        val gen = cloudGeneration.get()
        cloudClient?.close()
        cloudFinalBuilder.setLength(0)
        cloudCurrentPartial = ""
        renderCloud()

        val client = CloudAsrClient(
            url = CloudAsrPrefs.WS_URL,
            apiKey = CloudAsrPrefs.API_KEY,
            language = cloudLangCode(currentLang),
            hotwords = currentHotwordsApplied,
            listener = object : CloudAsrClient.Listener {
                override fun onStatus(status: CloudAsrClient.Status, detail: String?) {
                    runOnUiThread {
                        if (gen != cloudGeneration.get()) return@runOnUiThread
                        setCloudStatus(cloudStatusText(status, detail))
                    }
                }

                override fun onPartial(text: String) {
                    runOnUiThread {
                        if (gen != cloudGeneration.get()) return@runOnUiThread
                        cloudCurrentPartial = text
                        renderCloud()
                    }
                }

                override fun onFinal(text: String, durationSec: Double?) {
                    runOnUiThread {
                        if (gen != cloudGeneration.get()) return@runOnUiThread
                        cloudCurrentPartial = ""
                        appendCloudFinal(text)
                        if (durationSec != null) {
                            setCloudStatus(getString(R.string.cloud_status_duration, durationSec))
                        }
                    }
                }

                override fun onError(message: String) {
                    runOnUiThread {
                        if (gen != cloudGeneration.get()) return@runOnUiThread
                        setCloudStatus(getString(R.string.cloud_status_error, message))
                    }
                }
            },
        )
        cloudClient = client
        client.start()
    }

    private fun cloudStatusText(status: CloudAsrClient.Status, detail: String?): String = when (status) {
        CloudAsrClient.Status.CONNECTING -> getString(R.string.cloud_status_connecting)
        CloudAsrClient.Status.READY -> getString(R.string.cloud_status_ready)
        CloudAsrClient.Status.STOPPING -> getString(R.string.cloud_status_stopping)
        CloudAsrClient.Status.CLOSED -> getString(R.string.cloud_status_closed)
    }.let { if (detail.isNullOrBlank()) it else "$it · $detail" }

    private fun cloudLangCode(lang: AsrLanguage): String = when (lang) {
        AsrLanguage.ZH_EN -> "zh"
        AsrLanguage.YUE_EN -> "yue"
    }

    private fun appendCloudFinal(text: String) {
        if (text.isNotEmpty()) {
            if (cloudFinalBuilder.isNotEmpty()) cloudFinalBuilder.append("\n")
            cloudFinalBuilder.append(text)
        }
        renderCloud()
    }

    private fun renderCloud() {
        val sb = StringBuilder(cloudFinalBuilder)
        if (cloudCurrentPartial.isNotEmpty()) {
            if (sb.isNotEmpty()) sb.append("\n")
            sb.append(cloudCurrentPartial)
        }
        tvCloudFinal.text = sb.toString()
        svCloud.post { svCloud.fullScroll(android.view.View.FOCUS_DOWN) }
    }

    private fun setCloudStatus(s: String) {
        tvCloudStatus.text = s
    }

    private fun onPlateHotwordsToggle(enabled: Boolean) {
        if (plateEnhancePrefs.plateHotwordsEnabled == enabled) return
        plateEnhancePrefs.plateHotwordsEnabled = enabled
        loadEngineForLang(currentLang)
        refreshPlateEnhanceCard()
        refreshStationEnhanceCard()
        refreshTermsEnhanceCard()
    }

    private fun onStationHotwordsToggle(enabled: Boolean) {
        if (stationEnhancePrefs.stationHotwordsEnabled == enabled) return
        stationEnhancePrefs.stationHotwordsEnabled = enabled
        loadEngineForLang(currentLang)
        refreshStationEnhanceCard()
        refreshPlateEnhanceCard()
        refreshTermsEnhanceCard()
    }

    private fun onTermsHotwordsToggle(enabled: Boolean) {
        if (termsEnhancePrefs.termsHotwordsEnabled == enabled) return
        termsEnhancePrefs.termsHotwordsEnabled = enabled
        loadEngineForLang(currentLang)
        refreshTermsEnhanceCard()
        refreshPlateEnhanceCard()
        refreshStationEnhanceCard()
    }

    private fun refreshPlateEnhanceCard() {
        swPlateHotwords.setOnCheckedChangeListener(null)
        swPlateNormalize.setOnCheckedChangeListener(null)
        swPlateHotwords.isChecked = plateEnhancePrefs.plateHotwordsEnabled
        swPlateNormalize.isChecked = plateEnhancePrefs.plateNormalizeEnabled
        swPlateHotwords.setOnCheckedChangeListener { _, on -> onPlateHotwordsToggle(on) }
        swPlateNormalize.setOnCheckedChangeListener { _, on ->
            plateEnhancePrefs.plateNormalizeEnabled = on
            refreshPlateEnhanceCard()
        }
        val n = if (plateEnhancePrefs.plateHotwordsEnabled) {
            PlateHotwords.mergeWithUserWords(
                HotwordsPrefs(applicationContext).activeWords(currentLang),
                includePreset = true,
            ).size
        } else {
            HotwordsPrefs(applicationContext).activeWords(currentLang).size
        }
        tvPlatePipeline.text = if (plateEnhancePrefs.plateHotwordsEnabled && n > 0) {
            getString(R.string.cap_plate_hotwords_on, n) + " · " +
                getString(R.string.cap_plate_pipeline_hint)
        } else {
            getString(R.string.cap_plate_hotwords_off) + " · " +
                getString(R.string.cap_plate_pipeline_hint)
        }
    }

    private fun refreshStationEnhanceCard() {
        swStationHotwords.setOnCheckedChangeListener(null)
        swStationNormalize.setOnCheckedChangeListener(null)
        swStationHotwords.isChecked = stationEnhancePrefs.stationHotwordsEnabled
        swStationNormalize.isChecked = stationEnhancePrefs.stationNormalizeEnabled
        swStationHotwords.setOnCheckedChangeListener { _, on -> onStationHotwordsToggle(on) }
        swStationNormalize.setOnCheckedChangeListener { _, on ->
            stationEnhancePrefs.stationNormalizeEnabled = on
            refreshStationEnhanceCard()
        }
        val n = if (stationEnhancePrefs.stationHotwordsEnabled) {
            PoliceStationHotwords.mergeWithUserWords(
                HotwordsPrefs(applicationContext).activeWords(currentLang),
                includePreset = true,
            ).size
        } else {
            HotwordsPrefs(applicationContext).activeWords(currentLang).size
        }
        tvStationPipeline.text = if (stationEnhancePrefs.stationHotwordsEnabled && n > 0) {
            getString(R.string.cap_station_hotwords_on, n) + " · " +
                getString(R.string.cap_station_pipeline_hint)
        } else {
            getString(R.string.cap_station_hotwords_off) + " · " +
                getString(R.string.cap_station_pipeline_hint)
        }
    }

    private fun refreshTermsEnhanceCard() {
        swTermsHotwords.setOnCheckedChangeListener(null)
        swTermsNormalize.setOnCheckedChangeListener(null)
        swTermsHotwords.isChecked = termsEnhancePrefs.termsHotwordsEnabled
        swTermsNormalize.isChecked = termsEnhancePrefs.termsNormalizeEnabled
        swTermsHotwords.setOnCheckedChangeListener { _, on -> onTermsHotwordsToggle(on) }
        swTermsNormalize.setOnCheckedChangeListener { _, on ->
            termsEnhancePrefs.termsNormalizeEnabled = on
            refreshTermsEnhanceCard()
        }
        val n = if (termsEnhancePrefs.termsHotwordsEnabled) {
            PoliceTermsHotwords.mergeWithUserWords(
                HotwordsPrefs(applicationContext).activeWords(currentLang),
                includePreset = true,
            ).size
        } else {
            HotwordsPrefs(applicationContext).activeWords(currentLang).size
        }
        tvTermsPipeline.text = if (termsEnhancePrefs.termsHotwordsEnabled && n > 0) {
            getString(R.string.cap_terms_hotwords_on, n) + " · " +
                getString(R.string.cap_terms_pipeline_hint)
        } else {
            getString(R.string.cap_terms_hotwords_off) + " · " +
                getString(R.string.cap_terms_pipeline_hint)
        }
    }

    /**
     * 录音中锁定能力卡：避免跳转打断录音、避免热词 master 翻转触发 engine 重建。
     * 目标人开关 [swTarget] 不在此锁定——录音中允许实时切换目标人，其可用性由
     * [refreshTsStatus] 决定。
     */
    private fun setCapabilityLocked(locked: Boolean) {
        cardPlateEnhance.isEnabled = !locked
        cardPlateEnhance.alpha = if (locked) 0.5f else 1f
        swPlateHotwords.isEnabled = !locked
        cardStationEnhance.isEnabled = !locked
        cardStationEnhance.alpha = if (locked) 0.5f else 1f
        swStationHotwords.isEnabled = !locked
        cardTermsEnhance.isEnabled = !locked
        cardTermsEnhance.alpha = if (locked) 0.5f else 1f
        swTermsHotwords.isEnabled = !locked
        cardCloud.isEnabled = !locked
        cardCloud.alpha = if (locked) 0.5f else 1f
        swCloud.isEnabled = !locked
    }

    // ----------- 加载 / 切换语言 -----------

    private fun loadEngineForLang(lang: AsrLanguage) {
        val gen = asrLoadGeneration.incrementAndGet()
        val oldEngine = engine
        engine = null
        btnTalk.isEnabled = false

        // 池就绪（preload 完成）时 AmphionRuntime.create 命中池仅 O(ms)，无需加载 UI——
        // 这样切语种 / 拨热词开关不再闪“模型加载”。仅冷启动（池未就绪、需同步解包+加载）
        // 才显示加载条与“加载模型中”文案；完成时的隐藏在 mainHandler.post 里统一收尾（幂等）。
        val showLoadingUi = (application as? AmphionApp)?.preloadDone != true
        if (showLoadingUi) {
            tvLoadingHint.visibility = android.view.View.VISIBLE
            progress.visibility = android.view.View.VISIBLE
            progress.isIndeterminate = true
            setStatus(getString(R.string.status_loading_model, langDisplayName(lang)))
        }

        val prefs = HotwordsPrefs(applicationContext)
        val userHotwords = prefs.activeWords(lang)
        currentHotwordsApplied = userHotwords
        val targetThreshold = speakerStore.getThreshold()
        currentThresholdApplied = targetThreshold

        try {
            asrLoadExec.execute {
                // 旧 engine close → 走 EngineImpl 内部判断：池里有就归还（保留 native），否则 free
                try { oldEngine?.close() } catch (_: Throwable) {}

                // 等 preload 完成；最多 60 秒。这样 create 必然命中池，避免 race 重复加载。
                waitForPreload(timeoutMs = 60_000)

                val cfg = SceneAsrConfig.build(
                    applicationContext,
                    lang,
                    plateHotwords = plateEnhancePrefs.plateHotwordsEnabled,
                    stationHotwords = stationEnhancePrefs.stationHotwordsEnabled,
                    termsHotwords = termsEnhancePrefs.termsHotwordsEnabled,
                    itn = true,
                )
                val cfgWithTarget = if (speakerModelReady()) {
                    AsrConfig.Builder()
                        .numThreads(cfg.numThreads)
                        .punctuation(cfg.punctuation)
                        .itn(cfg.itn)
                        .vad(cfg.vad)
                        .vadConfig(cfg.vadConfig)
                        .endpoint(cfg.endpoint)
                        .endpointRules(cfg.endpointRules)
                        .apply {
                            if (cfg.hotwords.isNotEmpty()) {
                                hotwords(cfg.hotwords, cfg.hotwordsScore)
                            }
                            targetSpeaker(
                                TargetSpeakerConfig(
                                    modelPath = speakerModelPath(),
                                    threshold = targetThreshold,
                                    preload = false,
                                ),
                            )
                        }
                        .build()
                } else {
                    cfg
                }

                val newEngine: AsrEngine = try {
                    AmphionRuntime.create(applicationContext, lang, cfgWithTarget)
                } catch (t: Throwable) {
                    mainHandler.post {
                        if (gen != asrLoadGeneration.get()) return@post
                        setStatus(getString(R.string.status_install_failed, t.message ?: "unknown"))
                        progress.visibility = android.view.View.GONE
                        tvLoadingHint.visibility = android.view.View.GONE
                    }
                    return@execute
                }

                mainHandler.post {
                    if (gen != asrLoadGeneration.get()) {
                        try { newEngine.close() } catch (_: Throwable) {}
                        return@post
                    }
                    engine = newEngine
                    btnTalk.isEnabled = true
                    progress.visibility = android.view.View.GONE
                    tvLoadingHint.visibility = android.view.View.GONE
                    setStatus("模型就绪（${langDisplayName(lang)}），点击开始识别")
                }
            }
        } catch (t: java.util.concurrent.RejectedExecutionException) {
            // Activity 已 onDestroy 关掉 executor
        }
    }

    private fun langDisplayName(lang: AsrLanguage): String = when (lang) {
        AsrLanguage.ZH_EN -> getString(R.string.lang_zh_en)
        AsrLanguage.YUE_EN -> getString(R.string.lang_yue_en)
    }

    /** 阻塞等 [AmphionApp.preloadDone] 变 true；超时则继续走旧路径（同步加载）。 */
    private fun waitForPreload(timeoutMs: Long) {
        val app = application as? AmphionApp ?: return
        if (app.preloadDone) return
        val deadline = System.currentTimeMillis() + timeoutMs
        while (!app.preloadDone && System.currentTimeMillis() < deadline) {
            Thread.sleep(50)
        }
    }

    // ----------- 录音 -----------

    private fun onTalkButtonClick() {
        if (listening) stopListening() else startListening()
    }

    private fun startListening() {
        val eng = engine ?: return
        if (session != null) return

        listening = true
        clearTexts()
        setStatus("识别中…（再次点击停止）")
        setTalkButtonRecording(true)
        setCapabilityLocked(true)
        invalidateOptionsMenu()

        cloudGeneration.incrementAndGet()
        if (cloudPrefs.isEnabled()) {
            startCloudForCurrentSession()
        } else {
            cloudClient?.close()
            cloudClient = null
        }

        waveform.reset()
        waveform.visibility = android.view.View.VISIBLE

        var capturedSession: AsrSession? = null

        val s = eng.newSession(object : AsrCallback {
            override fun onPartial(text: String) {
                runOnUiThread { tvPartial.text = text }
            }

            override fun onFinal(result: AsrResult) {
                val enhanced = applyDomainEnhance(result.text)
                recordDomainEnhance(enhanced, result.text)
                runOnUiThread {
                    appendFinalSegment(result, rejected = false, enhanced = enhanced)
                    tvPartial.text = ""
                }
            }

            override fun onFinalRejected(result: AsrResult) {
                val enhanced = applyDomainEnhance(result.text)
                recordDomainEnhance(enhanced, result.text)
                runOnUiThread {
                    appendFinalSegment(result, rejected = true, enhanced = enhanced)
                    tvPartial.text = ""
                }
            }

            override fun onError(error: AsrError) {
                runOnUiThread { setStatus("识别错误：${error.code} ${error.message}") }
            }

            override fun onMetrics(metrics: AmphionMetrics) {
                if (metrics.kind != AmphionMetricsKind.UTTERANCE) return
                val rss = if (metrics.nativeRssMb >= 0) metrics.nativeRssMb else 0
                val rtf = if (metrics.rtf >= 0f) metrics.rtf else 0f
                val text = if (metrics.firstPartialLatencyMs >= 0L) {
                    getString(
                        R.string.metrics_format,
                        metrics.utteranceE2eLatencyMs,
                        metrics.firstPartialLatencyMs,
                        rtf,
                        rss,
                    )
                } else {
                    getString(
                        R.string.metrics_format_no_partial,
                        metrics.utteranceE2eLatencyMs,
                        rtf,
                        rss,
                    )
                }
                runOnUiThread { tvMetrics.text = text }
            }

            override fun onSessionStopped() {
                capturedSession?.close()
                runOnUiThread {
                    if (!listening) {
                        waveform.visibility = android.view.View.GONE
                        setStatus("已停止；点击可重新开始")
                    }
                }
            }
        })
        capturedSession = s
        session = s

        targetEmbedding?.let { emb ->
            s.setTargetSpeaker(emb)
            s.setTargetSpeakerEnabled(true)
        }

        recorder = AudioRecorder(
            sampleRate = 16000,
            onPcm = { samples ->
                s.acceptPcmShort(samples)
                feedWaveform(samples)
                cloudClient?.sendPcm(samples)
            },
            onError = { msg -> runOnUiThread { setStatus("录音错误：$msg") } },
            gainDb = 10f,
        ).also { it.start() }
    }

    private fun stopListening() {
        if (!listening && session == null && recorder == null) return
        listening = false

        recorder?.stop()
        recorder = null

        val s = session
        session = null
        s?.stop()

        setTalkButtonRecording(false)
        setCapabilityLocked(false)
        invalidateOptionsMenu()
        cloudClient?.stop()
        if (engine != null) {
            setStatus("正在结束本段…")
        }
    }

    private fun stopListeningForSwitch() {
        listening = false
        recorder?.stop()
        recorder = null
        session = null
        cloudGeneration.incrementAndGet()
        cloudClient?.close()
        cloudClient = null
        setTalkButtonRecording(false)
        setCapabilityLocked(false)
        invalidateOptionsMenu()
        waveform.visibility = android.view.View.GONE
    }

    private fun setTalkButtonRecording(recording: Boolean) {
        if (recording) {
            btnTalk.setText(R.string.btn_talk_stop)
            btnTalk.setCompoundDrawablesRelativeWithIntrinsicBounds(
                R.drawable.ic_mic_stop, 0, 0, 0,
            )
            btnTalk.setBackgroundResource(R.drawable.bg_button_recording)
        } else {
            btnTalk.setText(R.string.btn_talk_start)
            btnTalk.setCompoundDrawablesRelativeWithIntrinsicBounds(
                R.drawable.ic_mic, 0, 0, 0,
            )
            btnTalk.setBackgroundResource(R.drawable.bg_button_primary)
        }
    }

    private fun feedWaveform(samples: ShortArray) {
        if (samples.isEmpty()) return
        val frames = WAVEFORM_FRAMES_PER_BATCH
        val frameLen = max(1, samples.size / frames)
        val amps = FloatArray(frames)
        var i = 0
        var written = 0
        while (i < samples.size && written < frames) {
            val end = (i + frameLen).coerceAtMost(samples.size)
            var peak = 0
            var k = i
            while (k < end) {
                val a = abs(samples[k].toInt())
                if (a > peak) peak = a
                k++
            }
            val norm = (peak / 32768f).coerceIn(0f, 1f)
            amps[written] = kotlin.math.sqrt(norm)
            i = end
            written++
        }
        mainHandler.post {
            for (j in 0 until written) {
                waveform.pushAmplitude(amps[j])
            }
        }
    }

    private fun clearTexts() {
        tvPartial.text = ""
        tvFinal.text = ""
        finalBuilder.clear()
        tvMetrics.text = getString(R.string.metrics_placeholder)
        cloudFinalBuilder.setLength(0)
        cloudCurrentPartial = ""
        renderCloud()
        if (cloudPrefs.isEnabled()) setCloudStatus(getString(R.string.cloud_status_idle))
    }

    private fun setStatus(s: String) {
        tvStatus.text = s
    }

    // ----------- 目标说话人 demo -----------

    private fun speakerModelPath(): String =
        File(getExternalFilesDir(null), SPEAKER_MODEL_FILENAME).absolutePath

    private fun speakerModelReady(): Boolean = File(speakerModelPath()).exists()

    private fun reloadTargetSpeaker() {
        val emb = speakerStore.loadEmbedding()
        targetEmbedding = emb
        if (emb == null) {
            session?.clearTargetSpeaker()
        } else {
            session?.setTargetSpeaker(emb)
            session?.setTargetSpeakerEnabled(true)
        }
    }

    /**
     * 声纹页改阈值后回主页：startActivity 无 result，故 onResume 主动比对 prefs 与
     * [currentThresholdApplied]。阈值只在 engine 的 TargetSpeakerConfig 里生效，变更需静默重建
     * engine（命中池 O(ms)），新值在下一段识别生效。无声纹模型 / 录音中则跳过：前者 engine 不带
     * 目标人能力、阈值无意义，后者重建会打断当前 session。
     */
    private fun maybeReloadThreshold() {
        if (!speakerModelReady() || listening) return
        val t = speakerStore.getThreshold()
        if (!currentThresholdApplied.isNaN() && t != currentThresholdApplied) {
            loadEngineForLang(currentLang)
        }
    }

    private fun applyDomainEnhance(asrRaw: String): PoliceEnhancePipeline.Result =
        AsrTextEnhance.apply(
            asrRaw,
            termsNormalizer,
            termsEnhancePrefs.termsNormalizeEnabled,
            plateNormalizer,
            plateEnhancePrefs.plateNormalizeEnabled,
            stationNormalizer,
            stationEnhancePrefs.stationNormalizeEnabled,
        )

    private fun recordDomainEnhance(enhanced: PoliceEnhancePipeline.Result, asrRaw: String) {
        termsEvalRecorder.append(
            uttId = "mic_${System.currentTimeMillis()}",
            refText = "",
            expectedTerms = emptyList(),
            asrRaw = asrRaw,
            result = enhanced.terms,
        )
        logTermsEnhance(asrRaw, enhanced.terms)
        plateEvalRecorder.append(asrRaw, enhanced.plate)
        logPlateEnhance(asrRaw, enhanced.plate)
        stationEvalRecorder.append(
            uttId = "mic_${System.currentTimeMillis()}",
            refText = "",
            expectedStation = "",
            asrRaw = asrRaw,
            result = enhanced.station,
        )
        logStationEnhance(asrRaw, enhanced.station)
    }

    private fun logTermsEnhance(
        raw: String,
        norm: com.amphion.police.terms.PoliceTermsNormalizeResult,
    ) {
        if (norm.spans.isEmpty()) return
        Log.i(
            TAG,
            "PoliceTermsEnhance raw=$raw norm=${norm.text} terms=${norm.matchedTerms} " +
                "valid=${norm.spans.any { it.valid }}",
        )
    }

    private fun logPlateEnhance(raw: String, norm: com.amphion.police.plate.PlateNormalizeResult) {
        if (norm.spans.isEmpty()) return
        Log.i(
            TAG,
            "PlateEnhance raw=$raw norm=${norm.text} primary=${norm.primaryPlate} " +
                "valid=${norm.spans.any { it.valid }}",
        )
    }

    private fun logStationEnhance(
        raw: String,
        norm: com.amphion.police.station.PoliceStationNormalizeResult,
    ) {
        if (norm.spans.isEmpty()) return
        Log.i(
            TAG,
            "PoliceStationEnhance raw=$raw norm=${norm.text} primary=${norm.primaryStation} " +
                "valid=${norm.spans.any { it.valid }}",
        )
    }

    private fun appendFinalSegment(
        result: AsrResult,
        rejected: Boolean,
        enhanced: PoliceEnhancePipeline.Result? = null,
    ) {
        var text = enhanced?.text ?: result.text
        if (enhanced != null && enhanced.text != result.text) {
            text = "${enhanced.text}\n(原文: ${result.text})"
        }
        if (text.isEmpty()) return
        if (finalBuilder.isNotEmpty()) finalBuilder.append("\n")
        val start = finalBuilder.length
        finalBuilder.append(text)
        result.speakerScore?.let {
            finalBuilder.append(if (rejected) " [✗ %.2f]".format(it) else " [✓ %.2f]".format(it))
        }
        if (rejected) {
            val end = finalBuilder.length
            finalBuilder.setSpan(
                ForegroundColorSpan(Color.GRAY), start, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE,
            )
            finalBuilder.setSpan(
                StrikethroughSpan(), start, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE,
            )
        }
        tvFinal.text = finalBuilder
    }

    private fun toast(s: String) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show()
    }
}
