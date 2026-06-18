package com.lits.tts.sample

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.ProgressBar
import android.widget.RadioGroup
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.Toolbar
import com.lits.tts.sdk.Callback
import com.lits.tts.sdk.CompleteResponse
import com.lits.tts.sdk.CompleteType
import com.lits.tts.sdk.CreateEngineParams
import com.lits.tts.sdk.PlayType
import com.lits.tts.sdk.QueueMode
import com.lits.tts.sdk.RunMode
import com.lits.tts.sdk.SpeakListener
import com.lits.tts.sdk.SpeakParams
import com.lits.tts.sdk.StartResponse
import com.lits.tts.sdk.StopResponse
import com.lits.tts.sdk.SynthesisResponse
import com.lits.tts.sdk.TextToSpeechEngine
import com.lits.tts.sdk.TextToSpeechSdk
import java.io.ByteArrayOutputStream
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

class MainActivity : AppCompatActivity() {
    private val mainHandler = Handler(Looper.getMainLooper())
    private val ioExecutor: ExecutorService = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "lits-tts-sample-io").apply { isDaemon = true }
    }
    private val requestCounter = AtomicInteger(0)
    private val logLines = ArrayDeque<String>()
    private val requestPlayTypes = ConcurrentHashMap<String, PlayType>()
    private val requestBuffers = ConcurrentHashMap<String, ByteArrayOutputStream>()
    private val requestChunkCounts = ConcurrentHashMap<String, Int>()
    private val requestSampleRates = ConcurrentHashMap<String, Int>()
    private val requestStartedAtMs = ConcurrentHashMap<String, Long>()
    private val player = PcmPlayer()

    private lateinit var inputText: EditText
    private lateinit var modeGroup: RadioGroup
    private lateinit var synthesizeButton: Button
    private lateinit var sdkPlaybackButton: Button
    private lateinit var playButton: Button
    private lateinit var saveButton: Button
    private lateinit var statusText: TextView
    private lateinit var metricsText: TextView
    private lateinit var logText: TextView
    private lateinit var progressBar: ProgressBar

    private var engine: TextToSpeechEngine? = null
    private var engineLanguage: String? = null
    private var lastAudio: ByteArray? = null
    private var lastSampleRate: Int = 16000
    private var busy: Boolean = false
    private var activeRequestId: String? = null
    private var loadingLanguage: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        setSupportActionBar(findViewById<Toolbar>(R.id.toolbar))
        supportActionBar?.setDisplayShowTitleEnabled(false)

        inputText = findViewById(R.id.edit_input)
        modeGroup = findViewById(R.id.group_mode)
        synthesizeButton = findViewById(R.id.button_synthesize)
        sdkPlaybackButton = findViewById(R.id.button_sdk_playback)
        playButton = findViewById(R.id.button_play)
        saveButton = findViewById(R.id.button_save)
        statusText = findViewById(R.id.text_status)
        metricsText = findViewById(R.id.text_metrics)
        logText = findViewById(R.id.text_log)
        progressBar = findViewById(R.id.progress_busy)

        configureWorkPath()
        modeGroup.check(R.id.radio_mode_mixed)
        modeGroup.setOnCheckedChangeListener { _, _ ->
            val language = selectedLanguage()
            applyPresetText(language)
            preloadEngine(language)
        }
        synthesizeButton.setOnClickListener { submitSynthesis(PlayType.SYNTHESIZE_ONLY) }
        sdkPlaybackButton.setOnClickListener { submitSynthesis(PlayType.SYNTHESIZE_AND_PLAY) }
        playButton.setOnClickListener { playLastAudio() }
        saveButton.setOnClickListener { saveLastAudio() }

        applyPresetText(selectedLanguage())
        setStatus(getString(R.string.status_ready))
        setMetrics(getString(R.string.metrics_placeholder))
        refreshActionState()
        appendLog("sample 已启动，当前页面参考 clean sample 的 TTS 卡片布局，只保留纯 TTS 流程。")
        preloadEngine(selectedLanguage())
    }

    override fun onDestroy() {
        player.stop()
        ioExecutor.shutdownNow()
        runCatching { engine?.shutdown() }
        engine = null
        super.onDestroy()
    }

    private fun configureWorkPath() {
        val workDir = File(filesDir, "lits-tts-work").apply { mkdirs() }
        TextToSpeechSdk.setWorkPath(workDir.absolutePath)
        appendLog("workPath=${workDir.absolutePath}")
    }

    private fun selectedLanguage(): String = when (modeGroup.checkedRadioButtonId) {
        R.id.radio_mode_en -> "en-US"
        else -> "zh-en"
    }

    private fun submitSynthesis(playType: PlayType) {
        val text = inputText.text?.toString()?.trim().orEmpty()
        if (text.isEmpty()) {
            setStatus(getString(R.string.status_empty_text))
            return
        }
        val language = selectedLanguage()
        val readyEngine = engine
        if (readyEngine == null || engineLanguage != language) {
            setStatus("\u6a21\u578b\u52a0\u8f7d\u4e2d\uff1a$language")
            preloadEngine(language)
            return
        }
        val requestId = nextRequestId(if (playType == PlayType.SYNTHESIZE_ONLY) "synth" else "speak")

        requestPlayTypes[requestId] = playType
        requestSampleRates.remove(requestId)
        requestChunkCounts.remove(requestId)
        requestStartedAtMs[requestId] = System.currentTimeMillis()
        if (playType == PlayType.SYNTHESIZE_ONLY) {
            lastAudio = null
        }
        requestBuffers[requestId] = ByteArrayOutputStream()
        requestChunkCounts[requestId] = 0
        refreshActionState()

        val actionText = if (playType == PlayType.SYNTHESIZE_ONLY) "\u5f00\u59cb\u5408\u6210" else "SDK \u76f4\u63a5\u64ad\u62a5"
        setStatus("$actionText\uff1a$requestId")
        setMetrics(getString(R.string.metrics_placeholder))
        appendLog("\u63d0\u4ea4\u8bf7\u6c42 requestId=$requestId language=$language playType=$playType")
        beginBusy(requestId)

        runCatching {
            readyEngine.speak(
                text,
                SpeakParams(
                    requestId = requestId,
                    playType = playType,
                    queueMode = QueueMode.PREEMPT,
                    languageContext = if (language == "en-US") "en-US" else "zh-en",
                ),
            )
        }.onFailure { error ->
            requestPlayTypes.remove(requestId)
            requestBuffers.remove(requestId)
            requestChunkCounts.remove(requestId)
            requestSampleRates.remove(requestId)
            requestStartedAtMs.remove(requestId)
            endBusy(requestId)
            setStatus("\u63d0\u4ea4\u8bf7\u6c42\u5931\u8d25\uff1a${error.message ?: "unknown"}")
            appendLog("speak failed requestId=$requestId message=${error.message}")
        }
    }

    private fun playLastAudio() {
        val audio = lastAudio ?: return
        playButton.isEnabled = false
        setStatus(getString(R.string.status_playing_result))
        player.play(audio, lastSampleRate) {
            mainHandler.post {
                refreshActionState()
                setStatus(getString(R.string.status_play_result_done))
            }
        }
    }

    private fun saveLastAudio() {
        val audio = lastAudio ?: return
        val sampleRate = lastSampleRate
        ioExecutor.execute {
            val file = File(getExternalFilesDir(null), "tts-${timestamp()}.wav")
            runCatching {
                WavIo.write(file, audio, sampleRate)
            }.onSuccess {
                mainHandler.post {
                    setStatus(getString(R.string.status_saved, file.absolutePath))
                    appendLog("已保存 WAV：${file.absolutePath}")
                }
            }.onFailure { error ->
                mainHandler.post {
                    setStatus(getString(R.string.status_save_failed, error.message ?: "unknown"))
                    appendLog("保存 WAV 失败：${error.message}")
                }
            }
        }
    }

    private fun preloadEngine(language: String) {
        val current = engine
        if (current != null && engineLanguage == language) {
            setStatus("\u6a21\u578b\u5df2\u52a0\u8f7d\uff1a$language")
            refreshActionState()
            return
        }
        if (loadingLanguage == language) {
            return
        }
        val previousEngine = engine
        if (previousEngine != null) {
            engine = null
            engineLanguage = null
            player.stop()
            ioExecutor.execute { runCatching { previousEngine.shutdown() } }
        }
        val loadRequestId = nextRequestId("preload")
        loadingLanguage = language
        setStatus("\u6b63\u5728\u52a0\u8f7d\u6a21\u578b\uff1a$language")
        setMetrics(getString(R.string.metrics_placeholder))
        appendLog("\u5f00\u59cb\u52a0\u8f7d\u6a21\u578b language=$language requestId=$loadRequestId")
        beginBusy(loadRequestId)
        val voiceId = "lits-female-01"
        TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = language,
                mode = RunMode.OFFLINE,
                voiceId = voiceId,
            ),
            object : Callback<TextToSpeechEngine> {
                override fun onSuccess(result: TextToSpeechEngine) {
                    result.setListener(sampleListener)
                    mainHandler.post {
                        if (loadingLanguage != language) {
                            runCatching { result.shutdown() }
                            return@post
                        }
                        engine = result
                        engineLanguage = language
                        loadingLanguage = null
                        endBusy(loadRequestId)
                        setStatus("\u6a21\u578b\u52a0\u8f7d\u5b8c\u6210\uff1a$language")
                        appendLog("\u6a21\u578b\u52a0\u8f7d\u5b8c\u6210 language=$language requestId=$loadRequestId voiceId=$voiceId")
                    }
                }

                override fun onError(errorCode: Int, errorMessage: String) {
                    mainHandler.post {
                        if (loadingLanguage != language) {
                            return@post
                        }
                        loadingLanguage = null
                        endBusy(loadRequestId)
                        setStatus("\u6a21\u578b\u52a0\u8f7d\u5931\u8d25\uff1a$errorMessage")
                        appendLog("\u6a21\u578b\u52a0\u8f7d\u5931\u8d25 language=$language requestId=$loadRequestId code=$errorCode message=$errorMessage")
                    }
                }
            },
        )
    }

    private fun ensureEngine(language: String): TextToSpeechEngine {
        val current = engine
        if (current != null && engineLanguage == language) {
            return current
        }
        if (current != null) {
            runCatching { current.shutdown() }
            player.stop()
        }
        val voiceId = "lits-female-01"
        return TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = language,
                mode = RunMode.OFFLINE,
                voiceId = voiceId,
            ),
        ).also { created ->
            created.setListener(sampleListener)
            engine = created
            engineLanguage = language
            appendLog("已创建引擎 language=$language voiceId=$voiceId")
        }
    }

    private fun applyPresetText(language: String) {
        val preset = if (language == "en-US") {
            "Welcome to the Lits delivery TTS sample. Room 204 is ready."
        } else {
            "欢迎使用 Lits delivery 纯 TTS sample，room 204 is ready."
        }
        inputText.setText(preset)
        inputText.setSelection(preset.length)
        if (!busy) {
            setStatus(getString(R.string.status_ready))
        }
    }

    private fun nextRequestId(prefix: String): String {
        val index = requestCounter.incrementAndGet()
        val time = SimpleDateFormat("HHmmss", Locale.US).format(Date())
        return "$prefix-$time-$index"
    }

    private fun timestamp(): String = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date())

    private fun setStatus(text: String) {
        mainHandler.post { statusText.text = text }
    }

    private fun setMetrics(text: String) {
        mainHandler.post { metricsText.text = text }
    }

    private fun appendLog(text: String) {
        Log.i("LitsTtsSample", text)
        mainHandler.post {
            val time = SimpleDateFormat("HH:mm:ss", Locale.US).format(Date())
            logLines += "[$time] $text"
            while (logLines.size > 60) {
                logLines.removeFirst()
            }
            logText.text = logLines.joinToString(separator = "\n")
        }
    }

    private fun beginBusy(requestId: String) {
        activeRequestId = requestId
        busy = true
        refreshActionState()
        mainHandler.post { progressBar.visibility = View.VISIBLE }
    }

    private fun endBusy(requestId: String) {
        if (activeRequestId != requestId) {
            return
        }
        activeRequestId = null
        busy = false
        refreshActionState()
        mainHandler.post { progressBar.visibility = View.GONE }
    }

    private fun refreshActionState() {
        mainHandler.post {
            synthesizeButton.isEnabled = !busy
            sdkPlaybackButton.isEnabled = !busy
            playButton.isEnabled = !busy && lastAudio?.isNotEmpty() == true
            saveButton.isEnabled = !busy && lastAudio?.isNotEmpty() == true
            for (index in 0 until modeGroup.childCount) {
                modeGroup.getChildAt(index).isEnabled = !busy
            }
        }
    }

    private val sampleListener = object : SpeakListener {
        override fun onStart(requestId: String, response: StartResponse) {
            requestSampleRates[requestId] = response.sampleRate
            requestStartedAtMs[requestId] = System.currentTimeMillis()
            val playType = requestPlayTypes[requestId]
            val status = if (playType == PlayType.SYNTHESIZE_AND_PLAY) {
                "正在合成并准备播报：$requestId"
            } else {
                "正在合成：$requestId"
            }
            setStatus(status)
            setMetrics(getString(R.string.metrics_placeholder))
            appendLog(
                "onStart requestId=$requestId sampleRate=${response.sampleRate} sampleBit=${response.sampleBit} channel=${response.audioChannel}",
            )
        }

        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {
            requestBuffers[requestId]?.write(audio, 0, audio.size)
            requestChunkCounts.compute(requestId) { _, count -> (count ?: 0) + 1 }
            appendLog("onData requestId=$requestId sequence=${response.sequence} bytes=${audio.size}")
        }

        override fun onComplete(requestId: String, response: CompleteResponse) {
            when (response.type) {
                CompleteType.SYNTHESIS_COMPLETE -> {
                    val synthesisMs =
                        (System.currentTimeMillis() - (requestStartedAtMs[requestId] ?: System.currentTimeMillis()))
                            .coerceAtLeast(0L)
                    val buffer = requestBuffers.remove(requestId)
                    val audioBytes = buffer?.toByteArray() ?: ByteArray(0)
                    val sampleRate = requestSampleRates[requestId] ?: 16000
                    requestChunkCounts.remove(requestId)
                    val audioDurationMs = audioDurationMs(audioBytes.size, sampleRate)
                    if (requestPlayTypes[requestId] == PlayType.SYNTHESIZE_ONLY) {
                        lastAudio = audioBytes
                        lastSampleRate = sampleRate
                        val hasAudio = lastAudio?.isNotEmpty() == true
                        endBusy(requestId)
                        if (!hasAudio) {
                            refreshActionState()
                        }
                        setStatus(getString(R.string.status_synth_done, requestId))
                        setMetrics(
                            getString(
                                R.string.metrics_format_pcm,
                                sampleRate,
                                synthesisMs,
                                audioDurationMs,
                                formatRtf(synthesisMs, audioDurationMs),
                            ),
                        )
                    } else {
                        setStatus(getString(R.string.status_sdk_playback_started, requestId))
                        setMetrics(
                            getString(
                                R.string.metrics_format_sdk_playback,
                                sampleRate,
                                synthesisMs,
                                audioDurationMs,
                                formatRtf(synthesisMs, audioDurationMs),
                            ),
                        )
                    }
                }

                CompleteType.PLAYBACK_COMPLETE -> {
                    endBusy(requestId)
                    setStatus(getString(R.string.status_sdk_playback_done, requestId))
                }
            }
            if (response.type == CompleteType.PLAYBACK_COMPLETE || requestPlayTypes[requestId] == PlayType.SYNTHESIZE_ONLY) {
                requestPlayTypes.remove(requestId)
                requestSampleRates.remove(requestId)
                requestStartedAtMs.remove(requestId)
            }
            appendLog("onComplete requestId=$requestId type=${response.type} message=${response.message}")
        }

        override fun onStop(requestId: String, response: StopResponse) {
            requestPlayTypes.remove(requestId)
            requestBuffers.remove(requestId)
            requestChunkCounts.remove(requestId)
            requestSampleRates.remove(requestId)
            requestStartedAtMs.remove(requestId)
            player.stop()
            endBusy(requestId)
            setStatus(getString(R.string.status_stopped, requestId))
            appendLog("onStop requestId=$requestId type=${response.type} message=${response.message}")
        }

        override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
            requestPlayTypes.remove(requestId)
            requestBuffers.remove(requestId)
            requestChunkCounts.remove(requestId)
            requestSampleRates.remove(requestId)
            requestStartedAtMs.remove(requestId)
            player.stop()
            endBusy(requestId)
            setStatus(getString(R.string.status_error, requestId, errorCode, errorMessage))
            appendLog("onError requestId=$requestId code=$errorCode message=$errorMessage")
        }
    }

    private fun audioDurationMs(totalBytes: Int, sampleRate: Int): Long {
        if (sampleRate <= 0) return 0L
        return totalBytes.toLong() * 1000L / (sampleRate.toLong() * 2L)
    }

    private fun formatRtf(synthesisMs: Long, audioDurationMs: Long): String {
        if (audioDurationMs <= 0L) return "--"
        return String.format(Locale.US, "%.2f", synthesisMs.toDouble() / audioDurationMs.toDouble())
    }
}
