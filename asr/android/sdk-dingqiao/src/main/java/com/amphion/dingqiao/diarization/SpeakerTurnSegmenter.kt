package com.amphion.dingqiao.diarization

internal data class SpeakerSegmentationSegment(
    val startSample: Int,
    val endSample: Int,
    val speaker: Int,
    val speakerMask: Int,
)

/** JNI wrapper around the same pyannote powerset decoder used by HarmonyOS. */
internal class SpeakerTurnSegmenter(modelPath: String) : AutoCloseable {
    private var handle: Long = nativeCreate(modelPath)

    init {
        check(handle != 0L) { "speaker segmentation model load failed" }
    }

    @Synchronized
    fun process(samples: FloatArray): List<SpeakerSegmentationSegment> {
        check(handle != 0L) { "speaker segmenter is closed" }
        val flattened = nativeProcess(handle, samples)
        check(flattened.size % 4 == 0) { "invalid speaker segmentation result" }
        return List(flattened.size / 4) { index ->
            SpeakerSegmentationSegment(
                startSample = flattened[index * 4],
                endSample = flattened[index * 4 + 1],
                speaker = flattened[index * 4 + 2],
                speakerMask = flattened[index * 4 + 3],
            )
        }
    }

    @Synchronized
    override fun close() {
        if (handle == 0L) return
        nativeClose(handle)
        handle = 0L
    }

    private external fun nativeCreate(modelPath: String): Long
    private external fun nativeProcess(handle: Long, samples: FloatArray): IntArray
    private external fun nativeClose(handle: Long)

    companion object {
        init {
            System.loadLibrary("amphion_diarization_jni")
        }
    }
}
