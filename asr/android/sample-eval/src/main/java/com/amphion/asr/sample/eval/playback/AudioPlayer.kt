package com.amphion.asr.sample.eval.playback

import android.media.MediaPlayer
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import java.io.File

/**
 * 单文件 WAV 播放器，包装 [MediaPlayer]。
 *
 * 设计要点：
 * - lifecycle-aware：Activity / Fragment 把 owner 传进来后会自动在 onStop 暂停、onDestroy 释放
 * - 进度回调：UI 用 SeekBar 的就调用 [observeProgress] 拿到周期性 ms 进度
 * - 错误兜底：MediaPlayer.create 或 start 失败时 onError 回调，UI 显示"播放失败"即可
 *
 * 不支持：seek 跳转 / 倍速播放（评估场景每条录音 < 10s，没必要）；如未来需要可加
 */
class AudioPlayer(
    private val onError: (String) -> Unit = {},
    private val onCompletion: () -> Unit = {},
    private val onTick: ((positionMs: Int, durationMs: Int) -> Unit)? = null,
) : DefaultLifecycleObserver {

    private var player: MediaPlayer? = null
    private val mainHandler = Handler(Looper.getMainLooper())
    private var tickPosted: Boolean = false

    @Volatile
    var isPlaying: Boolean = false
        private set

    /** 当前已加载的文件路径；null 表示没加载。 */
    var loadedPath: String? = null
        private set

    /**
     * 加载并立刻开始播放。如果当前已在播放其他文件会先 release。
     * 失败时 onError 被调用，[isPlaying] 保持 false。
     */
    fun play(file: File) {
        release()
        val p = try {
            MediaPlayer().apply {
                setDataSource(file.absolutePath)
                prepare()
            }
        } catch (t: Throwable) {
            Log.w(TAG, "prepare failed: ${t.message}")
            onError("播放失败：${t.message}")
            return
        }
        p.setOnCompletionListener {
            isPlaying = false
            stopTicks()
            onCompletion()
        }
        p.setOnErrorListener { _, what, extra ->
            Log.w(TAG, "MediaPlayer onError what=$what extra=$extra")
            onError("播放出错（$what/$extra）")
            isPlaying = false
            stopTicks()
            true
        }
        try {
            p.start()
        } catch (t: Throwable) {
            Log.w(TAG, "start failed: ${t.message}")
            onError("播放失败：${t.message}")
            try { p.release() } catch (_: Throwable) {}
            return
        }
        player = p
        loadedPath = file.absolutePath
        isPlaying = true
        if (onTick != null) startTicks()
    }

    fun pause() {
        val p = player ?: return
        if (p.isPlaying) {
            try { p.pause() } catch (_: Throwable) {}
        }
        isPlaying = false
        stopTicks()
    }

    fun resume() {
        val p = player ?: return
        try { p.start() } catch (_: Throwable) { return }
        isPlaying = true
        if (onTick != null) startTicks()
    }

    fun release() {
        stopTicks()
        val p = player
        player = null
        loadedPath = null
        isPlaying = false
        try { p?.release() } catch (_: Throwable) {}
    }

    private fun startTicks() {
        if (tickPosted) return
        tickPosted = true
        mainHandler.post(tickRunnable)
    }

    private fun stopTicks() {
        tickPosted = false
        mainHandler.removeCallbacks(tickRunnable)
    }

    private val tickRunnable = object : Runnable {
        override fun run() {
            val p = player ?: return
            val cb = onTick ?: return
            try {
                cb(p.currentPosition, p.duration)
            } catch (_: Throwable) {}
            if (isPlaying && tickPosted) {
                mainHandler.postDelayed(this, TICK_INTERVAL_MS)
            }
        }
    }

    // ----- Lifecycle hooks -----

    override fun onStop(owner: LifecycleOwner) {
        pause()
    }

    override fun onDestroy(owner: LifecycleOwner) {
        release()
    }

    companion object {
        private const val TAG = "AudioPlayer"
        private const val TICK_INTERVAL_MS = 100L
    }
}
