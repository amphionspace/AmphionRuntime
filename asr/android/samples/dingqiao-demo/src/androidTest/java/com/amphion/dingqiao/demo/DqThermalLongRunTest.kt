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
        // 二分用：diarization=false 关掉角色分离。长跑在约 2 分钟后停止出回调、进程全部
        // 线程休眠，而不带角色分离的 DqFeedRateTest 不复现，所以先隔离这个变量。
        val diarization = args.getString("diarization")?.toBooleanStrictOrNull() ?: true
        val startedAt = android.os.SystemClock.elapsedRealtime()
        val deadline = startedAt + minutes * 60_000

        val engine = engine()
        startStallWatchdog()
        val wavs = mainWavs(testCtx)
        check(wavs.isNotEmpty()) { "语料为空，无法长跑" }
        val corpus = wavs.map { readAssetPcm(testCtx, it) }
        val totalSeconds = corpus.sumOf { it.size } / (DQ_SR * 2).toDouble()

        var session = 0
        var fedSeconds = 0.0
        var cursor = 0
        while (android.os.SystemClock.elapsedRealtime() < deadline) {
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
                    speakerDiarization = if (diarization) SpeakerDiarizationConfig(maxSpeakers = 4) else null,
                ),
            )
            check(listener.awaitStarted(20_000)) {
                "会话 $sid 启动失败: ${listener.errorCodes()}"
            }

            val sessionEnd = minOf(
                android.os.SystemClock.elapsedRealtime() + sessionSeconds * 1000,
                deadline,
            )
            while (android.os.SystemClock.elapsedRealtime() < sessionEnd) {
                val pcm = corpus[cursor % corpus.size]
                cursor += 1
                fedSeconds += feedPaced(engine, sid, pcm, sessionEnd)
            }
            feedSilence(engine, sid, 1_000)
            engine.finish(sid)
            listener.awaitComplete(30_000)
            awaitIdle(engine, timeoutMs = 20_000)

            // 把本会话的识别文本落盘。喂进去的是不是真语音，看回调计数只是旁证，
            // 文本才是直接证据；SDK 不把文本打到 logcat，内存里的又拿不出来。
            DqReport.append(
                ctx,
                mapOf(
                    "case" to "thermalText",
                    "session" to session,
                    "finals" to listener.finals.size,
                    "text_head" to listener.finalText().take(200),
                ),
            )

            // 进度同时写 logcat 和设备上的 report.jsonl。只写 logcat 不够：这台机器的摄像头
            // 报错每分钟刷几千行，进度行很快被冲出缓冲区，曾因此误以为测试没在跑。
            // feed_ratio 是实际喂入音频秒数 / 已耗墙钟秒数：1.0 才是真实时。
            val wallSeconds = (android.os.SystemClock.elapsedRealtime() - startedAt) / 1000.0
            val feedRatio = if (wallSeconds > 0) fedSeconds / wallSeconds else 0.0
            val remainMin = (deadline - android.os.SystemClock.elapsedRealtime()) / 60000.0
            android.util.Log.i(
                "DqThermalLongRun",
                "THERMAL_LONGRUN|session=%d|wall_s=%.0f|fed_s=%.0f|feed_ratio=%.3f|remain_min=%.1f"
                    .format(session, wallSeconds, fedSeconds, feedRatio, remainMin),
            )
            DqReport.append(
                ctx,
                mapOf(
                    "case" to "thermalProgress",
                    "session" to session,
                    "wall_s" to wallSeconds,
                    "fed_s" to fedSeconds,
                    "feed_ratio" to feedRatio,
                    "remain_min" to remainMin,
                ),
            )
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

    /** 喂帧计数。看门狗据此判断喂音频的线程是否还在前进。 */
    @Volatile private var progressTicks = 0L

    /**
     * 卡死看门狗：喂帧计数 90 秒不变就把**全部 Java 线程栈**写进设备上的 report.jsonl。
     *
     * 为什么要它：长跑曾在约 2 分钟后停止出回调、44 个线程全部休眠、CPU 为 0，而
     * jdb 的 JDWP 握手在这台机器上一直挂着拿不到栈，debuggerd 又要 root。进程内自己
     * dump 不依赖任何外部调试器，下一次复现就能直接拿到卡在哪一帧。
     */
    private fun startStallWatchdog() {
        val t = Thread({
            var last = progressTicks
            var stalledSince = 0L
            var lastDumpAt = 0L
            while (true) {
                Thread.sleep(30_000)
                val now = android.os.SystemClock.elapsedRealtime()
                val cur = progressTicks
                if (cur != last) {
                    last = cur; stalledSince = 0L; continue
                }
                if (stalledSince == 0L) stalledSince = now
                // 卡满 90 秒才 dump，再卡每 5 分钟补一次，避免刷爆文件
                if (now - stalledSince >= 90_000 && now - lastDumpAt >= 300_000) {
                    lastDumpAt = now
                    dumpStacks("feeder stalled ${(now - stalledSince) / 1000}s at ticks=$cur")
                }
            }
        }, "dq-stall-watchdog")
        t.isDaemon = true
        t.start()
    }

    private fun dumpStacks(reason: String) {
        // 不走 DqReport.append：它是 @Synchronized，若卡死的正是持有那把锁的线程，
        // dump 自己也会被堵住、一行都写不出。先逐行打 logcat（无锁），再写独立文件。
        android.util.Log.e("DqThermalLongRun", "STALL_DUMP|BEGIN|$reason")
        val sb = StringBuilder()
        for ((th, frames) in Thread.getAllStackTraces()) {
            if (frames.isEmpty()) continue
            val line = "${th.state.name}|${th.name}|" +
                frames.take(14).joinToString(" <- ") { "${it.className.substringAfterLast('.')}.${it.methodName}:${it.lineNumber}" }
            android.util.Log.e("DqThermalLongRun", "STALL_DUMP|$line")
            sb.append(line).append('\n')
        }
        android.util.Log.e("DqThermalLongRun", "STALL_DUMP|END")
        runCatching {
            java.io.File(ctx.filesDir, "dq_corner/stall_dump.txt").appendText("## $reason\n$sb\n")
        }
    }

    /**
     * 按绝对时间喂帧，并在到达 [stopAtMs] 时提前收手；返回实际喂入的音频秒数。
     *
     * 不用 `feedFrames(..., DQ_FRAME_MS)`：那是每帧 `Thread.sleep(20)`，安卓的调度粒度
     * 会让每帧超调到 25~30 ms。后果不只是慢——**实际喂入速率低于实时**，两小时跑下来
     * 负载比真实工况轻，发热会被低估。这里以首帧时刻为基准算每帧的应到时刻，误差不累积；
     * 已经落后就不睡，直接追上去。
     */
    private fun feedPaced(
        engine: SpeechRecognitionEngine,
        sid: String,
        pcm: ByteArray,
        stopAtMs: Long,
    ): Double {
        // 一律用单调时钟。System.currentTimeMillis 是墙钟，手机会被 NITZ/NTP 校时；
        // 时钟往回跳一次，"应到时刻 − 现在"就变成巨大的正数，Thread.sleep 会把喂帧线程
        // 冻住几分钟到几小时——表现正是"回调停止、全部线程休眠、CPU 为 0"。
        val t0 = android.os.SystemClock.elapsedRealtime()
        var offset = 0
        var frames = 0L
        while (offset < pcm.size) {
            if (android.os.SystemClock.elapsedRealtime() >= stopAtMs) break
            val n = minOf(DQ_FRAME, pcm.size - offset)
            val frame = ByteArray(DQ_FRAME)
            System.arraycopy(pcm, offset, frame, 0, n)
            engine.writeAudio(sid, frame)
            offset += n
            frames += 1
            progressTicks += 1
            // 第 frames 帧的应到时刻；落后则不睡
            val due = t0 + frames * DQ_FRAME_MS
            // 再加一道保险：单次睡眠封顶 1 秒，任何时钟异常都不可能把线程冻死
            val wait = (due - android.os.SystemClock.elapsedRealtime()).coerceAtMost(1_000L)
            if (wait > 0) Thread.sleep(wait)
        }
        return offset / (DQ_SR * 2).toDouble()
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
