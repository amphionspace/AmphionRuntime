package com.amphion.asr.sample.plate

import android.content.Intent
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
import com.amphion.asr.sample.R
import com.amphion.police.plate.PlateEnhancePrefs
import com.amphion.police.plate.PlateNormalizer
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 批量车牌评测：adb push batch-eval/ 后在本页一键跑完，落盘路径与 roundN 相同。
 *
 * adb 触发示例：
 * ```
 * adb shell am start -n com.amphion.asr.sample/.plate.PlateBatchEvalActivity \
 *   --es filter license_plate_v2 --ez auto_start true --ez fresh true
 * ```
 */
class PlateBatchEvalActivity : AppCompatActivity() {

    private lateinit var tvStatus: TextView
    private lateinit var tvDetail: TextView
    private lateinit var progress: ProgressBar
    private lateinit var btnStart: Button
    private lateinit var btnStop: Button

    private val mainHandler = Handler(Looper.getMainLooper())
    private val exec: ExecutorService = Executors.newSingleThreadExecutor { r ->
        Thread(r, "plate-batch-eval").apply { isDaemon = true }
    }

    private lateinit var plateNormalizer: PlateNormalizer
    private lateinit var plateEvalRecorder: PlateEvalRecorder

    private var engine: AsrEngine? = null
    private var cases: List<BatchEvalCase> = emptyList()
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

        tvStatus = findViewById(R.id.tv_batch_status)
        tvDetail = findViewById(R.id.tv_batch_detail)
        progress = findViewById(R.id.progress_batch)
        btnStart = findViewById(R.id.btn_batch_start)
        btnStop = findViewById(R.id.btn_batch_stop)

        val prefs = PlateEnhancePrefs(applicationContext)
        val useFst = intent.getBooleanExtra(EXTRA_USE_FST, prefs.plateFstEnabled)
        plateNormalizer = PlateNormalizer.create(this, useFst = useFst)
        plateEvalRecorder = PlateEvalRecorder(this)
        Log.i(TAG, "normalize plate_fst=${plateNormalizer.fstEnabled}")

        filterPrefix = intent.getStringExtra(EXTRA_FILTER)
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
            plateNormalizer.close()
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
        cases = BatchEvalManifest.loadCases(this, filterPrefix)
        val filterLabel = filterPrefix ?: "all"
        val done = BatchEvalManifest.loadDoneIds(this).size
        val dir = BatchEvalManifest.batchDir(this).absolutePath
        tvStatus.text = getString(
            R.string.batch_eval_status_fmt,
            cases.size,
            filterLabel,
            done,
            dir,
        )
        tvDetail.text = getString(R.string.batch_eval_detail_hint) + "\n\n" +
            PlateEvalRecorder.pullHint()
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
        val platePrefs = PlateEnhancePrefs(applicationContext)
        return PlateAsrConfig.build(
            applicationContext,
            AsrLanguage.ZH_EN,
            PlateAsrConfig.Options(
                plateHotwords = platePrefs.plateHotwordsEnabled,
                plateNormalize = platePrefs.plateNormalizeEnabled,
                itn = true,
                batchMode = true,
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
            plateEvalRecorder.reset()
            BatchEvalManifest.clearProgress(this)
        }

        val skipIds = BatchEvalManifest.loadDoneIds(this)
        val runner = PlateBatchEvalRunner(eng, plateNormalizer, plateEvalRecorder)

        exec.execute {
            val result = runner.run(
                cases = cases,
                skipIds = skipIds,
                onProgress = { p ->
                    mainHandler.post { onRunnerProgress(p) }
                    if (p.status != "skip") {
                        BatchEvalManifest.appendDoneId(this@PlateBatchEvalActivity, p.uttId)
                    }
                },
                shouldStop = { stopRequested.get() },
            )
            mainHandler.post { onRunnerFinished(result) }
        }
    }

    private fun onRunnerProgress(p: PlateBatchEvalRunner.Progress) {
        val pct = if (p.total > 0) p.index * 100 / p.total else 0
        progress.progress = pct
        val line = "${p.index}/${p.total} ${p.uttId} ${p.status}"
        logLines.addFirst(line)
        while (logLines.size > 15) logLines.removeLast()
        tvDetail.text = logLines.joinToString("\n")
        Log.i(TAG, line)
    }

    private fun onRunnerFinished(result: PlateBatchEvalRunner.Result) {
        running.set(false)
        btnStart.isEnabled = true
        btnStop.isEnabled = false
        val summary = getString(
            R.string.batch_eval_done_fmt,
            result.processed,
            result.skipped,
            result.failed,
            plateEvalRecorder.filePath(),
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
        private const val TAG = "PlateBatchEvalAct"
        const val EXTRA_FILTER = "filter"
        const val EXTRA_AUTO_START = "auto_start"
        const val EXTRA_FRESH = "fresh"
        const val EXTRA_USE_FST = "use_fst"

        fun launchIntent(
            filter: String? = "license_plate_v2",
            autoStart: Boolean = false,
            fresh: Boolean = false,
        ): Intent = Intent().apply {
            setClassName(
                "com.amphion.asr.sample",
                "com.amphion.police.plate.PlateBatchEvalActivity",
            )
            filter?.let { putExtra(EXTRA_FILTER, it) }
            putExtra(EXTRA_AUTO_START, autoStart)
            putExtra(EXTRA_FRESH, fresh)
        }
    }
}
