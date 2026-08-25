package com.amphion.dingqiao.demo

import com.amphion.dingqiao.DINGQIAO_AUDIO_FRAME_BYTES
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** 将任意长度 PCM 切分为鼎桥要求的 640 字节帧。 */
class PcmFrameWriter(
    private val frameBytes: Int = DINGQIAO_AUDIO_FRAME_BYTES,
    private val onFrame: (ByteArray) -> Unit,
) {
    private val frameSamples = frameBytes / 2
    private var pending = ShortArray(0)

    @Synchronized
    fun accept(samples: ShortArray) {
        if (samples.isEmpty()) return
        pending = if (pending.isEmpty()) {
            samples.copyOf()
        } else {
            pending + samples
        }
        var offset = 0
        while (pending.size - offset >= frameSamples) {
            val frame = ByteBuffer.allocate(frameBytes).order(ByteOrder.LITTLE_ENDIAN)
            var i = 0
            while (i < frameSamples) {
                frame.putShort(pending[offset + i])
                i++
            }
            onFrame(frame.array())
            offset += frameSamples
        }
        pending = if (offset > 0) pending.copyOfRange(offset, pending.size) else pending
    }

    @Synchronized
    fun reset() {
        pending = ShortArray(0)
    }

    /** Zero-pad and emit the recorder tail once before the caller finishes the SDK session. */
    @Synchronized
    fun flushFinalFrame() {
        if (pending.isEmpty()) return
        val padded = pending.copyOf(frameSamples)
        pending = ShortArray(0)
        val frame = ByteBuffer.allocate(frameBytes).order(ByteOrder.LITTLE_ENDIAN)
        for (sample in padded) frame.putShort(sample)
        onFrame(frame.array())
    }
}
