package com.amphion.asr.sample.eval

import android.Manifest
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.format.Formatter
import android.view.Menu
import android.view.MenuItem
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.SwitchCompat
import androidx.appcompat.widget.Toolbar
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import com.amphion.asr.sample.BuildConfig
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.amphion.asr.sample.R
import com.amphion.asr.sample.eval.data.RecordingStore
import com.amphion.asr.sample.eval.data.SentenceRepository
import com.amphion.asr.sample.eval.data.TesterPrefs
import com.amphion.asr.sample.eval.data.UploadSettings
import com.amphion.asr.sample.eval.export.RecordingExporter
import com.amphion.asr.sample.eval.export.ZipExporter
import com.amphion.asr.sample.eval.model.CustomSentence
import com.amphion.asr.sample.eval.model.RecordingMeta
import com.amphion.asr.sample.eval.model.Sentence
import com.amphion.asr.sample.eval.upload.HttpUploader
import com.amphion.asr.sample.eval.upload.UploadScanner
import com.amphion.asr.sample.eval.upload.UploadStatusBar

/**
 * 评估模式主页：句子列表 + 测试员管理 + 上传状态条 + Toolbar 菜单。
 *
 * 不直接持有 ASR 引擎；引擎在 RecordSentenceActivity 内独立加载（每次进录音页加载一次，
 * onDestroy 关掉），避免引擎在不录音时一直驻留 native 内存。
 *
 * 数据流：
 * - onCreate：加载 SentenceRepository（assets fallback）+ TesterPrefs + UploadSettings
 * - onResume：扫描 RecordingStore 重算 attemptsBySentence，刷新列表与上传状态条
 * - 用户点击 item → 跳 SentenceDetailActivity（看历史）或 RecordSentenceActivity（直接录）
 */
class EvalActivity : AppCompatActivity(), UploadScanner.Listener {

    private lateinit var prefs: TesterPrefs
    private lateinit var settings: UploadSettings
    private lateinit var store: RecordingStore
    private lateinit var repo: SentenceRepository
    private lateinit var scanner: UploadScanner
    private lateinit var adapter: SentenceListAdapter

    private lateinit var rv: RecyclerView
    private lateinit var statusBar: UploadStatusBar
    private lateinit var tvCurrentTester: TextView

    private val mainHandler = Handler(Looper.getMainLooper())

    private val recordPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (!granted) {
            Toast.makeText(this, R.string.eval_no_permission, Toast.LENGTH_SHORT).show()
            finish()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_eval)

        prefs = TesterPrefs(this)
        settings = UploadSettings(this)
        store = RecordingStore(this)
        scanner = UploadScanner(store, settings)

        try {
            repo = SentenceRepository.load(this)
        } catch (t: Throwable) {
            Toast.makeText(this, getString(R.string.eval_load_failed, t.message ?: ""), Toast.LENGTH_LONG).show()
            finish()
            return
        }

        setSupportActionBar(findViewById<Toolbar>(R.id.toolbar))

        rv = findViewById(R.id.rv_sentences)
        rv.layoutManager = LinearLayoutManager(this)
        adapter = SentenceListAdapter(
            onClickSentence = { sentence -> onSentenceClick(sentence) },
            onClickNewCustom = { startCustomRecording() },
        )
        rv.adapter = adapter

        statusBar = findViewById(R.id.upload_status_bar)
        statusBar.onActionClick = ::onStatusBarAction

        tvCurrentTester = findViewById(R.id.tv_current_tester)

