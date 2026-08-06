package com.lits.tts.sdk.internal

import androidx.test.core.app.ApplicationProvider
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
import com.lits.tts.sdk.TextToSpeechException
import com.lits.tts.sdk.TextToSpeechSdk
import com.lits.tts.sdk.TtsErrorCode
import com.lits.tts.sdk.TtsStreamingConfig
import com.lits.tts.sdk.VoiceQuery
import java.io.File
import java.util.Collections
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TtsEngineeringBatchTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val outputDir = File(context.getExternalFilesDir(null) ?: context.filesDir, "tts-batch").apply { mkdirs() }
    private val resultFile = File(outputDir, "tts-batch-results.jsonl")
    private val summaryFile = File(outputDir, "tts-batch-summary.json")
    private val runId = "tts-batch-${System.currentTimeMillis()}"
    private val results = mutableListOf<CaseResult>()
    private val engines = mutableListOf<TextToSpeechEngine>()

    @Test
    fun engineeringBatchCoversStabilityPerformanceAndEdgeCases() {
        resultFile.writeText("", Charsets.UTF_8)
        TextToSpeechSdk.setWorkPath(File(context.cacheDir, "tts-batch-work").apply { mkdirs() }.absolutePath)

        verifyVoiceListing()
        runSuccessMatrix()
        runExpectedErrorMatrix()
        runDuplicateRequestIdCase()
        runStopAndPreemptCases()

        engines.forEach { runCatching { it.shutdown() } }
        engines.clear()

        val summary = buildSummary()
        summaryFile.writeText(summary.toString(2) + "\n", Charsets.UTF_8)
        val failures = results.filter { it.status == "FAIL" || it.status == "TIMEOUT" }
        assertTrue("Expected at least 200 batch cases, got ${results.size}", results.size >= MIN_CASE_COUNT)
        assertTrue("Batch failures: ${failures.map { it.id to it.message }}\nReport: ${summaryFile.absolutePath}", failures.isEmpty())
    }

    private fun verifyVoiceListing() {
        val voices = TextToSpeechSdk.listVoices(VoiceQuery(requestId = "voices-$runId", mode = RunMode.OFFLINE))
        assertEquals(setOf("zh-en", "en-US"), voices.map { it.language }.toSet())
        assertTrue(voices.any { it.voiceId == VOICE_ZH })
        assertTrue(voices.any { it.voiceId == VOICE_EN })
    }

    private fun runSuccessMatrix() {
        val zhEngine = createEngine(language = "zh-en", voiceId = VOICE_ZH, name = "batch-zh")
        val enEngine = createEngine(language = "en-US", voiceId = VOICE_EN, name = "batch-en")
        val cases = buildSuccessCases(zhEngine, enEngine)
        cases.forEach { runCase(it, expectError = null) }
        shutdownEngine(zhEngine)
        shutdownEngine(enEngine)
    }

    private fun runExpectedErrorMatrix() {
        val engine = createEngine(language = "zh-en", voiceId = VOICE_ZH, name = "batch-errors")
        buildErrorCases(engine).forEach { (case, expectedError) ->
            runCase(case, expectError = expectedError)
        }
        shutdownEngine(engine)
    }

    private fun buildSuccessCases(zhEngine: TextToSpeechEngine, enEngine: TextToSpeechEngine): List<BatchCase> {
        val cases = mutableListOf<BatchCase>()
        val zhSeeds = listOf(
            TextSeed("zh-greeting", "您好，欢迎使用语音合成服务。"),
            TextSeed("zh-question", "请问今天下午三点可以开会吗？"),
            TextSeed("zh-command", "请打开蓝牙，并把音量调到百分之六十。"),
            TextSeed("zh-temperature", "室外温度是-24.5度，体感温度更低。"),
            TextSeed("zh-time", "闹钟设为7点05分，提醒我喝水。"),
            TextSeed("zh-date", "会议安排在2026年6月25日星期四。"),
            TextSeed("zh-money", "本次订单金额为1234.56元，优惠8.8折。"),
            TextSeed("zh-percent", "电量剩余12%，预计还能使用30分钟。"),
            TextSeed("zh-address", "请导航到深圳市南山区科技园一号楼。"),
            TextSeed("zh-phone", "客服电话是400-800-1234，请稍后拨打。"),
            TextSeed("zh-code", "验证码是A9B8C7，请不要告诉别人。"),
            TextSeed("zh-url", "请访问www.example.com查看帮助文档。"),
            TextSeed("zh-email", "反馈邮箱是service@example.com。"),
            TextSeed("zh-punctuation", "好的！稍等一下……正在为您查询天气。"),
            TextSeed("zh-parentheses", "设备状态（低电量）需要尽快处理。"),
            TextSeed("zh-quote", "他说：“马上出发，不要迟到。”"),
            TextSeed("zh-list", "购物清单包括牛奶、面包、鸡蛋和咖啡。"),
            TextSeed("zh-unit", "当前速度为80km/h，距离目的地3.5公里。"),
            TextSeed("zh-mixed-en", "Type-C接口已连接，请播放hello world。"),
            TextSeed("zh-ai-term", "请打开ChatGPT应用，生成一段摘要。"),
            TextSeed("zh-product", "LITS TTS SDK正在进行稳定性测试。"),
            TextSeed("zh-repeated", "测试测试测试，请确认没有异常停顿。"),
            TextSeed("zh-homophone", "银行行长正在整理行程。"),
            TextSeed("zh-polyphone", "重庆火锅很好吃，重量也很足。"),
            TextSeed("zh-short-one", "好。"),
            TextSeed("zh-short-two", "收到。"),
            TextSeed("zh-space", "请  稍后  再试。"),
            TextSeed("zh-fullwidth", "ＡＢＣ１２３已经转换完成。"),
            TextSeed("zh-symbol", "Wi-Fi信号强度为-65dBm。"),
            TextSeed("zh-fraction", "请加入1/2杯牛奶和3/4杯水。"),
            TextSeed("zh-ordinal", "第1名和第2名之间相差0.5分。"),
            TextSeed("zh-id", "身份证尾号是123X，请核对。"),
            TextSeed("zh-license", "车牌号粤B12345已经入场。"),
            TextSeed("zh-stock", "股票代码600519今日上涨1.23%。"),
            TextSeed("zh-weather", "今天有小雨转多云，出门记得带伞。"),
            TextSeed("zh-navigation", "前方200米右转，然后进入辅路。"),
            TextSeed("zh-reminder", "晚上九点提醒我提交测试报告。"),
            TextSeed("zh-dialogue", "小明问，小红答，好的我们马上开始。"),
            TextSeed("zh-long-lite", "这是一段中等长度的稳定性测试文本，用来观察分段、首包时延、整体合成耗时和音频回调数量。"),
            TextSeed("zh-long-repeat", "长文本边界稳定性测试，包含多个短句，覆盖连续合成能力。".repeat(3)),
        )
        val enSeeds = listOf(
            TextSeed("en-greeting", "Hello, welcome to the text to speech stability test."),
            TextSeed("en-question", "Can we start the meeting at three fifteen this afternoon?"),
            TextSeed("en-command", "Please turn on Bluetooth and set the volume to sixty percent."),
            TextSeed("en-time", "Set an alarm for seven oh five tomorrow morning."),
            TextSeed("en-date", "The release is scheduled for June twenty fifth, twenty twenty six."),
            TextSeed("en-money", "The total price is one thousand two hundred thirty four dollars."),
            TextSeed("en-percent", "Battery level is twelve percent and charging is recommended."),
            TextSeed("en-address", "Navigate to building one in the science park."),
            TextSeed("en-phone", "Please call four zero zero eight zero zero one two three four."),
            TextSeed("en-code", "The verification code is A nine B eight C seven."),
            TextSeed("en-url", "Open example dot com for more information."),
            TextSeed("en-email", "Send feedback to service at example dot com."),
            TextSeed("en-punctuation", "Wait a moment, please; the weather query is running."),
            TextSeed("en-parentheses", "The device status, low battery, needs attention."),
            TextSeed("en-product", "The LITS TTS SDK is running a batch test."),
            TextSeed("en-repeated", "Test test test, confirm there is no abnormal pause."),
            TextSeed("en-short-one", "Okay."),
            TextSeed("en-short-two", "Received."),
            TextSeed("en-usb", "The USB C cable is connected and ready."),
            TextSeed("en-speed", "Speed adjustment should keep the audio stable."),
            TextSeed("en-chunk", "Streaming chunks should arrive in the correct order."),
            TextSeed("en-long-lite", "This medium length sentence checks segmentation, first packet latency, synthesis time, and callback stability."),
            TextSeed("en-long-repeat", "Long text stability coverage should keep callbacks ordered and complete. ".repeat(3).trim()),
        )

        zhSeeds.forEachIndexed { index, seed ->
            val profile = successProfiles[index % successProfiles.size]
            cases += BatchCase(
                id = "ok-${seed.id}-${index.toCaseNumber()}",
                category = seed.id,
                engine = zhEngine,
                language = "zh-en",
                voiceId = VOICE_ZH,
                text = seed.text,
                speed = profile.speed,
                pitch = profile.pitch,
                volume = profile.volume,
                languageContext = profile.languageContext,
                playType = profile.playType,
                queueMode = profile.queueMode,
                chunkSize = profile.chunkSize,
                pcmQueueCapacity = profile.pcmQueueCapacity,
                timeoutMs = profile.timeoutMs,
            )
        }

        enSeeds.forEachIndexed { index, seed ->
            val profile = successProfiles[(index + 3) % successProfiles.size]
            cases += BatchCase(
                id = "ok-${seed.id}-${index.toCaseNumber()}",
                category = seed.id,
                engine = enEngine,
                language = "en-US",
                voiceId = VOICE_EN,
                text = seed.text,
                speed = profile.speed,
                pitch = profile.pitch,
                volume = profile.volume,
                languageContext = "en-US",
                playType = profile.playType,
                queueMode = profile.queueMode,
                chunkSize = profile.chunkSize,
                pcmQueueCapacity = profile.pcmQueueCapacity,
                timeoutMs = profile.timeoutMs,
            )
        }

        val speedBoundaryTexts = listOf("语速下限截断测试。", "语速上限截断测试。", "语速正常边界测试。")
        val speedValues = listOf(0.1f, 0.25f, 0.49f, 0.5f, 0.75f, 1.0f, 1.25f, 1.5f, 2.0f, 2.01f, 3.0f, 4.0f, Float.NaN, Float.POSITIVE_INFINITY)
        speedValues.forEachIndexed { index, speed ->
            cases += BatchCase(
                id = "ok-speed-boundary-${index.toCaseNumber()}",
                category = "speed-boundary",
                engine = zhEngine,
                language = "zh-en",
                voiceId = VOICE_ZH,
                text = speedBoundaryTexts[index % speedBoundaryTexts.size],
                speed = speed,
                chunkSize = if (index % 2 == 0) 50 else 100,
            )
        }

        val chunkSizes = listOf(16, 32, 50, 64, 100, 128, 256, 512, 1024)
        chunkSizes.forEachIndexed { index, chunkSize ->
            cases += BatchCase(
                id = "ok-chunk-boundary-${index.toCaseNumber()}",
                category = "chunk-boundary",
                engine = zhEngine,
                language = "zh-en",
                voiceId = VOICE_ZH,
                text = "流式切块边界测试，当前chunk大小为$chunkSize。",
                chunkSize = chunkSize,
                pcmQueueCapacity = listOf(1, 2, 4, 8, 16, 32)[index % 6],
            )
        }

        val compactTexts = (1..112).map { index ->
            val template = compactTemplates[(index - 1) % compactTemplates.size]
            val suffix = when (index % 8) {
                0 -> "序号$index。"
                1 -> "温度${index - 30}.5度。"
                2 -> "时间${index % 24}点${(index * 3) % 60}分。"
                3 -> "编号A${1000 + index}。"
                4 -> "电量${index % 100}%。"
                5 -> "金额${index * 7}.25元。"
                6 -> "路径A/B/C$index。"
                else -> "混合hello$index。"
            }
            "$template$suffix"
        }
        compactTexts.forEachIndexed { index, text ->
            val profile = successProfiles[(index + 7) % successProfiles.size]
            cases += BatchCase(
                id = "ok-compact-${index.toCaseNumber()}",
                category = "compact-generated",
                engine = zhEngine,
                language = "zh-en",
                voiceId = VOICE_ZH,
                text = text,
                speed = profile.speed,
                pitch = profile.pitch,
                volume = profile.volume,
                languageContext = if (index % 5 == 0) "zh-CN" else "zh-en",
                playType = if (index % 37 == 0) PlayType.SYNTHESIZE_AND_PLAY else PlayType.SYNTHESIZE_ONLY,
                queueMode = profile.queueMode,
                chunkSize = profile.chunkSize,
                pcmQueueCapacity = profile.pcmQueueCapacity,
            )
        }

        return cases
    }

    private fun buildErrorCases(engine: TextToSpeechEngine): List<Pair<BatchCase, Int>> {
        val cases = mutableListOf<Pair<BatchCase, Int>>()
        fun add(case: BatchCase, expected: Int = TtsErrorCode.RUNTIME_EXCEPTION) {
            cases += case to expected
        }

        listOf(
            " ",
            "\n\t",
            "",
        ).forEachIndexed { index, text ->
            add(
                BatchCase(
                    id = "err-text-empty-${index.toCaseNumber()}",
                    category = "err-text-length",
                    engine = engine,
                    language = "zh-en",
                    voiceId = VOICE_ZH,
                    text = text,
                    expectedRequestId = "err-empty-${index.toCaseNumber()}",
                ),
                TtsErrorCode.TEXT_LENGTH_INVALID,
            )
        }
        listOf(10001, 10050, 12000).forEachIndexed { index, length ->
            add(
                BatchCase(
                    id = "err-text-overlong-${index.toCaseNumber()}",
                    category = "err-text-length",
                    engine = engine,
                    language = "zh-en",
                    voiceId = VOICE_ZH,
                    text = "长".repeat(length),
                    expectedRequestId = "err-overlong-${index.toCaseNumber()}",
                ),
                TtsErrorCode.TEXT_LENGTH_INVALID,
            )
        }
        listOf(0.0f, 0.49f, 2.01f, 10.0f, Float.NaN, Float.NEGATIVE_INFINITY).forEachIndexed { index, pitch ->
            add(
                BatchCase(
                    id = "err-pitch-${index.toCaseNumber()}",
                    category = "err-pitch",
                    engine = engine,
                    language = "zh-en",
                    voiceId = VOICE_ZH,
                    text = "音调非法边界测试。",
                    pitch = pitch,
                ),
            )
        }
        listOf(-1.0f, -0.01f, 2.01f, 10.0f, Float.NaN, Float.POSITIVE_INFINITY).forEachIndexed { index, volume ->
            add(
                BatchCase(
                    id = "err-volume-${index.toCaseNumber()}",
                    category = "err-volume",
                    engine = engine,
                    language = "zh-en",
                    voiceId = VOICE_ZH,
                    text = "音量非法边界测试。",
                    volume = volume,
                ),
            )
        }
        listOf("wav", "mp3", "aac", "pcm16", "PCM", "", " pcm ").forEachIndexed { index, audioType ->
            add(
                BatchCase(
                    id = "err-audio-type-${index.toCaseNumber()}",
                    category = "err-audio-type",
                    engine = engine,
                    language = "zh-en",
                    voiceId = VOICE_ZH,
                    text = "音频格式非法边界测试。",
                    audioType = audioType,
                ),
            )
        }
        listOf("ja-JP", "fr-FR", "zh", "en", "zh-TW", "", "EN-US", " zh-en ").forEachIndexed { index, languageContext ->
            add(
                BatchCase(
                    id = "err-language-context-${index.toCaseNumber()}",
                    category = "err-language-context",
                    engine = engine,
                    language = "zh-en",
                    voiceId = VOICE_ZH,
                    text = "语言上下文非法边界测试。",
                    languageContext = languageContext,
                ),
            )
        }
        return cases
    }

    private fun runDuplicateRequestIdCase() {
        val engine = createEngine(language = "zh-en", voiceId = VOICE_ZH, name = "batch-dup")
        val shared = "dup-${System.currentTimeMillis()}"
        runCase(
            BatchCase(
                id = "dup-first",
                category = "duplicate-request-id",
                engine = engine,
                language = "zh-en",
                voiceId = VOICE_ZH,
                text = "第一次请求。",
                expectedRequestId = shared,
            ),
            expectError = null,
        )
        runCase(
            BatchCase(
                id = "dup-second",
                category = "duplicate-request-id",
                engine = engine,
                language = "zh-en",
                voiceId = VOICE_ZH,
                text = "重复请求。",
                expectedRequestId = shared,
            ),
            expectError = TtsErrorCode.RUNTIME_EXCEPTION,
        )
        shutdownEngine(engine)
    }

    private fun runStopAndPreemptCases() {
        val engine = createEngine(language = "zh-en", voiceId = VOICE_ZH, name = "batch-control")
        val stopResult = runAsyncControlCase(
            id = "stop-active-long",
            engine = engine,
            firstText = "主动停止稳定性测试。".repeat(80),
            secondText = null,
            action = { startedLatch, _ ->
                startedLatch.await(5, TimeUnit.SECONDS)
                engine.stop()
            },
        )
        record(stopResult)

        val preemptResult = runAsyncControlCase(
            id = "preempt-active-long",
            engine = engine,
            firstText = "抢占稳定性测试。".repeat(80),
            secondText = "新的抢占请求应该完成。",
            action = { startedLatch, secondRequest ->
                startedLatch.await(5, TimeUnit.SECONDS)
                secondRequest?.invoke()
            },
        )
        record(preemptResult)
        shutdownEngine(engine)
    }

    private fun createEngine(language: String, voiceId: String, name: String): TextToSpeechEngine {
        val engine = TextToSpeechSdk.createEngine(
            CreateEngineParams(
                language = language,
                mode = RunMode.OFFLINE,
                voiceId = voiceId,
                engineName = "$name-$runId",
            ),
        )
        engines += engine
        return engine
    }

    private fun shutdownEngine(engine: TextToSpeechEngine) {
        runCatching { engine.shutdown() }
        engines.remove(engine)
    }

    private fun runCase(case: BatchCase, expectError: Int?) {
        val listener = RecordingListener(case.id)
        case.engine.setListener(listener)
        val requestId = case.expectedRequestId ?: "${case.id}-${System.nanoTime()}"
        val submittedAt = System.currentTimeMillis()
        try {
            case.engine.speak(
                case.text,
                SpeakParams(
                    requestId = requestId,
                    speed = case.speed,
                    volume = case.volume,
                    pitch = case.pitch,
                    languageContext = case.languageContext,
                    audioType = case.audioType,
                    playType = case.playType,
                    queueMode = case.queueMode,
                    streamingConfig = TtsStreamingConfig(
                        chunkSize = case.chunkSize,
                        pcmQueueCapacity = case.pcmQueueCapacity,
                    ),
                ),
            )
        } catch (error: TextToSpeechException) {
            val status = if (expectError == error.errorCode) "EXPECTED_ERROR" else "FAIL"
            record(CaseResult.from(case, requestId, status, submittedAt, errorCode = error.errorCode, message = error.message))
            return
        }

        val completed = listener.done.await(case.timeoutMs, TimeUnit.MILLISECONDS)
        val result = listener.toResult(case, requestId, submittedAt, completed, expectError)
        record(result)
    }

    private fun runAsyncControlCase(
        id: String,
        engine: TextToSpeechEngine,
        firstText: String,
        secondText: String?,
        action: (CountDownLatch, (() -> Unit)?) -> Unit,
    ): CaseResult {
        val listener = ControlListener(id)
        engine.setListener(listener)
        val startedAt = System.currentTimeMillis()
        val firstRequestId = "$id-old-${System.nanoTime()}"
        val secondRequestId = "$id-new-${System.nanoTime()}"
        engine.speak(
            firstText,
            SpeakParams(requestId = firstRequestId, playType = PlayType.SYNTHESIZE_ONLY, queueMode = QueueMode.PREEMPT),
        )
        val secondRequest = secondText?.let {
            {
                engine.speak(
                    it,
                    SpeakParams(requestId = secondRequestId, playType = PlayType.SYNTHESIZE_ONLY, queueMode = QueueMode.PREEMPT),
                )
            }
        }
        action(listener.started, secondRequest)
        val completed = listener.done.await(20, TimeUnit.SECONDS)
        val ok = completed && (listener.stops.isNotEmpty() || listener.completes.isNotEmpty()) && listener.errors.isEmpty()
        return CaseResult(
            id = id,
            category = "control",
            status = if (ok) "PASS" else if (!completed) "TIMEOUT" else "FAIL",
            requestId = firstRequestId,
            language = "zh-en",
            voiceId = VOICE_ZH,
            playType = PlayType.SYNTHESIZE_ONLY.name,
            queueMode = QueueMode.PREEMPT.name,
            textLength = firstText.length,
            speed = 1.0f,
            pitch = 1.0f,
            volume = 1.0f,
            languageContext = "zh-CN",
            submittedAtMs = startedAt,
            startLatencyMs = listener.firstStartAtMs.takeIf { it > 0 }?.let { it - startedAt },
            firstPacketMs = null,
            synthesisMs = null,
            audioDurationMs = null,
            rtf = null,
            chunkCount = listener.dataCount,
            bytes = listener.bytes,
            sampleRate = listener.sampleRate,
            dataPath = listener.dataPath,
            errorCode = listener.errors.firstOrNull()?.first,
            message = listener.errors.firstOrNull()?.second ?: "stops=${listener.stops.size} completes=${listener.completes.size}",
            profilingInfo = null,
        )
    }

    private fun record(result: CaseResult) {
        results += result
        resultFile.appendText(result.toJson().toString() + "\n", Charsets.UTF_8)
    }

    private fun buildSummary(): JSONObject {
        val successResults = results.filter { it.status == "PASS" }
        val firstPackets = successResults.mapNotNull { it.firstPacketMs }.sorted()
        val rtfs = successResults.mapNotNull { it.rtf }.sorted()
        val failures = results.filter { it.status == "FAIL" || it.status == "TIMEOUT" }
        val categories = results
            .groupBy { it.category }
            .toSortedMap()
            .map { (category, categoryResults) ->
                JSONObject()
                    .put("category", category)
                    .put("total", categoryResults.size)
                    .put("pass", categoryResults.count { it.status == "PASS" })
                    .put("expectedError", categoryResults.count { it.status == "EXPECTED_ERROR" })
                    .put("fail", categoryResults.count { it.status == "FAIL" })
                    .put("timeout", categoryResults.count { it.status == "TIMEOUT" })
            }
        return JSONObject()
            .put("runId", runId)
            .put("resultFile", resultFile.absolutePath)
            .put("summaryFile", summaryFile.absolutePath)
            .put("total", results.size)
            .put("pass", results.count { it.status == "PASS" })
            .put("expectedError", results.count { it.status == "EXPECTED_ERROR" })
            .put("fail", results.count { it.status == "FAIL" })
            .put("timeout", results.count { it.status == "TIMEOUT" })
            .put("firstPacketMs", stats(firstPackets.map(Long::toDouble)))
            .put("rtf", stats(rtfs))
            .put("categories", JSONArray(categories))
            .put("slowestFirstPacket", JSONArray(successResults.sortedByDescending { it.firstPacketMs ?: -1L }.take(5).map { it.toJson() }))
            .put("slowestRtf", JSONArray(successResults.sortedByDescending { it.rtf ?: -1.0 }.take(5).map { it.toJson() }))
            .put("failures", JSONArray(failures.map { it.toJson() }))
    }

    private fun stats(values: List<Double>): JSONObject {
        if (values.isEmpty()) return JSONObject()
        fun percentile(p: Double): Double {
            val idx = ((values.size - 1) * p).toInt().coerceIn(0, values.lastIndex)
            return values[idx]
        }
        return JSONObject()
            .put("count", values.size)
            .put("p50", percentile(0.50))
            .put("p90", percentile(0.90))
            .put("max", values.last())
    }

    private data class TextSeed(
        val id: String,
        val text: String,
    )

    private data class SuccessProfile(
        val speed: Float,
        val pitch: Float = 1.0f,
        val volume: Float = 1.0f,
        val languageContext: String = "zh-en",
        val playType: PlayType = PlayType.SYNTHESIZE_ONLY,
        val queueMode: QueueMode = QueueMode.PREEMPT,
        val chunkSize: Int = 50,
        val pcmQueueCapacity: Int = 32,
        val timeoutMs: Long = 60_000L,
    )

    private data class BatchCase(
        val id: String,
        val category: String,
        val engine: TextToSpeechEngine,
        val language: String,
        val voiceId: String,
        val text: String,
        val speed: Float = 1.0f,
        val volume: Float = 1.0f,
        val pitch: Float = 1.0f,
        val languageContext: String = "zh-en",
        val audioType: String = "pcm",
        val playType: PlayType = PlayType.SYNTHESIZE_ONLY,
        val queueMode: QueueMode = QueueMode.PREEMPT,
        val chunkSize: Int = 50,
        val pcmQueueCapacity: Int = 32,
        val timeoutMs: Long = 60_000L,
        val expectedRequestId: String? = null,
    )

    private class RecordingListener(private val id: String) : SpeakListener {
        val done = CountDownLatch(1)
        private var startAtMs: Long? = null
        private var firstDataAtMs: Long? = null
        private var startResponse: StartResponse? = null
        private var completeResponse: CompleteResponse? = null
        private var error: Pair<Int, String>? = null
        private var chunkCount = 0
        private var bytes = 0L

        override fun onStart(requestId: String, response: StartResponse) {
            startAtMs = System.currentTimeMillis()
            startResponse = response
        }

        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {
            if (firstDataAtMs == null) firstDataAtMs = System.currentTimeMillis()
            chunkCount += 1
            bytes += audio.size
        }

        override fun onComplete(requestId: String, response: CompleteResponse) {
            if (response.type == CompleteType.SYNTHESIS_COMPLETE) {
                completeResponse = response
                done.countDown()
            } else if (response.type == CompleteType.PLAYBACK_COMPLETE) {
                completeResponse = response
                done.countDown()
            }
        }

        override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
            error = errorCode to errorMessage
            done.countDown()
        }

        fun toResult(case: BatchCase, requestId: String, submittedAt: Long, completed: Boolean, expectError: Int?): CaseResult {
            if (!completed) {
                return CaseResult.from(case, requestId, "TIMEOUT", submittedAt, message = "timeout waiting for callback in $id")
            }
            val currentError = error
            if (expectError != null) {
                val ok = currentError?.first == expectError
                return CaseResult.from(
                    case,
                    requestId,
                    if (ok) "EXPECTED_ERROR" else "FAIL",
                    submittedAt,
                    errorCode = currentError?.first,
                    message = currentError?.second ?: "expected error $expectError but no error arrived",
                )
            }
            if (currentError != null) {
                return CaseResult.from(case, requestId, "FAIL", submittedAt, errorCode = currentError.first, message = currentError.second)
            }
            val startMs = startAtMs
            val complete = completeResponse
            val firstPacket = complete?.firstPacketMs?.takeIf { it >= 0L }
                ?: if (startMs != null && firstDataAtMs != null) firstDataAtMs!! - startMs else null
            return CaseResult(
                id = case.id,
                category = case.category,
                status = if (complete != null) "PASS" else "FAIL",
                requestId = requestId,
                language = case.language,
                voiceId = case.voiceId,
                playType = case.playType.name,
                queueMode = case.queueMode.name,
                textLength = case.text.trim().length,
                speed = case.speed,
                pitch = case.pitch,
                volume = case.volume,
                languageContext = case.languageContext,
                submittedAtMs = submittedAt,
                startLatencyMs = startMs?.let { it - submittedAt },
                firstPacketMs = firstPacket,
                synthesisMs = complete?.synthesisMs?.takeIf { it >= 0L },
                audioDurationMs = complete?.audioDurationMs?.takeIf { it >= 0L },
                rtf = complete?.rtf?.takeIf { it >= 0.0 },
                chunkCount = chunkCount,
                bytes = bytes,
                sampleRate = startResponse?.sampleRate,
                dataPath = startResponse?.dataPath,
                errorCode = null,
                message = complete?.message,
                profilingInfo = complete?.profilingInfo,
            )
        }
    }

    private class ControlListener(private val id: String) : SpeakListener {
        val started = CountDownLatch(1)
        val done = CountDownLatch(1)
        val stops = Collections.synchronizedList(mutableListOf<String>())
        val completes = Collections.synchronizedList(mutableListOf<String>())
        val errors = Collections.synchronizedList(mutableListOf<Pair<Int, String>>())
        var firstStartAtMs: Long = -1L
        var dataCount: Int = 0
        var bytes: Long = 0
        var sampleRate: Int? = null
        var dataPath: String? = null

        override fun onStart(requestId: String, response: StartResponse) {
            if (firstStartAtMs < 0) firstStartAtMs = System.currentTimeMillis()
            sampleRate = response.sampleRate
            dataPath = response.dataPath
            started.countDown()
        }

        override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {
            dataCount += 1
            bytes += audio.size
        }

        override fun onComplete(requestId: String, response: CompleteResponse) {
            completes += "$requestId:${response.type}"
            if (response.type == CompleteType.SYNTHESIS_COMPLETE || response.type == CompleteType.PLAYBACK_COMPLETE) done.countDown()
        }

        override fun onStop(requestId: String, response: StopResponse) {
            stops += requestId
            done.countDown()
        }

        override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
            errors += errorCode to "$id:$errorMessage"
            done.countDown()
        }
    }

    private data class CaseResult(
        val id: String,
        val category: String,
        val status: String,
        val requestId: String,
        val language: String,
        val voiceId: String,
        val playType: String,
        val queueMode: String,
        val textLength: Int,
        val speed: Float,
        val pitch: Float,
        val volume: Float,
        val languageContext: String,
        val submittedAtMs: Long,
        val startLatencyMs: Long?,
        val firstPacketMs: Long?,
        val synthesisMs: Long?,
        val audioDurationMs: Long?,
        val rtf: Double?,
        val chunkCount: Int,
        val bytes: Long,
        val sampleRate: Int?,
        val dataPath: String?,
        val errorCode: Int?,
        val message: String?,
        val profilingInfo: String?,
    ) {
        fun toJson(): JSONObject = JSONObject()
            .put("id", id)
            .put("category", category)
            .put("status", status)
            .put("requestId", requestId)
            .put("language", language)
            .put("voiceId", voiceId)
            .put("playType", playType)
            .put("queueMode", queueMode)
            .put("textLength", textLength)
            .putFiniteAware("speed", speed)
            .putFiniteAware("pitch", pitch)
            .putFiniteAware("volume", volume)
            .put("languageContext", languageContext)
            .put("submittedAtMs", submittedAtMs)
            .put("startLatencyMs", startLatencyMs ?: JSONObject.NULL)
            .put("firstPacketMs", firstPacketMs ?: JSONObject.NULL)
            .put("synthesisMs", synthesisMs ?: JSONObject.NULL)
            .put("audioDurationMs", audioDurationMs ?: JSONObject.NULL)
            .put("rtf", rtf ?: JSONObject.NULL)
            .put("chunkCount", chunkCount)
            .put("bytes", bytes)
            .put("sampleRate", sampleRate ?: JSONObject.NULL)
            .put("dataPath", dataPath ?: JSONObject.NULL)
            .put("errorCode", errorCode ?: JSONObject.NULL)
            .put("message", message ?: JSONObject.NULL)
            .put("profilingInfo", profilingInfo ?: JSONObject.NULL)

        companion object {
            fun from(
                case: BatchCase,
                requestId: String,
                status: String,
                submittedAt: Long,
                errorCode: Int? = null,
                message: String? = null,
            ): CaseResult = CaseResult(
                id = case.id,
                category = case.category,
                status = status,
                requestId = requestId,
                language = case.language,
                voiceId = case.voiceId,
                playType = case.playType.name,
                queueMode = case.queueMode.name,
                textLength = case.text.trim().length,
                speed = case.speed,
                pitch = case.pitch,
                volume = case.volume,
                languageContext = case.languageContext,
                submittedAtMs = submittedAt,
                startLatencyMs = null,
                firstPacketMs = null,
                synthesisMs = null,
                audioDurationMs = null,
                rtf = null,
                chunkCount = 0,
                bytes = 0,
                sampleRate = null,
                dataPath = null,
                errorCode = errorCode,
                message = message,
                profilingInfo = null,
            )
        }
    }

    private companion object {
        const val MIN_CASE_COUNT = 200
        const val VOICE_EN = "lits-female-01"
        const val VOICE_ZH = "lits-female-02"

        val successProfiles = listOf(
            SuccessProfile(speed = 1.0f, chunkSize = 50),
            SuccessProfile(speed = 0.5f, chunkSize = 50),
            SuccessProfile(speed = 2.0f, chunkSize = 50),
            SuccessProfile(speed = 0.75f, pitch = 0.8f, chunkSize = 32),
            SuccessProfile(speed = 1.25f, pitch = 1.2f, chunkSize = 64),
            SuccessProfile(speed = 1.5f, volume = 0.6f, chunkSize = 100),
            SuccessProfile(speed = 1.0f, volume = 1.5f, chunkSize = 128),
            SuccessProfile(speed = 0.25f, chunkSize = 50),
            SuccessProfile(speed = 4.0f, chunkSize = 100),
            SuccessProfile(speed = 1.0f, languageContext = "zh-CN", chunkSize = 50),
            SuccessProfile(speed = 1.0f, playType = PlayType.SYNTHESIZE_AND_PLAY, chunkSize = 50),
            SuccessProfile(speed = 1.0f, queueMode = QueueMode.QUEUE, chunkSize = 50),
        )

        val compactTemplates = listOf(
            "请播报当前状态，",
            "系统检测完成，",
            "边缘样例验证，",
            "请确认订单信息，",
            "正在执行批量测试，",
            "语音服务保持运行，",
            "本条用于回调稳定性，",
            "请记录性能指标，",
        )

        fun Int.toCaseNumber(): String = String.format(Locale.US, "%03d", this)

        fun JSONObject.putFiniteAware(name: String, value: Float): JSONObject {
            return if (value.isFinite()) {
                put(name, value.toDouble())
            } else {
                put(name, value.toString())
            }
        }
    }
}
