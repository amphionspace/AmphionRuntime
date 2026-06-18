package com.lits.tts.sdk.internal

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.nio.FloatBuffer
import java.nio.LongBuffer
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

internal class LitsTtsOrtRuntime(
    private val layout: LitsTtsAssetInstaller.InstalledLayout,
) : AutoCloseable {
    private val environment: OrtEnvironment = OrtEnvironment.getEnvironment()
    private val acousticSession: OrtSession
    private val vocoderSession: OrtSession

    init {
        acousticSession = environment.createSession(layout.acousticModel.absolutePath, createSessionOptions(intraOpThreads = 2))
        vocoderSession = environment.createSession(layout.vocoderModel.absolutePath, createSessionOptions(intraOpThreads = 6))
    }

    fun synthesize(tokenIds: LongArray, speakerId: Int): FloatArray {
        OnnxTensor.createTensor(environment, LongBuffer.wrap(tokenIds), longArrayOf(1L, tokenIds.size.toLong())).use { tokenTensor ->
            OnnxTensor.createTensor(environment, LongBuffer.wrap(longArrayOf(tokenIds.size.toLong())), longArrayOf(1L)).use { lengthTensor ->
                OnnxTensor.createTensor(environment, LongBuffer.wrap(longArrayOf(speakerId.toLong())), longArrayOf(1L)).use { speakerTensor ->
                    val acousticInputs = mapOf(
                        "token_ids" to tokenTensor,
                        "token_lengths" to lengthTensor,
                        "speaker_id" to speakerTensor,
                    )
                    acousticSession.run(acousticInputs, setOf("mel")).use { acousticResult ->
                        val melTensor = acousticResult.get("mel").orElseThrow {
                            IllegalStateException("acoustic output 'mel' missing")
                        } as OnnxTensor
                        val melInfo = melTensor.info as ai.onnxruntime.TensorInfo
                        val melValues = melTensor.floatBuffer.toFloatArray(melInfo.numElements.toInt())
                        OnnxTensor.createTensor(environment, FloatBuffer.wrap(melValues), melInfo.shape).use { melInputTensor ->
                            vocoderSession.run(mapOf("mel" to melInputTensor), setOf("waveform")).use { vocoderResult ->
                                val waveformTensor = vocoderResult.get("waveform").orElseThrow {
                                    IllegalStateException("vocoder output 'waveform' missing")
                                } as OnnxTensor
                                val info = waveformTensor.info as ai.onnxruntime.TensorInfo
                                return waveformTensor.floatBuffer.toFloatArray(info.numElements.toInt())
                            }
                        }
                    }
                }
            }
        }
    }

    override fun close() {
        vocoderSession.close()
        acousticSession.close()
    }

    companion object {
        private fun createSessionOptions(intraOpThreads: Int): OrtSession.SessionOptions {
            return OrtSession.SessionOptions().apply {
                setIntraOpNumThreads(intraOpThreads)
                setInterOpNumThreads(1)
                setExecutionMode(OrtSession.SessionOptions.ExecutionMode.SEQUENTIAL)
                setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT)
            }
        }

        fun floatToPcm16(waveform: FloatArray): ShortArray = ShortArray(waveform.size) { index ->
            val clipped = max(-1.0f, min(1.0f, waveform[index]))
            (clipped * Short.MAX_VALUE).roundToInt().toShort()
        }
    }
}

private fun FloatBuffer.toFloatArray(size: Int): FloatArray {
    val duplicate = duplicate()
    duplicate.rewind()
    return FloatArray(size).also { duplicate.get(it) }
}
