package com.amphion.dingqiao.demo

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.graphics.Typeface
import android.os.Bundle
import android.os.SystemClock
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.text.style.StyleSpan
import android.util.Log
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.ImageButton
import android.widget.LinearLayout
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
import com.amphion.dingqiao.DingqiaoEventCode
import com.amphion.dingqiao.DingqiaoOnlineMode
import com.amphion.dingqiao.RecognitionListener
import com.amphion.dingqiao.SpeechRecognitionEngine
import com.amphion.dingqiao.SpeechRecognitionResult
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.StartParams
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.Locale
import java.util.concurrent.Executors

/**
 * Customer-facing Dingqiao demo aligned with the HarmonyOS sample.
 *
 * Runtime is prepared by [DingqiaoApp]. A microphone capture starts immediately on tap while a
 * configuration-specific engine is created asynchronously; fixed 640-byte frames are buffered and
 * replayed at the public SDK boundary once onStart makes the session usable.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var btnTalk: Button
    private lateinit var btnMenu: ImageButton
    private lateinit var tvPartial: TextView
    private lateinit var tvFinal: TextView
    private lateinit var tvStatus: TextView
    private lateinit var tvVoiceprintInfo: TextView
    private lateinit var tvScenarioInfo: TextView
    private lateinit var progress: ProgressBar
    private lateinit var swVoiceprint: SwitchCompat
    private lateinit var swSpeakerVad: SwitchCompat
    private lateinit var swPoliceEnhancement: SwitchCompat
    private lateinit var cardCapture: LinearLayout
    private lateinit var tvCaptureInfo: TextView
    private lateinit var tvLiveCompare: TextView
    private lateinit var tvReplayCompare: TextView
    private lateinit var tvCompareInfo: TextView
    private lateinit var etCaseNote: EditText
    private lateinit var btnSaveCase: Button
    private lateinit var tvCaseInfo: TextView
    private lateinit var btnPlayCapture: Button
    private lateinit var btnReplayCapture: Button

    private lateinit var scenarioButtons: Map<CustomerScenario, Button>
    private lateinit var sourceButtons: Map<DemoAudioSource, Button>

    private val worker = Executors.newSingleThreadExecutor()
    private val stateLock = Any()
    private val coldStartPttGate = ColdStartPttGate()
    private val sdkCapture = SdkPcmCapture()
    private val capturePlayer = PcmPlayer()
    private val finalLines = SpannableStringBuilder()

    private var engine: SpeechRecognitionEngine? = null
    private var recorder: AudioRecorder? = null
    private var frameWriter: PcmFrameWriter? = null
    private lateinit var debugRecordStore: DebugRecordStore
    private lateinit var caseStore: DemoCaseStore
    private var activeDebugRecord: DebugRecordStore.ActiveRecord? = null

    @Volatile private var active = true
    @Volatile private var runtimeReady = false
    @Volatile private var listening = false
    @Volatile private var stoppingListening = false
    @Volatile private var replaying = false
    @Volatile private var playingCapture = false
    @Volatile private var engineLoading = false
    @Volatile private var modelReleaseInProgress = false
    @Volatile private var modelReady = false

    private var createGeneration = 0L
    private var coldStartGeneration = -1
    private var coldReleasePending = false
    private var sessionId: String? = null
    private var replaySessionId: String? = null
    private val preRoll = mutableListOf<ByteArray>()
    private var preRollDroppedFrames = 0
    private var startTapMs = 0L

    private var customerScenario = CustomerScenario.PTT
    private var audioSource = DemoAudioSource.VOICE_COMMUNICATION
    private var voiceprintVerifyDesired = false
    private var speakerVadDesired = false
    private var policeEnhancementDesired = true

    private var capturedScenario = CustomerScenario.PTT
    private var capturedAudioSource = DemoAudioSource.VOICE_COMMUNICATION
    private var capturedHotwords = emptyList<String>()
    private var capturedVoiceprintId: String? = null
    private var capturedVoiceprintVerify = false
    private var capturedSpeakerVad = false
    private var capturedPoliceEnhancement = true
    private var recorderStats = AudioRecorderStats()
    private var captureSnapshot: SdkPcmCaptureSnapshot? = null
    private var captureReady = false
    private var liveHasCompleted = false
    private var replayHasCompleted = false
    private var liveCompareText = ""
    private var replayCompareText = ""
    private var compareInfo = ""

    private val permLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) awaitRuntime() else setStatus(getString(R.string.status_no_permission))
    }

    private val hotwordsLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        if (result.resultCode == RESULT_OK &&
            result.data?.getBooleanExtra(HotwordsActivity.EXTRA_HOTWORDS_CHANGED, false) == true
        ) {
            reloadEngineForHotwords()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        bindViews()

        debugRecordStore = DebugRecordStore(File(DingqiaoApp.workPath(), "debug_records"))
        caseStore = DemoCaseStore(File(getExternalFilesDir(null), "asr-cases"))
        policeEnhancementDesired = DemoPrefs.getPoliceEnhancementEnabled(this)
        swPoliceEnhancement.isChecked = policeEnhancementDesired

        bindActions()
        updateScenarioUi()
        refreshVoiceprintUi()
        updateOperationControls()

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            permLauncher.launch(Manifest.permission.RECORD_AUDIO)
        } else {
            awaitRuntime()
        }
    }

    override fun onResume() {
        super.onResume()
        refreshVoiceprintUi()
    }

    override fun onDestroy() {
        active = false
        createGeneration += 1
        coldStartPttGate.cancel()
        capturePlayer.stop()
        replaying = false
        listening = false
        stopCapture(flushTail = false)
        val sid = sessionId ?: replaySessionId
        if (sid != null && engine?.isBusy() == true) runCatching { engine?.cancel(sid) }
        finishActiveDebugRecord(DebugRecordStore.STATUS_ABORTED)
        engine?.shutdown()
        engine = null
        runCatching { SpeechRecognizeSdk.unloadModel() }
        worker.shutdownNow()
        super.onDestroy()
    }

    private fun bindViews() {
        btnTalk = findViewById(R.id.btn_talk)
        btnMenu = findViewById(R.id.btn_menu)
        tvPartial = findViewById(R.id.tv_partial)
        tvFinal = findViewById(R.id.tv_final)
        tvStatus = findViewById(R.id.tv_status)
        tvVoiceprintInfo = findViewById(R.id.tv_voiceprint_info)
        tvScenarioInfo = findViewById(R.id.tv_scenario_info)
        progress = findViewById(R.id.progress)
        swVoiceprint = findViewById(R.id.sw_voiceprint)
        swSpeakerVad = findViewById(R.id.sw_speaker_vad)
        swPoliceEnhancement = findViewById(R.id.sw_police_enhancement)
        cardCapture = findViewById(R.id.card_capture)
        tvCaptureInfo = findViewById(R.id.tv_capture_info)
        tvLiveCompare = findViewById(R.id.tv_live_compare)
        tvReplayCompare = findViewById(R.id.tv_replay_compare)
        tvCompareInfo = findViewById(R.id.tv_compare_info)
        etCaseNote = findViewById(R.id.et_case_note)
        btnSaveCase = findViewById(R.id.btn_save_case)
        tvCaseInfo = findViewById(R.id.tv_case_info)
        btnPlayCapture = findViewById(R.id.btn_play_capture)
        btnReplayCapture = findViewById(R.id.btn_replay_capture)
        scenarioButtons = mapOf(
            CustomerScenario.TAP_VAD to findViewById(R.id.btn_scenario_tap_vad),
            CustomerScenario.PTT to findViewById(R.id.btn_scenario_ptt),
            CustomerScenario.TRANSCRIPTION to findViewById(R.id.btn_scenario_transcription),
            CustomerScenario.FORM to findViewById(R.id.btn_scenario_form),
            CustomerScenario.MEETING_MINUTES to findViewById(R.id.btn_scenario_meeting),
        )
        sourceButtons = mapOf(
            DemoAudioSource.MIC to findViewById(R.id.btn_source_mic),
            DemoAudioSource.VOICE_RECOGNITION to findViewById(R.id.btn_source_recognition),
            DemoAudioSource.VOICE_COMMUNICATION to findViewById(R.id.btn_source_communication),
        )
    }

    private fun bindActions() {
        btnTalk.setOnClickListener { if (listening) stopListening() else startListening() }
        btnMenu.setOnClickListener { showMenu(it) }
        scenarioButtons.forEach { (scenario, button) ->
            button.setOnClickListener { selectCustomerScenario(scenario) }
        }
        sourceButtons.forEach { (source, button) ->
            button.setOnClickListener { selectAudioSource(source) }
        }
        swVoiceprint.setOnCheckedChangeListener { _, checked -> onVoiceprintSwitch(checked) }
        swSpeakerVad.setOnCheckedChangeListener { _, checked -> onSpeakerVadSwitch(checked) }
        swPoliceEnhancement.setOnCheckedChangeListener { _, checked ->
            policeEnhancementDesired = checked
            DemoPrefs.setPoliceEnhancementEnabled(this, checked)
        }
        btnPlayCapture.setOnClickListener { playLastSdkCapture() }
        btnReplayCapture.setOnClickListener { replayLastSdkCapture() }
        btnSaveCase.setOnClickListener { saveCurrentCase() }
    }

    private fun awaitRuntime() {
        progress.visibility = View.VISIBLE
        btnTalk.isEnabled = false
        setStatus(getString(R.string.status_loading_engine))
        (application as DingqiaoApp).whenRuntimeReady { runtime ->
            runOnUiThread {
                if (!active) return@runOnUiThread
                progress.visibility = View.GONE
                if (runtime.isReady) {
                    runtimeReady = true
                    setStatus(getString(R.string.status_engine_ready))
                } else {
                    runtimeReady = false
                    setStatus(getString(R.string.status_engine_failed, "${runtime.errorCode} ${runtime.errorMessage}"))
                }
                updateOperationControls()
            }
        }
    }

    private fun buildCreateEngineParams(hotwords: List<String>): CreateEngineParams {
        val extra = mutableMapOf<String, Any>("disablePrepack" to true)
        if (hotwords.isNotEmpty()) extra["sysGeneralLexicon"] = hotwords
        return CreateEngineParams(
            language = "zh-CN",
            online = DingqiaoOnlineMode.OFFLINE,
            extraParams = extra,
        )
    }

    private fun createEngineForOperation(coldGeneration: Int = -1) {
        val requestGeneration = ++createGeneration
        engineLoading = true
        progress.visibility = View.VISIBLE
        updateOperationControls()
        SpeechRecognizeSdk.createEngineAsync(
            buildCreateEngineParams(capturedHotwords),
            object : CreateEngineCallback {
                override fun onSuccess(engine: SpeechRecognitionEngine) {
                    runOnUiThread {
                        if (!active || requestGeneration != createGeneration) {
                            engine.shutdown()
                            return@runOnUiThread
                        }
                        if (replaying) {
                            this@MainActivity.engine = engine
                            engine.setListener(createListener())
                            engineLoading = false
                            progress.visibility = View.GONE
                            startSavedPcmReplay()
                            return@runOnUiThread
                        }
                        val decision = coldStartPttGate.engineReady(coldGeneration)
                        if (!decision.accepted || !listening) {
                            engine.shutdown()
                            engineLoading = false
                            progress.visibility = View.GONE
                            if (!listening) {
                                releaseModel(tvStatus.text.toString())
                            } else {
                                updateOperationControls()
                            }
                            return@runOnUiThread
                        }
                        this@MainActivity.engine = engine
                        engine.setListener(createListener())
                        engineLoading = false
                        progress.visibility = View.GONE
                        coldStartGeneration = -1
                        startSessionAndFlush(decision.finishAfterFlush)
                    }
                }

                override fun onError(errorCode: Int, errorMessage: String) {
                    runOnUiThread {
                        if (!active || requestGeneration != createGeneration) return@runOnUiThread
                        engineLoading = false
                        progress.visibility = View.GONE
                        if (replaying) {
                            failSavedPcmReplay("$errorCode $errorMessage")
                        } else {
                            coldStartPttGate.cancel()
                            coldStartGeneration = -1
                            listening = false
                            coldReleasePending = false
                            synchronized(stateLock) { preRoll.clear() }
                            stopCapture(flushTail = false)
                            finishActiveDebugRecord(
                                DebugRecordStore.STATUS_ERROR,
                                errorCode,
                                errorMessage,
                            )
                            setStatus(getString(R.string.status_engine_failed, "$errorCode $errorMessage"))
                            updateOperationControls()
                        }
                    }
                }
            },
        )
    }

    private fun createListener(): RecognitionListener = object : RecognitionListener {
        override fun onStart(sessionId: String, eventMessage: String) {
            runOnUiThread {
                if (!active) return@runOnUiThread
                if (sessionId == replaySessionId) {
                    setStatus(getString(R.string.replay_running))
                } else {
                    setStatus(getString(R.string.status_listening))
                }
            }
        }

        override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) {
            if (eventCode == DingqiaoEventCode.SPEAKER_VAD_REJECTED) {
                runOnUiThread {
                    if (active) setStatus("说话人 VAD：检测到非目标说话人，已截断")
                }
            }
        }

        override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
            runOnUiThread {
                if (!active) return@runOnUiThread
                if (result.isFinal) {
                    if (sessionId == replaySessionId) {
                        replayCompareText += result.result
                    } else {
                        liveCompareText += result.result
                        appendFinal(result)
                        tvPartial.text = ""
                    }
                } else if (sessionId != replaySessionId) {
                    activeDebugRecord?.updatePartial(result.result)
                    tvPartial.text = result.result
                }
                updateCaptureUi()
            }
        }

        override fun onComplete(sessionId: String, eventMessage: String) {
            runOnUiThread { if (active) handleComplete(sessionId) }
        }

        override fun onError(sessionId: String, errorCode: Int, errorMessage: String) {
            runOnUiThread { if (active) handleError(sessionId, errorCode, errorMessage) }
        }
    }

    private fun startListening() {
        if (!runtimeReady || listening || stoppingListening || replaying || playingCapture || modelReleaseInProgress) return
        startTapMs = SystemClock.elapsedRealtime()
        finalLines.clear()
        tvFinal.text = ""
        tvPartial.text = ""
        synchronized(stateLock) {
            preRoll.clear()
            preRollDroppedFrames = 0
            sessionId = null
            modelReady = false
        }
        sdkCapture.reset()
        captureSnapshot = null
        captureReady = false
        recorderStats = AudioRecorderStats()
        liveCompareText = ""
        replayCompareText = ""
        liveHasCompleted = false
        replayHasCompleted = false
        compareInfo = ""
        etCaseNote.setText("")
        tvCaseInfo.visibility = View.GONE

        val profile = CustomerScenarioProfiles.forScenario(customerScenario)
        capturedScenario = customerScenario
        capturedAudioSource = audioSource
        capturedHotwords = DemoPrefs.getUserHotwords(this)
        capturedVoiceprintId = if (profile.allowVoiceprint) DemoPrefs.getVoiceprintId(this) else null
        capturedVoiceprintVerify = profile.allowVoiceprint && voiceprintVerifyDesired && capturedVoiceprintId != null
        capturedSpeakerVad = profile.allowVoiceprint && speakerVadDesired && capturedVoiceprintId != null
        capturedPoliceEnhancement = policeEnhancementDesired
        activeDebugRecord = runCatching { debugRecordStore.begin() }
            .onFailure { toast("调试记录创建失败：${it.message ?: it.javaClass.simpleName}") }
            .getOrNull()

        listening = true
        coldReleasePending = false
        cardCapture.visibility = View.VISIBLE
        tvCaptureInfo.setText(R.string.sdk_pcm_capturing)
        updateCaptureUi()
        startCapture()
        coldStartGeneration = coldStartPttGate.begin()
        setStatus(getString(R.string.status_loading_model_with_audio))
        createEngineForOperation(coldStartGeneration)
        updateOperationControls()
    }

    private fun startSessionAndFlush(finishAfterFlush: Boolean) {
        val currentEngine = engine ?: return
        val sid = "demo-${System.currentTimeMillis()}"
        synchronized(stateLock) { sessionId = sid }
        activeDebugRecord?.addSession(sid)
        currentEngine.startListening(buildCapturedStartParams(sid))
        val buffered = synchronized(stateLock) {
            modelReady = true
            preRoll.toList().also { preRoll.clear() }
        }
        buffered.forEach { feedFrameLive(sid, it) }
        Log.i(TAG, "cold start ready in ${SystemClock.elapsedRealtime() - startTapMs}ms; preRoll=${buffered.size}; dropped=$preRollDroppedFrames")
        if (finishAfterFlush) {
            finishColdStartSession()
        } else {
            setStatus(getString(R.string.status_listening))
            updateOperationControls()
        }
    }

    private fun buildCapturedStartParams(sid: String): StartParams {
        val profile = CustomerScenarioProfiles.forScenario(capturedScenario)
        val extra = mutableMapOf<String, Any>(
            "enablePartialResult" to profile.enablePartialResult,
            "vadEnd" to profile.vadEndMs,
            "maxAudioDuration" to profile.maxAudioDurationMs,
            "endpointMaxUtteranceMs" to profile.endpointMaxUtteranceMs,
            "enableContinuousRecognition" to CustomerScenarioProfiles.usesContinuousRecognition(capturedScenario),
            "enablePoliceEnhancement" to capturedPoliceEnhancement,
        )
        profile.vadBeginMs?.let { extra["vadBegin"] = it }
        if (capturedVoiceprintVerify) extra["enableVoiceprintVerification"] = true
        if (capturedSpeakerVad) {
            extra["enableSpeakerVad"] = true
            extra["speakerVadThreshold"] = SPEAKER_VAD_THRESHOLD
            extra["speakerVadWindowMs"] = SPEAKER_VAD_WINDOW_MS
            extra["speakerVadHopMs"] = SPEAKER_VAD_HOP_MS
            extra["speakerVadConsecutiveBelow"] = SPEAKER_VAD_CONSECUTIVE_BELOW
        }
        capturedVoiceprintId?.let { extra["voiceprintIds"] = listOf(it) }
        return StartParams(sid, AudioInfo(), extra)
    }

    private fun writeFrameToCurrentSession(frame: ByteArray) {
        val current = synchronized(stateLock) {
            if (!listening) return
            if (!modelReady) {
                if (preRoll.size < MAX_PREROLL_FRAMES) preRoll += frame.copyOf() else preRollDroppedFrames += 1
                return
            }
            sessionId
        }
        if (current != null) feedFrameLive(current, frame)
    }

    private fun feedFrameLive(sid: String, frame: ByteArray) {
        if (sid != replaySessionId) {
            sdkCapture.capture(frame)
            activeDebugRecord?.appendPcmBytes(frame)
        }
        engine?.writeAudio(sid, frame)
    }

    private fun stopListening() {
        if (!listening || stoppingListening || coldReleasePending) return
        stoppingListening = true
        val sid = synchronized(stateLock) { sessionId }
        val coldGeneration = if (sid == null && engineLoading) coldStartGeneration else -1
        val waitsForColdEngine = coldGeneration >= 0 && coldStartPttGate.release(coldGeneration)
        recorderStats = stopCapture(flushTail = true)
        if (!waitsForColdEngine) saveSdkCaptureBestEffort()

        if (waitsForColdEngine) {
            coldReleasePending = true
            stoppingListening = false
            if (coldStartPttGate.captureStopped(coldGeneration)) {
                finishColdStartSession()
            } else {
                setStatus(getString(R.string.status_capture_cached))
                updateOperationControls()
            }
            return
        }

        listening = false
        stoppingListening = false
        synchronized(stateLock) {
            modelReady = false
            sessionId = null
            preRoll.clear()
        }
        setStatus(getString(R.string.status_finishing))
        updateOperationControls()
        if (sid != null) {
            engine?.finish(sid)
        } else {
            finishActiveDebugRecord(DebugRecordStore.STATUS_COMPLETED)
            releaseModel(getString(R.string.model_released))
        }
    }

    private fun finishColdStartSession() {
        val sid = synchronized(stateLock) { sessionId } ?: return
        saveSdkCaptureBestEffort()
        listening = false
        stoppingListening = false
        coldReleasePending = false
        synchronized(stateLock) {
            modelReady = false
            sessionId = null
            preRoll.clear()
        }
        setStatus(getString(R.string.status_finishing))
        updateOperationControls()
        engine?.finish(sid)
    }

    private fun startCapture() {
        if (recorder != null) return
        frameWriter = PcmFrameWriter { frame -> writeFrameToCurrentSession(frame) }
        recorder = AudioRecorder(
            gainDb = 0f,
            audioSource = capturedAudioSource,
            onPcm = { samples -> frameWriter?.accept(samples) },
            onError = { message ->
                runOnUiThread {
                    if (!active) return@runOnUiThread
                    val failedSid = synchronized(stateLock) { sessionId }
                    listening = false
                    coldReleasePending = false
                    coldStartPttGate.cancel()
                    coldStartGeneration = -1
                    stopCapture(flushTail = false)
                    synchronized(stateLock) {
                        sessionId = null
                        modelReady = false
                        preRoll.clear()
                    }
                    finishActiveDebugRecord(DebugRecordStore.STATUS_ERROR, errorMessage = message)
                    val status = "录音错误：$message"
                    setStatus(status)
                    if (failedSid != null) {
                        if (engine?.isBusy() == true) runCatching { engine?.cancel(failedSid) }
                        releaseModel(status)
                    } else {
                        updateOperationControls()
                    }
                }
            },
        ).also { it.start() }
    }

    private fun stopCapture(flushTail: Boolean): AudioRecorderStats {
        val stats = recorder?.stop() ?: recorderStats
        recorder = null
        if (flushTail) frameWriter?.flushFinalFrame() else frameWriter?.reset()
        frameWriter = null
        return stats
    }

    private fun handleComplete(completedSessionId: String) {
        if (completedSessionId == replaySessionId) {
            replayHasCompleted = true
            replaying = false
            replaySessionId = null
            compareInfo = if (liveCompareText == replayCompareText) {
                getString(R.string.replay_match)
            } else {
                getString(R.string.replay_different)
            }
            writeSdkCaptureMetadataBestEffort()
            updateCaptureUi()
            releaseModel(compareInfo)
            return
        }

        if (listening) {
            // An explicit vadBegin/max-duration condition ended the SDK session.
            listening = false
            coldReleasePending = false
            synchronized(stateLock) {
                sessionId = null
                modelReady = false
                preRoll.clear()
            }
            recorderStats = stopCapture(flushTail = false)
            saveSdkCaptureBestEffort()
            liveHasCompleted = true
            finishActiveDebugRecord(DebugRecordStore.STATUS_COMPLETED)
            writeSdkCaptureMetadataBestEffort()
            updateCaptureUi()
            releaseModel("SDK 已按 VAD/最长时长自动结束 · 模型已卸载")
        } else {
            liveHasCompleted = true
            finishActiveDebugRecord(DebugRecordStore.STATUS_COMPLETED)
            writeSdkCaptureMetadataBestEffort()
            updateCaptureUi()
            releaseModel(
                if (captureReady) "SDK PCM 已保存 · 可试听或原样重新识别 · 模型已卸载"
                else getString(R.string.model_released),
            )
        }
    }

    private fun handleError(failedSessionId: String, errorCode: Int, errorMessage: String) {
        if (failedSessionId == replaySessionId) {
            failSavedPcmReplay("$errorCode $errorMessage")
            return
        }
        listening = false
        coldReleasePending = false
        coldStartPttGate.cancel()
        stopCapture(flushTail = false)
        synchronized(stateLock) {
            sessionId = null
            modelReady = false
            preRoll.clear()
        }
        finishActiveDebugRecord(DebugRecordStore.STATUS_ERROR, errorCode, errorMessage)
        releaseModel("错误 $errorCode：$errorMessage")
    }

    private fun releaseModel(nextStatus: String) {
        val oldEngine = engine
        engine = null
        modelReady = false
        oldEngine?.shutdown()
        if (!runtimeReady || modelReleaseInProgress) {
            setStatus(nextStatus)
            updateOperationControls()
            return
        }
        modelReleaseInProgress = true
        progress.visibility = View.VISIBLE
        updateOperationControls()
        worker.execute {
            val failure = runCatching { SpeechRecognizeSdk.unloadModel() }.exceptionOrNull()
            runOnUiThread {
                if (!active) return@runOnUiThread
                modelReleaseInProgress = false
                progress.visibility = View.GONE
                setStatus(if (failure == null) nextStatus else "$nextStatus · 卸载失败：${failure.message}")
                updateOperationControls()
            }
        }
    }

    private fun saveSdkCaptureBestEffort() {
        runCatching { saveSdkCapture() }.onFailure {
            captureReady = false
            tvCaptureInfo.text = "SDK PCM 保存失败：${it.message ?: it.javaClass.simpleName}"
        }
    }

    private fun saveSdkCapture() {
        val snapshot = sdkCapture.snapshot()
        captureSnapshot = snapshot
        if (snapshot.frameCount == 0) {
            captureReady = false
            tvCaptureInfo.setText(R.string.sdk_pcm_no_frames)
            updateCaptureUi()
            return
        }
        WavIo.writePcmBytes(sdkCaptureFile(), snapshot.pcm)
        captureReady = true
        val suffix = if (snapshot.truncated) getString(R.string.sdk_pcm_truncated) else ""
        tvCaptureInfo.text = getString(
            R.string.sdk_pcm_saved,
            snapshot.frameCount,
            snapshot.durationMs / 1000.0,
            snapshot.rmsDbfs,
            recorderStats.maxCallbackGapMs,
            suffix,
        )
        writeSdkCaptureMetadataBestEffort()
        updateCaptureUi()
    }

    private fun sdkCaptureFile(): File = File(DingqiaoApp.workPath(), SDK_CAPTURE_WAV)
    private fun sdkCaptureMetadataFile(): File = File(DingqiaoApp.workPath(), SDK_CAPTURE_META)

    private fun writeSdkCaptureMetadataBestEffort() {
        runCatching { writeSdkCaptureMetadata() }
            .onFailure { Log.w(TAG, "metadata write failed", it) }
    }

    private fun writeSdkCaptureMetadata() {
        val snapshot = captureSnapshot ?: return
        if (!captureReady) return
        val samples = snapshot.pcm.size / 2
        val metadata = JSONObject()
            .put("wavPath", sdkCaptureFile().absolutePath)
            .put("adbPullPath", sdkCaptureFile().absolutePath)
            .put("sampleRate", SAMPLE_RATE)
            .put("channels", 1)
            .put("sampleFormat", "s16le")
            .put("audioSource", audioSourceName(capturedAudioSource))
            .put("customerScenario", scenarioName(capturedScenario))
            .put("softwareGainDb", 0)
            .put("frameBytes", SDK_FRAME_BYTES)
            .put("frameCount", snapshot.frameCount)
            .put("byteCount", snapshot.pcm.size)
            .put("durationMs", snapshot.durationMs)
            .put("rmsDbfs", String.format(Locale.US, "%.3f", snapshot.rmsDbfs).toDouble())
            .put("peak", snapshot.peak)
            .put("clipSamples", snapshot.clipSamples)
            .put("clipRate", if (samples > 0) snapshot.clipSamples.toDouble() / samples else 0.0)
            .put("truncated", snapshot.truncated)
            .put("captureThread", "AudioRecord")
            .put("capturerOverflowCount", recorderStats.overflowCount)
            .put("captureCallbackCount", recorderStats.callbackCount)
            .put("captureTotalBytes", recorderStats.totalBytes)
            .put("captureBufferSizeBytes", recorderStats.bufferSizeBytes)
            .put("captureMaxCallbackGapMs", recorderStats.maxCallbackGapMs)
            .put("captureLateCallbackCount", recorderStats.lateCallbackCount)
            .put("captureMaxCallbackWorkMs", recorderStats.maxCallbackWorkMs)
            .put("disablePrepack", true)
            .put("hotwords", JSONArray(capturedHotwords))
            .put("voiceprintId", capturedVoiceprintId ?: "")
            .put("voiceprintVerify", capturedVoiceprintVerify)
            .put("speakerVad", capturedSpeakerVad)
            .put("policeEnhancement", capturedPoliceEnhancement)
            .put("liveText", liveCompareText)
            .put("replayText", replayCompareText)
            .put(
                "comparison",
                if (!replayHasCompleted) "pending" else if (liveCompareText == replayCompareText) "exact-match" else "different",
            )
        sdkCaptureMetadataFile().writeText(metadata.toString(2) + "\n", Charsets.UTF_8)
    }

    private fun playLastSdkCapture() {
        if (!captureReady || listening || replaying || playingCapture || engineLoading || modelReleaseInProgress) return
        val pcm = WavIo.readPcm(sdkCaptureFile())
        if (pcm.isEmpty()) {
            toast("上次 SDK PCM 文件为空")
            return
        }
        playingCapture = true
        updateOperationControls()
        capturePlayer.play(pcm) {
            runOnUiThread {
                playingCapture = false
                updateOperationControls()
            }
        }
    }

    private fun replayLastSdkCapture() {
        val snapshot = captureSnapshot
        if (!captureReady || snapshot == null || snapshot.truncated || listening || replaying ||
            playingCapture || engineLoading || modelReleaseInProgress
        ) return
        capturePlayer.stop()
        replayHasCompleted = false
        replayCompareText = ""
        replaying = true
        compareInfo = getString(R.string.replay_loading)
        setStatus(compareInfo)
        updateCaptureUi()
        createEngineForOperation()
    }

    private fun startSavedPcmReplay() {
        val currentEngine = engine ?: return
        val pcm = WavIo.readPcmBytes(sdkCaptureFile())
        if (pcm.isEmpty() || pcm.size % SDK_FRAME_BYTES != 0) {
            failSavedPcmReplay("PCM 长度非法：${pcm.size}B")
            return
        }
        val sid = "replay-${System.currentTimeMillis()}"
        replaySessionId = sid
        currentEngine.startListening(buildCapturedStartParams(sid))
        updateOperationControls()
        worker.execute {
            try {
                val frames = pcm.size / SDK_FRAME_BYTES
                repeat(frames) { index ->
                    if (!replaying || replaySessionId != sid) return@execute
                    val offset = index * SDK_FRAME_BYTES
                    currentEngine.writeAudio(sid, pcm.copyOfRange(offset, offset + SDK_FRAME_BYTES))
                    if ((index + 1) % REPLAY_YIELD_EVERY_FRAMES == 0) Thread.yield()
                }
                if (replaying && replaySessionId == sid) currentEngine.finish(sid)
            } catch (t: Throwable) {
                runOnUiThread { failSavedPcmReplay(t.message ?: t.javaClass.simpleName) }
            }
        }
    }

    private fun failSavedPcmReplay(message: String) {
        val sid = replaySessionId
        if (sid != null && engine?.isBusy() == true) runCatching { engine?.cancel(sid) }
        replaying = false
        replaySessionId = null
        engineLoading = false
        progress.visibility = View.GONE
        compareInfo = getString(R.string.replay_failed, message)
        writeSdkCaptureMetadataBestEffort()
        updateCaptureUi()
        releaseModel(compareInfo)
    }

    private fun saveCurrentCase() {
        val snapshot = captureSnapshot ?: return
        if (!captureReady || snapshot.pcm.isEmpty()) return
        val profile = CustomerScenarioProfiles.forScenario(capturedScenario)
        val metadata = JSONObject()
            .put("customerScenario", scenarioName(capturedScenario))
            .put("audioSource", audioSourceName(capturedAudioSource))
            .put("sampleRate", SAMPLE_RATE)
            .put("channels", 1)
            .put("sampleFormat", "s16le")
            .put("frameBytes", SDK_FRAME_BYTES)
            .put("frameCount", snapshot.frameCount)
            .put("durationMs", snapshot.durationMs)
            .put("enablePartialResult", profile.enablePartialResult)
            .put("vadEnd", profile.vadEndMs)
            .put("maxAudioDuration", profile.maxAudioDurationMs)
            .put("endpointMaxUtteranceMs", profile.endpointMaxUtteranceMs)
            .put("voiceprintVerify", capturedVoiceprintVerify)
            .put("speakerVad", capturedSpeakerVad)
            .put("policeEnhancement", capturedPoliceEnhancement)
            .put("liveText", liveCompareText)
            .put("replayText", if (replayHasCompleted) replayCompareText else "")
            .put("rmsDbfs", snapshot.rmsDbfs)
            .put("peak", snapshot.peak)
            .put("clipSamples", snapshot.clipSamples)
            .put("truncated", snapshot.truncated)
            .put("capturerOverflowCount", recorderStats.overflowCount)
            .put("captureMaxCallbackGapMs", recorderStats.maxCallbackGapMs)
        profile.vadBeginMs?.let { metadata.put("vadBegin", it) }
        runCatching { caseStore.save(snapshot.pcm, etCaseNote.text?.toString().orEmpty(), metadata) }
            .onSuccess { result ->
                tvCaseInfo.visibility = View.VISIBLE
                tvCaseInfo.text = getString(R.string.case_saved, result.caseId)
                etCaseNote.setText("")
                toast("Case 已保存：${result.caseId}")
            }
            .onFailure {
                tvCaseInfo.visibility = View.VISIBLE
                tvCaseInfo.text = getString(R.string.case_failed, it.message ?: it.javaClass.simpleName)
                toast(tvCaseInfo.text.toString())
            }
    }

    private fun appendFinal(result: SpeechRecognitionResult) {
        if (result.result.isEmpty()) return
        activeDebugRecord?.addFinal(result.result, result.speakerSimilarity)
        if (finalLines.isNotEmpty()) finalLines.append('\n')
        result.speakerSimilarity?.let { score ->
            val start = finalLines.length
            finalLines.append(getString(R.string.speaker_score_tag, score))
            val end = finalLines.length
            finalLines.setSpan(
                ForegroundColorSpan(ContextCompat.getColor(this, R.color.brand_accent)),
                start,
                end,
                Spanned.SPAN_EXCLUSIVE_EXCLUSIVE,
            )
            finalLines.setSpan(StyleSpan(Typeface.BOLD), start, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            finalLines.append(' ')
        }
        finalLines.append(result.result)
        tvFinal.text = finalLines
    }

    private fun finishActiveDebugRecord(
        status: String,
        errorCode: Int? = null,
        errorMessage: String? = null,
    ): DebugRecordSummary? {
        val record = activeDebugRecord ?: return null
        activeDebugRecord = null
        return record.finish(status, errorCode, errorMessage)
    }

    private fun selectCustomerScenario(scenario: CustomerScenario) {
        if (isConfigurationLocked()) return
        customerScenario = scenario
        audioSource = CustomerScenarioProfiles.forScenario(scenario).audioSource
        setStatus("${scenarioLabel(scenario)} · SourceType=${audioSourceValue(audioSource)}")
        updateScenarioUi()
        refreshVoiceprintUi()
        updateOperationControls()
    }

    private fun selectAudioSource(source: DemoAudioSource) {
        if (isConfigurationLocked() || CustomerScenarioProfiles.forScenario(customerScenario).lockAudioSource) return
        audioSource = source
        setStatus("${scenarioLabel(customerScenario)} · SourceType=${audioSourceValue(source)}")
        updateScenarioUi()
    }

    private fun isConfigurationLocked(): Boolean =
        listening || replaying || engineLoading || modelReleaseInProgress || playingCapture

    private fun updateScenarioUi() {
        val profile = CustomerScenarioProfiles.forScenario(customerScenario)
        scenarioButtons.forEach { (scenario, button) -> tintSelection(button, scenario == customerScenario, false) }
        sourceButtons.forEach { (source, button) -> tintSelection(button, source == audioSource, true) }
        tvScenarioInfo.text = "SourceType=${audioSourceValue(audioSource)} · vadEnd=${profile.vadEndMs}ms · max=${formatMaxDuration(profile.maxAudioDurationMs)}"
    }

    private fun tintSelection(button: Button, selected: Boolean, sourceSelection: Boolean) {
        val color = when {
            selected && sourceSelection -> ContextCompat.getColor(this, R.color.brand_success)
            selected -> ContextCompat.getColor(this, R.color.brand_accent)
            else -> ContextCompat.getColor(this, R.color.brand_surface_alt)
        }
        button.backgroundTintList = ColorStateList.valueOf(color)
        button.setTextColor(
            ContextCompat.getColor(
                this,
                if (selected) R.color.brand_on_accent else R.color.brand_text_primary,
            ),
        )
    }

    private fun refreshVoiceprintUi() {
        if (!::tvVoiceprintInfo.isInitialized) return
        val modelFile = VoiceprintModelHelper.modelFile(DingqiaoApp.workPath())
        val modelReadyNow = VoiceprintModelHelper.isReady(modelFile)
        val id = DemoPrefs.getVoiceprintId(this)
        val profile = CustomerScenarioProfiles.forScenario(customerScenario)
        tvVoiceprintInfo.text = when {
            !profile.allowVoiceprint -> getString(R.string.scenario_voiceprint_disabled)
            !modelReadyNow && modelFile.exists() && !modelFile.canRead() -> getString(R.string.vp_model_unreadable)
            !modelReadyNow -> getString(R.string.vp_model_missing)
            id.isNullOrBlank() -> getString(R.string.vp_not_registered)
            else -> getString(R.string.vp_registered, id)
        }
        swVoiceprint.setOnCheckedChangeListener(null)
        swSpeakerVad.setOnCheckedChangeListener(null)
        if (id.isNullOrBlank()) {
            voiceprintVerifyDesired = false
            speakerVadDesired = false
        }
        swVoiceprint.isChecked = profile.allowVoiceprint && voiceprintVerifyDesired
        swSpeakerVad.isChecked = profile.allowVoiceprint && speakerVadDesired
        swVoiceprint.setOnCheckedChangeListener { _, checked -> onVoiceprintSwitch(checked) }
        swSpeakerVad.setOnCheckedChangeListener { _, checked -> onSpeakerVadSwitch(checked) }
    }

    private fun onVoiceprintSwitch(enabled: Boolean) {
        if (enabled && DemoPrefs.getVoiceprintId(this).isNullOrBlank()) {
            voiceprintVerifyDesired = false
            swVoiceprint.isChecked = false
            toast(getString(R.string.vp_need_register))
            return
        }
        voiceprintVerifyDesired = enabled
    }

    private fun onSpeakerVadSwitch(enabled: Boolean) {
        if (enabled && DemoPrefs.getVoiceprintId(this).isNullOrBlank()) {
            speakerVadDesired = false
            swSpeakerVad.isChecked = false
            toast(getString(R.string.vp_need_register))
            return
        }
        speakerVadDesired = enabled
        toast(getString(if (enabled) R.string.speaker_vad_enabled_hint else R.string.speaker_vad_disabled_hint))
    }

    private fun updateCaptureUi() {
        cardCapture.visibility = if (captureReady || listening || replaying) View.VISIBLE else View.GONE
        tvLiveCompare.visibility = if (liveHasCompleted) View.VISIBLE else View.GONE
        tvLiveCompare.text = getString(
            R.string.live_result_label,
            liveCompareText.ifEmpty { getString(R.string.empty_result_label) },
        )
        tvReplayCompare.visibility = if (replaying || replayHasCompleted) View.VISIBLE else View.GONE
        tvReplayCompare.text = getString(
            R.string.replay_result_label,
            if (!replayHasCompleted) getString(R.string.replay_waiting)
            else replayCompareText.ifEmpty { getString(R.string.empty_result_label) },
        )
        tvCompareInfo.visibility = if (compareInfo.isNotEmpty()) View.VISIBLE else View.GONE
        tvCompareInfo.text = compareInfo
    }

    private fun updateOperationControls() {
        if (!::btnTalk.isInitialized) return
        val profile = CustomerScenarioProfiles.forScenario(customerScenario)
        val configLocked = isConfigurationLocked()
        scenarioButtons.values.forEach { it.isEnabled = !configLocked }
        sourceButtons.values.forEach { it.isEnabled = !configLocked && !profile.lockAudioSource }
        val idPresent = !DemoPrefs.getVoiceprintId(this).isNullOrBlank()
        val voiceprintEnabled = profile.allowVoiceprint && idPresent && !configLocked
        swVoiceprint.isEnabled = voiceprintEnabled
        swSpeakerVad.isEnabled = voiceprintEnabled
        swPoliceEnhancement.isEnabled = !listening && !replaying && !engineLoading

        btnTalk.text = when {
            replaying -> getString(R.string.replaying_last_pcm)
            listening -> getString(R.string.btn_talk_stop)
            else -> getString(R.string.btn_talk_start)
        }
        btnTalk.isEnabled = runtimeReady && !stoppingListening && !coldReleasePending &&
            !replaying && !playingCapture && !modelReleaseInProgress
        btnPlayCapture.text = getString(if (playingCapture) R.string.playing_last_pcm else R.string.play_last_pcm)
        btnReplayCapture.text = getString(if (replaying) R.string.replaying_last_pcm else R.string.replay_last_pcm)
        btnPlayCapture.isEnabled = captureReady && !configLocked
        btnReplayCapture.isEnabled = captureReady && captureSnapshot?.truncated != true && !configLocked
        btnSaveCase.isEnabled = captureReady && !configLocked
        etCaseNote.isEnabled = !configLocked
        updateScenarioUi()
        refreshVoiceprintUi()
    }

    private fun reloadEngineForHotwords() {
        if (engine != null && !listening && !replaying) {
            releaseModel("热词已更新 · 下次识别将按新热词加载")
        } else {
            setStatus("热词已更新 · 下次识别将按新热词加载")
        }
        toast("热词已更新，下次识别按新热词加载")
    }

    private fun showMenu(anchor: View) {
        PopupMenu(this, anchor).apply {
            menuInflater.inflate(R.menu.menu_main, menu)
            menu.findItem(R.id.action_delete_voiceprint).isVisible =
                !VoiceprintHelper.registeredId(this@MainActivity).isNullOrBlank()
            setOnMenuItemClickListener { item ->
                if (listening || replaying || engineLoading) {
                    toast("请先结束当前识别")
                    return@setOnMenuItemClickListener true
                }
                when (item.itemId) {
                    R.id.action_hotwords -> {
                        hotwordsLauncher.launch(Intent(this@MainActivity, HotwordsActivity::class.java)); true
                    }
                    R.id.action_debug_records -> {
                        startActivity(Intent(this@MainActivity, DebugRecordsActivity::class.java)); true
                    }
                    R.id.action_voiceprint -> {
                        startActivity(Intent(this@MainActivity, VoiceprintEnrollActivity::class.java)); true
                    }
                    R.id.action_delete_voiceprint -> {
                        confirmDeleteVoiceprint(); true
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
                runCatching { VoiceprintHelper.deleteRegistered(this) }
                    .onSuccess {
                        voiceprintVerifyDesired = false
                        speakerVadDesired = false
                        refreshVoiceprintUi()
                        toast(getString(R.string.vp_delete_success, it ?: id))
                    }
                    .onFailure { toast(getString(R.string.vp_delete_failed, it.message ?: it.javaClass.simpleName)) }
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun scenarioLabel(scenario: CustomerScenario): String = when (scenario) {
        CustomerScenario.TAP_VAD -> getString(R.string.scenario_tap_vad)
        CustomerScenario.PTT -> getString(R.string.scenario_ptt)
        CustomerScenario.TRANSCRIPTION -> getString(R.string.scenario_transcription)
        CustomerScenario.FORM -> getString(R.string.scenario_form)
        CustomerScenario.MEETING_MINUTES -> getString(R.string.scenario_meeting_minutes)
    }

    private fun scenarioName(scenario: CustomerScenario): String = when (scenario) {
        CustomerScenario.TAP_VAD -> "tap-vad"
        CustomerScenario.PTT -> "ptt"
        CustomerScenario.TRANSCRIPTION -> "transcription"
        CustomerScenario.FORM -> "form"
        CustomerScenario.MEETING_MINUTES -> "meeting-minutes"
    }

    private fun audioSourceValue(source: DemoAudioSource): String = when (source) {
        DemoAudioSource.MIC -> "mic"
        DemoAudioSource.VOICE_RECOGNITION -> "voiceRecognition"
        DemoAudioSource.VOICE_COMMUNICATION -> "voiceCommunication"
    }

    private fun audioSourceName(source: DemoAudioSource): String = when (source) {
        DemoAudioSource.MIC -> "SOURCE_TYPE_MIC"
        DemoAudioSource.VOICE_RECOGNITION -> "SOURCE_TYPE_VOICE_RECOGNITION"
        DemoAudioSource.VOICE_COMMUNICATION -> "SOURCE_TYPE_VOICE_COMMUNICATION"
    }

    private fun formatMaxDuration(durationMs: Int): String =
        if (durationMs % 3_600_000 == 0) "${durationMs / 3_600_000}h" else "${durationMs}ms"

    private fun setStatus(text: String) {
        tvStatus.text = text
    }

    private fun toast(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
    }

    private companion object {
        const val TAG = "DingqiaoDemo"
        const val SAMPLE_RATE = 16_000
        const val SDK_FRAME_BYTES = 640
        const val MAX_PREROLL_FRAMES = 500
        const val REPLAY_YIELD_EVERY_FRAMES = 50
        const val SDK_CAPTURE_WAV = "last_sdk_input.wav"
        const val SDK_CAPTURE_META = "last_sdk_input.json"
        const val SPEAKER_VAD_THRESHOLD = 0.35f
        const val SPEAKER_VAD_WINDOW_MS = 1_500
        const val SPEAKER_VAD_HOP_MS = 500
        const val SPEAKER_VAD_CONSECUTIVE_BELOW = 2
    }
}
