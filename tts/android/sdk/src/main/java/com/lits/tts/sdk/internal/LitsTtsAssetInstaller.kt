package com.lits.tts.sdk.internal

import android.content.Context
import com.lits.tts.sdk.TtsErrorCode
import java.io.File
import org.json.JSONArray
import org.json.JSONObject

internal object LitsTtsAssetInstaller {
    @Synchronized
    fun ensureInstalled(context: Context, workPath: String?): InstalledLayout {
        val installRoot = installRoot(context, workPath)
        discoverExternalLayout(installRoot)?.let { return it }
        val assetRoot = "${LitsTtsAssetRegistry.ASSET_ROOT}/${LitsTtsAssetRegistry.MODEL_ROOT}"
        val candidates = context.assets.list(assetRoot).orEmpty().flatMap { model ->
            context.assets.list("$assetRoot/$model").orEmpty().map { version -> "$assetRoot/$model/$version" }
        }.filter { path -> context.assets.list(path).orEmpty().contains(LitsTtsAssetRegistry.MANIFEST) }
        if (candidates.size != 1) {
            throw illegalState(TtsErrorCode.CREATE_ENGINE_FAILED,
                "Expected one bundled TTS model, found ${candidates.size}; no external resources under $installRoot")
        }
        val assetPath = candidates.single()
        val manifestText = context.assets.open("$assetPath/manifest.json").bufferedReader().use { it.readText() }
        val json = JSONObject(manifestText)
        val modelId = json.getString("model_id")
        val version = json.getString("version")
        requireSafeAssetPath(modelId, singleSegment = true)
        requireSafeAssetPath(version, singleSegment = true)
        check(assetPath == "$assetRoot/$modelId/$version") { "Bundled TTS identity mismatch" }
        val entries = json.getJSONArray("files")
        val files = (0 until entries.length()).map { entries.getJSONObject(it) }
        files.forEach { requireSafeAssetPath(it.getString("name")) }
        val rootDir = installRoot.resolve(modelId).resolve(version)
        val signature = manifestText.trim()
        val needsInstall = rootDir.resolve(".asset_signature").readTextSafely() != signature ||
            !rootDir.resolve("manifest.json").isFile ||
            files.any { entry ->
                val file = rootDir.resolve(entry.getString("name"))
                !file.isFile || file.length() != entry.getLong("size_bytes")
            }
        if (needsInstall) {
            // Stage fully before replacing the previous installed bundle. Mark staging so
            // interrupted extraction can never be mistaken for an external model.
            val staging = rootDir.parentFile!!.resolve(".$version.installing")
            staging.deleteRecursively()
            staging.mkdirsOrThrow()
            staging.resolve(".version").writeText(version)
            try {
                for (entry in files) {
                    val name = entry.getString("name")
                    val outFile = staging.resolve(name)
                    outFile.parentFile?.mkdirsOrThrow()
                    val digest = java.security.MessageDigest.getInstance("SHA-256")
                    context.assets.open("$assetPath/$name").use { input ->
                        java.security.DigestInputStream(input, digest).use { checked ->
                            outFile.outputStream().use { output -> checked.copyTo(output) }
                        }
                    }
                    val hash = digest.digest().joinToString("") { "%02x".format(it) }
                    check(outFile.length() == entry.getLong("size_bytes") && hash == entry.getString("sha256")) {
                        "Bundled TTS resource checksum mismatch: $name"
                    }
                }
                staging.resolve("manifest.json").writeText(manifestText)
                val layout = InstalledLayout.of(staging, parseAndValidateManifest(staging.resolve("manifest.json")), LayoutSource.BUNDLED_ASSET)
                check(layout.hasRequiredFiles()) { "Bundled TTS resources are incomplete" }
                staging.resolve(".asset_signature").writeText(signature)
                check(!rootDir.exists() || rootDir.deleteRecursively()) { "Cannot replace installed TTS bundle" }
                check(staging.renameTo(rootDir)) { "Cannot publish installed TTS bundle" }
            } finally {
                staging.deleteRecursively()
            }
        }
        return InstalledLayout.of(rootDir, parseAndValidateManifest(rootDir.resolve("manifest.json")), LayoutSource.BUNDLED_ASSET)
    }

