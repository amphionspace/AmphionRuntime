package com.amphion.dingqiao.diarization

import java.io.File
import org.json.JSONObject

internal data class CommunityDiarizationWindow(
    val segments: FloatArray,
    val embeddings: FloatArray,
    val segmentationMs: Double,
    val featureMs: Double,
    val embeddingMs: Double,
    // [window, channel, begin frame, end frame) per contiguous clean run, its vector and PCM level.
    val runEmbeddings: FloatArray = FloatArray(0),
    val runRanges: FloatArray = FloatArray(0),
    val runRms: FloatArray = FloatArray(0),
)

internal data class CommunityDiarizationCluster(
    val speakerCount: Int,
    val hard: IntArray,
    val turns: List<DoubleArray>,
)

/** Uses the same native model, feature extraction and PLDA/VBx implementation as Harmony. */
internal class CommunityDiarizationInference(assets: List<File>) : AutoCloseable {
    init { System.loadLibrary("amphion_diarization_jni") }
    private var handle = nativeLoad(assets[0].absolutePath, assets[1].absolutePath,
        assets[2].absolutePath, assets[3].absolutePath, assets[4].absolutePath)

    fun process(samples: FloatArray): CommunityDiarizationWindow = nativeProcess(handle, samples)

    fun cluster(segments: FloatArray, embeddings: FloatArray, maxSpeakers: Int,
        starts: DoubleArray, beginSample: Double, runEmbeddings: FloatArray = FloatArray(0),
        runRanges: FloatArray = FloatArray(0), runRms: FloatArray = FloatArray(0)): CommunityDiarizationCluster {
        val result = JSONObject(nativeCluster(handle, segments, embeddings, maxSpeakers, starts, beginSample,
            runEmbeddings, runRanges, runRms))
        val hard = result.getJSONArray("hard")
        val turns = result.getJSONArray("turns")
        return CommunityDiarizationCluster(result.getInt("speakerCount"),
            IntArray(hard.length()) { hard.getInt(it) },
            List(turns.length()) { index ->
                val turn = turns.getJSONArray(index)
                DoubleArray(3) { turn.getDouble(it) }
            })
    }

    override fun close() { if (handle != 0L) nativeClose(handle); handle = 0 }
    private external fun nativeLoad(segmentation: String, encoder: String, pooling: String, feature: String, plda: String): Long
    private external fun nativeProcess(handle: Long, samples: FloatArray): CommunityDiarizationWindow
    private external fun nativeCluster(handle: Long, segments: FloatArray, embeddings: FloatArray,
        maxSpeakers: Int, starts: DoubleArray, beginSample: Double, runEmbeddings: FloatArray,
        runRanges: FloatArray, runRms: FloatArray): String
    private external fun nativeClose(handle: Long)

}