        ensureRecordPermission()
    }

    override fun onResume() {
        super.onResume()
        if (!prefs.isConfigured()) {
            promptTesterDialog()
            return
        }
        tvCurrentTester.text = getString(R.string.eval_tester_current_fmt, prefs.nickname())
        refreshList()
        refreshUploadStatus()
        // 应用启动 / 进入评估页时自动触发一轮同步（仅 pending/retry，不含 failed）
        if (settings.isConfigured() && settings.autoUploadEnabled()) {
            scanner.setListener(this)
            scanner.trigger(includeFailed = false)
        }
    }

    override fun onPause() {
        super.onPause()
        scanner.setListener(null)
    }

    override fun onDestroy() {
        super.onDestroy()
        scanner.shutdown()
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.menu_eval, menu)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean = when (item.itemId) {
        R.id.action_sync_now -> { triggerSyncNow(); true }
        R.id.action_upload_settings -> { showUploadSettingsDialog(); true }
        R.id.action_export_zip -> { exportZip(); true }
        R.id.action_change_tester -> { confirmChangeTester(); true }
        else -> super.onOptionsItemSelected(item)
    }

    // ----- 列表 / 数据 -----

    private fun refreshList() {
        val tester = prefs.testerId()
        val attemptsBySentence = HashMap<String, List<RecordingMeta>>()
        for (s in repo.manifest.allSentences()) {
            attemptsBySentence[s.id] = store.listAttempts(tester, s.id)
        }
        val customSentences = collectCustomSentences(tester, attemptsBySentence)
        adapter.refresh(
            manifest = repo.manifest,
            attemptsBySentence = attemptsBySentence,
            customSentences = customSentences,
            customSectionTitle = getString(R.string.eval_custom_section_title),
            customSectionDesc = getString(R.string.eval_custom_section_desc),
        )
    }

    /**
     * 扫 RecordingStore 中所有 sentence_id 以 [CustomSentence.ID_PREFIX] 开头的录音，
     * 按 sentence_id 分组，用首条 attempt 的 referenceText 作为「标题」回填到 Sentence。
     *
     * 为什么不引入单独的 CustomSentenceStore：reference_text 已经是 meta.json 强制字段，
     * 多一张表 = 多一个状态机要维护 + 多一个一致性 invariant；从录音元信息反推就足够。
     */
    private fun collectCustomSentences(
        tester: String,
        attemptsBySentence: MutableMap<String, List<RecordingMeta>>,
    ): List<Sentence> {
        val grouped = HashMap<String, MutableList<RecordingMeta>>()
        store.scanAll { meta ->
            if (meta.testerId == tester && CustomSentence.isCustomSentenceId(meta.sentenceId)) {
                grouped.getOrPut(meta.sentenceId) { ArrayList() }.add(meta)
            }
            false
        }
        val out = ArrayList<Sentence>(grouped.size)
        for ((id, list) in grouped) {
            list.sortBy { it.recordedAt }
            attemptsBySentence[id] = list
            out.add(
                Sentence(
                    id = id,
                    text = list.first().referenceText,
                    categoryId = CustomSentence.CUSTOM_CATEGORY_ID,
                )
            )
        }
        // 按最近一次录制时间倒序展示（越新越靠前）
        out.sortByDescending { s -> attemptsBySentence[s.id]?.maxOfOrNull { it.recordedAt } ?: "" }
        return out
    }

    private fun refreshUploadStatus() {
        val snap = scanner.snapshot()
        statusBar.render(snap, hasConfig = settings.isConfigured())
    }

    private fun onSentenceClick(sentence: Sentence) {
        val tester = prefs.testerId()
        val attempts = store.listAttempts(tester, sentence.id)
        if (attempts.isEmpty()) {
            startActivity(RecordSentenceActivity.intent(this, sentence.id))
        } else {
            startActivity(SentenceDetailActivity.intent(this, sentence.id))
        }
    }

    /**
     * 「+ 自由录音」入口：直接进入录音页（不再弹输入框）。
     *
     * UX 改造：测试员先录、再校对识别结果作为 reference，比「先输入文本再念」自然得多
     * （想到啥念啥）。识别结果会自动填到 reference 输入框作为草稿，测试员通常只需微调。
     */
    private fun startCustomRecording() {
        startActivity(RecordSentenceActivity.intentForCustomRecording(this))
    }

    // ----- 测试员管理 -----

    private fun promptTesterDialog() {
        val ctx = this
        val input = EditText(ctx).apply {
            hint = getString(R.string.eval_tester_dialog_hint)
            setSingleLine()
        }
        AlertDialog.Builder(ctx)
            .setTitle(R.string.eval_tester_dialog_title)
            .setMessage(R.string.eval_tester_dialog_msg)
            .setView(input)
            .setCancelable(false)
            .setPositiveButton(android.R.string.ok) { _, _ ->
                val name = input.text.toString().trim()
                if (name.isEmpty()) {
                    promptTesterDialog()
                    return@setPositiveButton
                }
                prefs.setNickname(name)
                tvCurrentTester.text = getString(R.string.eval_tester_current_fmt, name)
                refreshList()
            }
            .setNegativeButton(android.R.string.cancel) { _, _ -> finish() }
            .show()
    }

    private fun confirmChangeTester() {
        AlertDialog.Builder(this)
            .setTitle(R.string.eval_tester_change_title)
            .setMessage(R.string.eval_tester_change_msg)
            .setPositiveButton(android.R.string.ok) { _, _ ->
                prefs.clear()
                promptTesterDialog()
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    // ----- 上传 -----

    private fun onStatusBarAction() {
        if (!settings.isConfigured()) {
            showUploadSettingsDialog()
            return
        }
        triggerSyncNow()
    }

    private fun triggerSyncNow() {
        if (!settings.isConfigured()) {
            showUploadSettingsDialog()
            return
        }
        scanner.setListener(this)
        // 用户主动「立即同步」：绕过指数退避到点判定，立刻重试所有 RETRY / FAILED 条目。
        // 自动触发（onResume / 录音保存）保持退避，避免无效请求。
        scanner.trigger(includeFailed = true, ignoreBackoff = true)
        refreshUploadStatus()
    }

    private fun showUploadSettingsDialog() {
        val view = layoutInflater.inflate(R.layout.dialog_upload_settings, null)
        val etUrl = view.findViewById<EditText>(R.id.et_server_url)
        val etToken = view.findViewById<EditText>(R.id.et_bearer_token)
        val swAuto = view.findViewById<SwitchCompat>(R.id.sw_auto_upload)
        val btnOfficial = view.findViewById<android.widget.Button>(R.id.btn_use_official_server)
        etUrl.setText(settings.serverUrl().orEmpty())
        etToken.setText(settings.bearerToken().orEmpty())
        swAuto.isChecked = settings.autoUploadEnabled()
        btnOfficial.setOnClickListener {
            // 只填 URL，不填 token —— token 仍要工程师线下给，避免 apk 里硬编码默认凭证。
            etUrl.setText(OFFICIAL_SERVER_URL)
            etUrl.setSelection(OFFICIAL_SERVER_URL.length)
        }
        AlertDialog.Builder(this)
            .setTitle(R.string.eval_upload_settings_title)
            .setView(view)
            .setPositiveButton(R.string.eval_upload_btn_save) { _, _ ->
                settings.update(
                    serverUrl = etUrl.text.toString().trim().ifEmpty { null },
                    bearerToken = etToken.text.toString().trim().ifEmpty { null },
                    autoUpload = swAuto.isChecked,
                )
                refreshUploadStatus()
            }
            .setNeutralButton(R.string.eval_upload_btn_clear) { _, _ ->
                settings.clear()
                refreshUploadStatus()
            }
            .setNegativeButton(R.string.eval_upload_btn_cancel, null)
            .show()
    }

    // ----- 导出 zip -----

    private fun exportZip() {
        val tester = prefs.testerId()
        val exporter: RecordingExporter = ZipExporter()
        val result = try {
            exporter.export(
                this, store,
                RecordingExporter.ExportFilter.notUploadedOfTester(tester),
            )
        } catch (t: Throwable) {
            Toast.makeText(this, getString(R.string.eval_export_failed_fmt, t.message ?: ""), Toast.LENGTH_LONG).show()
            return
        }
        if (result.itemCount == 0 || result.zipFile == null) {
            Toast.makeText(this, R.string.eval_export_empty, Toast.LENGTH_SHORT).show()
            return
        }
        Toast.makeText(
            this,
            getString(R.string.eval_export_done_fmt, result.itemCount, Formatter.formatShortFileSize(this, result.totalBytes)),
            Toast.LENGTH_LONG,
        ).show()
        shareZip(result.zipFile)
    }

    private fun shareZip(zip: java.io.File) {
        // 用 BuildConfig.APPLICATION_ID 而不是 packageName，避免 build flavor 加 .debug
        // 后缀时 authority 与 manifest 不一致。AndroidManifest 用的也是 ${applicationId}.fileprovider。
        // sample-eval 已经独立成模块，applicationId = com.amphion.asr.sample.eval，
        // 不需要在 authority 里再叠 .eval. 后缀。
        val authority = "${BuildConfig.APPLICATION_ID}.fileprovider"
        val uri: Uri = FileProvider.getUriForFile(this, authority, zip)
        val send = Intent(Intent.ACTION_SEND).apply {
            type = "application/zip"
            putExtra(Intent.EXTRA_STREAM, uri)
            putExtra(Intent.EXTRA_SUBJECT, getString(R.string.eval_export_share_subject))
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        startActivity(Intent.createChooser(send, getString(R.string.eval_export_share_chooser)))
    }

    // ----- 权限 -----

    private fun ensureRecordPermission() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            recordPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    // ----- UploadScanner.Listener（运行在 scanner 内部线程，需 post 到主线程更新 UI） -----

    override fun onScanStarted(total: Int) {
        mainHandler.post { refreshUploadStatus() }
    }

    override fun onItemDone(meta: RecordingMeta, result: HttpUploader.Result, remaining: Int) {
        mainHandler.post { refreshUploadStatus() }
    }

    override fun onScanFinished(stats: UploadScanner.Stats) {
        mainHandler.post {
            refreshUploadStatus()
            refreshList()
            Toast.makeText(
                this,
                getString(
                    R.string.eval_sync_done_fmt,
                    stats.uploaded, stats.duplicates, stats.retried, stats.failed,
                ),
                Toast.LENGTH_SHORT,
            ).show()
        }
    }

    companion object {
        /**
         * 官方 eval-collector 服务地址。提供"用官方服务器"按钮一键回填，
         * 避免测试员手抄 URL 出错。token 不在此提供（避免硬编码默认凭证到 apk）。
         *
         * 如需换 staging / prod，与 docs/eval/CLIENT_INTEGRATION.md §2 同步变更。
         */
        private const val OFFICIAL_SERVER_URL = "https://testdata.amphion.top"
    }
}