    private fun requireSafeAssetPath(name: String, singleSegment: Boolean = false) {
        require(name.isNotBlank() && !name.startsWith("/") && '\\' !in name &&
            name.split('/').all { it.isNotBlank() && it != "." && it != ".." } &&
            (!singleSegment || '/' !in name)) { "Invalid bundled TTS resource path" }
    }

    internal fun parseAndValidateManifest(file: File): ManifestInfo {
        val json = try {
            JSONObject(file.readText())
        } catch (error: Throwable) {
            throw illegalState(TtsErrorCode.CREATE_ENGINE_FAILED, "failed to parse TTS manifest", error)
        }
        val task = json.optString("task")
        val modelId = json.optString("model_id")
        val version = json.optString("version")
        val runtimeFormat = json.optString("runtime_format")
        val sampleRate = json.optInt("sample_rate", -1)
        val hopLength = json.optInt("hop_length", -1)
        val speakerCount = json.optInt("speaker_count", -1)
        val defaultSpeakerId = json.optInt("default_speaker_id", -1)
        val defaultLanguage = json.optString("default_language")
        val vocoderType = json.optString("vocoder_type")
        val supportsStreaming = json.optBoolean("supports_streaming", false)
        val supportedLanguages = json.optJSONArray("supported_languages")
        val acousticFile = json.optJSONObject("acoustic_model")?.optString("file")
        val vocoderFile = json.optJSONObject("vocoder_model")?.optString("file")
        val hiddenEncoderFile = json.optJSONObject("hidden_encoder_model")?.optString("file")
        val streamDecoderChunkFile = json.optJSONObject("stream_decoder_chunk_model")?.optString("file")
        val streamDecoderFinalFile = json.optJSONObject("stream_decoder_final_model")?.optString("file")
        val streamDecoderExternalLoop = json.optBoolean("stream_decoder_external_loop", false)
        val streamDecoderTimesteps = json.optInt("stream_decoder_n_timesteps", -1)
        val streamDecoderTemperature = json.optDouble("stream_decoder_temperature", Double.NaN).toFloat()
        val streamConditionChunkFile = json.optJSONObject("stream_condition_chunk_model")?.optString("file")
        val streamConditionFinalFile = json.optJSONObject("stream_condition_final_model")?.optString("file")
        val streamDecoderStepFile = json.optJSONObject("stream_decoder_step_model")?.optString("file")
        val streamDecoderCacheInfo = parseStreamDecoderCacheInfo(json.optJSONObject("stream_decoder_cache"))
        if (json.optString("model_type") == "lits_intmeanflow_streaming" &&
            streamDecoderCacheInfo?.mode != IntMeanFlowStreamingContract.CACHE_MODE) {
            throw illegalState(TtsErrorCode.CREATE_ENGINE_FAILED, "IntMeanFlow streaming requires its trained KV cache contract")
        }
        val streamFinalZeroPadWithChunkCondition =
            json.optBoolean("stream_final_zero_pad_with_chunk_condition", false)
        val streamingChunkSize = json.optInt("streaming_chunk_size", -1)
        val streamingPreLookaheadLen = json.optInt("streaming_pre_lookahead_len", -1)
        val streamingMelCacheLen = json.optInt("streaming_mel_cache_len", -1)
        if (
            task != "tts" ||
            modelId.isBlank() ||
            version.isBlank() ||
            runtimeFormat != "onnx"
        ) {
            throw illegalState(TtsErrorCode.CREATE_ENGINE_FAILED, "TTS manifest identity mismatch")
        }
        if (
            sampleRate <= 0 ||
            hopLength <= 0 ||
            speakerCount <= 0 ||
            defaultSpeakerId !in 0 until speakerCount ||
            defaultLanguage != "zh-en" ||
            vocoderType !in setOf("hifigan", "vocos") ||
            !supportedLanguages.containsString("zh-en") ||
            !supportedLanguages.containsString("en-US")
        ) {
            throw illegalState(TtsErrorCode.CREATE_ENGINE_FAILED, "TTS manifest core fields are invalid")
        }
        if (
            !supportsStreaming &&
            (
                acousticFile != LitsTtsAssetRegistry.ACOUSTIC_MODEL ||
                    vocoderFile != LitsTtsAssetRegistry.VOCODER_MODEL
                )
        ) {
            throw illegalState(TtsErrorCode.CREATE_ENGINE_FAILED, "TTS manifest model files are invalid")
        }
        if (
            supportsStreaming &&
            (
                hiddenEncoderFile.isNullOrBlank() ||
                    (
                        streamDecoderExternalLoop &&
                            (
                                streamConditionChunkFile.isNullOrBlank() ||
                                    (!streamFinalZeroPadWithChunkCondition && streamConditionFinalFile.isNullOrBlank()) ||
                                    streamDecoderStepFile.isNullOrBlank() ||
                                    streamDecoderTimesteps <= 0 ||
                                    streamDecoderTemperature.isNaN()
                                )
                        ) ||
                    (!streamDecoderExternalLoop && streamDecoderChunkFile.isNullOrBlank()) ||
                    vocoderFile.isNullOrBlank() ||
                    streamingChunkSize <= 0 ||
                    streamingPreLookaheadLen < 0 ||
                    streamingMelCacheLen <= 0
                )
        ) {
            throw illegalState(TtsErrorCode.CREATE_ENGINE_FAILED, "TTS streaming manifest fields are invalid")
        }
        return ManifestInfo(
            modelId = modelId,
            version = version,
            sampleRate = sampleRate,
            hopLength = hopLength,
            speakerCount = speakerCount,
            defaultSpeakerId = defaultSpeakerId,
            supportsStreaming = supportsStreaming,
            acousticModelFile = acousticFile,
            vocoderModelFile = vocoderFile ?: throw illegalState(TtsErrorCode.CREATE_ENGINE_FAILED, "TTS manifest vocoder file missing"),
            hiddenEncoderModelFile = hiddenEncoderFile,
            streamDecoderChunkModelFile = streamDecoderChunkFile,
            streamDecoderFinalModelFile = streamDecoderFinalFile,
            streamDecoderExternalLoop = streamDecoderExternalLoop,
            streamDecoderTimesteps = streamDecoderTimesteps,
            streamDecoderTemperature = streamDecoderTemperature,
            streamConditionChunkModelFile = streamConditionChunkFile,
            streamConditionFinalModelFile = streamConditionFinalFile,
            streamFinalZeroPadWithChunkCondition = streamFinalZeroPadWithChunkCondition,
            streamDecoderStepModelFile = streamDecoderStepFile,
            streamDecoderCacheInfo = streamDecoderCacheInfo,
            streamingChunkSize = streamingChunkSize,
            streamingPreLookaheadLen = streamingPreLookaheadLen,
            streamingMelCacheLen = streamingMelCacheLen,
        )
    }

