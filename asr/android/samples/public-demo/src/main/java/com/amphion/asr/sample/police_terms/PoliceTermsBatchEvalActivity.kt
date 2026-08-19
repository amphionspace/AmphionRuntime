package com.amphion.asr.sample.police_terms

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.MenuItem
import android.widget.Button
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.Toolbar
import com.amphion.asr.AmphionRuntime
import com.amphion.asr.AsrConfig
import com.amphion.asr.AsrEngine
import com.amphion.asr.AsrLanguage
import com.amphion.asr.sample.AmphionApp
import com.amphion.asr.sample.HotwordsPrefs
import com.amphion.asr.sample.R
import com.amphion.police.PoliceEnhancePipeline
import com.amphion.police.PoliceHotwordProfile
import com.amphion.police.terms.PoliceTermsEnhancePrefs
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 批量警务术语评测：adb push batch-eval/ 后在本页一键跑完。
 *
 * adb 触发示例：
 * ```
 * adb shell am start -n com.amphion.asr.sample/.police_terms.PoliceTermsBatchEvalActivity \
 *   --es filter police_terms_samples --ez auto_start true --ez fresh true
 * ```
 */
class PoliceTermsBatchEvalActivity : AppCompatActivity() {

    private lateinit var tvStatus: TextView
    private lateinit var tvDetail: TextView
    private lateinit var progress: ProgressBar
    private lateinit var btnStart: Button
    private lateinit var btnStop: Button

    private val mainHandler = Handler(Looper.getMainLooper())
    private val exec: ExecutorService = Executors.newSingleThreadExecutor { r ->
        Thread(r, "police-terms-batch-eval").apply { isDaemon = true }
    }

    private lateinit var pipeline: PoliceEnhancePipeline
    private lateinit var evalRecorder: PoliceTermsEvalRecorder

    private var engine: AsrEngine? = null
    private var cases: List<PoliceTermsBatchEvalCase> = emptyList()
    private val running = AtomicBoolean(false)
    private val stopRequested = AtomicBoolean(false)
    private val logLines = ArrayDeque<String>()

