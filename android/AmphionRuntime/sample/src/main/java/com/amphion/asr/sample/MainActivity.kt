package com.amphion.asr.sample

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.Button
import android.widget.ProgressBar
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.SwitchCompat
import androidx.core.content.ContextCompat
import com.amphion.asr.AsrCallback
import com.amphion.asr.AsrConfig
import com.amphion.asr.AsrEngine
import com.amphion.asr.AsrError
import com.amphion.asr.AsrLogLevel
import com.amphion.asr.AsrSdk
import com.amphion.asr.AsrSdkOptions
import com.amphion.asr.AsrSession
import com.amphion.asr.LocalModel
import com.amphion.asr.ModelDownloadCallback
import com.amphion.asr.ModelManager
import com.amphion.asr.PunctuationConfig
import com.amphion.asr.PunctuationEngine
import com.amphion.asr.WeitnConfig
import com.amphion.asr.WeitnEngine
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger
import kotlin.math.abs
import kotlin.math.max

/**
 * 单 Activity Sample：
 *  - 启动时扫描本地模型，按 manifest.json 的 `lang` 字段把「中英 / 粤英」绑定到顶部 RadioGroup
 *  - 默认语言（优先中英，否则粤英）加载 engine 后允许 点击开始 / 再次点击停止 的常驻监听模式
 *  - 切换 RadioGroup 时会自动停掉当前监听 + close 旧 engine + 用对应 modelDir 重建
 *  - 期间 SDK 内部 endpoint 触发会自动 emit final 并自动 reset 进入下一句，
 *    不会出现「英文短句 endpoint 后 final 为空」的边界
 *  - partial 文本随时刷新；final 文本累计追加显示
 *
 * 与"按住说话"的临时短流模式相比，本模式：
 *  - engine + session 均常驻，每次 endpoint 不重建 stream
 *  - 录音线程不断送 PCM，short utterance 也会被自然累计到 chunk
 */
class MainActivity : AppCompatActivity() {

    private companion object {
        /** manifest.json `lang` 约定值：中英混合。 */
        const val LANG_ZH_EN = "zh-en"

        /** manifest.json `lang` 约定值：粤英混合。 */
        const val LANG_YUE_EN = "yue-en"

        /** 每个 100ms PCM 批次拆成几个子帧喂 waveform（4 = 25ms 一根条）。 */
        const val WAVEFORM_FRAMES_PER_BATCH = 4
    }

    // ----------- 替换为你自己的服务端 manifest.json -----------
    // 仅当本地完全没有任何模型时才会走这条在线下载分支。多语言 demo 推荐直接用
    // tools/asr/00_push_my_model.sh 把两份模型分别 push 到设备。
    private val manifestUrl: String = "https://your-cdn.example.com/asr/zh-en/1.0.0/manifest.json"

    private lateinit var btnTalk: Button
    private lateinit var tvPartial: TextView
    private lateinit var tvFinal: TextView
    private lateinit var tvStatus: TextView
    private lateinit var tvLoadingHint: TextView
    private lateinit var progress: ProgressBar
    private lateinit var rgLang: RadioGroup
    private lateinit var rbZhEn: RadioButton
    private lateinit var rbYueEn: RadioButton
    private lateinit var swItn: SwitchCompat
    private lateinit var swPunct: SwitchCompat
    private lateinit var waveform: WaveformView

    private val mainHandler: Handler by lazy { Handler(Looper.getMainLooper()) }

    /**
     * 单线程串行 ASR engine 加载 / 关闭 executor。
     * - 串行：sherpa-onnx native init 占内存大，避免并发加载。
     * - 与 [punctExec] 分开：punct 任务是高频小推理（20-100ms），engine 加载是 1-3s 大动作。
     */
    private val asrLoadExec: ExecutorService = Executors.newSingleThreadExecutor { r ->
        Thread(r, "amphion-asr-load").apply { isDaemon = true }
    }

    /**
     * 每次"切换/加载 engine"递增一次；后台加载完成后通过它判断结果是否还有效，
     * 若期间用户又点了新语言，则当前结果作废并 close。
     */
    private val asrLoadGeneration = AtomicInteger(0)

    private var engine: AsrEngine? = null
    private var session: AsrSession? = null
    private var recorder: AudioRecorder? = null
    private var recorderDump: SessionRecorder? = null
    private var modelDir: File? = null
    private var lastDumpDir: File? = null

    /**
     * WeText ITN FST 路径（tagger + verbalizer）；external 未 push 且 internal 也没旧副本时
     * 为 null，对应 sw_itn 灰禁。由 [WeitnAssetInstaller.installOrLocate] 在
     * [installWeitnAsync] 中异步填回。
     */
    @Volatile
    private var weitnAssets: WeitnAssetInstaller.Installed? = null

    /**
     * WeText ITN 引擎；仅在 [swItn] 真正打开时 lazy 创建，关闭时 release 释放 native
     * FST 内存。所有读写都走 [weitnLock] 串行化。
     */
    private var weitnEngine: WeitnEngine? = null
    private val weitnLock = Any()

