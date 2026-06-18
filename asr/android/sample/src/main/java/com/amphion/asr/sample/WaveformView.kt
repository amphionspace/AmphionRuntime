package com.amphion.asr.sample

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import androidx.core.content.ContextCompat
import kotlin.math.max

/**
 * 录音期间用的实时声波图：左到右滚动的等距竖条，上下镜像。
 *
 * 调用方在录音线程拿到 PCM 后，自己换算成 0..1 的振幅，通过
 * [pushAmplitude] 在 UI 线程喂进来；每次 push 都会触发 invalidate。
 *
 * View 本身不持有任何线程；环形 buffer + invalidate 都假定在主线程上做。
 * 一帧典型推荐 ~25ms 一次（在 100ms PCM 帧上切 4 子帧算 peak），
 * 满屏约 60-120 根条，能拿到 2-3 秒的历史窗。
 */
class WaveformView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0,
) : View(context, attrs, defStyleAttr) {

    private val density: Float = context.resources.displayMetrics.density
    private val barWidthPx: Float = dimenPx(R.dimen.waveform_bar_width, fallback = 3f)
    private val barGapPx: Float = dimenPx(R.dimen.waveform_bar_gap, fallback = 2f)
    private val barCornerPx: Float = barWidthPx / 2f
    /** 最小可见高度，安静时也能看到一条细线，避免观感"死掉"。 */
    private val minBarHalfPx: Float = 1.5f * density

    private val paint: Paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = ContextCompat.getColor(context, R.color.brand_recording)
        style = Paint.Style.FILL
    }

    /** 环形 buffer，存最近 [capacity] 个振幅 (0..1)。 */
    private var amplitudes: FloatArray = FloatArray(0)
    /** 下一个写入位置；最老的一根条就在这个位置。 */
    private var writeIndex: Int = 0
    private var capacity: Int = 0

    /** 复用以避免每帧分配。 */
    private val barRect = RectF()

    /** 把 0..1 的振幅写入环形 buffer，触发重绘。仅允许在 UI 线程调用。 */
    fun pushAmplitude(amp: Float) {
        if (capacity == 0) return
        val clamped = if (amp < 0f) 0f else if (amp > 1f) 1f else amp
        amplitudes[writeIndex] = clamped
        writeIndex = (writeIndex + 1) % capacity
        invalidate()
    }

    /** 清空所有振幅并重绘成"静默"态。仅允许在 UI 线程调用。 */
    fun reset() {
        if (capacity == 0) return
        amplitudes.fill(0f)
        writeIndex = 0
        invalidate()
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        val usable = w - paddingLeft - paddingRight
        val newCapacity = max(1, ((usable + barGapPx) / (barWidthPx + barGapPx)).toInt())
        amplitudes = FloatArray(newCapacity)
        writeIndex = 0
        capacity = newCapacity
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        if (capacity == 0) return

        val centerY = height / 2f
        val maxBarHalf = (height - paddingTop - paddingBottom) / 2f - minBarHalfPx
        val left0 = paddingLeft.toFloat()

        var x = left0
        for (i in 0 until capacity) {
            // writeIndex 是"下一个写入位置"，所以最老的样本就在它当前指向的格子。
            // 想要左到右展示老->新，所以 i=0 取 writeIndex，i=cap-1 取 (writeIndex-1+cap)%cap。
            val idx = (writeIndex + i) % capacity
            val amp = amplitudes[idx]
            val half = minBarHalfPx + amp * max(0f, maxBarHalf)
            barRect.set(x, centerY - half, x + barWidthPx, centerY + half)
            canvas.drawRoundRect(barRect, barCornerPx, barCornerPx, paint)
            x += barWidthPx + barGapPx
        }
    }

    private fun dimenPx(resId: Int, fallback: Float): Float {
        return try {
            resources.getDimension(resId)
        } catch (_: Throwable) {
            fallback * density
        }
    }
}