    private var filterPrefix: String? = null
    private var autoStart = false
    private var freshSession = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_plate_batch_eval)

        setSupportActionBar(findViewById<Toolbar>(R.id.toolbar))
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        supportActionBar?.title = getString(R.string.terms_batch_eval_title)

        tvStatus = findViewById(R.id.tv_batch_status)
        tvDetail = findViewById(R.id.tv_batch_detail)
        progress = findViewById(R.id.progress_batch)
        btnStart = findViewById(R.id.btn_batch_start)
        btnStop = findViewById(R.id.btn_batch_stop)

        val prefs = PoliceTermsEnhancePrefs(applicationContext)
        val useFst = intent.getBooleanExtra(EXTRA_USE_FST, prefs.termsFstEnabled)
        // 交付基线：完整三域 V2 pipeline（与 dingqiao SDK 一致），而非裸 V1。
        pipeline = PoliceEnhancePipeline.create(
            context = this,
            termsUseFst = useFst,
            plateV2Enabled = true,
            stationV2Enabled = true,
            termsV2Enabled = true,
        )
        evalRecorder = PoliceTermsEvalRecorder(this)
        Log.i(TAG, "pipeline terms_v2=true plate_v2=true station_v2=true terms_fst=${pipeline.termsNormalizer.fstEnabled}")

        filterPrefix = intent.getStringExtra(EXTRA_FILTER) ?: "police_terms_samples"
        autoStart = intent.getBooleanExtra(EXTRA_AUTO_START, false)
        freshSession = intent.getBooleanExtra(EXTRA_FRESH, false)

        btnStart.setOnClickListener { startBatch() }
        btnStop.setOnClickListener { requestStop() }

        reloadCases()
        loadEngineAsync {
            if (autoStart && cases.isNotEmpty()) startBatch()
        }
    }

    override fun onDestroy() {
        stopRequested.set(true)
        try {
            engine?.close()
        } catch (_: Throwable) {}
        engine = null
        try {
            pipeline.close()
        } catch (_: Throwable) {}
        exec.shutdownNow()
        super.onDestroy()
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        if (item.itemId == android.R.id.home) {
            finish()
            return true
        }
        return super.onOptionsItemSelected(item)
    }

    private fun reloadCases() {
        cases = PoliceTermsBatchEvalManifest.loadCases(this, filterPrefix, pipeline.termsNormalizer)
        val filterLabel = filterPrefix ?: "all"
        val done = PoliceTermsBatchEvalManifest.loadDoneIds(this).size
        val dir = PoliceTermsBatchEvalManifest.batchDir(this).absolutePath
        tvStatus.text = getString(
            R.string.terms_batch_eval_status_fmt,
            cases.size,
            filterLabel,
            done,
            dir,
        )
        tvDetail.text = getString(R.string.terms_batch_eval_detail_hint) + "\n\n" +
            PoliceTermsEvalRecorder.pullHint()
        progress.progress = 0
        btnStart.isEnabled = cases.isNotEmpty() && engine != null && !running.get()
    }

    private fun loadEngineAsync(onReady: () -> Unit = {}) {
        btnStart.isEnabled = false
        tvStatus.append("\n" + getString(R.string.batch_eval_loading_engine))
        exec.execute {
            waitForPreload(60_000)
            val cfg = buildConfig()
            val eng = try {
                AmphionRuntime.create(applicationContext, AsrLanguage.ZH_EN, cfg)
            } catch (t: Throwable) {
                mainHandler.post {
                    tvStatus.append("\n" + getString(R.string.batch_eval_engine_failed, t.message))
                    toast(getString(R.string.batch_eval_engine_failed, t.message))
                }
                return@execute
            }
            mainHandler.post {
                engine = eng
                reloadCases()
                onReady()
            }
        }
    }

    private fun buildConfig(): AsrConfig {
        val prefs = PoliceTermsEnhancePrefs(applicationContext)
        // 端点实验：--ei endpoint_ms N 覆盖主动 endpoint 尾静音阈值（<0 = 沿用 batchMode 默认 0=关闭）
        val epMs = intent.getIntExtra(EXTRA_ENDPOINT_MS, -1).takeIf { it >= 0 }
        val hotwordProfile = intent.getStringExtra(EXTRA_HOTWORD_PROFILE)?.let {
            PoliceHotwordProfile.parse(it)
        }
        val userHotwords = HotwordsPrefs(applicationContext).activeWords(AsrLanguage.ZH_EN)
        evalRecorder.writeRunConfig(
            hotwordProfile = hotwordProfile?.wireValue ?: "preference",
            termsHotwordsEnabled = prefs.termsHotwordsEnabled,
            userHotwords = userHotwords,
            filterPrefix = filterPrefix,
        )
        Log.i(
            TAG,
            "buildConfig activeEndpointMs=${epMs ?: "default(batch=0/关闭)"} " +
                "hotwordProfile=${hotwordProfile?.wireValue ?: "preference"} " +
                "userHotwordCount=${userHotwords.map { it.trim() }.filter { it.isNotEmpty() }.distinct().size}",
        )
        return PoliceTermsAsrConfig.build(
            applicationContext,
            AsrLanguage.ZH_EN,
            PoliceTermsAsrConfig.Options(
                termsHotwords = prefs.termsHotwordsEnabled,
                termsNormalize = prefs.termsNormalizeEnabled,
                itn = true,
                batchMode = true,
                hotwordProfile = hotwordProfile,
                activeEndpointMs = epMs,
            ),
        )
    }

    private fun waitForPreload(timeoutMs: Long) {
        val app = application as? AmphionApp ?: return
        if (app.preloadDone) return
        val deadline = System.currentTimeMillis() + timeoutMs
        while (!app.preloadDone && System.currentTimeMillis() < deadline) {
            Thread.sleep(50)
        }
    }

    private fun startBatch() {
        val eng = engine ?: return
        if (!running.compareAndSet(false, true)) return
        stopRequested.set(false)
        btnStart.isEnabled = false
        btnStop.isEnabled = true

        if (freshSession) {
            evalRecorder.reset()
            PoliceTermsBatchEvalManifest.clearProgress(this)
        }

        val prefs = PoliceTermsEnhancePrefs(applicationContext)
        val skipIds = PoliceTermsBatchEvalManifest.loadDoneIds(this)
        val runner = PoliceTermsBatchEvalRunner(
            eng,
            pipeline,
            evalRecorder,
            normalizeEnabled = prefs.termsNormalizeEnabled,
        )

        exec.execute {
            val result = runner.run(
                cases = cases,
                skipIds = skipIds,
                onProgress = { p ->
                    mainHandler.post { onRunnerProgress(p) }
                    if (p.status != "skip") {
                        PoliceTermsBatchEvalManifest.appendDoneId(
                            this@PoliceTermsBatchEvalActivity,
                            p.uttId,
                        )
                    }
                },
                shouldStop = { stopRequested.get() },
            )
            mainHandler.post { onRunnerFinished(result) }
        }
    }

    private fun onRunnerProgress(p: PoliceTermsBatchEvalRunner.Progress) {
        val pct = if (p.total > 0) p.index * 100 / p.total else 0
        progress.progress = pct
        val line = "${p.index}/${p.total} ${p.uttId} ${p.status}"
        logLines.addFirst(line)
        while (logLines.size > 15) logLines.removeLast()
        tvDetail.text = logLines.joinToString("\n")
        Log.i(TAG, line)
    }

    private fun onRunnerFinished(result: PoliceTermsBatchEvalRunner.Result) {
        running.set(false)
        btnStart.isEnabled = true
        btnStop.isEnabled = false
        val summary = getString(
            R.string.terms_batch_eval_done_fmt,
            result.processed,
            result.skipped,
            result.failed,
            evalRecorder.filePath(),
        )
        tvStatus.text = summary
        if (result.errors.isNotEmpty()) {
            tvDetail.text = result.errors.take(20).joinToString("\n")
        }
        toast(summary)
        reloadCases()
    }

    private fun requestStop() {
        stopRequested.set(true)
        btnStop.isEnabled = false
        toast(getString(R.string.batch_eval_stopping))
    }

    private fun toast(msg: String) {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
    }

    companion object {
        private const val TAG = "PoliceTermsBatchAct"
        const val EXTRA_FILTER = "filter"
        const val EXTRA_AUTO_START = "auto_start"
        const val EXTRA_FRESH = "fresh"
        const val EXTRA_USE_FST = "use_fst"
        const val EXTRA_ENDPOINT_MS = "endpoint_ms"
        const val EXTRA_HOTWORD_PROFILE = "hotword_profile"
    }
}
