package com.amphion.dingqiao.demo

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.AudioInfo
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.DingqiaoOnlineMode
import com.amphion.dingqiao.SpeakerDiarizationConfig
import com.amphion.dingqiao.SpeechRecognitionEngine
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.StartParams
import java.io.File
import org.junit.Test
import org.junit.runner.RunWith

/**
 * 安卓侧发热长跑：按实时速率持续喂音频，开启角色分离，跑满指定时长。
 *
 * 与鸿蒙 `run_device_stress.py --mode paced` 对齐：20 ms 定长帧（640 字节）按节拍喂，
 * 所以负载是真实时而非灌数据。温度与内存由主机侧采样器并行采集——设备侧不采，
 * 因为采样进程本身会算进被测应用的占用。
 *
 * 用法：
 *   ./gradlew :samples:dingqiao-demo:connectedDebugAndroidTest \
 *     -Pandroid.testInstrumentationRunnerArguments.class=\
 *        com.amphion.dingqiao.demo.DqThermalLongRunTest \
 *     -Pandroid.testInstrumentationRunnerArguments.durationMinutes=120
 *
 * 时长通过 instrumentation 参数 `durationMinutes` 给，默认 120。Gradle 侧要把
 * connectedAndroidTest 的超时放够，否则会在测试跑完前被判超时。
 */
@RunWith(AndroidJUnit4::class)
class DqThermalLongRunTest {

    private val ctx: Context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val testCtx: Context get() = InstrumentationRegistry.getInstrumentation().context

    @Test
    fun longRunWithDiarization() {
        val args = InstrumentationRegistry.getArguments()
        val minutes = args.getString("durationMinutes")?.toLongOrNull() ?: 120L
        // 一个会话跑多久就切下一个。太长会撞 maxAudioDuration，太短则起停开销占比过高。
        val sessionSeconds = args.getString("sessionSeconds")?.toLongOrNull() ?: 300L
        val deadline = System.currentTimeMillis() + minutes * 60_000

        val engine = engine()
        val wavs = mainWavs(testCtx)
        check(wavs.isNotEmpty()) { "语料为空，无法长跑" }
        val corpus = wavs.map { readAssetPcm(testCtx, it) }
        val totalSeconds = corpus.sumOf { it.size } / (DQ_SR * 2).toDouble()

        var session = 0
        var fedSeconds = 0.0
        var cursor = 0
        while (System.currentTimeMillis() < deadline) {
            session += 1
            val sid = "thermal-%04d".format(session)
            val listener = CapturingListener().also { engine.setListener(it) }
            engine.startListening(
                StartParams(
                    sessionId = sid,
                    audioInfo = AudioInfo(),
                    extraParams = mapOf(
                        "enablePartialResult" to true,
                        // 比单会话目标时长留足余量，避免引擎自己截断会话
                        "maxAudioDuration" to (sessionSeconds * 1000 + 60_000).toInt(),
                        "vadEnd" to 800,
                    ),
                    // 角色分离配置在 StartParams 上（不在 CreateEngineParams）
                    speakerDiarization = SpeakerDiarizationConfig(maxSpeakers = 4),
                ),
            )
            check(listener.awaitStarted(20_000)) {
                "会话 $sid 启动失败: ${listener.errorCodes()}"
            }

            val sessionEnd = minOf(
                System.currentTimeMillis() + sessionSeconds * 1000,
                deadline,
            )
            while (System.currentTimeMillis() < sessionEnd) {
                val pcm = corpus[cursor % corpus.size]
                cursor += 1
                feedFrames(engine, sid, pcm, DQ_FRAME_MS)
                fedSeconds += pcm.size / (DQ_SR * 2).toDouble()
            }
            feedSilence(engine, sid, 1_000)
            engine.finish(sid)
            listener.awaitComplete(30_000)
            awaitIdle(engine, timeoutMs = 20_000)
        }

        DqReport.append(
            ctx,
            mapOf(
                "case" to "thermalLongRun",
                "requested_minutes" to minutes,
                "sessions" to session,
                "fed_audio_seconds" to fedSeconds,
                "corpus_files" to corpus.size,
                "corpus_seconds" to totalSeconds,
            ),
        )
    }

    companion object {
        @Volatile private var engine: SpeechRecognitionEngine? = null

        @Synchronized
        private fun engine(): SpeechRecognitionEngine {
            engine?.let { return it }
            val target = InstrumentationRegistry.getInstrumentation().targetContext
            prepareSdkRuntime(target, File(target.getExternalFilesDir(null), "dq_thermal_work"))
            return SpeechRecognizeSdk.createEngine(
                CreateEngineParams(
                    language = "zh-CN",
                    online = DingqiaoOnlineMode.OFFLINE,
                    extraParams = mapOf("vadEnd" to 800),
                ),
            ).also { engine = it }
        }
    }
}
