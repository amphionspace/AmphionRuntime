package com.amphion.dingqiao.diarization

import android.content.res.AssetManager
import org.json.JSONObject

internal data class NmnetDiarizationDelta(
    val inferenceThroughSample: Long,
    val rolesCommittedThroughSample: Long,
    val turns: List<DoubleArray>,
    val speakerCount: Int,
    val segmentationMs: Double,
    val embeddingMs: Double,
)

internal class NmnetDiarizationInference(assets: AssetManager, maxSpeakers: Int) : AutoCloseable {
    init { System.loadLibrary("amphion_diarization_jni") }
    private var handle = nativeLoad(assets, maxSpeakers)
    @Synchronized fun process(samples: FloatArray, validSamples: Int, chunkIndex: Long): NmnetDiarizationDelta {
        check(handle != 0L)
        return parse(nativeProcess(handle, samples, validSamples, chunkIndex))
    }
    @Synchronized fun finish(): NmnetDiarizationDelta { check(handle != 0L); return parse(nativeFinish(handle)) }
    @Synchronized override fun close() { if (handle != 0L) nativeClose(handle); handle = 0 }
    private fun parse(json: String): NmnetDiarizationDelta {
        val value = JSONObject(json)
        val turns = value.getJSONArray("turns")
        return NmnetDiarizationDelta(value.getLong("inferenceThroughSample"),
            value.getLong("rolesCommittedThroughSample"), (0 until turns.length()).map { i ->
                val row = turns.getJSONArray(i); DoubleArray(3) { row.getDouble(it) }
            }, value.getInt("speakerCount"), value.getDouble("segmentationMs"), value.getDouble("embeddingMs"))
    }
    private external fun nativeLoad(assets: AssetManager, maxSpeakers: Int): Long
    private external fun nativeProcess(handle: Long, samples: FloatArray, validSamples: Int, chunkIndex: Long): String
    private external fun nativeFinish(handle: Long): String
    private external fun nativeClose(handle: Long)
}
