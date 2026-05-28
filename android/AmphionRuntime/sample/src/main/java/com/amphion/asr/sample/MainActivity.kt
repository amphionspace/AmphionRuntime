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

    override fun onDestroy() {
        super.onDestroy()
        stopListening()
        asrLoadGeneration.incrementAndGet()
        asrLoadExec.shutdownNow()
        engine?.close()
        engine = null
        // 不调 AmphionRuntime.release()：保留池给下次 Activity 用，避免重复加载
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.menu_main, menu)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        return when (item.itemId) {
            R.id.action_hotwords -> {
                hotwordsLauncher.launch(Intent(this, HotwordsActivity::class.java))
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
                s.updateHotwords(newActive, HOTWORDS_SCORE)
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

    // ----------- 加载 / 切换语言 -----------

    private fun loadEngineForLang(lang: AsrLanguage) {
        val gen = asrLoadGeneration.incrementAndGet()
        val oldEngine = engine
        engine = null
        btnTalk.isEnabled = false
        tvLoadingHint.visibility = android.view.View.VISIBLE
        progress.visibility = android.view.View.VISIBLE
        progress.isIndeterminate = true
        setStatus(getString(R.string.status_loading_model, langDisplayName(lang)))

        val prefs = HotwordsPrefs(applicationContext)
        val userHotwords = prefs.activeWords(lang)
        val poolArmed = (application as AmphionApp).hotwordsArmed
        // 占位词补齐策略（详见 HOTWORD_POOL_PLACEHOLDER）：池 armed 时 cfg 始终非空热词
        val effectiveHotwords: List<String> = when {
            userHotwords.isNotEmpty() -> userHotwords
            poolArmed -> listOf(HOTWORD_POOL_PLACEHOLDER)
            else -> emptyList()
        }
        currentHotwordsApplied = userHotwords

        try {
            asrLoadExec.execute {
                // 旧 engine close → 走 EngineImpl 内部判断：池里有就归还（保留 native），否则 free
                try { oldEngine?.close() } catch (_: Throwable) {}

                // 等 preload 完成；最多 60 秒。这样 create 必然命中池，避免 race 重复加载。
                waitForPreload(timeoutMs = 60_000)

                val cfgBuilder = AsrConfig.Builder()
                    .numThreads(2)
                    .punctuation(true)
                    .itn(true)
                    .vad(true)
                    .endpoint(true)
                if (effectiveHotwords.isNotEmpty()) {
                    cfgBuilder.hotwords(effectiveHotwords, HOTWORDS_SCORE)
                }
                val cfg = cfgBuilder.build()

                val newEngine: AsrEngine = try {
                    AmphionRuntime.create(applicationContext, lang, cfg)
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

        waveform.reset()
        waveform.visibility = android.view.View.VISIBLE

        var capturedSession: AsrSession? = null

        val s = eng.newSession(object : AsrCallback {
            override fun onPartial(text: String) {
                runOnUiThread { tvPartial.text = text }
            }

            override fun onFinal(text: String, confidence: Float) {
                runOnUiThread {
                    if (text.isNotEmpty()) {
                        val existing = tvFinal.text?.toString().orEmpty()
                        tvFinal.text = if (existing.isEmpty()) text else "$existing\n$text"
                    }
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

        recorder = AudioRecorder(
            sampleRate = 16000,
            onPcm = { samples ->
                s.acceptPcmShort(samples)
                feedWaveform(samples)
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
        if (engine != null) {
            setStatus("正在结束本段…")
        }
    }

    private fun stopListeningForSwitch() {
        listening = false
        recorder?.stop()
        recorder = null
        session = null
        setTalkButtonRecording(false)
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
        tvMetrics.text = getString(R.string.metrics_placeholder)
    }

    private fun setStatus(s: String) {
        tvStatus.text = s
    }

    private fun toast(s: String) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show()
    }
}