    private fun parseStreamDecoderCacheInfo(json: JSONObject?): StreamDecoderCacheInfo? {
        if (json == null) return null
        val initFile = json.optJSONObject("init_model")?.optString("file").orEmpty()
        val stepFile = json.optJSONObject("step_model")?.optString("file").orEmpty()
        val stateNamesJson = json.optJSONArray("state_names")
        val stateNames = mutableListOf<String>()
        if (stateNamesJson != null) {
            for (index in 0 until stateNamesJson.length()) {
                val name = stateNamesJson.optString(index)
                if (name.isNotBlank()) stateNames += name
            }
        }
        val stateCount = json.optInt("state_count", -1)
        val mode = json.optString("mode")
        val fixedChunkSize = json.optInt("requires_fixed_chunk_size", -1)
        if (
            initFile.isBlank() ||
            stepFile.isBlank() ||
            stateNames.isEmpty() ||
            stateCount != stateNames.size ||
            mode !in setOf("relative_left_window_v1", IntMeanFlowStreamingContract.CACHE_MODE) ||
            fixedChunkSize <= 0
        ) {
            throw illegalState(TtsErrorCode.CREATE_ENGINE_FAILED, "TTS stream decoder cache fields are invalid")
        }
        return StreamDecoderCacheInfo(
            initModelFile = initFile,
            stepModelFile = stepFile,
            stateNames = stateNames,
            mode = mode,
            requiresFixedChunkSize = fixedChunkSize,
        )
    }

    private fun installRoot(context: Context, workPath: String?): File {
        val base = workPath?.takeIf { it.isNotBlank() }?.let(::File)
            ?: File(context.filesDir, "lits-tts-runtime")
        return base.resolve("tts")
    }

