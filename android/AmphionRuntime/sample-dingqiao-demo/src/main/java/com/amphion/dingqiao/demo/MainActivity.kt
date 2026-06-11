package com.amphion.dingqiao.demo

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Button
import android.widget.ImageButton
import android.widget.PopupMenu
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.SwitchCompat
import androidx.core.content.ContextCompat
import com.amphion.dingqiao.AudioInfo
import com.amphion.dingqiao.CreateEngineCallback
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.DINGQIAO_SPEAKER_MODEL_FILENAME
import com.amphion.dingqiao.DingqiaoOnlineMode
import com.amphion.dingqiao.RecognitionListener
import com.amphion.dingqiao.SpeechRecognitionEngine
import com.amphion.dingqiao.SpeechRecognitionResult
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.StartParams
import java.io.File
import java.util.concurrent.Executors

/**
 * 鼎桥交付 Demo：通过 [SpeechRecognizeSdk] 完成离线识别 + 警务增强 + 可选声纹打分。
 */
class MainActivity : AppCompatActivity() {

    private lateinit var btnTalk: Button
    private lateinit var btnMenu: ImageButton
    private lateinit var tvPartial: TextView
    private lateinit var tvFinal: TextView
    private lateinit var tvStatus: TextView
    private lateinit var tvVoiceprintInfo: TextView
    private lateinit var progress: ProgressBar
    private lateinit var swVoiceprint: SwitchCompat

    private val worker = Executors.newSingleThreadExecutor()
    private var engine: SpeechRecognitionEngine? = null
    private var recorder: AudioRecorder? = null
    private var frameWriter: PcmFrameWriter? = null

    @Volatile
    private var listening = false

    @Volatile
    private var sessionId: String? = null

    private var voiceprintVerifyDesired = false
    private val finalLines = StringBuilder()