    /**
     * 单线程串行执行器：
     *  - 异步装载 WeText fst / 创建 WeitnEngine
     *  - 异步对 final 文本做 normalize（FST Compose，单次约 1-10 ms）
     */
    private var weitnExec: java.util.concurrent.ExecutorService? = null

    /**
     * sw_itn 自动开启状态：sw_itn 行 UI 已默认显示，但首次资源就绪时由
     * [maybeAutoEnableWeitn] 自动开一次；不管首次结果成功/失败都置 true，避免
     * install/startEngine 等钩子反复重试。
     */
    @Volatile
    private var weitnAutoEnableTried: Boolean = false

    /**
     * 标点模型文件路径；external 未 push 且 internal 也没旧副本时为 null，对应 Switch 灰禁。
     * 由 [PunctModelInstaller.installOrLocate] 在 [installPunctAsync] 中异步填回。
     */
    @Volatile
    private var punctModelFile: File? = null

    /**
     * 标点引擎；仅在 [swPunct] 真正打开时 lazy 创建，关闭时 release 释放 ~70 MB 内存。
     * 所有读写都走 [punctLock] 串行化，避免与 [punctExec] 竞态。
     */
    private var punctEngine: PunctuationEngine? = null
    private val punctLock = Any()

    /**
     * 单线程串行执行器：
     *  - 异步装载标点模型 / 创建 PunctuationEngine
     *  - 异步对 final 文本做 addPunctuation（推理 20-100 ms）
     * 用单线程是为了避免多个 final 同时争抢 native 推理；执行器在 onDestroy 时 shutdownNow。
     */
    private var punctExec: ExecutorService? = null

    /** 给每条 final 行分配的递增 id，标点异步回来时按这个 id 找到原行做替换。 */
    private val finalLineIdSeq = AtomicInteger(0)

    /**
     * 标点自动开启状态：UI 上 sw_punct 已经被隐藏，启动后由 [maybeAutoEnablePunct] 在
     * punctModelFile + engine 都就绪时自动开一次；不管首次结果成功/失败都置 true，
     * 避免在 onPunctSwitchChanged 失败回滚后被 install/startEngine 等钩子反复重试。
     */
    @Volatile
    private var punctAutoEnableTried: Boolean = false

    /** 按 manifest.lang 索引的本地模型；同一 lang 出现多个版本时取第一个。 */
    private var localByLang: Map<String, LocalModel> = emptyMap()

    /** 当前生效的语言（与 RadioGroup 选中项一致）；尚未加载或加载失败时为 null。 */
    private var currentLang: String? = null

    @Volatile
    private var listening: Boolean = false

    /**
     * Final 文本按行维护：每段 final 用 (id, text) 表示，回放时 join("\n")。
     * 这样标点异步回来后可以按 id 替换那一行（而不必清空整段重排）。
     */
    private val finalLines: MutableList<FinalLine> = ArrayList()