    private fun discoverExternalLayout(installRoot: File): InstalledLayout? {
        if (!installRoot.isDirectory) return null
        val manifests = installRoot.walkTopDown()
            .maxDepth(3)
            .filter { it.isFile && it.name == LitsTtsAssetRegistry.MANIFEST }
            .toList()
        return manifests
            .mapNotNull { manifestFile ->
                val rootDir = manifestFile.parentFile?.absoluteFile ?: return@mapNotNull null
                if (rootDir.resolve(".version").isFile || rootDir.resolve(".asset_signature").isFile) {
                    return@mapNotNull null
                }
                val manifest = runCatching { parseAndValidateManifest(manifestFile) }.getOrNull() ?: return@mapNotNull null
                InstalledLayout.of(rootDir, manifest, LayoutSource.EXTERNAL_PACKAGE)
                    .takeIf(InstalledLayout::hasRequiredFiles)
            }
            .sortedWith(
                compareByDescending<InstalledLayout> { it.manifest.supportsStreaming }
                    .thenBy { it.rootDir.absolutePath },
            )
            .firstOrNull()
    }

    private fun File.mkdirsOrThrow() {
        if (!isDirectory && !mkdirs()) {
            throw illegalState(TtsErrorCode.CREATE_ENGINE_FAILED, "failed to create directory: $absolutePath")
        }
    }

    private fun File.readTextSafely(): String? = try {
        readText().trim()
    } catch (_: Throwable) {
        null
    }

    private fun JSONArray?.containsString(expected: String): Boolean {
        if (this == null) return false
        for (index in 0 until length()) {
            if (optString(index) == expected) return true
        }
        return false
    }

    private fun illegalState(code: Int, message: String, cause: Throwable? = null): IllegalStateException =
        IllegalStateException("$code:$message", cause)