    private val permLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) initEngine() else setStatus(getString(R.string.status_no_permission))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        btnTalk = findViewById(R.id.btn_talk)
        btnMenu = findViewById(R.id.btn_menu)
        tvPartial = findViewById(R.id.tv_partial)
        tvFinal = findViewById(R.id.tv_final)
        tvStatus = findViewById(R.id.tv_status)
        tvVoiceprintInfo = findViewById(R.id.tv_voiceprint_info)
        progress = findViewById(R.id.progress)
        swVoiceprint = findViewById(R.id.sw_voiceprint)

        btnTalk.setOnClickListener { if (listening) stopListening() else startListening() }
        btnMenu.setOnClickListener { showMenu(it) }
        swVoiceprint.setOnCheckedChangeListener { _, checked -> onVoiceprintSwitch(checked) }

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            permLauncher.launch(Manifest.permission.RECORD_AUDIO)
        } else {
            initEngine()
        }
    }

    override fun onResume() {
        super.onResume()
        refreshVoiceprintUi()
    }

    override fun onDestroy() {
        super.onDestroy()
        stopListening()
        engine?.shutdown()
        engine = null
        worker.shutdownNow()
    }

    private fun initEngine() {
        progress.visibility = android.view.View.VISIBLE
        setStatus(getString(R.string.status_loading_engine))
        btnTalk.isEnabled = false

        SpeechRecognizeSdk.createEngine(
            CreateEngineParams(
                language = "zh-CN",
                online = DingqiaoOnlineMode.OFFLINE,
            ),
            object : CreateEngineCallback {
                override fun onResult(resultEngine: SpeechRecognitionEngine) {
                    runOnUiThread {
                        engine = resultEngine
                        engine?.setListener(createListener())
                        progress.visibility = android.view.View.GONE
                        btnTalk.isEnabled = true
                        setStatus(getString(R.string.status_engine_ready))
                        refreshVoiceprintUi()
                    }
                }

                override fun onError(errorCode: Int, errorMessage: String) {
                    runOnUiThread {
                        progress.visibility = android.view.View.GONE
                        setStatus(getString(R.string.status_engine_failed, "$errorCode $errorMessage"))
                    }
                }
            },
        )
    }

    private fun createListener(): RecognitionListener = object : RecognitionListener {
        override fun onStart(sessionId: String, eventMessage: String) {
            runOnUiThread { setStatus(getString(R.string.status_listening)) }
        }

        override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) {
            // VAD 事件可选展示
        }

        override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
            runOnUiThread {
                if (result.isFinal) {
                    appendFinal(result)
                    tvPartial.text = ""
                } else {
                    tvPartial.text = result.result
                }
            }
        }

        override fun onComplete(sessionId: String, eventMessage: String) {
            runOnUiThread {
                listening = false
                setTalkButtonRecording(false)
                btnTalk.isEnabled = true
                setStatus(getString(R.string.status_engine_ready))
            }
        }

        override fun onError(sessionId: String, errorCode: Int, errorMessage: String) {
            runOnUiThread {
                setStatus("错误 $errorCode：$errorMessage")
                listening = false
                setTalkButtonRecording(false)
                btnTalk.isEnabled = engine != null
            }
        }
    }

    private fun startListening() {
        val eng = engine ?: return
        if (listening) return

        val sid = "demo-${System.currentTimeMillis()}"
        sessionId = sid
        listening = true
        finalLines.clear()
        tvPartial.text = ""
        tvFinal.text = ""

        val voiceprintId = DemoPrefs.getVoiceprintId(this)
        val verify = voiceprintVerifyDesired && !voiceprintId.isNullOrBlank()
        val extra = mutableMapOf<String, Any>(
            "enablePartialResult" to true,
            "maxAudioDuration" to 60_000,
            "vadEnd" to 800,
        )
        if (verify) {
            extra["enableVoiceprintVerification"] = true
            extra["voiceprintIds"] = listOf(voiceprintId!!)
        }

        eng.startListening(
            StartParams(
                sessionId = sid,
                audioInfo = AudioInfo(),
                extraParams = extra,
            ),
        )

        setTalkButtonRecording(true)
        btnTalk.isEnabled = true

        frameWriter = PcmFrameWriter { frame ->
            eng.writeAudio(sid, frame)
        }
        recorder = AudioRecorder(
            onPcm = { samples -> frameWriter?.accept(samples) },
            onError = { msg -> runOnUiThread { setStatus("录音错误：$msg") } },
        ).also { it.start() }
    }

    private fun stopListening() {
        if (!listening) return
        listening = false
        recorder?.stop()
        recorder = null
        frameWriter?.reset()
        frameWriter = null

        val sid = sessionId
        sessionId = null
        setTalkButtonRecording(false)
        if (sid != null) {
            engine?.finish(sid)
        }
    }

    private fun appendFinal(result: SpeechRecognitionResult) {
        if (result.result.isEmpty()) return
        if (finalLines.isNotEmpty()) finalLines.append('\n')
        finalLines.append(result.result)
        result.speakerSimilarity?.let {
            finalLines.append(' ')
            finalLines.append(getString(R.string.speaker_score_format, it))
        }
        tvFinal.text = finalLines
    }

    private fun refreshVoiceprintUi() {
        val modelReady = File(DingqiaoApp.workPath(), DINGQIAO_SPEAKER_MODEL_FILENAME).isFile
        val id = DemoPrefs.getVoiceprintId(this)
        tvVoiceprintInfo.text = when {
            !modelReady -> getString(R.string.vp_model_missing)
            id.isNullOrBlank() -> getString(R.string.vp_not_registered)
            else -> getString(R.string.vp_registered, id)
        }
        swVoiceprint.setOnCheckedChangeListener(null)
        swVoiceprint.isEnabled = modelReady && !id.isNullOrBlank()
        if (id.isNullOrBlank()) {
            voiceprintVerifyDesired = false
            swVoiceprint.isChecked = false
        } else {
            swVoiceprint.isChecked = voiceprintVerifyDesired
        }
        swVoiceprint.setOnCheckedChangeListener { _, checked -> onVoiceprintSwitch(checked) }
    }

    private fun onVoiceprintSwitch(enabled: Boolean) {
        val id = DemoPrefs.getVoiceprintId(this)
        if (enabled && id.isNullOrBlank()) {
            swVoiceprint.isChecked = false
            toast(getString(R.string.vp_need_register))
            return
        }
        voiceprintVerifyDesired = enabled
    }

    private fun showMenu(anchor: android.view.View) {
        PopupMenu(this, anchor).apply {
            menuInflater.inflate(R.menu.menu_main, menu)
            menu.findItem(R.id.action_delete_voiceprint).isVisible =
                !VoiceprintHelper.registeredId(this@MainActivity).isNullOrBlank()
            setOnMenuItemClickListener { item ->
                when (item.itemId) {
                    R.id.action_voiceprint -> {
                        startActivity(Intent(this@MainActivity, VoiceprintEnrollActivity::class.java))
                        true
                    }
                    R.id.action_delete_voiceprint -> {
                        confirmDeleteVoiceprint()
                        true
                    }
                    else -> false
                }
            }
            show()
        }
    }

    private fun confirmDeleteVoiceprint() {
        val id = VoiceprintHelper.registeredId(this) ?: return
        AlertDialog.Builder(this)
            .setTitle(R.string.vp_delete_title)
            .setMessage(getString(R.string.vp_delete_msg) + "\n\n$id")
            .setPositiveButton(R.string.vp_delete_ok) { _, _ ->
                try {
                    val deleted = VoiceprintHelper.deleteRegistered(this)
                    voiceprintVerifyDesired = false
                    refreshVoiceprintUi()
                    toast(getString(R.string.vp_delete_success, deleted ?: id))
                } catch (t: Throwable) {
                    toast(getString(R.string.vp_delete_failed, t.message ?: "unknown"))
                }
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun setTalkButtonRecording(recording: Boolean) {
        if (recording) {
            btnTalk.setText(R.string.btn_talk_stop)
            btnTalk.setCompoundDrawablesRelativeWithIntrinsicBounds(R.drawable.ic_mic_stop, 0, 0, 0)
            btnTalk.setBackgroundResource(R.drawable.bg_button_recording)
        } else {
            btnTalk.setText(R.string.btn_talk_start)
            btnTalk.setCompoundDrawablesRelativeWithIntrinsicBounds(R.drawable.ic_mic, 0, 0, 0)
            btnTalk.setBackgroundResource(R.drawable.bg_button_primary)
        }
    }

    private fun setStatus(text: String) {
        tvStatus.text = text
    }

    private fun toast(msg: String) {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
    }
}
