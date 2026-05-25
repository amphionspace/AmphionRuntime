package com.amphion.asr.sample.eval

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.RadioGroup
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.Toolbar
import com.amphion.asr.AsrEngine
import com.amphion.asr.AsrSdk
import com.amphion.asr.LocalModel
import com.amphion.asr.ModelManager
import com.amphion.asr.sample.R
import com.amphion.asr.sample.eval.data.DeviceInfo
import com.amphion.asr.sample.eval.data.EnginePrefs
import com.amphion.asr.sample.eval.data.RecordingStore
import com.amphion.asr.sample.eval.data.SentenceRepository
import com.amphion.asr.sample.eval.data.TesterPrefs
import com.amphion.asr.sample.eval.data.UploadSettings
import com.amphion.asr.sample.eval.model.CustomSentence
import com.amphion.asr.sample.eval.model.EnvMeta
import com.amphion.asr.sample.eval.model.NoiseLevel
import com.amphion.asr.sample.eval.model.RecordingMeta
import com.amphion.asr.sample.eval.model.Sentence
import com.amphion.asr.sample.eval.model.UploadMeta
import com.amphion.asr.sample.eval.playback.AudioPlayer
import com.amphion.asr.sample.eval.upload.HttpUploader
import com.amphion.asr.sample.eval.upload.UploadScanner
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.UUID

/**
 * 单句录音页：
 * 1. 加载本地 ASR 引擎（按 sentence 所在 manifest.lang 选模型）
 * 2. 用户点击「开始录音」→ 创建 _temp 目录 + EvalRecorder + OnDeviceTranscriber
 * 3. 用户点击「停止录音」→ stop recorder → 生成 hypothesis → 算估算 WER → 落 meta.json
 * 4. atomic rename 到正式目录 → 触发一次 UploadScanner
 * 5. 保存后原地展示三件套：diff + 播放 + 估算 WER；用户可继续校对或下一句
 *
 * 不在此页直接列出"该句历史 attempts"（那是 SentenceDetailActivity 的职责）；
 * 此页面只关心"当前这次录音"。
 */
class RecordSentenceActivity : AppCompatActivity() {

    private lateinit var prefs: TesterPrefs
    private lateinit var settings: UploadSettings
    private lateinit var store: RecordingStore
    private lateinit var repo: SentenceRepository
    private lateinit var scanner: UploadScanner
    private lateinit var enginePrefs: EnginePrefs

    private lateinit var sentence: Sentence
    private lateinit var deviceMeta: com.amphion.asr.sample.eval.model.DeviceMeta

    private var engine: AsrEngine? = null
    private var modelDescriptor: LocalModel? = null

    /** Engine 状态机：与录音状态独立。引擎加载是异步的，UI 应明确反馈。 */
    private enum class EngineState { LOADING, READY, FAILED, NONE }
    private var engineState: EngineState = EngineState.LOADING

    private var recorder: EvalRecorder? = null
    private var transcriber: OnDeviceTranscriber? = null
    private val player = AudioPlayer(
        onError = { msg -> Toast.makeText(this, msg, Toast.LENGTH_SHORT).show() },
        onCompletion = { resetReplayButtonsText() },
    )

    private var currentTempDir: File? = null
    private var currentRecordingId: String? = null
    private var currentMeta: RecordingMeta? = null
    private var currentFinalAudioFile: File? = null

    private lateinit var tvReference: TextView
    private lateinit var etReference: EditText
    private lateinit var tvReferenceHint: TextView
    private lateinit var tvEngineName: TextView
    private lateinit var tvEngineState: TextView
    private lateinit var btnEngineSwitch: Button
    private lateinit var tvStatus: TextView
    private lateinit var cardHypothesis: View
    private lateinit var tvDiffRef: TextView
    private lateinit var tvDiffHyp: TextView
    private lateinit var tvWer: TextView
    private lateinit var btnReplay: Button
    private lateinit var btnReplayPending: Button
    private lateinit var btnMain: Button
    private lateinit var btnRetake: Button
    private lateinit var btnSaveNext: Button
    private lateinit var etLocation: EditText
    private lateinit var etNotes: EditText
    private lateinit var rgNoise: RadioGroup

    /**
     * IDLE → RECORDING → SAVED 是内置模式的全部状态机。
     *
     * 自定义模式多一个中间状态 PENDING_REFERENCE：audio 已 stop、hypothesis 已拿到，
     * 但 reference 还没校对，meta 和落盘都未发生。用户校对后点保存才进入 SAVED。
     */
    private enum class State { IDLE, RECORDING, PENDING_REFERENCE, SAVED }
    private var state: State = State.IDLE