    internal data class InstalledLayout(
        val rootDir: File,
        val manifest: ManifestInfo,
        val source: LayoutSource,
        val acousticModel: File?,
        val vocoderModel: File,
        val hiddenEncoderModel: File?,
        val streamDecoderChunkModel: File?,
        val streamDecoderFinalModel: File?,
        val streamConditionChunkModel: File?,
        val streamConditionFinalModel: File?,
        val streamDecoderStepModel: File?,
        val streamDecoderCacheInitModel: File?,
        val streamDecoderCacheStepModel: File?,
        val frontendGolden: File,
        val frontendRules: File,
        val chineseLexicon: File,
        val chineseLexiconBin: File,
        val cmudict: File,
        val cmudictBin: File,
        val supplementLexicon: File,
        val symbols: File,
        val pinyinToTokens: File,
        val arpabetToTokens: File,
        val polychar: File,
    ) {
        companion object {
            fun of(rootDir: File, manifest: ManifestInfo, source: LayoutSource): InstalledLayout = InstalledLayout(
                rootDir = rootDir,
                manifest = manifest,
                source = source,
                acousticModel = manifest.acousticModelFile?.let(rootDir::resolve),
                vocoderModel = rootDir.resolve(manifest.vocoderModelFile),
                hiddenEncoderModel = manifest.hiddenEncoderModelFile?.let(rootDir::resolve),
                streamDecoderChunkModel = manifest.streamDecoderChunkModelFile
                    ?.takeUnless { manifest.streamDecoderExternalLoop }
                    ?.let(rootDir::resolve),
                streamDecoderFinalModel = manifest.streamDecoderFinalModelFile
                    ?.takeUnless { manifest.streamDecoderExternalLoop }
                    ?.let(rootDir::resolve),
                streamConditionChunkModel = manifest.streamConditionChunkModelFile?.let(rootDir::resolve),
                streamConditionFinalModel = manifest.streamConditionFinalModelFile?.let(rootDir::resolve),
                streamDecoderStepModel = manifest.streamDecoderStepModelFile?.let(rootDir::resolve),
                streamDecoderCacheInitModel = manifest.streamDecoderCacheInfo?.initModelFile?.let(rootDir::resolve),
                streamDecoderCacheStepModel = manifest.streamDecoderCacheInfo?.stepModelFile?.let(rootDir::resolve),
                frontendGolden = rootDir.resolve(LitsTtsAssetRegistry.FRONTEND_GOLDEN),
                frontendRules = rootDir.resolve(LitsTtsAssetRegistry.FRONTEND_RULES),
                chineseLexicon = rootDir.resolve(LitsTtsAssetRegistry.CHINESE_LEXICON),
                chineseLexiconBin = rootDir.resolve(LitsTtsAssetRegistry.CHINESE_LEXICON_BIN),
                cmudict = rootDir.resolve(LitsTtsAssetRegistry.CMUDICT),
                cmudictBin = rootDir.resolve(LitsTtsAssetRegistry.CMUDICT_BIN),
                supplementLexicon = rootDir.resolve(LitsTtsAssetRegistry.SUPPLEMENT_LEXICON),
                symbols = rootDir.resolve(LitsTtsAssetRegistry.SYMBOLS),
                pinyinToTokens = rootDir.resolve(LitsTtsAssetRegistry.PINYIN_TO_TOKENS),
                arpabetToTokens = rootDir.resolve(LitsTtsAssetRegistry.ARPABET_TO_TOKENS),
                polychar = rootDir.resolve(LitsTtsAssetRegistry.POLYCHAR),
            )
        }

        fun hasRequiredFiles(): Boolean {
            val coreFiles = listOf(
                vocoderModel,
                frontendGolden,
                chineseLexicon,
                cmudict,
                symbols,
                pinyinToTokens,
                arpabetToTokens,
                polychar,
            )
            if (coreFiles.any { !it.isFile }) return false
            return if (manifest.supportsStreaming) {
                if (manifest.streamDecoderExternalLoop) {
                    val cacheFilesReady = manifest.streamDecoderCacheInfo == null ||
                        (
                            streamDecoderCacheInitModel?.isFile == true &&
                                streamDecoderCacheStepModel?.isFile == true
                            )
                    hiddenEncoderModel?.isFile == true &&
                        streamConditionChunkModel?.isFile == true &&
                        (
                            manifest.streamFinalZeroPadWithChunkCondition ||
                                streamConditionFinalModel?.isFile == true
                            ) &&
                        streamDecoderStepModel?.isFile == true &&
                        cacheFilesReady
                } else {
                    hiddenEncoderModel?.isFile == true &&
                        streamDecoderChunkModel?.isFile == true &&
                        streamDecoderFinalModel?.isFile == true
                }
            } else {
                acousticModel?.isFile == true
            }
        }

        fun debugSummary(): String {
            val sourceLabel = when (source) {
                LayoutSource.EXTERNAL_PACKAGE -> "external"
                LayoutSource.BUNDLED_ASSET -> "bundled"
            }
            val streamingLabel = if (manifest.supportsStreaming) "streaming" else "non_streaming"
            val chunkSizeLabel = if (manifest.supportsStreaming) manifest.streamingChunkSize.toString() else "-"
            return buildString {
                append("source=").append(sourceLabel)
                append(" model=").append(manifest.modelId)
                append(" version=").append(manifest.version)
                append(" mode=").append(streamingLabel)
                append(" chunkSize=").append(chunkSizeLabel)
                append(" path=").append(rootDir.absolutePath)
            }
        }
    }

    internal enum class LayoutSource {
        EXTERNAL_PACKAGE,
        BUNDLED_ASSET,
    }

    internal data class ManifestInfo(
        val modelId: String,
        val version: String,
        val sampleRate: Int,
        val hopLength: Int,
        val speakerCount: Int,
        val defaultSpeakerId: Int,
        val supportsStreaming: Boolean,
        val acousticModelFile: String?,
        val vocoderModelFile: String,
        val hiddenEncoderModelFile: String?,
        val streamDecoderChunkModelFile: String?,
        val streamDecoderFinalModelFile: String?,
        val streamDecoderExternalLoop: Boolean,
        val streamDecoderTimesteps: Int,
        val streamDecoderTemperature: Float,
        val streamConditionChunkModelFile: String?,
        val streamConditionFinalModelFile: String?,
        val streamFinalZeroPadWithChunkCondition: Boolean = false,
        val streamDecoderStepModelFile: String?,
        // Optional so manifests/tests without the explicit decoder-state cache
        // remain compatible with the ordinary no-cache streaming path.
        val streamDecoderCacheInfo: StreamDecoderCacheInfo? = null,
        val streamingChunkSize: Int,
        val streamingPreLookaheadLen: Int,
        val streamingMelCacheLen: Int,
    )

    internal data class StreamDecoderCacheInfo(
        val initModelFile: String,
        val stepModelFile: String,
        val stateNames: List<String>,
        val mode: String,
        val requiresFixedChunkSize: Int,
    )
}
