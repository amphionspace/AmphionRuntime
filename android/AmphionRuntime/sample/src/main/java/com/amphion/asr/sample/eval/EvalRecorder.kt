package com.amphion.asr.sample.eval

import android.util.Log
import com.amphion.asr.sample.AudioRecorder
import java.io.File

/**
 * 单条录音控制器：包装 [AudioRecorder] + [WavWriter] + 可选的 [OnDeviceTranscriber]。
 *
 * 与 [com.amphion.asr.sample.SessionRecorder] 的区别：
 * - per-recording 语义（一次 start..stop = 一条录音 = 一个 sentence_id）
 * - 录音直接写到 `_temp/<recording_id>/audio.wav`，stop 时由 finalize 搬迁到正式目录
 * - 同步把 PCM 喂给可选的 transcriber，复用录音管线的 PCM 流，不再起第二条采集线程
 *
 * 增益策略：默认 +10dB，与生产链路（MainActivity 的 demo 模式）一致，让 WER 数据复刻
 * 生产场景；如果想测"模型本征 WER"，调用方可显式传 gainDb=0。meta.json 里始终记录实际 gain_db。
 */
class EvalRecorder private constructor(
    val audioFile: File,
    private val writer: WavWriter,
    val sampleRate: Int,
    val gainDb: Float,
    private val transcriber: OnDeviceTranscriber?,
    private val onWaveformLevel: ((ShortArray) -> Unit)?,
    private val onError: (String) -> Unit,
) {

    private var recorder: AudioRecorder? = null

    @Volatile
    private var running: Boolean = false

    val durationMs: Long get() = writer.durationMs

    fun start() {
        if (running) return
        running = true
        transcriber?.start()
        recorder = AudioRecorder(
            sampleRate = sampleRate,
            onPcm = { samples ->
                if (!running) return@AudioRecorder
                writer.appendPcm(samples)
                transcriber?.feedPcm(samples)
                onWaveformLevel?.invoke(samples)
            },
            onError = { msg ->
                Log.w(TAG, "AudioRecorder error: $msg")
                onError(msg)
            },
            gainDb = gainDb,
        ).also { it.start() }
    }

    /**
     * 停止录音；同步 join 录音线程后 finalize WAV header。
     * 调用 [transcriber.stop] 但不阻塞等待 final 文本（调用方应自行注册 callback）。
     */
    fun stop() {
        if (!running) return
        running = false
        recorder?.stop()
        recorder = null
        writer.finalize()
        transcriber?.stop()
    }

    /** 录音中途出错或用户丢弃时调用：直接停录 + 删除已写文件。 */
    fun discard() {
        stop()
        try {
            if (audioFile.exists()) audioFile.delete()
        } catch (t: Throwable) {
            Log.w(TAG, "discard delete failed: ${t.message}")
        }
    }

    companion object {
        private const val TAG = "EvalRecorder"

        /**
         * 创建一个新的 EvalRecorder；audioFile 父目录必须已存在（_temp/<recording_id>/）。
         *
         * @param audioFile WAV 文件目标路径（典型 `_temp/<id>/audio.wav`）
         * @param sampleRate 采样率（与模型一致，默认 16000）
         * @param gainDb 软增益，与生产链路一致默认 +10dB
         * @param transcriber 可选的 on-device 实时识别器；为 null 表示不做现场识别
         * @param onWaveformLevel 给 WaveformView 喂 PCM；为 null 表示无波形 UI
         * @param onError 录音管线错误回调（如麦克风初始化失败、读取失败）
         */
        fun create(
            audioFile: File,
            sampleRate: Int = 16000,
            gainDb: Float = 10f,
            transcriber: OnDeviceTranscriber? = null,
            onWaveformLevel: ((ShortArray) -> Unit)? = null,
            onError: (String) -> Unit,
        ): EvalRecorder? {
            val w = WavWriter.create(audioFile, sampleRate) ?: return null
            return EvalRecorder(
                audioFile = audioFile,
                writer = w,
                sampleRate = sampleRate,
                gainDb = gainDb,
                transcriber = transcriber,
                onWaveformLevel = onWaveformLevel,
                onError = onError,
            )
        }
    }
}