    /** 自定义录音模式：先录后校对 reference。 */
    private var customMode: Boolean = false

    /** 自定义模式 PENDING_REFERENCE 阶段暂存的录音元数据。 */
    private data class PendingRecording(
        val tempDir: File,
        val recordingId: String,
        val hypothesis: String,
        val durationMs: Long,
        val gainDb: Float,
    )
    private var pendingRecording: PendingRecording? = null

    private val mainHandler = Handler(Looper.getMainLooper())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_record_sentence)

        val sentenceId = intent.getStringExtra(EXTRA_SENTENCE_ID)
        val isCustomRecording = intent.getBooleanExtra(EXTRA_CUSTOM_RECORDING, false)
        if (sentenceId.isNullOrEmpty() && !isCustomRecording) {
            finish()
            return
        }
        // 注意 customMode 仅当用「新建自由录音」入口进入时为 true。
        // 从 SentenceDetailActivity「再录一次」进入 custom 句子时仍然走 reference 锁定模式 —
        // 因为 detail 页的语义是「同一段 reference 多录几次」，让用户改 reference 会派生新 sentence_id 失去聚合。
        customMode = isCustomRecording

        prefs = TesterPrefs(this)
        settings = UploadSettings(this)
        store = RecordingStore(this)
        scanner = UploadScanner(store, settings)
        enginePrefs = EnginePrefs(this)
        deviceMeta = DeviceInfo.collect()

        repo = SentenceRepository.load(this)

        val toolbar = findViewById<Toolbar>(R.id.toolbar)
        setSupportActionBar(toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        toolbar.setNavigationOnClickListener { finish() }

        tvReference = findViewById(R.id.tv_reference)
        etReference = findViewById(R.id.et_reference)
        tvReferenceHint = findViewById(R.id.tv_reference_hint)
        tvEngineName = findViewById(R.id.tv_engine_name)
        tvEngineState = findViewById(R.id.tv_engine_state)
        btnEngineSwitch = findViewById(R.id.btn_engine_switch)
        tvStatus = findViewById(R.id.tv_status)
        cardHypothesis = findViewById(R.id.card_hypothesis)
        tvDiffRef = findViewById(R.id.tv_diff_ref)
        tvDiffHyp = findViewById(R.id.tv_diff_hyp)
        tvWer = findViewById(R.id.tv_wer)
        btnReplay = findViewById(R.id.btn_replay)
        btnReplayPending = findViewById(R.id.btn_replay_pending)
        btnMain = findViewById(R.id.btn_main)
        btnRetake = findViewById(R.id.btn_retake)
        btnSaveNext = findViewById(R.id.btn_save_next)
        etLocation = findViewById(R.id.et_location)
        etNotes = findViewById(R.id.et_notes)
        rgNoise = findViewById(R.id.rg_noise)

        btnMain.setOnClickListener { onMainButtonClick() }
        btnRetake.setOnClickListener { onRetakeClick() }
        btnSaveNext.setOnClickListener { onSaveAndNextClick() }
        btnReplay.setOnClickListener { onReplayClick() }
        btnReplayPending.setOnClickListener { onReplayPendingClick() }
        btnEngineSwitch.setOnClickListener { showEnginePickerDialog() }

        lifecycle.addObserver(player)
        renderEngineCard(null, EngineState.LOADING)
        loadInitialEngineAsync()

        val ok = when {
            isCustomRecording -> startCustomRecordingMode()
            !sentenceId.isNullOrEmpty() -> loadSentence(sentenceId)
            else -> false
        }
        if (!ok) finish()
    }

    /**
     * 切换到新句子并重置 UI。返回 false 表示找不到 sentence，调用方应 finish。
     *
     * 不重新加载 engine —— 这是把 next-sentence 复用同 Activity 的关键收益：
     * 75 句一气呵成时只首次 1-3s engine load，其余切换 < 50ms。
     *
     * 同时兼容 [CustomSentence.isCustomSentenceId]：custom_xxx 也走这里，前提是
     * 该 custom 句子至少录过一次（这样 EvalActivity 列表点击进来能复活历史 text）。
     * 没历史时调用方应改走 [loadCustomText]。
     */
    private fun loadSentence(sentenceId: String): Boolean {
        val s = repo.manifest.findSentence(sentenceId)
            ?: resolveCustomFromHistory(sentenceId)
            ?: return false
        applySentence(s)
        return true
    }

    /**
     * 从 RecordingStore 中已存在的 attempts 还原 custom sentence text。
     * 用于 EvalActivity 列表点击「已录过的 custom 句子」时，无需重新让用户输入 text。
     */
    private fun resolveCustomFromHistory(sentenceId: String): Sentence? {
        if (!CustomSentence.isCustomSentenceId(sentenceId)) return null
        val attempts = store.listAttempts(prefs.testerId(), sentenceId)
        val first = attempts.firstOrNull() ?: return null
        return Sentence(id = sentenceId, text = first.referenceText, categoryId = CustomSentence.CUSTOM_CATEGORY_ID)
    }

    /**
     * 自定义录音模式初始化：sentence 暂未确定，先准备空的占位，UI 显示提示语。
     * 真正的 sentence 在 [confirmCustomReference] 中按校对后的 text 派生。
     */
    private fun startCustomRecordingMode(): Boolean {
        sentence = Sentence(id = "__pending__", text = "", categoryId = CustomSentence.CUSTOM_CATEGORY_ID)
        supportActionBar?.title = getString(R.string.eval_record_title_custom)

        // 顶部句子卡片改为「提示」样式：不显示 reference，显示"录完后再填"
        tvReference.visibility = View.GONE
        etReference.visibility = View.GONE
        tvReferenceHint.visibility = View.VISIBLE
        tvReferenceHint.text = getString(R.string.eval_custom_idle_hint)
        btnSaveNext.text = getString(R.string.eval_record_btn_save_and_return)

        resetCommonUi()
        return true
    }

    private fun applySentence(s: Sentence) {
        sentence = s
        val isCustom = CustomSentence.isCustomSentenceId(s.id)
        supportActionBar?.title = if (isCustom) {
            getString(R.string.eval_record_title_custom)
        } else {
            getString(R.string.eval_record_title)
        }

        // 内置 / detail 回访 custom：reference 锁定，显示为只读 TextView
        tvReference.visibility = View.VISIBLE
        tvReference.text = s.text
        etReference.visibility = View.GONE
        tvReferenceHint.visibility = View.GONE

        btnSaveNext.text = if (isCustom) {
            getString(R.string.eval_record_btn_save_and_return)
        } else {
            getString(R.string.eval_record_btn_save_next)
        }
        resetCommonUi()
    }

    /** UI 与录音状态重置回 IDLE。两个入口（applySentence / startCustomRecordingMode）共用。 */
    private fun resetCommonUi() {
        state = State.IDLE
        cardHypothesis.visibility = View.GONE
        btnRetake.visibility = View.GONE
        btnSaveNext.visibility = View.GONE
        btnReplayPending.visibility = View.GONE
        btnReplayPending.text = getString(R.string.eval_custom_btn_replay)
        btnMain.text = getString(R.string.eval_record_btn_start)
        // 引擎正在加载时不放开录音按钮（避免没引擎也启录）
        btnMain.isEnabled = (engineState != EngineState.LOADING)
        tvStatus.text = getString(R.string.eval_record_status_idle)

        currentTempDir = null
        currentRecordingId = null
        currentMeta = null
        currentFinalAudioFile = null
        pendingRecording = null

        // env 表单保留上一句的内容（同一测试场景，地点 / 噪声等级通常一致），仅清空 notes
        etNotes.setText("")
        if (rgNoise.checkedRadioButtonId == -1) {
            rgNoise.check(R.id.rb_noise_low)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        recorder?.discard()
        transcriber?.close()
        engine?.close()
        scanner.shutdown()
        // currentTempDir 若未 finalize，丢弃；防止 _temp/ 目录残留
        currentTempDir?.let { store.discardTemp(it) }
        // PENDING_REFERENCE 中途退出（如用户按返回键放弃校对）：也丢弃 audio
        pendingRecording?.let { store.discardTemp(it.tempDir) }
    }

    // ----- 引擎加载（异步） -----

    /**
     * 选择初始引擎的策略（优先级从高到低）：
     * 1. EnginePrefs 持久化的「上次用的」
     * 2. manifest.lang 匹配的第一个
     * 3. 任意第一个本地模型
     * 4. 没有本地模型 → NONE 状态，仍允许录音但不出 hypothesis
     *
     * 进入前会先跑一次 [ModelImporter.importIfPresent]：sample 的设计是用户用
     * `adb push` 把模型推到 `externalFilesDir/asr-models-import/...`，由 ModelImporter
     * 一次性搬到 internal storage 后 ModelManager 才能看到。原本只在 MainActivity 触发，
     * LandingActivity → EvalActivity → RecordSentenceActivity 这条新路径完全绕过了它，
     * 用户会看到「无可用模型」而模型其实就躺在外部目录。在引擎发现路径上 import 一次
     * 是最局部、最 idempotent 的修复（importIfPresent 自带 skip existing 判断）。
     */
    private fun loadInitialEngineAsync() {
        Thread({
            try {
                val imported = com.amphion.asr.sample.ModelImporter(applicationContext).importIfPresent()
                if (imported.isNotEmpty()) {
                    Log.i(TAG, "imported ${imported.size} model version(s) from external storage")
                }
            } catch (t: Throwable) {
                Log.w(TAG, "ModelImporter.importIfPresent failed: ${t.message}")
            }
            val mm = ModelManager(applicationContext)
            val locals = mm.listLocal()
            val chosen = pickInitialModel(locals)
            mainHandler.post {
                if (chosen == null) {
                    engineState = EngineState.NONE
                    renderEngineCard(null, EngineState.NONE)
                    Toast.makeText(this, R.string.eval_engine_unavailable, Toast.LENGTH_SHORT).show()
                } else {
                    loadEngineAsync(chosen)
                }
            }
        }, "eval-engine-discover").apply { isDaemon = true; start() }
    }

    private fun pickInitialModel(locals: List<LocalModel>): LocalModel? {
        if (locals.isEmpty()) return null
        val lastId = enginePrefs.lastModelId()
        val lastVer = enginePrefs.lastVersion()
        val byPref = if (lastId != null) {
            locals.firstOrNull { it.modelId == lastId && (lastVer == null || it.version == lastVer) }
        } else null
        return byPref
            ?: locals.firstOrNull { it.lang == repo.manifest.lang }
            ?: locals.firstOrNull()
    }

    /**
     * 加载指定模型；UI 立即进入 LOADING 状态，加载完成后切换 READY/FAILED。
     * 切换引擎时调用方应先 close 旧 engine（[onPickModel] 会处理）。
     */
    private fun loadEngineAsync(model: LocalModel) {
        modelDescriptor = model
        engineState = EngineState.LOADING
        renderEngineCard(model, EngineState.LOADING)
        // 加载期间禁用录音按钮，避免引擎未 ready 时启动录音造成 hypothesis 为空
        btnMain.isEnabled = false

        Thread({
            val cfg = try {
                com.amphion.asr.AsrConfig.Builder(model.dir)
                    .numThreads(2)
                    .enableEndpoint(true)
                    .build()
            } catch (t: Throwable) {
                Log.w(TAG, "AsrConfig build failed: ${t.message}")
                mainHandler.post { onEngineLoadFailed(model) }
                return@Thread
            }
            val newEngine = try {
                AsrSdk.init(applicationContext)
                AsrEngine(cfg)
            } catch (t: Throwable) {
                Log.w(TAG, "AsrEngine create failed: ${t.message}")
                null
            }
            mainHandler.post {
                if (newEngine == null) {
                    onEngineLoadFailed(model)
                } else {
                    engine = newEngine
                    engineState = EngineState.READY
                    enginePrefs.set(model.modelId, model.version)
                    renderEngineCard(model, EngineState.READY)
                    restoreMainButtonAfterEngine()
                }
            }
        }, "eval-engine-load").apply { isDaemon = true; start() }
    }

    private fun onEngineLoadFailed(model: LocalModel) {
        engineState = EngineState.FAILED
        renderEngineCard(model, EngineState.FAILED)
        // 加载失败仍允许录音（只是 hypothesis 为空）
        restoreMainButtonAfterEngine()
    }

    /**
     * Engine 加载完成（READY 或 FAILED）后，按当前录音状态恢复 btnMain：
     * - RECORDING：按钮文案应为「停止」，仍 enable
     * - PENDING_REFERENCE：「重录」，enable
     * - IDLE / SAVED：「开始录音」，enable
     */
    private fun restoreMainButtonAfterEngine() {
        btnMain.isEnabled = true
    }

    private fun renderEngineCard(model: LocalModel?, st: EngineState) {
        tvEngineName.text = if (model != null) {
            friendlyEngineName(model)
        } else {
            getString(R.string.eval_engine_name_none)
        }
        val (text, color) = when (st) {
            EngineState.LOADING -> getString(R.string.eval_engine_state_loading) to R.color.eval_state_pending
            EngineState.READY -> getString(R.string.eval_engine_state_ready) to R.color.eval_state_uploaded
            EngineState.FAILED -> getString(R.string.eval_engine_state_failed) to R.color.eval_state_failed
            EngineState.NONE -> getString(R.string.eval_engine_state_none) to R.color.eval_state_failed
        }
        tvEngineState.text = text
        tvEngineState.setTextColor(getColor(color))
        btnEngineSwitch.isEnabled = (st != EngineState.LOADING)
    }

    /**
     * 把 LocalModel 渲染成测试员友好的名字：
     * - 已知 lang → 「中英」「粤英」「中文」「英文」
     * - 未知 lang → 不暴露 modelId/version 这种工程内部串，统一为「其他模型」
     *
     * 工程信息（modelId / version）仍然落到 meta.json，给后台 by_model 报告用。
     */
    private fun friendlyEngineName(model: LocalModel): String = when (model.lang) {
        "zh-en" -> getString(R.string.lang_zh_en)
        "yue-en" -> getString(R.string.lang_yue_en)
        "zh" -> getString(R.string.eval_engine_lang_zh)
        "en" -> getString(R.string.eval_engine_lang_en)
        else -> getString(R.string.eval_engine_lang_other)
    }

    private fun showEnginePickerDialog() {
        val mm = ModelManager(applicationContext)
        val locals = mm.listLocal()
        if (locals.isEmpty()) {
            androidx.appcompat.app.AlertDialog.Builder(this)
                .setTitle(R.string.eval_engine_dialog_title)
                .setMessage(R.string.eval_engine_dialog_empty)
                .setPositiveButton(android.R.string.ok, null)
                .show()
            return
        }
        // 按 lang 去重：同 lang 多 version 取第一个；测试员不需要关心版本号。
        // 如果未来真的需要 A/B 同 lang 不同 version，再加「高级模式」入口。
        val grouped = locals.groupBy { it.lang ?: "" }
        val display = grouped.map { (_, list) -> list.first() }
        val items = display.map { friendlyEngineName(it) }.toTypedArray()
        val currentIdx = display.indexOfFirst {
            it.modelId == modelDescriptor?.modelId && it.version == modelDescriptor?.version
        }
        androidx.appcompat.app.AlertDialog.Builder(this)
            .setTitle(R.string.eval_engine_dialog_title)
            .setSingleChoiceItems(items, currentIdx) { dlg, which ->
                dlg.dismiss()
                onPickModel(display[which])
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun onPickModel(model: LocalModel) {
        if (model.modelId == modelDescriptor?.modelId && model.version == modelDescriptor?.version
            && engineState == EngineState.READY) return
        // 切换引擎前 close 旧的，避免 native 资源泄漏
        engine?.close()
        engine = null
        transcriber?.close()
        transcriber = null
        loadEngineAsync(model)
    }

    // ----- 主按钮：开始 / 停止 -----

    private fun onMainButtonClick() = when (state) {
        State.IDLE -> startRecording()
        State.RECORDING -> stopRecording()
        State.PENDING_REFERENCE -> discardPendingAndRetake()
        State.SAVED -> {
            // 二次点击主按钮 = 重录
            onRetakeClick()
        }
    }

    private fun startRecording() {
        // 引擎加载中不允许启动；其他状态（READY/FAILED/NONE）都允许（只是 hypothesis 可能为空）
        if (engineState == EngineState.LOADING) {
            Toast.makeText(this, R.string.eval_engine_busy_hint, Toast.LENGTH_SHORT).show()
            return
        }
        val recordingId = UUID.randomUUID().toString()
        val tempDir = store.newTempDir(recordingId)
        val audioFile = File(tempDir, RecordingStore.AUDIO_FILE)
        val t = engine?.let { OnDeviceTranscriber.wrap(it) }
        val rec = EvalRecorder.create(
            audioFile = audioFile,
            sampleRate = 16000,
            gainDb = 10f,
            transcriber = t,
            onWaveformLevel = null,
            onError = { msg ->
                mainHandler.post {
                    tvStatus.text = getString(R.string.eval_record_error_fmt, msg)
                }
            },
        ) ?: run {
            Toast.makeText(this, "录音初始化失败", Toast.LENGTH_SHORT).show()
            store.discardTemp(tempDir)
            return
        }

        currentTempDir = tempDir
        currentRecordingId = recordingId
        currentFinalAudioFile = null
        transcriber = t
        recorder = rec
        rec.start()

        state = State.RECORDING
        cardHypothesis.visibility = View.GONE
        tvStatus.text = getString(R.string.eval_record_status_recording)
        btnMain.text = getString(R.string.eval_record_btn_stop)
        btnRetake.visibility = View.GONE
        btnSaveNext.visibility = View.GONE
    }

    private fun stopRecording() {
        val rec = recorder ?: return
        rec.stop()
        recorder = null
        val tempDir = currentTempDir ?: return
        val t = transcriber

        // env 表单需要在主线程读取，先 snapshot 到局部变量
        val envSnapshot = readEnvFromUi()
        val recordingId = currentRecordingId!!

        // worker 等 transcriber 异步 final 收到（最多等 1.5s）+ 内置模式下的 finalize IO
        Thread({
            val waitMs = if (t != null) 1500L else 0L
            if (waitMs > 0) {
                val start = System.currentTimeMillis()
                while (System.currentTimeMillis() - start < waitMs) {
                    val h = t!!.finalHypothesis()
                    if (h.isNotEmpty()) break
                    Thread.sleep(50)
                }
            }
            val hypothesis = t?.finalHypothesis().orEmpty()
            t?.close()
            transcriber = null

            if (customMode) {
                // 自定义模式：暂存 audio + hypothesis，不做 IO。让用户校对 reference 后再 finalize
                mainHandler.post {
                    pendingRecording = PendingRecording(
                        tempDir = tempDir,
                        recordingId = recordingId,
                        hypothesis = hypothesis,
                        durationMs = rec.durationMs,
                        gainDb = rec.gainDb,
                    )
                    renderPendingReferenceState(hypothesis)
                }
            } else {
                // 内置模式：worker 上做完 meta + finalize 的 IO，再 post UI
                val attempts = store.listAttempts(prefs.testerId(), sentence.id)
                val attemptIndex = attempts.size + 1
                val wer = if (hypothesis.isNotEmpty()) {
                    DeviceWerEstimator.estimate(sentence.text, hypothesis)
                } else null
                val meta = buildMeta(
                    recordingId = recordingId,
                    attemptIndex = attemptIndex,
                    hypothesis = hypothesis.ifEmpty { null },
                    wer = wer,
                    durationMs = rec.durationMs,
                    gainDb = rec.gainDb,
                    env = envSnapshot,
                )
                persistMetaAndFinalize(tempDir, meta, hypothesis)
                mainHandler.post {
                    renderSavedState(meta)
                    triggerAutoUpload()
                }
            }
        }, "eval-finalize").apply { isDaemon = true; start() }

        tvStatus.text = "正在生成识别结果…"
        btnMain.isEnabled = false
    }

    /**
     * 自定义模式 stop 后：进入校对态。
     * - reference 输入框 pre-fill 识别结果
     * - 不显示「准确率」（避免暗示「识别得很准」，引诱测试员直接保存假数据）
     * - 主按钮 → 重录；保存并返回按钮 → confirmCustomReference
     */
    private fun renderPendingReferenceState(hypothesis: String) {
        state = State.PENDING_REFERENCE

        tvReference.visibility = View.GONE
        etReference.visibility = View.VISIBLE
        etReference.setText(hypothesis)
        etReference.setSelection(etReference.text.length)
        tvReferenceHint.visibility = View.VISIBLE
        tvReferenceHint.text = getString(R.string.eval_custom_pending_hint)

        cardHypothesis.visibility = View.GONE

        // 校对阶段的回放：让用户对照 audio 校对识别结果，比单看文字可靠得多
        btnReplayPending.visibility = View.VISIBLE
        btnReplayPending.text = getString(R.string.eval_custom_btn_replay)

        btnMain.isEnabled = true
        btnMain.text = getString(R.string.eval_record_btn_retake)
        btnRetake.visibility = View.GONE
        btnSaveNext.visibility = View.VISIBLE
        btnSaveNext.text = getString(R.string.eval_custom_btn_save)
        tvStatus.text = ""
    }

    private fun persistMetaAndFinalize(tempDir: File, meta: RecordingMeta, hypothesis: String) {
        // 1. 写入 hypothesis.txt（可选）
        if (hypothesis.isNotEmpty()) {
            try {
                File(tempDir, RecordingStore.HYPOTHESIS_FILE).writeText(hypothesis, Charsets.UTF_8)
            } catch (t: Throwable) {
                Log.w(TAG, "write hypothesis failed: ${t.message}")
            }
        }
        // 2. 写入 meta.json（finalized=true）
        try {
            File(tempDir, RecordingStore.META_FILE).writeText(meta.toJsonString(), Charsets.UTF_8)
        } catch (t: Throwable) {
            Log.w(TAG, "write meta failed: ${t.message}")
        }
        // 3. atomic rename 到正式目录
        val finalDir = store.finalize(
            tempDir = tempDir,
            testerId = meta.testerId,
            sentenceId = meta.sentenceId,
            recordingId = meta.recordingId,
        )
        currentTempDir = null
        if (finalDir == null) {
            mainHandler.post {
                Toast.makeText(this, "保存失败：rename 异常", Toast.LENGTH_SHORT).show()
            }
            return
        }
        currentMeta = meta
        currentFinalAudioFile = File(finalDir, RecordingStore.AUDIO_FILE)
    }

    // ----- 渲染保存后的"三件套" -----

    private fun renderSavedState(meta: RecordingMeta) {
        state = State.SAVED
        btnMain.isEnabled = true
        btnMain.text = getString(R.string.eval_record_btn_start)
        btnRetake.visibility = View.VISIBLE
        btnSaveNext.visibility = View.VISIBLE
        tvStatus.text = getString(R.string.eval_record_status_saved)

        cardHypothesis.visibility = View.VISIBLE
        val ref = sentence.text
        val hyp = meta.onDeviceHypothesis.orEmpty()
        tvDiffRef.text = DiffRenderer.renderReference(this, ref, hyp)
        tvDiffHyp.text = DiffRenderer.renderHypothesis(this, ref, hyp)
        tvWer.text = meta.onDeviceWerEstimate?.let { DeviceWerEstimator.formatPercent(it) } ?: "—"
    }

    private fun triggerAutoUpload() {
        if (settings.isConfigured() && settings.autoUploadEnabled()) {
            scanner.trigger(includeFailed = false)
        }
    }

    private fun onRetakeClick() {
        // 重录：当前 attempt 已保存，下一次 startRecording 会建新的 _temp 目录。
        // 此处仅 UI 重置回 IDLE。
        state = State.IDLE
        cardHypothesis.visibility = View.GONE
        btnRetake.visibility = View.GONE
        btnSaveNext.visibility = View.GONE
        btnMain.text = getString(R.string.eval_record_btn_start)
        tvStatus.text = getString(R.string.eval_record_status_idle)
        startRecording()
    }

    private fun onSaveAndNextClick() {
        // PENDING_REFERENCE：先 finalize 校对后的录音，再 finish
        if (state == State.PENDING_REFERENCE) {
            confirmCustomReference()
            return
        }
        // SAVED 状态：
        // - custom 模式：保存已完成，直接 finish 回 EvalActivity
        if (customMode || CustomSentence.isCustomSentenceId(sentence.id)) {
            finish()
            return
        }
        // 内置集模式：自动跳下一句。复用同 Activity（不重建），engine 不重新加载。
        val all = repo.manifest.allSentences().toList()
        val idx = all.indexOfFirst { it.id == sentence.id }
        val next = if (idx >= 0 && idx + 1 < all.size) all[idx + 1] else null
        if (next != null) {
            // 主动停掉当前的播放（避免 next 句子加载时旧句子还在响）
            player.release()
            loadSentence(next.id)
        } else {
            finish()
        }
    }

    /**
     * 自定义模式 PENDING_REFERENCE → SAVED：
     * 1. 校验 reference 非空
     * 2. 按 reference text 派生 sentence_id（CustomSentence.deriveId）
     * 3. 算 wer estimate（reference 已经校对，可信）
     * 4. 构造 meta + finalize 落盘（worker thread）
     * 5. 触发自动上传
     */
    private fun confirmCustomReference() {
        val pending = pendingRecording ?: return
        val rawRef = etReference.text.toString()
        val refText = CustomSentence.normalize(rawRef)
        if (refText.isEmpty()) {
            Toast.makeText(this, R.string.eval_custom_save_empty, Toast.LENGTH_SHORT).show()
            return
        }
        // 锁定 sentence：以校对后的 reference 派生 id
        sentence = CustomSentence.adHoc(refText)
        pendingRecording = null

        val envSnapshot = readEnvFromUi()
        btnSaveNext.isEnabled = false
        btnMain.isEnabled = false

        Thread({
            val attempts = store.listAttempts(prefs.testerId(), sentence.id)
            val attemptIndex = attempts.size + 1
            val hyp = pending.hypothesis
            val wer = if (hyp.isNotEmpty()) {
                DeviceWerEstimator.estimate(refText, hyp)
            } else null
            val meta = buildMeta(
                recordingId = pending.recordingId,
                attemptIndex = attemptIndex,
                hypothesis = hyp.ifEmpty { null },
                wer = wer,
                durationMs = pending.durationMs,
                gainDb = pending.gainDb,
                env = envSnapshot,
            )
            persistMetaAndFinalize(pending.tempDir, meta, hyp)
            mainHandler.post {
                triggerAutoUpload()
                finish()
            }
        }, "eval-custom-confirm").apply { isDaemon = true; start() }
    }

    /** PENDING_REFERENCE 状态点主按钮 → 丢弃当前 audio，回到 IDLE。 */
    private fun discardPendingAndRetake() {
        val pending = pendingRecording
        if (pending != null) {
            store.discardTemp(pending.tempDir)
            pendingRecording = null
        }
        // 重置回 custom 入口的初始 UI
        if (customMode) {
            startCustomRecordingMode()
        } else {
            resetCommonUi()
        }
        startRecording()
    }

    private fun onReplayClick() {
        val f = currentFinalAudioFile ?: return
        if (!f.isFile) return
        if (player.isPlaying) {
            player.pause()
            btnReplay.text = getString(R.string.eval_record_btn_replay)
        } else {
            player.play(f)
        }
    }

    /**
     * 校对阶段回放：audio 还在 _temp，不是 finalize 后的位置。
     * 文件存在性必然为真（录音 stop 时已 flush），但仍 defensive check。
     */
    private fun onReplayPendingClick() {
        val pending = pendingRecording ?: return
        val f = File(pending.tempDir, RecordingStore.AUDIO_FILE)
        if (!f.isFile) return
        if (player.isPlaying) {
            player.pause()
            btnReplayPending.text = getString(R.string.eval_custom_btn_replay)
        } else {
            player.play(f)
            btnReplayPending.text = getString(R.string.eval_custom_btn_replay_stop)
        }
    }

    /** 播放结束后两个回放按钮都恢复初始文案（只有当前 visible 的那个用户能看到）。 */
    private fun resetReplayButtonsText() {
        btnReplay.text = getString(R.string.eval_record_btn_replay)
        btnReplayPending.text = getString(R.string.eval_custom_btn_replay)
    }

    // ----- 构造 meta -----

    private fun buildMeta(
        recordingId: String,
        attemptIndex: Int,
        hypothesis: String?,
        wer: Double?,
        durationMs: Long,
        gainDb: Float,
        env: EnvMeta,
    ): RecordingMeta = RecordingMeta(
        finalized = true,
        recordingId = recordingId,
        attemptIndex = attemptIndex,
        sentenceId = sentence.id,
        categoryId = sentence.categoryId,
        referenceText = sentence.text,
        testerId = prefs.testerId(),
        testerNickname = prefs.nickname(),
        device = deviceMeta,
        appVersion = DeviceInfo.appVersion(this),
        sdkVersion = DeviceInfo.sdkVersion(),
        modelId = modelDescriptor?.modelId,
        modelVersion = modelDescriptor?.version,
        recordedAt = nowIso(),
        durationMs = durationMs,
        sampleRate = 16000,
        gainDb = gainDb,
        audioSource = "VOICE_RECOGNITION",
        env = env,
        onDeviceHypothesis = hypothesis,
        onDeviceWerEstimate = wer,
        upload = UploadMeta(state = UploadMeta.State.PENDING),
    )

    private fun readEnvFromUi(): EnvMeta {
        val noise = when (rgNoise.checkedRadioButtonId) {
            R.id.rb_noise_silent -> NoiseLevel.SILENT.token
            R.id.rb_noise_low -> NoiseLevel.LOW.token
            R.id.rb_noise_medium -> NoiseLevel.MEDIUM.token
            R.id.rb_noise_high -> NoiseLevel.HIGH.token
            else -> NoiseLevel.UNSPECIFIED.token
        }
        return EnvMeta(
            location = etLocation.text.toString().trim(),
            noiseLevel = noise,
            noiseLevelDbEstimate = null,
            notes = etNotes.text.toString().trim(),
        )
    }

    companion object {
        private const val TAG = "RecordSentenceActivity"
        private const val EXTRA_SENTENCE_ID = "sentence_id"
        private const val EXTRA_CUSTOM_RECORDING = "custom_recording"

        /** 内置测试集中的句子；或从 SentenceDetailActivity「再录一次」回到 custom 句子（reference 锁定）。 */
        fun intent(ctx: Context, sentenceId: String): Intent =
            Intent(ctx, RecordSentenceActivity::class.java).apply {
                putExtra(EXTRA_SENTENCE_ID, sentenceId)
            }

        /**
         * 自由录音入口：reference 未知，先录后校对。
         * sentence_id 在用户保存时按校对后的 reference text 派生（[CustomSentence.deriveId]）。
         */
        fun intentForCustomRecording(ctx: Context): Intent =
            Intent(ctx, RecordSentenceActivity::class.java).apply {
                putExtra(EXTRA_CUSTOM_RECORDING, true)
            }

        private val ISO_FMT = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }

        fun nowIso(): String = ISO_FMT.format(Date())
    }
}
