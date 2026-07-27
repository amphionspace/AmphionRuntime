package com.amphion.dingqiao.demo

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.AudioInfo
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.DingqiaoOnlineMode
import com.amphion.dingqiao.SpeechRecognitionEngine
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.StartParams
import java.io.File
import org.junit.FixMethodOrder
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.MethodSorters

/**
 * 隔离“喂入速率 / finish 前 settle 时长”对 final 完整性的影响。
 *
 * 现象：fast feed（无 20ms 节拍）会让部分短/重叠句 final 变空，而 realtime 同音频可正常出字。
 * 假设：finish()/stop() 不等待解码 backlog 排空，导致快喂时尾部/整句丢失。
 */
@RunWith(AndroidJUnit4::class)
@FixMethodOrder(MethodSorters.NAME_ASCENDING)
class DqFeedRateTest {

    private val ctx: Context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val testCtx: Context get() = InstrumentationRegistry.getInstrumentation().context

    @Test
    fun f01_feedRate_matrix() {
        val engine = engine()
        // 取在 fast feed 下出现空 final 的可疑文件 + 一个长句对照。
        val all = mainWavs(testCtx)
        val suspects = all.filter { it.startsWith("04") || it.startsWith("06") || it.startsWith("11") }
        val control = all.filter { it.startsWith("01") }
        for (wav in (suspects + control)) {
            val pcm = readAssetPcm(testCtx, wav)
            val realtime = decode(engine, "rt-${tag(wav)}", pcm, frameSleepMs = 20, drainMs = 300)
            val fast = decode(engine, "fast-${tag(wav)}", pcm, frameSleepMs = 0, drainMs = 300)
            val fastLongDrain = decode(engine, "fastdrain-${tag(wav)}", pcm, frameSleepMs = 0, drainMs = 3_000)
            DqReport.append(
                ctx,
                mapOf(
                    "case" to "f01_feedRate",
                    "file" to wav,
                    "realtime_text" to realtime,
                    "fast_text" to fast,
                    "fastLongDrain_text" to fastLongDrain,
                    "realtime_len" to realtime.length,
                    "fast_len" to fast.length,
                    "fastLongDrain_len" to fastLongDrain.length,
                ),
            )
        }
    }

    private fun decode(engine: SpeechRecognitionEngine, sid: String, pcm: ByteArray, frameSleepMs: Long, drainMs: Long): String {
        val listener = CapturingListener().also { engine.setListener(it) }
        engine.startListening(
            StartParams(sid, AudioInfo(), extraParams = mapOf("enablePartialResult" to true, "maxAudioDuration" to 60_000, "vadEnd" to 800)),
        )
        if (!listener.awaitStarted(15_000)) return "<START_FAIL:${listener.errorCodes()}>"
        feedFrames(engine, sid, pcm, frameSleepMs)
        feedSilence(engine, sid, 1_000)
        if (drainMs > 0) Thread.sleep(drainMs)
        engine.finish(sid)
        listener.awaitComplete(25_000)
        Thread.sleep(300)
        awaitIdle(engine)
        return listener.finalText()
    }

    private fun tag(wav: String): String = wav.substringBefore('_')

    companion object {
        @Volatile private var engine: SpeechRecognitionEngine? = null

        @Synchronized
        private fun engine(): SpeechRecognitionEngine {
            engine?.let { return it }
            val target = InstrumentationRegistry.getInstrumentation().targetContext
            val test = InstrumentationRegistry.getInstrumentation().context
            prepareSdkRuntime(
                test,
                target,
                File(target.getExternalFilesDir(null), "dq_feedrate_work"),
            )
            return SpeechRecognizeSdk.createEngine(
                CreateEngineParams(language = "zh-CN", online = DingqiaoOnlineMode.OFFLINE, extraParams = mapOf("vadEnd" to 800)),
            ).also { engine = it }
        }
    }
}
