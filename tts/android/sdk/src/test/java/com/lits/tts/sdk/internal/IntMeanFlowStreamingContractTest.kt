package com.lits.tts.sdk.internal

import org.junit.Assert.*
import org.junit.Test

class IntMeanFlowStreamingContractTest {
    private fun manifest() = LitsTtsAssetInstaller.ManifestInfo(
        modelId = "student", version = "0.1.0", sampleRate = 24000, hopLength = 384,
        speakerCount = 2, defaultSpeakerId = 0, supportsStreaming = true,
        acousticModelFile = null, vocoderModelFile = "vocos.onnx", hiddenEncoderModelFile = "hidden.onnx",
        streamDecoderChunkModelFile = null, streamDecoderFinalModelFile = null,
        streamDecoderExternalLoop = true, streamDecoderTimesteps = 2, streamDecoderTemperature = 0f,
        streamConditionChunkModelFile = "condition.onnx", streamConditionFinalModelFile = "condition.onnx",
        streamDecoderStepModelFile = "init.onnx", streamingChunkSize = 100,
        streamingPreLookaheadLen = 0, streamingMelCacheLen = 8,
        streamDecoderCacheInfo = LitsTtsAssetInstaller.StreamDecoderCacheInfo(
            "init.onnx", "step.onnx", listOf("cache_att_0"), IntMeanFlowStreamingContract.CACHE_MODE, 100),
    )

    @Test fun fiftyFrameModelAllowsLargerInferenceChunks() {
        val fifty = manifest().copy(streamingChunkSize = 50,
            streamDecoderCacheInfo = manifest().streamDecoderCacheInfo!!.copy(requiresFixedChunkSize = 50))
        IntMeanFlowStreamingContract.validate(fifty, 50, 2, 0, 50, 50, 50, 1, 50)
        for (chunk in listOf(40, 42, 50, 64, 75, 100, 150, 200)) {
            IntMeanFlowStreamingContract.validate(fifty, chunk, 2, 0, chunk, chunk, chunk, 1, chunk)
        }
        assertThrows(IllegalArgumentException::class.java) {
            IntMeanFlowStreamingContract.validate(fifty.copy(streamDecoderCacheInfo = manifest().streamDecoderCacheInfo),
                null, null, null, null, null, null, null, null)
        }
        for ((frames, expected) in listOf(49 to listOf(0), 99 to listOf(0),
            100 to listOf(0, 50), 101 to listOf(0, 50), 151 to listOf(0, 50, 100))) {
            assertEquals(expected, LitsTtsOrtRuntime.buildStreamingChunkSlices(frames, 50, 50).map { it.startIdx })
        }
    }

    @Test fun selectedModelManifestIsReadable() {
        val selected = LitsTtsAssetInstaller.parseAndValidateManifest(TtsTestAssets.root().resolve("manifest.json"))
        if (IntMeanFlowStreamingContract.requiresCache(selected)) {
            IntMeanFlowStreamingContract.validate(selected, null, null, null, null, null, null, null, null)
        }
    }

    @Test fun streamingStudentManifestCannotOmitTheCacheContract() {
        val json = org.json.JSONObject(TtsTestAssets.root().resolve("manifest.json").readText())
        json.put("model_type", "lits_intmeanflow_streaming")
        json.remove("stream_decoder_cache")
        val file = kotlin.io.path.createTempFile("invalid-student", ".json").toFile()
        try {
            file.writeText(json.toString())
            val error = assertThrows(IllegalStateException::class.java) {
                LitsTtsAssetInstaller.parseAndValidateManifest(file)
            }
            assertTrue(error.message.orEmpty().contains("trained KV cache contract"))
        } finally { file.delete() }
    }

    @Test fun trainedCacheIsRequiredIndependentlyOfLegacyDefaults() {
        assertFalse(LitsTtsRuntimeOptions.decoderCacheEnabled)
        assertTrue(IntMeanFlowStreamingContract.requiresCache(manifest()))
        assertFalse(IntMeanFlowStreamingContract.requiresCache(manifest().copy(streamDecoderCacheInfo = null)))
        validate()
    }

    @Test fun rejectsUnsupportedSolverAndPartitionOverrides() {
        validate(chunk = 50)
        assertThrows(IllegalArgumentException::class.java) { validate(chunk = 25) }
        assertThrows(IllegalArgumentException::class.java) { validate(chunk = 39) }
        assertThrows(IllegalArgumentException::class.java) { validate(steps = 4) }
        assertThrows(IllegalArgumentException::class.java) { validate(context = 20) }
        assertThrows(IllegalArgumentException::class.java) { validate(first = 25) }
        assertThrows(IllegalArgumentException::class.java) { validate(growth = 2) }
    }

    @Test fun trainedPartitionMergesTheRemainderIntoTheFinalChunk() {
        for ((frames, expected) in listOf(16 to listOf(0), 199 to listOf(0),
            200 to listOf(0, 100), 201 to listOf(0, 100), 350 to listOf(0, 100, 200))) {
            val slices = LitsTtsOrtRuntime.buildStreamingChunkSlices(frames, 100, 100)
            assertEquals("frames=$frames", expected, slices.map { it.startIdx })
        }
    }

    private fun validate(chunk: Int? = null, steps: Int? = null, context: Int? = null,
        first: Int? = null, growth: Int? = null) = IntMeanFlowStreamingContract.validate(
        manifest(), chunk, steps, context, first, null, null, growth, null)
}
