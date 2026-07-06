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
    private val requestFirstChunkAtMs = ConcurrentHashMap<String, Long>()
    private val requestWarmupFlags = ConcurrentHashMap<String, Boolean>()
    private val requestStreamingFlags = ConcurrentHashMap<String, Boolean>()
    private val requestDataPaths = ConcurrentHashMap<String, String>()
    private val requestModelInfos = ConcurrentHashMap<String, String>()
    private val requestLoadProfiles = ConcurrentHashMap<String, String>()
    private val requestProfiles = ConcurrentHashMap<String, String>()
    private val engineLoadStartedAtMs = ConcurrentHashMap<String, Long>()
    private val engineLoadMsByLanguage = ConcurrentHashMap<String, Long>()
    private val player = PcmPlayer()

    private lateinit var inputText: EditText
    private lateinit var chunkSizeInput: EditText
    private lateinit var pcmQueueCapacityInput: EditText
    private lateinit var speedInput: EditText
    private lateinit var modeGroup: RadioGroup
    private lateinit var synthesizeButton: Button
    private lateinit var sdkPlaybackButton: Button
    private lateinit var warmupButton: Button
    private lateinit var playButton: Button
    private lateinit var saveButton: Button
    private lateinit var stopButton: Button
    private lateinit var statusText: TextView
    private lateinit var metricsText: TextView
    private lateinit var logText: TextView
    private lateinit var progressBar: ProgressBar

    private var engine: TextToSpeechEngine? = null
    private var engineLanguage: String? = null
    private var lastAudio: ByteArray? = null
    private var lastSampleRate: Int = 16000
    private var busy: Boolean = false
    private var localPlaying: Boolean = false
    private var activeRequestId: String? = null
    private var loadingLanguage: String? = null
    private var warmupDone: Boolean = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        setSupportActionBar(findViewById<Toolbar>(R.id.toolbar))
        supportActionBar?.setDisplayShowTitleEnabled(false)

        inputText = findViewById(R.id.edit_input)
        chunkSizeInput = findViewById(R.id.edit_chunk_size)
        pcmQueueCapacityInput = findViewById(R.id.edit_pcm_queue_capacity)
        speedInput = findViewById(R.id.edit_speed)
        modeGroup = findViewById(R.id.group_mode)
        synthesizeButton = findViewById(R.id.button_synthesize)
        sdkPlaybackButton = findViewById(R.id.button_sdk_playback)
        warmupButton = findViewById(R.id.button_warmup)
        playButton = findViewById(R.id.button_play)
        saveButton = findViewById(R.id.button_save)
        stopButton = findViewById(R.id.button_stop)
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
        warmupButton.setOnClickListener { submitWarmup(autoTriggered = false) }
        playButton.setOnClickListener { playLastAudio() }
        saveButton.setOnClickListener { saveLastAudio() }
        stopButton.setOnClickListener { stopCurrentWork() }

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
        val baseDir = getExternalFilesDir(null) ?: filesDir
        val workDir = File(baseDir, "lits-tts-work").apply { mkdirs() }
        TextToSpeechSdk.setWorkPath(workDir.absolutePath)
        appendLog("workPath=${workDir.absolutePath}")
    }

    private fun selectedLanguage(): String = when (modeGroup.checkedRadioButtonId) {
        R.id.radio_mode_en -> "en-US"
        else -> "zh-en"
    }

    private fun voiceIdForLanguage(language: String): String = when (language) {
        "en-US" -> VOICE_ID_SPEAKER_0
        else -> VOICE_ID_SPEAKER_1
    }

    private fun selectedChunkSize(): Int {
        val value = chunkSizeInput.text?.toString()?.trim()?.toIntOrNull()
        return value?.takeIf { it > 0 } ?: DEFAULT_STREAMING_CHUNK_SIZE
    }

    private fun selectedPcmQueueCapacity(): Int {
        val value = pcmQueueCapacityInput.text?.toString()?.trim()?.toIntOrNull()
        return value?.takeIf { it > 0 } ?: DEFAULT_PCM_QUEUE_CAPACITY
    }

    private fun selectedSpeed(): Float {
        val value = speedInput.text?.toString()?.trim()?.toFloatOrNull()
        return value?.takeIf { it.isFinite() }?.coerceIn(0.5f, 2.0f) ?: 1.0f
    }

    private fun submitSynthesis(playType: PlayType) {
        val text = inputText.text?.toString()?.trim().orEmpty()
        if (text.isEmpty()) {
            setStatus(getString(R.string.status_empty_text))
            return
        }
        val language = selectedLanguage()
        val readyEngine = engine
        val chunkSize = selectedChunkSize()
        val pcmQueueCapacity = selectedPcmQueueCapacity()
        val speed = selectedSpeed()
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
        requestFirstChunkAtMs.remove(requestId)
        requestWarmupFlags[requestId] = false
        requestStreamingFlags.remove(requestId)
        requestDataPaths.remove(requestId)
        requestModelInfos.remove(requestId)
        requestLoadProfiles.remove(requestId)
        requestProfiles.remove(requestId)
        if (playType == PlayType.SYNTHESIZE_ONLY) {
            lastAudio = null
        }
        requestBuffers[requestId] = ByteArrayOutputStream()
        requestChunkCounts[requestId] = 0
        refreshActionState()

        val actionText = if (playType == PlayType.SYNTHESIZE_ONLY) "\u5f00\u59cb\u5408\u6210" else "SDK \u76f4\u63a5\u64ad\u62a5"
        setStatus("$actionText\uff1a$requestId")
        setMetrics(getString(R.string.metrics_placeholder))
        appendLog("提交请求 requestId=$requestId language=$language playType=$playType speed=$speed chunkSize=$chunkSize pcmQueueCapacity=$pcmQueueCapacity")
        beginBusy(requestId)

        runCatching {
            readyEngine.speak(
                text,
                SpeakParams(
                    requestId = requestId,
                    speed = speed,
                    playType = playType,
                    queueMode = QueueMode.PREEMPT,
                    languageContext = if (language == "en-US") "en-US" else "zh-en",
                    extraParams = mapOf(
                        "streamingChunkSize" to chunkSize,
                        "pcmQueueCapacity" to pcmQueueCapacity,
                    ),
                ),
            )
        }.onFailure { error ->
            requestPlayTypes.remove(requestId)
            requestBuffers.remove(requestId)
            requestChunkCounts.remove(requestId)
            requestSampleRates.remove(requestId)
            requestStartedAtMs.remove(requestId)
            requestFirstChunkAtMs.remove(requestId)
            requestWarmupFlags.remove(requestId)
            requestStreamingFlags.remove(requestId)
            requestDataPaths.remove(requestId)
            requestModelInfos.remove(requestId)
            requestLoadProfiles.remove(requestId)
            requestProfiles.remove(requestId)
            endBusy(requestId)
            setStatus("\u63d0\u4ea4\u8bf7\u6c42\u5931\u8d25\uff1a${error.message ?: "unknown"}")
            appendLog("speak failed requestId=$requestId message=${error.message}")
        }
    }

    private fun submitWarmup(autoTriggered: Boolean) {
        val language = selectedLanguage()
        val readyEngine = engine
        if (readyEngine == null || engineLanguage != language) {
            setStatus("\u6a21\u578b\u52a0\u8f7d\u4e2d\uff1a$language")
            preloadEngine(language)
            return
        }
        val requestId = nextRequestId("warmup")
        val chunkSize = selectedChunkSize()
        val pcmQueueCapacity = selectedPcmQueueCapacity()
        val speed = selectedSpeed()
        requestPlayTypes[requestId] = PlayType.SYNTHESIZE_ONLY
        requestWarmupFlags[requestId] = true
        requestSampleRates.remove(requestId)
        requestChunkCounts.remove(requestId)
        requestStartedAtMs[requestId] = System.currentTimeMillis()
        requestFirstChunkAtMs.remove(requestId)
        requestStreamingFlags.remove(requestId)
        requestDataPaths.remove(requestId)
        requestModelInfos.remove(requestId)
        requestLoadProfiles.remove(requestId)
        requestProfiles.remove(requestId)
        requestBuffers[requestId] = ByteArrayOutputStream()
        requestChunkCounts[requestId] = 0
        refreshActionState()

        setStatus(getString(R.string.status_warming_up, requestId))
        setMetrics(buildMetricsText(null, null, null, null, 0L, 0))
        appendLog(
            if (autoTriggered) {
                "自动 Warmup requestId=$requestId language=$language speed=$speed chunkSize=$chunkSize pcmQueueCapacity=$pcmQueueCapacity"
            } else {
                "提交 Warmup requestId=$requestId language=$language speed=$speed chunkSize=$chunkSize pcmQueueCapacity=$pcmQueueCapacity"
            },
        )
        beginBusy(requestId)

        runCatching {
            readyEngine.speak(
                if (language == "en-US") "hello." else "你好。",
                SpeakParams(
                    requestId = requestId,
                    speed = speed,
                    playType = PlayType.SYNTHESIZE_ONLY,
                    queueMode = QueueMode.PREEMPT,
                    languageContext = if (language == "en-US") "en-US" else "zh-en",
                    extraParams = mapOf(
                        "streamingChunkSize" to chunkSize,
                        "pcmQueueCapacity" to pcmQueueCapacity,
                    ),
                ),
            )
        }.onFailure { error ->
            requestPlayTypes.remove(requestId)
            requestWarmupFlags.remove(requestId)
            requestBuffers.remove(requestId)
            requestChunkCounts.remove(requestId)
            requestSampleRates.remove(requestId)
            requestStartedAtMs.remove(requestId)
            requestFirstChunkAtMs.remove(requestId)
            requestStreamingFlags.remove(requestId)
            requestDataPaths.remove(requestId)
            requestModelInfos.remove(requestId)
            requestLoadProfiles.remove(requestId)
            requestProfiles.remove(requestId)
            endBusy(requestId)
            setStatus("\u9884\u70ed\u5931\u8d25\uff1a${error.message ?: "unknown"}")
            appendLog("warmup failed requestId=$requestId message=${error.message}")
        }
    }

    private fun playLastAudio() {
        val audio = lastAudio ?: return
        localPlaying = true
        playButton.isEnabled = false
        refreshActionState()
        setStatus(getString(R.string.status_playing_result))
        player.play(audio, lastSampleRate) {
            mainHandler.post {
                localPlaying = false
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

    private fun stopCurrentWork() {
        player.stop()
        localPlaying = false
        runCatching { engine?.stop() }
        val requestId = activeRequestId
        if (requestId != null) {
            endBusy(requestId)
        } else {
            refreshActionState()
        }
        setStatus(getString(R.string.status_stop_current))
        appendLog("stop current work")
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
        engineLoadStartedAtMs[language] = System.currentTimeMillis()
        setStatus("\u6b63\u5728\u52a0\u8f7d\u6a21\u578b\uff1a$language")
        setMetrics(buildMetricsText(null, null, null, null, 0L, 0))
        appendLog("\u5f00\u59cb\u52a0\u8f7d\u6a21\u578b language=$language requestId=$loadRequestId")
        beginBusy(loadRequestId)
        val voiceId = voiceIdForLanguage(language)
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
                        val loadMs = (System.currentTimeMillis() - (engineLoadStartedAtMs.remove(language)
                            ?: System.currentTimeMillis())).coerceAtLeast(0L)
                        engineLoadMsByLanguage[language] = loadMs
                        endBusy(loadRequestId)
                        setStatus("\u6a21\u578b\u52a0\u8f7d\u5b8c\u6210\uff1a$language")
                        setMetrics(buildMetricsText(null, null, null, null, 0L, 0))
                        appendLog("\u6a21\u578b\u52a0\u8f7d\u5b8c\u6210 language=$language requestId=$loadRequestId voiceId=$voiceId")
                        if (!warmupDone) {
                            submitWarmup(autoTriggered = true)
                        }
                    }
                }

                override fun onError(errorCode: Int, errorMessage: String) {
                    mainHandler.post {
                        if (loadingLanguage != language) {
                            return@post
                        }
                        loadingLanguage = null
                        engineLoadStartedAtMs.remove(language)
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
        val voiceId = voiceIdForLanguage(language)
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
            val uiBusy = busy || localPlaying
            synthesizeButton.isEnabled = !uiBusy
            sdkPlaybackButton.isEnabled = !uiBusy
            warmupButton.isEnabled = !uiBusy
            playButton.isEnabled = !uiBusy && lastAudio?.isNotEmpty() == true
            saveButton.isEnabled = !uiBusy && lastAudio?.isNotEmpty() == true
            stopButton.isEnabled = busy || localPlaying
            chunkSizeInput.isEnabled = !uiBusy
            pcmQueueCapacityInput.isEnabled = !uiBusy
            speedInput.isEnabled = !uiBusy
            for (index in 0 until modeGroup.childCount) {
                modeGroup.getChildAt(index).isEnabled = !uiBusy
            }
        }
    }

    private val sampleListener = object : SpeakListener {
        override fun onStart(requestId: String, response: StartResponse) {
            requestSampleRates[requestId] = response.sampleRate
            requestStartedAtMs[requestId] = System.currentTimeMillis()
            requestFirstChunkAtMs.remove(requestId)
            requestStreamingFlags[requestId] = response.isStreaming
            requestDataPaths[requestId] = response.dataPath
            if (response.modelInfo.isNotBlank()) {
                requestModelInfos[requestId] = response.modelInfo
            }
            if (response.loadProfileInfo.isNotBlank()) {
                requestLoadProfiles[requestId] = response.loadProfileInfo
            }
            val playType = requestPlayTypes[requestId]
            val status = if (playType == PlayType.SYNTHESIZE_AND_PLAY) {
                "正在合成并准备播报：$requestId"
            } else {
                "正在合成：$requestId"
            }
            setStatus(status)
            setMetrics(
                buildMetricsText(
                    playType = playType,
                    sampleRate = response.sampleRate,
                    firstPacketMs = null,
                    synthesisMs = null,
                    audioDurationMs = 0L,
                    chunkCount = 0,
                    requestId = requestId,
                ),
            )
            appendLog(
                "onStart requestId=$requestId sampleRate=${response.sampleRate} sampleBit=${response.sampleBit} channel=${response.audioChannel} " +
                    "isStreaming=${response.isStreaming} dataPath=${response.dataPath} modelSource=${response.modelSource} " +
                    "modelInfo=${response.modelInfo} loadProfile=${response.loadProfileInfo}",
            )
        }

        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {
            requestBuffers[requestId]?.write(audio, 0, audio.size)
            requestChunkCounts.compute(requestId) { _, count -> (count ?: 0) + 1 }
            requestFirstChunkAtMs.putIfAbsent(requestId, System.currentTimeMillis())
            requestStreamingFlags[requestId] = response.isStreaming
            requestDataPaths[requestId] = response.chunkSource
            val startedAtMs = requestStartedAtMs[requestId]
            val firstChunkMs = requestFirstChunkAtMs[requestId]
            val sampleRate = requestSampleRates[requestId] ?: 16000
            val chunkCount = requestChunkCounts[requestId] ?: 0
            val totalBytes = requestBuffers[requestId]?.size() ?: 0
            setMetrics(
                buildMetricsText(
                    requestId = requestId,
                    playType = requestPlayTypes[requestId],
                    sampleRate = sampleRate,
                    firstPacketMs = if (startedAtMs != null && firstChunkMs != null) {
                        (firstChunkMs - startedAtMs).coerceAtLeast(0L)
                    } else {
                        null
                    },
                    synthesisMs = if (startedAtMs != null) {
                        (System.currentTimeMillis() - startedAtMs).coerceAtLeast(0L)
                    } else {
                        null
                    },
                    audioDurationMs = audioDurationMs(totalBytes, sampleRate),
                    chunkCount = chunkCount,
                ),
            )
            appendLog(
                "onData requestId=$requestId sequence=${response.sequence} bytes=${audio.size} " +
                    "isStreaming=${response.isStreaming} chunkSource=${response.chunkSource}",
            )
        }

        override fun onComplete(requestId: String, response: CompleteResponse) {
            when (response.type) {
                CompleteType.SYNTHESIS_COMPLETE -> {
                    if (response.profilingInfo.isNotBlank()) {
                        requestProfiles[requestId] = response.profilingInfo
                    }
                    val startedAtMs = requestStartedAtMs[requestId]
                    val wallClockSynthesisMs =
                        (System.currentTimeMillis() - (startedAtMs ?: System.currentTimeMillis())).coerceAtLeast(0L)
                    val synthesisMs = response.synthesisMs.takeIf { it >= 0L } ?: wallClockSynthesisMs
                    val buffer = requestBuffers.remove(requestId)
                    val audioBytes = buffer?.toByteArray() ?: ByteArray(0)
                    val sampleRate = requestSampleRates[requestId] ?: 16000
                    val chunkCount = requestChunkCounts.remove(requestId) ?: 0
                    val firstChunkAtMs = requestFirstChunkAtMs[requestId]
                    val firstPacketMs = response.firstPacketMs.takeIf { it >= 0L } ?: if (startedAtMs != null && firstChunkAtMs != null) {
                        (firstChunkAtMs - startedAtMs).coerceAtLeast(0L)
                    } else {
                        null
                    }
                    val isWarmup = requestWarmupFlags[requestId] == true
                    val audioDurationMs = response.audioDurationMs.takeIf { it > 0L } ?: audioDurationMs(audioBytes.size, sampleRate)
                    if (isWarmup) {
                        warmupDone = true
                        endBusy(requestId)
                        setStatus(getString(R.string.status_warmup_done, requestId))
                        setMetrics(
                            buildMetricsText(
                                requestId = requestId,
                                playType = null,
                                sampleRate = sampleRate,
                                firstPacketMs = firstPacketMs,
                                synthesisMs = synthesisMs,
                                audioDurationMs = audioDurationMs,
                                chunkCount = chunkCount,
                            ),
                        )
                    } else if (requestPlayTypes[requestId] == PlayType.SYNTHESIZE_ONLY) {
                        lastAudio = audioBytes
                        lastSampleRate = sampleRate
                        val hasAudio = lastAudio?.isNotEmpty() == true
                        endBusy(requestId)
                        if (!hasAudio) {
                            refreshActionState()
                        }
                        setStatus(getString(R.string.status_synth_done, requestId))
                        setMetrics(
                            buildMetricsText(
                                requestId = requestId,
                                playType = requestPlayTypes[requestId],
                                sampleRate = sampleRate,
                                firstPacketMs = firstPacketMs,
                                synthesisMs = synthesisMs,
                                audioDurationMs = audioDurationMs,
                                chunkCount = chunkCount,
                            ),
                        )
                    } else {
                        setStatus(getString(R.string.status_sdk_playback_started, requestId))
                        setMetrics(
                            buildMetricsText(
                                requestId = requestId,
                                playType = requestPlayTypes[requestId],
                                sampleRate = sampleRate,
                                firstPacketMs = firstPacketMs,
                                synthesisMs = synthesisMs,
                                audioDurationMs = audioDurationMs,
                                chunkCount = chunkCount,
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
                requestFirstChunkAtMs.remove(requestId)
                requestWarmupFlags.remove(requestId)
                requestStreamingFlags.remove(requestId)
                requestDataPaths.remove(requestId)
                requestModelInfos.remove(requestId)
                requestLoadProfiles.remove(requestId)
                requestProfiles.remove(requestId)
            }
            appendLog(
                "onComplete requestId=$requestId type=${response.type} message=${response.message} " +
                    "firstPacketMs=${response.firstPacketMs} synthesisMs=${response.synthesisMs} " +
                    "audioDurationMs=${response.audioDurationMs} rtf=${response.rtf} profile=${response.profilingInfo}",
            )
        }

        override fun onStop(requestId: String, response: StopResponse) {
            requestPlayTypes.remove(requestId)
            requestBuffers.remove(requestId)
            requestChunkCounts.remove(requestId)
            requestSampleRates.remove(requestId)
            requestStartedAtMs.remove(requestId)
            requestFirstChunkAtMs.remove(requestId)
            requestWarmupFlags.remove(requestId)
            requestStreamingFlags.remove(requestId)
            requestDataPaths.remove(requestId)
            requestModelInfos.remove(requestId)
            requestLoadProfiles.remove(requestId)
            requestProfiles.remove(requestId)
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
            requestFirstChunkAtMs.remove(requestId)
            requestWarmupFlags.remove(requestId)
            requestStreamingFlags.remove(requestId)
            requestDataPaths.remove(requestId)
            requestModelInfos.remove(requestId)
            requestLoadProfiles.remove(requestId)
            requestProfiles.remove(requestId)
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

    private fun buildMetricsText(
        playType: PlayType?,
        sampleRate: Int?,
        firstPacketMs: Long?,
        synthesisMs: Long?,
        audioDurationMs: Long,
        chunkCount: Int,
        requestId: String? = null,
    ): String {
        val dataPath = requestId?.let(requestDataPaths::get)
        val modelInfo = requestId?.let(requestModelInfos::get)
        val loadProfileInfo = requestId?.let(requestLoadProfiles::get)
        val profilingInfo = requestId?.let(requestProfiles::get)
        val mode = when {
            dataPath == "model_stream_callback" || (dataPath == "model_stream" && playType == PlayType.SYNTHESIZE_ONLY) -> "真流式回调"
            dataPath == "model_stream_playback" || (dataPath == "model_stream" && playType == PlayType.SYNTHESIZE_AND_PLAY) -> "真流式播报"
            dataPath == "buffered_pcm_callback" || (dataPath == "buffered_pcm" && playType == PlayType.SYNTHESIZE_ONLY) -> "整段合成后切块"
            dataPath == "buffered_pcm_playback" || (dataPath == "buffered_pcm" && playType == PlayType.SYNTHESIZE_AND_PLAY) -> "整段合成后播放"
            playType == null -> "Warmup/待机"
            else -> "待确认"
        }
        val engineLoadMs = engineLoadMsByLanguage[selectedLanguage()]
        val modelText = when {
            modelInfo.isNullOrBlank() -> "--"
            modelInfo.contains("source=external") -> "外部模型包"
            modelInfo.contains("source=bundled") -> "内置模型包"
            else -> "未知"
        }
        val sampleRateText = sampleRate?.toString() ?: "--"
        val firstPacketText = firstPacketMs?.toString() ?: "--"
        val synthesisText = synthesisMs?.toString() ?: "--"
        val audioDurationText = if (audioDurationMs > 0L) audioDurationMs.toString() else "--"
        val rtfText = if (synthesisMs != null) formatRtf(synthesisMs, audioDurationMs) else "--"
        return buildString {
            appendLine("模式: $mode")
            appendLine("模型来源: $modelText")
            appendLine("引擎加载: ${engineLoadMs?.toString() ?: "--"} ms")
            if (!loadProfileInfo.isNullOrBlank()) {
                appendLine("加载Profile: $loadProfileInfo")
            }
            appendLine("采样率: ${sampleRateText} Hz")
            appendLine("首包时延: ${firstPacketText} ms")
            appendLine("合成耗时: ${synthesisText} ms")
            appendLine("音频时长: ${audioDurationText} ms")
            appendLine("RTF: $rtfText")
            if (!profilingInfo.isNullOrBlank()) {
                appendLine("Profile: $profilingInfo")
            }
            append("Chunk数: $chunkCount")
        }
    }

    private companion object {
        const val VOICE_ID_SPEAKER_0 = "lits-female-01"
        const val VOICE_ID_SPEAKER_1 = "lits-female-02"
        const val DEFAULT_STREAMING_CHUNK_SIZE = 50
        const val DEFAULT_PCM_QUEUE_CAPACITY = 128
    }
}
