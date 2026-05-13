package com.yourco.asr.sample

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Button
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.yourco.asr.AsrCallback
import com.yourco.asr.AsrConfig
import com.yourco.asr.AsrEngine
import com.yourco.asr.AsrError
import com.yourco.asr.AsrLogLevel
import com.yourco.asr.AsrSdk
import com.yourco.asr.AsrSdkOptions
import com.yourco.asr.AsrSession
import com.yourco.asr.ModelDownloadCallback
import com.yourco.asr.ModelManager
import java.io.File

/**
 * 单 Activity Sample：
 *  - 启动时拉起模型（先看本地，没有就走 ModelManager 下载）
 *  - 模型 ready 后允许 点击开始 / 再次点击停止 的常驻监听模式
 *  - 期间 SDK 内部 endpoint 触发会自动 emit final 并自动 reset 进入下一句，
 *    不会出现「英文短句 endpoint 后 final 为空」的边界
 *  - partial 文本随时刷新；final 文本累计追加显示
 *
 * 与"按住说话"的临时短流模式相比，本模式：
 *  - engine + session 均常驻，每次 endpoint 不重建 stream
 *  - 录音线程不断送 PCM，short utterance 也会被自然累计到 chunk
 */
class MainActivity : AppCompatActivity() {

    // ----------- 替换为你自己的服务端 manifest.json -----------
    // 例如 https://your-cdn.example.com/asr/zh-en/1.0.0/manifest.json
    private val manifestUrl: String = "https://your-cdn.example.com/asr/zh-en/1.0.0/manifest.json"

    private lateinit var btnTalk: Button
    private lateinit var tvPartial: TextView
    private lateinit var tvFinal: TextView
    private lateinit var tvStatus: TextView
    private lateinit var progress: ProgressBar

    private var engine: AsrEngine? = null
    private var session: AsrSession? = null
    private var recorder: AudioRecorder? = null
    private var recorderDump: SessionRecorder? = null
    private var modelDir: File? = null
    private var lastDumpDir: File? = null

    @Volatile
    private var listening: Boolean = false

    private val finalBuffer = StringBuilder()

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
        progress = findViewById(R.id.progress)

        // 调试期把 SDK 日志打到 INFO，方便 logcat 看到 native 加载 / 错误码
        AsrSdk.init(applicationContext, AsrSdkOptions(logLevel = AsrLogLevel.INFO))

        btnTalk.isEnabled = false
        btnTalk.setText(R.string.btn_talk_start)
        btnTalk.setOnClickListener { onTalkButtonClick() }

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
        engine?.close()
        engine = null
        AsrSdk.release()
    }

    // ----------- 模型确保 -----------

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
        val local = mm.listLocal().firstOrNull()
        if (local != null) {
            modelDir = local.dir
            onModelReady(local.dir)
            return
        }

        if (manifestUrl.contains("your-cdn.example.com")) {
            setStatus(
                "没找到本地模型。\n\n" +
                "快速验证：\n" +
                "  bash tools/asr-sdk/00_fetch_demo_model.sh push\n\n" +
                "或自定义：\n" +
                "  在 MainActivity#manifestUrl 配置你的 manifest URL；\n" +
                "  或手动把模型放到 ${filesDir}/asr-models/<id>/<v>/"
            )
            progress.visibility = android.view.View.GONE
            return
        }

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
                runOnUiThread {
                    this@MainActivity.modelDir = modelDir
                    onModelReady(modelDir)
                }
            }
            override fun onError(modelId: String, error: AsrError) {
                runOnUiThread {
                    setStatus("模型下载失败：${error.code} ${error.message}")
                    progress.visibility = android.view.View.GONE
                }
            }
        })
    }

    private fun onModelReady(dir: File) {
        progress.visibility = android.view.View.GONE
        try {
            val cfg = AsrConfig.Builder(dir)
                .numThreads(2)
                .enableEndpoint(true)
                .build()
            engine = AsrEngine(cfg)
            btnTalk.isEnabled = true
            setStatus("模型就绪，点击开始识别")
        } catch (t: Throwable) {
            setStatus("加载模型失败：${t.message}")
        }
    }

    // ----------- 录音 + 识别（常驻监听 toggle） -----------

    private fun onTalkButtonClick() {
        if (listening) stopListening() else startListening()
    }

    private fun startListening() {
        val eng = engine ?: return
        if (session != null) return

        listening = true
        finalBuffer.clear()
        tvPartial.text = ""
        tvFinal.text = ""
        setStatus("识别中…（再次点击停止）")
        btnTalk.setText(R.string.btn_talk_stop)

        val dump = SessionRecorder.create(applicationContext, sampleRate = 16000)
        recorderDump = dump
        lastDumpDir = dump?.dir
        dump?.logEvent("SESSION_START")

        // 占位引用，下面 newSession 返回后回填；callback.onSessionStopped 通过它关 session。
        // 用 var 在 callback 闭包里走 Kotlin 的 Ref.ObjectRef，赋值后能被 lambda 内看见。
        var capturedSession: AsrSession? = null

        val s = eng.newSession(object : AsrCallback {
            override fun onPartial(text: String) {
                dump?.logEvent("PARTIAL", text)
                runOnUiThread { tvPartial.text = text }
            }

            override fun onFinal(text: String, confidence: Float) {
                dump?.logEvent("FINAL", "conf=$confidence  $text")
                runOnUiThread {
                    if (text.isNotEmpty()) {
                        finalBuffer.append(text).append('\n')
                        tvFinal.text = finalBuffer.toString()
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
                        val path = dump?.dir?.absolutePath
                        setStatus(
                            if (path != null) "已停止；dump → $path"
                            else "已停止；点击可重新开始"
                        )
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
            },
            onError = { msg ->
                dump?.logEvent("ERROR", "mic=$msg")
                runOnUiThread { setStatus("录音错误：$msg") }
            },
            gainDb = 10f,
        ).also { it.start() }
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

        btnTalk.setText(R.string.btn_talk_start)
        if (engine != null) {
            setStatus("正在结束本段…")
        }
    }

    private fun setStatus(s: String) {
        tvStatus.text = s
    }

    private fun toast(s: String) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show()
    }
}