    private val recordPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            ensureModel()
        } else {
            toast("没有录音权限，无法识别")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        btnTalk = findViewById(R.id.btn_talk)
        tvPartial = findViewById(R.id.tv_partial)
        tvFinal = findViewById(R.id.tv_final)
        tvStatus = findViewById(R.id.tv_status)
        tvLoadingHint = findViewById(R.id.tv_loading_hint)
        progress = findViewById(R.id.progress)
        rgLang = findViewById(R.id.rg_lang)
        rbZhEn = findViewById(R.id.rb_zh_en)
        rbYueEn = findViewById(R.id.rb_yue_en)
        swItn = findViewById(R.id.sw_itn)
        swPunct = findViewById(R.id.sw_punct)
        waveform = findViewById(R.id.waveform)

        // 调试期把 SDK 日志打到 INFO，方便 logcat 看到 native 加载 / 错误码
        AsrSdk.init(applicationContext, AsrSdkOptions(logLevel = AsrLogLevel.INFO))

        btnTalk.isEnabled = false
        setTalkButtonRecording(false)
        btnTalk.setOnClickListener { onTalkButtonClick() }

        // 模型扫描完成前 RadioButton 全部禁用，避免 mockup 点击
        rbZhEn.isEnabled = false
        rbYueEn.isEnabled = false

        // WeText ITN 初始化：UI 上 Switch 默认关；fst 路径异步定位（external -> internal 拷贝可能数百毫秒）
        // 真正的 WeitnEngine 仅在用户首次打开 Switch / [maybeAutoEnableWeitn] 自动开时 lazy create
        swItn.isChecked = false
        swItn.isEnabled = false
        swItn.setOnCheckedChangeListener { _, checked -> onWeitnSwitchChanged(checked) }
        installWeitnAsync()

        // 标点初始化：UI 上 Switch 默认关；模型路径异步定位（external -> internal 拷贝可能 1-2 秒）
        // 真正的 PunctuationEngine 仅在用户首次打开 Switch 时 lazy create，避免空跑 70 MB 内存
        swPunct.isChecked = false
        swPunct.isEnabled = false
        swPunct.setOnCheckedChangeListener { _, checked -> onPunctSwitchChanged(checked) }
        installPunctAsync()

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            recordPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        } else {
            ensureModel()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        stopListening()
        // 让后台 engine load 任务作废：generation 提升后即使有 task 跑完也会丢弃结果
        asrLoadGeneration.incrementAndGet()
        asrLoadExec.shutdownNow()
        engine?.close()
        engine = null
        // ITN / 标点都持有 native 句柄，必须先关再 SDK.release
        synchronized(weitnLock) {
            weitnEngine?.close()
            weitnEngine = null
        }
        weitnExec?.shutdownNow()
        weitnExec = null
        synchronized(punctLock) {
            punctEngine?.close()
            punctEngine = null
        }
        punctExec?.shutdownNow()
        punctExec = null
        AsrSdk.release()
    }

    // ----------- 模型扫描 / RadioGroup 初始化 -----------

    private fun ensureModel() {
        setStatus("准备模型…")
        progress.visibility = android.view.View.VISIBLE
        progress.isIndeterminate = true

        // demo / 调试：先把外部存储的待导入模型迁移到 filesDir
        val imported = ModelImporter(this).importIfPresent()
        if (imported.isNotEmpty()) {
            setStatus("已从外部存储导入 ${imported.size} 个模型版本")
        }

        val mm = ModelManager(this)
        val all = mm.listLocal()

        // 同 lang 多版本取第一个；过滤掉 lang 为 null 的（manifest 缺该字段）
        localByLang = all
            .filter { !it.lang.isNullOrBlank() }
            .groupBy { it.lang!! }
            .mapValues { (_, list) -> list.first() }

        rbZhEn.isEnabled = localByLang.containsKey(LANG_ZH_EN)
        rbYueEn.isEnabled = localByLang.containsKey(LANG_YUE_EN)

        if (localByLang.isEmpty()) {
            if (all.isEmpty()) {
                showNoModelHint()
                return
            }
            // 有本地模型但都没有 lang 字段：兜底用第一个加载，RadioGroup 仍然灰着
            val fallback = all.first()
            setStatus(getString(R.string.status_no_lang_model))
            currentLang = null
            modelDir = fallback.dir
            // 主动断开 listener 后清掉选中态，防止后续 setOnCheckedChangeListener 时被误触发
            rgLang.setOnCheckedChangeListener(null)
            rgLang.clearCheck()
            startEngineForDir(fallback.dir)
            return
        }

        // 默认语言：优先 zh-en，否则 yue-en（哪个有就选哪个）
        val defaultLang = if (localByLang.containsKey(LANG_ZH_EN)) LANG_ZH_EN else LANG_YUE_EN

        // 先在不带 listener 的状态下 check 默认 RadioButton，避免初始化触发 switchToLang
        rgLang.setOnCheckedChangeListener(null)
        rgLang.check(radioIdForLang(defaultLang))
        loadEngineForLang(defaultLang)

        rgLang.setOnCheckedChangeListener { _, checkedId ->
            val newLang = langForRadioId(checkedId) ?: return@setOnCheckedChangeListener
            if (newLang == currentLang) return@setOnCheckedChangeListener
            switchToLang(newLang)
        }
    }

    /** 设备上完全没有任何本地模型时的提示 / 在线下载分支。 */
    private fun showNoModelHint() {
        progress.visibility = android.view.View.GONE
        if (manifestUrl.contains("your-cdn.example.com")) {
            setStatus(
                "没找到本地模型。\n\n" +
                "demo 双模型 push：\n" +
                "  bash tools/asr/00_push_my_model.sh \\\n" +
                "    --src tools/asr/demo-model/zipformer_L_zh_en \\\n" +
                "    --id  amphion-zh-en-streaming_large_crctc_full_lid_musan_traffic_v3_fix \\\n" +
                "    --version 1.0.0-iter-140000-avg-1-chunk-32-left-256\n" +
                "  bash tools/asr/00_push_my_model.sh \\\n" +
                "    --src tools/asr/demo-model/zipformer_L_yue_en \\\n" +
                "    --id  amphion-yue-en-streaming_large_crctc_lid_musan_traffic_v5_fix \\\n" +
                "    --version 1.0.0-iter-100000-avg-1-chunk-32-left-256\n\n" +
                "或：手动把模型放到 ${filesDir}/asr-models/<id>/<v>/"
            )
            return
        }

        val mm = ModelManager(this)
        mm.ensure(manifestUrl, object : ModelDownloadCallback {
            override fun onProgress(modelId: String, downloadedBytes: Long, totalBytes: Long) {
                runOnUiThread {
                    progress.isIndeterminate = false
                    progress.max = 100
                    progress.progress = (downloadedBytes * 100 / totalBytes.coerceAtLeast(1)).toInt()
                    setStatus("下载模型 ${progress.progress}% ...")
                }
            }
            override fun onCompleted(modelId: String, modelDir: File) {
                // 下载完后再走一遍扫描，让 RadioGroup 也被驱动
                runOnUiThread { ensureModel() }
            }
            override fun onError(modelId: String, error: AsrError) {
                runOnUiThread {
                    setStatus("模型下载失败：${error.code} ${error.message}")
                    progress.visibility = android.view.View.GONE
                }
            }
        })
    }

    /** 按 lang 找到对应 LocalModel 并加载 engine；找不到时灰按钮 + 提示。 */
    private fun loadEngineForLang(lang: String) {
        val local = localByLang[lang]
        if (local == null) {
            setStatus(getString(R.string.status_lang_missing, langDisplayName(lang)))
            btnTalk.isEnabled = false
            currentLang = null
            return
        }
        currentLang = lang
        modelDir = local.dir
        startEngineForDir(local.dir)
    }

    /**
     * 用 [dir] 在后台异步加载 [AsrEngine]，主线程立即返回。整个流程：
     *  1) 主线程：构造 [AsrConfig]（轻量，异常会立刻反馈）、把旧 engine 字段置空，
     *     提升 generation，btnTalk/swItn/swPunct 临时灰禁，UI 显示"模型加载中"小提示。
     *  2) 后台线程（[asrLoadExec]，单线程串行）：先 close 旧 engine（让出 native 内存），
     *     再 `AsrEngine(cfg)` 同步加载（1-3 秒）。
     *  3) 主线程 post：若 generation 还匹配则装上新 engine 并恢复 UI；否则把这个 engine
     *     close 丢弃（用户中途又切了别的语言，结果作废）。
     */
    private fun startEngineForDir(dir: File) {
        progress.visibility = android.view.View.GONE

        // 构造 cfg 在主线程做：用户在 Builder.build() 阶段就能直接拿到错误信息
        // 注：ITN 已经迁到独立的 [WeitnEngine]，不再走 SDK 的 rule_fsts
        val cfg = try {
            AsrConfig.Builder(dir)
                .numThreads(2)
                .enableEndpoint(true)
                .build()
        } catch (t: Throwable) {
            setStatus("加载模型失败：${t.message}")
            btnTalk.isEnabled = false
            refreshWeitnSwitchEnabled()
            refreshPunctSwitchEnabled()
            tvLoadingHint.visibility = android.view.View.GONE
            return
        }

        val gen = asrLoadGeneration.incrementAndGet()
        // 切走旧 engine：startListening 用 engine 字段判空，置空后就不会再被启动新录音
        val oldEngine = engine
        engine = null
        btnTalk.isEnabled = false
        swItn.isEnabled = false
        swPunct.isEnabled = false
        tvLoadingHint.visibility = android.view.View.VISIBLE
        val langTag = currentLang?.let { "（${langDisplayName(it)}）" } ?: ""
        setStatus(getString(R.string.status_loading_model, langTag.ifEmpty { "ASR" }))

        try {
            asrLoadExec.execute {
                // 先关旧的释放 native 内存，再加载新的；二者之间用户可能又点了几次，
                // 但都已经把这条任务的 gen 锁定在闭包里，结果回到主线程时再校验。
                try {
                    oldEngine?.close()
                } catch (t: Throwable) {
                    // 关旧 engine 失败不影响新加载流程，但记一笔便于排查
                    android.util.Log.w("AmphionSample", "close old engine failed: ${t.message}")
                }

                val newEngine: AsrEngine = try {
                    AsrEngine(cfg)
                } catch (t: Throwable) {
                    mainHandler.post {
                        if (gen != asrLoadGeneration.get()) return@post
                        setStatus("加载模型失败：${t.message}")
                        btnTalk.isEnabled = false
                        refreshWeitnSwitchEnabled()
                        refreshPunctSwitchEnabled()
                        tvLoadingHint.visibility = android.view.View.GONE
                    }
                    return@execute
                }

                mainHandler.post {
                    if (gen != asrLoadGeneration.get()) {
                        // 用户在加载完成前又切了，丢弃当前 engine 避免 native 泄漏
                        try {
                            newEngine.close()
                        } catch (_: Throwable) {
                        }
                        return@post
                    }
                    engine = newEngine
                    btnTalk.isEnabled = true
                    refreshWeitnSwitchEnabled()
                    refreshPunctSwitchEnabled()
                    tvLoadingHint.visibility = android.view.View.GONE
                    val tag = currentLang?.let { "（${langDisplayName(it)}）" } ?: ""
                    setStatus("模型就绪${tag}，点击开始识别")
                    maybeAutoEnableWeitn()
                    maybeAutoEnablePunct()
                }
            }
        } catch (t: java.util.concurrent.RejectedExecutionException) {
            // Activity 已 onDestroy 关掉 executor，不必再 setStatus（窗口都没了）
            android.util.Log.w("AmphionSample", "asrLoadExec rejected: ${t.message}")
        }
    }

    /** 用户切换 RadioGroup 时触发；语言不变、仅 ITN 开关变化时也走这里。 */
    private fun switchToLang(newLang: String) {
        restartEngineForCurrentLang(newLang)
    }

    /**
     * 硬停 + 用 [targetLang] 异步重建 engine。RadioButton 视觉态由 framework 立即翻好，
     * 这里不再禁用它们，用户可以在加载途中继续切换（依靠 generation 失配机制丢弃中间结果）。
     */
    private fun restartEngineForCurrentLang(targetLang: String) {
        // 停录音（清理 session/recorder 引用），engine.close 会被异步 startEngineForDir 接管
        stopListeningForSwitch()

        clearFinalLines()
        tvPartial.text = ""
        tvFinal.text = ""

        // 仅刷新缺失语言的禁用态；加载中两个 RadioButton 都保持可点
        rbZhEn.isEnabled = localByLang.containsKey(LANG_ZH_EN)
        rbYueEn.isEnabled = localByLang.containsKey(LANG_YUE_EN)

        loadEngineForLang(targetLang)
    }

    /**
     * 切换场景下的"硬停"：直接停录音并把 session/recorderDump 摘掉，
     * 不调 session.stop() 等尾段 drain；随后的 [AsrEngine.close] 会强制关掉残留 session。
     *
     * 注意 onSessionStopped 不会被触发（session 被 engine.close 强关），所以波形隐藏
     * 必须在这里显式做掉。
     */
    private fun stopListeningForSwitch() {
        listening = false
        recorder?.stop()
        recorder = null
        recorderDump?.close()
        recorderDump = null
        session = null
        setTalkButtonRecording(false)
        waveform.visibility = android.view.View.GONE
    }

    private fun radioIdForLang(lang: String): Int = when (lang) {
        LANG_ZH_EN -> R.id.rb_zh_en
        LANG_YUE_EN -> R.id.rb_yue_en
        else -> -1
    }

    private fun langForRadioId(id: Int): String? = when (id) {
        R.id.rb_zh_en -> LANG_ZH_EN
        R.id.rb_yue_en -> LANG_YUE_EN
        else -> null
    }

    private fun langDisplayName(lang: String): String = when (lang) {
        LANG_ZH_EN -> getString(R.string.lang_zh_en)
        LANG_YUE_EN -> getString(R.string.lang_yue_en)
        else -> lang
    }

    // ----------- 录音 + 识别（常驻监听 toggle） -----------

    private fun onTalkButtonClick() {
        if (listening) stopListening() else startListening()
    }

    private fun startListening() {
        val eng = engine ?: return
        if (session != null) return

        listening = true
        clearFinalLines()
        tvPartial.text = ""
        tvFinal.text = ""
        setStatus("识别中…（再次点击停止）")
        setTalkButtonRecording(true)
        // 录音期间不允许切换 ITN / 标点开关，避免中途 lazy create 期间状态错乱
        swItn.isEnabled = false
        swPunct.isEnabled = false

        // 声波图：清空历史 -> 显示
        waveform.reset()
        waveform.visibility = android.view.View.VISIBLE

        val dump = SessionRecorder.create(applicationContext, sampleRate = 16000)
        recorderDump = dump
        lastDumpDir = dump?.dir
        dump?.logEvent("SESSION_START")

        // 占位引用，下面 newSession 返回后回填；callback.onSessionStopped 通过它关 session。
        // 用 var 在 callback 闭包里走 Kotlin 的 Ref.ObjectRef，赋值后能被 lambda 内看见。
        var capturedSession: AsrSession? = null

        val s = eng.newSession(object : AsrCallback {
            override fun onPartial(text: String) {
                // dump 保留 SDK 原始输出，UI 部分只显示原文（partial 频率高且
                // WeitnEngine 期望整段文本，不在 partial 阶段调用以免抖动）
                dump?.logEvent("PARTIAL", text)
                runOnUiThread { tvPartial.text = text }
            }

            override fun onFinal(text: String, confidence: Float) {
                dump?.logEvent("FINAL", "conf=$confidence  $text")
                runOnUiThread {
                    if (text.isNotEmpty()) {
                        // 先占位一行（用户能立刻看到一段 final），后续 weitn / punct 异步替换
                        val lineId = appendFinalLine(text)
                        if (lineId != null) {
                            submitFinalLineProcessing(lineId, text)
                        }
                    }
                    tvPartial.text = ""
                }
            }

            override fun onEndpoint() {
                dump?.logEvent("ENDPOINT")
            }

            override fun onError(error: AsrError) {
                dump?.logEvent("ERROR", "code=${error.code}  ${error.message}")
                runOnUiThread {
                    setStatus("识别错误：${error.code} ${error.message}")
                }
            }

            override fun onSessionStopped() {
                // SessionImpl.stop 在 decoder 线程上 drain 完最后一帧并 emit final 后，
                // 才会 post 这个回调到 callback 线程。所以走到这里时 partial / final 都已经记录完了。
                dump?.logEvent("SESSION_STOP")
                dump?.close()
                capturedSession?.close()
                runOnUiThread {
                    if (!listening) {
                        // 录音正常结束（用户主动停 / endpoint）：恢复 ITN / 标点 switch
                        refreshWeitnSwitchEnabled()
                        refreshPunctSwitchEnabled()
                        waveform.visibility = android.view.View.GONE
                        val path = dump?.dir?.absolutePath
                        setStatus(
                            if (path != null) "已停止；dump → $path"
                            else "已停止；点击可重新开始"
                        )
                        // 兜底：若之前 weitn / punct 还没自动开成功（因 engine 没就绪 / 还在录音），
                        // 录音结束后再尝试一次
                        maybeAutoEnableWeitn()
                        maybeAutoEnablePunct()
                    }
                }
            }
        })
        capturedSession = s
        session = s

        recorder = AudioRecorder(
            sampleRate = 16000,
            onPcm = { samples ->
                dump?.appendPcm(samples)
                s.acceptPcmShort(samples, 16000)
                feedWaveform(samples)
            },
            onError = { msg ->
                dump?.logEvent("ERROR", "mic=$msg")
                runOnUiThread { setStatus("录音错误：$msg") }
            },
            gainDb = 10f,
        ).also { it.start() }
    }

    /**
     * 把 [samples]（默认 100ms / 1600 个 16-bit PCM）切成 [WAVEFORM_FRAMES_PER_BATCH] 个子帧，
     * 每个子帧算 peak（最大绝对值 / 32768），再做轻度对数压缩，最后 post 到 UI 线程喂
     * [waveform]。一帧 100ms 输出 4 根条 → ~40 帧/s，正好够柱状条平滑滚动。
     *
     * 注意 [AudioRecorder] 回调跑在录音线程，所有 UI 操作必须 post 到主线程。
     */
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
            // 16-bit 满量程是 32768；语音 peak 一般 < 0.3，做 sqrt 让小信号更明显
            val norm = (peak / 32768f).coerceIn(0f, 1f)
            amps[written] = kotlin.math.sqrt(norm)
            i = end
            written++
        }
        mainHandler.post {
            // 录音可能在 post 到达前已经被切走（用户切语言 / 停录音），这种情况 view 已经 gone，
            // 直接喂 pushAmplitude 也无害（仅刷新一次 invalidate），所以不再做额外判空。
            for (j in 0 until written) {
                waveform.pushAmplitude(amps[j])
            }
        }
    }

    private fun stopListening() {
        if (!listening && session == null && recorder == null) return
        listening = false

        recorder?.stop()
        recorder = null

        // 把 session / dump 引用从 sample 主路径上摘下来，让 onSessionStopped 闭包独立处理后续关闭。
        // 这样用户立刻再点「开始识别」时 session/recorderDump 已经为 null，不会被 startListening 早退拦截。
        val s = session
        session = null
        recorderDump = null

        // 触发尾段 drain；最后一段 partial -> final 会通过 callback 派发，
        // 然后 onSessionStopped 关 dump + close session。
        s?.stop()

        setTalkButtonRecording(false)
        if (engine != null) {
            setStatus("正在结束本段…")
        }
    }

    /**
     * 同步主按钮的文案、图标与背景：录音中 -> 红色 stop 态，空闲 -> 主色 mic 态。
     * 在所有跳变点（onCreate 初始化、startListening、stopListening、stopListeningForSwitch）
     * 都用同一个入口收敛，避免文案 / 视觉态不同步。
     */
    private fun setTalkButtonRecording(recording: Boolean) {
        if (recording) {
            btnTalk.setText(R.string.btn_talk_stop)
            btnTalk.setCompoundDrawablesRelativeWithIntrinsicBounds(
                R.drawable.ic_mic_stop, 0, 0, 0
            )
            btnTalk.setBackgroundResource(R.drawable.bg_button_recording)
        } else {
            btnTalk.setText(R.string.btn_talk_start)
            btnTalk.setCompoundDrawablesRelativeWithIntrinsicBounds(
                R.drawable.ic_mic, 0, 0, 0
            )
            btnTalk.setBackgroundResource(R.drawable.bg_button_primary)
        }
    }

    private fun setStatus(s: String) {
        tvStatus.text = s
    }

    private fun toast(s: String) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show()
    }

    // ----------- Final 行管理（标点异步替换需要按 id 找原行） -----------

    /**
     * 不可变行：[id] 用于异步标点回来时定位原行；[text] 是当前显示文本（可能是原文，也可能
     * 是标点回来后的版本）。
     */
    private data class FinalLine(val id: Int, val text: String)

    /** 必须在 UI 线程调用。返回新行的 id，供异步标点任务回来时定位。 */
    private fun appendFinalLine(text: String): Int? {
        if (text.isEmpty()) return null
        val id = finalLineIdSeq.incrementAndGet()
        finalLines.add(FinalLine(id, text))
        renderFinalLines()
        return id
    }

    /** 必须在 UI 线程调用。 */
    private fun replaceFinalLine(id: Int, newText: String) {
        val idx = finalLines.indexOfFirst { it.id == id }
        if (idx < 0) return // 切语言 / 重启时已被清空
        finalLines[idx] = FinalLine(id, newText)
        renderFinalLines()
    }

    private fun clearFinalLines() {
        finalLines.clear()
        tvFinal.text = ""
    }

    private fun renderFinalLines() {
        tvFinal.text = finalLines.joinToString(separator = "\n") { it.text }
    }

    // ----------- 标点模型 / 引擎生命周期 -----------

    /**
     * 异步把 external 的标点模型搬到 internal filesDir。注意：本步只做 IO 拷贝，
     * 真正的 PunctuationEngine（70+ MB 内存）等用户开 Switch 时才会构造。
     */
    private fun installPunctAsync() {
        ensurePunctExecutor().execute {
            val installed = try {
                PunctModelInstaller(this).installOrLocate()
            } catch (t: Throwable) {
                null
            }
            runOnUiThread {
                punctModelFile = installed
                refreshPunctSwitchEnabled()
                maybeAutoEnablePunct()
            }
        }
    }

    /** 创建 / 复用单线程 executor，所有标点相关任务都串行化在这一条线程上。 */
    private fun ensurePunctExecutor(): ExecutorService {
        val existing = punctExec
        if (existing != null && !existing.isShutdown) return existing
        val created = Executors.newSingleThreadExecutor { r ->
            Thread(r, "amphion-punct").apply { isDaemon = true }
        }
        punctExec = created
        return created
    }

    private fun onPunctSwitchChanged(checked: Boolean) {
        if (checked) {
            val model = punctModelFile
            if (model == null) {
                toast(getString(R.string.punct_unavailable))
                swPunct.isChecked = false
                // 模型路径不在场，标记 tried 防止后续每次 maybeAutoEnablePunct 再次 toast
                punctAutoEnableTried = true
                return
            }
            // 第一次开 Switch：异步 native 加载（~1 秒），加载期间 Switch 与按钮保持灰禁
            swPunct.isEnabled = false
            btnTalk.isEnabled = false
            setStatus("加载标点模型…")
            ensurePunctExecutor().execute {
                val created: PunctuationEngine? = try {
                    PunctuationEngine(
                        PunctuationConfig.Builder(model).numThreads(1).build()
                    )
                } catch (t: Throwable) {
                    null
                }
                runOnUiThread {
                    // 不管成功失败都标记 tried，避免 onSessionStopped / install 钩子反复重试
                    punctAutoEnableTried = true
                    if (created == null) {
                        swPunct.isChecked = false
                        refreshPunctSwitchEnabled()
                        btnTalk.isEnabled = engine != null
                        setStatus("标点模型加载失败，请重新 push 模型")
                        return@runOnUiThread
                    }
                    synchronized(punctLock) { punctEngine = created }
                    refreshPunctSwitchEnabled()
                    btnTalk.isEnabled = engine != null && !listening
                    val langTag = currentLang?.let { "（${langDisplayName(it)}）" } ?: ""
                    setStatus("模型就绪${langTag}，已启用标点")
                }
            }
        } else {
            // 关 Switch：立即释放 native（70 MB）
            ensurePunctExecutor().execute {
                synchronized(punctLock) {
                    punctEngine?.close()
                    punctEngine = null
                }
            }
            val langTag = currentLang?.let { "（${langDisplayName(it)}）" } ?: ""
            setStatus("模型就绪${langTag}，已关闭标点")
        }
    }

    /**
     * 自动开启标点开关：UI 上 sw_punct 被隐藏，启动后由本方法在 punctModelFile + engine
     * 双就绪且不在录音时自动 setChecked(true) 触发既有 lazy load 流程。
     *
     * 用 [punctAutoEnableTried] 节流，无论首次结果成功 / 失败都不会再被多个钩子反复打开，
     * 这样调用者（installPunctAsync / startEngineForDir / onSessionStopped）可以无脑调一遍。
     */
    private fun maybeAutoEnablePunct() {
        if (punctAutoEnableTried) return
        if (punctModelFile == null) return
        if (engine == null) return
        if (listening) return
        if (swPunct.isChecked) return
        if (punctEngine != null) return
        // setChecked 会走 onPunctSwitchChanged(true)，由它统一设置 status / 异步加载
        swPunct.isChecked = true
    }

    /**
     * 把已经显示在 UI 上的某条 final 文本提交到 punct 线程加标点，回来后替换那条行。
     * 调用方必须在 UI 线程调用；如果在执行期间 [punctEngine] 被关掉 / 替换，安静放弃。
     */
    private fun submitPunctTask(lineId: Int, original: String) {
        val exec = punctExec ?: return
        exec.execute {
            val punctText = synchronized(punctLock) {
                punctEngine?.addPunctuation(original)
            } ?: return@execute
            if (punctText == original) return@execute // 没变化就不必刷 UI
            runOnUiThread { replaceFinalLine(lineId, punctText) }
        }
    }

    /**
     * 收敛 swPunct.isEnabled 的判断条件：模型文件就位、ASR engine 已起、不在录音 / 切换中。
     * 任何一项变化时都应该调它，避免每处重复判断。
     */
    private fun refreshPunctSwitchEnabled() {
        swPunct.isEnabled = punctModelFile != null && engine != null && !listening
    }

    // ----------- WeText ITN（独立 SDK API；行为对齐 punct）  -----------

    /**
     * 单条 final 的后处理 pipeline：
     *   raw  -> (sw_itn?  WeitnEngine.normalize  : raw)
     *        -> (sw_punct? PunctuationEngine.addPunctuation : 前一步结果)
     *        -> UI replaceFinalLine
     *
     * 任一阶段引擎未开 / 未就绪：保留前一步结果。
     * 任一阶段输出与前一步等价：不重复刷 UI，避免行抖动。
     */
    private fun submitFinalLineProcessing(lineId: Int, original: String) {
        val weitnOn = swItn.isChecked
        val punctOn = swPunct.isChecked
        if (!weitnOn && !punctOn) return

        if (weitnOn) {
            val exec = ensureWeitnExecutor()
            exec.execute {
                val normalized = synchronized(weitnLock) {
                    weitnEngine?.normalize(original)
                } ?: original
                if (normalized != original) {
                    runOnUiThread { replaceFinalLine(lineId, normalized) }
                }
                if (punctOn) {
                    submitPunctTask(lineId, normalized)
                }
            }
        } else {
            // weitn 关闭：直接进入 punct 阶段
            submitPunctTask(lineId, original)
        }
    }

    /**
     * 异步把 external 的两份 WeText fst 搬到 internal filesDir。本步只做 IO 拷贝（毫秒级），
     * 真正的 WeitnEngine（FST 数 MB 内存）等用户开 Switch 时才会构造。
     */
    private fun installWeitnAsync() {
        ensureWeitnExecutor().execute {
            val installed = try {
                WeitnAssetInstaller(this).installOrLocate()
            } catch (t: Throwable) {
                android.util.Log.w("AmphionSample", "weitn install failed: ${t.message}")
                null
            }
            runOnUiThread {
                weitnAssets = installed
                refreshWeitnSwitchEnabled()
                maybeAutoEnableWeitn()
            }
        }
    }

    /** 创建 / 复用单线程 executor，所有 ITN 相关任务都串行化在这一条线程上。 */
    private fun ensureWeitnExecutor(): ExecutorService {
        val existing = weitnExec
        if (existing != null && !existing.isShutdown) return existing
        val created = Executors.newSingleThreadExecutor { r ->
            Thread(r, "amphion-weitn").apply { isDaemon = true }
        }
        weitnExec = created
        return created
    }

    private fun onWeitnSwitchChanged(checked: Boolean) {
        if (checked) {
            val installed = weitnAssets
            if (installed == null) {
                toast(getString(R.string.itn_unavailable))
                swItn.isChecked = false
                // fst 还没就绪：标记 tried 防止 maybeAutoEnableWeitn 再次 toast
                weitnAutoEnableTried = true
                return
            }
            swItn.isEnabled = false
            btnTalk.isEnabled = false
            setStatus("加载 WeText ITN…")
            ensureWeitnExecutor().execute {
                val created: WeitnEngine? = try {
                    WeitnEngine(
                        WeitnConfig.Builder(installed.tagger, installed.verbalizer).build()
                    )
                } catch (t: Throwable) {
                    android.util.Log.w("AmphionSample", "weitn engine create failed: ${t.message}")
                    null
                }
                runOnUiThread {
                    weitnAutoEnableTried = true
                    if (created == null) {
                        swItn.isChecked = false
                        refreshWeitnSwitchEnabled()
                        btnTalk.isEnabled = engine != null
                        setStatus("WeText ITN 加载失败，请重新 push fst")
                        return@runOnUiThread
                    }
                    synchronized(weitnLock) { weitnEngine = created }
                    refreshWeitnSwitchEnabled()
                    btnTalk.isEnabled = engine != null && !listening
                    val langTag = currentLang?.let { "（${langDisplayName(it)}）" } ?: ""
                    setStatus("模型就绪${langTag}，已启用 WeText ITN")
                }
            }
        } else {
            // 关 Switch：立即释放 native FST 内存（数 MB）
            ensureWeitnExecutor().execute {
                synchronized(weitnLock) {
                    weitnEngine?.close()
                    weitnEngine = null
                }
            }
            val langTag = currentLang?.let { "（${langDisplayName(it)}）" } ?: ""
            setStatus("模型就绪${langTag}，已关闭 WeText ITN")
        }
    }

    /**
     * 自动开启 sw_itn：fst + engine 双就绪且不在录音时自动 setChecked(true)，
     * 用 [weitnAutoEnableTried] 节流，无论结果成功失败都不会再被多个钩子反复触发。
     */
    private fun maybeAutoEnableWeitn() {
        if (weitnAutoEnableTried) return
        if (weitnAssets == null) return
        if (engine == null) return
        if (listening) return
        if (swItn.isChecked) return
        if (weitnEngine != null) return
        swItn.isChecked = true
    }

    /**
     * 收敛 swItn.isEnabled 的判断条件：fst 就位、ASR engine 已起、不在录音 / 切换中。
     */
    private fun refreshWeitnSwitchEnabled() {
        swItn.isEnabled = weitnAssets != null && engine != null && !listening
    }
}
