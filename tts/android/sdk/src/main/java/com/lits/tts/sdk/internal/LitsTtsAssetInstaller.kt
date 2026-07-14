package com.lits.tts.sdk.internal

import android.content.Context
import com.lits.tts.sdk.TtsErrorCode
import java.io.File
import org.json.JSONArray
import org.json.JSONObject

internal object LitsTtsAssetInstaller {
    fun ensureInstalled(context: Context, workPath: String?): InstalledLayout {
        val installRoot = installRoot(context, workPath)
        discoverExternalLayout(installRoot)?.let { return it }
        val rootDir = installRoot
            .resolve(LitsTtsAssetRegistry.MODEL_ID)
            .resolve(LitsTtsAssetRegistry.MODEL_VERSION)
        val versionFile = rootDir.resolve(".version")
        val signatureFile = rootDir.resolve(".asset_signature")
        val manifestFile = rootDir.resolve(LitsTtsAssetRegistry.MANIFEST)
        val assetSignature = runCatching { readAssetSignature(context) }.getOrElse { error ->
            throw illegalState(
                TtsErrorCode.CREATE_ENGINE_FAILED,
                "TTS external resources not found under ${installRoot.absolutePath}",
                error,
            )
        }
        val needsInstall = versionFile.readTextSafely() != LitsTtsAssetRegistry.MODEL_VERSION ||
            signatureFile.readTextSafely() != assetSignature ||
            !manifestFile.isFile ||
            LitsTtsAssetRegistry.files.any { !rootDir.resolve(it).isFile }

        if (needsInstall) {
            rootDir.deleteRecursively()
            rootDir.mkdirsOrThrow()
            for (name in LitsTtsAssetRegistry.files) {
                copyAssetFile(context, rootDir, name)
            }
            versionFile.writeText(LitsTtsAssetRegistry.MODEL_VERSION)
            signatureFile.writeText(assetSignature)
        }

        val manifest = parseAndValidateManifest(manifestFile)
        return InstalledLayout.of(rootDir, manifest, LayoutSource.BUNDLED_ASSET)
    }

    fun ensureTnBinariesInstalled(context: Context, layout: InstalledLayout) {
        if (layout.tnZhTts.isFile && layout.tnEnTts.isFile) return
        for (name in LitsTtsAssetRegistry.tnBinaryFiles) {
            copyAssetFile(context, layout.rootDir, name)
        }
    }

    private fun copyAssetFile(context: Context, rootDir: File, name: String) {
        val assetPath = "${LitsTtsAssetRegistry.ASSET_ROOT}/${LitsTtsAssetRegistry.assetSubPath}/$name"
        val outFile = rootDir.resolve(name)
        outFile.parentFile?.mkdirsOrThrow()
        context.assets.open(assetPath).use { input ->
            outFile.outputStream().use { output -> input.copyTo(output) }
        }
    }

    private fun parseAndValidateManifest(file: File): ManifestInfo {
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
                                    streamConditionFinalFile.isNullOrBlank() ||
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
            streamDecoderStepModelFile = streamDecoderStepFile,
            streamingChunkSize = streamingChunkSize,
            streamingPreLookaheadLen = streamingPreLookaheadLen,
            streamingMelCacheLen = streamingMelCacheLen,
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

    private fun readAssetSignature(context: Context): String {
        val assetPath =
            "${LitsTtsAssetRegistry.ASSET_ROOT}/${LitsTtsAssetRegistry.assetSubPath}/${LitsTtsAssetRegistry.MANIFEST}"
        val manifestSignature = context.assets.open(assetPath).use { input ->
            input.bufferedReader().use { it.readText() }
        }
        return "${LitsTtsAssetRegistry.ASSET_SIGNATURE_VERSION}\n$manifestSignature"
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
        val tnZhTts: File,
        val tnEnTts: File,
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
                tnZhTts = rootDir.resolve(LitsTtsAssetRegistry.TN_ZH_TTS),
                tnEnTts = rootDir.resolve(LitsTtsAssetRegistry.TN_EN_TTS),
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
                    hiddenEncoderModel?.isFile == true &&
                        streamConditionChunkModel?.isFile == true &&
                        streamConditionFinalModel?.isFile == true &&
                        streamDecoderStepModel?.isFile == true
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
        val streamDecoderStepModelFile: String?,
        val streamingChunkSize: Int,
        val streamingPreLookaheadLen: Int,
        val streamingMelCacheLen: Int,
    )
}
