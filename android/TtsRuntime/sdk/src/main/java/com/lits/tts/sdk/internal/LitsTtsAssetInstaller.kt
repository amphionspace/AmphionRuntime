package com.lits.tts.sdk.internal

import android.content.Context
import com.lits.tts.sdk.TtsErrorCode
import java.io.File
import org.json.JSONArray
import org.json.JSONObject

internal object LitsTtsAssetInstaller {
    fun ensureInstalled(context: Context, workPath: String?): InstalledLayout {
        val rootDir = installRoot(context, workPath)
            .resolve(LitsTtsAssetRegistry.MODEL_ID)
            .resolve(LitsTtsAssetRegistry.MODEL_VERSION)
        val versionFile = rootDir.resolve(".version")
        val signatureFile = rootDir.resolve(".asset_signature")
        val manifestFile = rootDir.resolve(LitsTtsAssetRegistry.MANIFEST)
        val assetSignature = readAssetSignature(context)
        val needsInstall = versionFile.readTextSafely() != LitsTtsAssetRegistry.MODEL_VERSION ||
            signatureFile.readTextSafely() != assetSignature ||
            !manifestFile.isFile ||
            LitsTtsAssetRegistry.files.any { !rootDir.resolve(it).isFile }

        if (needsInstall) {
            rootDir.deleteRecursively()
            rootDir.mkdirsOrThrow()
            for (name in LitsTtsAssetRegistry.files) {
                val assetPath = "${LitsTtsAssetRegistry.ASSET_ROOT}/${LitsTtsAssetRegistry.assetSubPath}/$name"
                val outFile = rootDir.resolve(name)
                outFile.parentFile?.mkdirsOrThrow()
                context.assets.open(assetPath).use { input ->
                    outFile.outputStream().use { output -> input.copyTo(output) }
                }
            }
            versionFile.writeText(LitsTtsAssetRegistry.MODEL_VERSION)
            signatureFile.writeText(assetSignature)
        }

        val manifest = parseAndValidateManifest(manifestFile)
        return InstalledLayout.of(rootDir, manifest)
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
        val speakerCount = json.optInt("speaker_count", -1)
        val defaultSpeakerId = json.optInt("default_speaker_id", -1)
        val defaultLanguage = json.optString("default_language")
        val vocoderType = json.optString("vocoder_type")
        val supportedLanguages = json.optJSONArray("supported_languages")
        val acousticFile = json.optJSONObject("acoustic_model")?.optString("file")
        val vocoderFile = json.optJSONObject("vocoder_model")?.optString("file")
        if (
            task != "tts" ||
            modelId != LitsTtsAssetRegistry.MODEL_ID ||
            version != LitsTtsAssetRegistry.MODEL_VERSION ||
            runtimeFormat != "onnx"
        ) {
            throw illegalState(TtsErrorCode.CREATE_ENGINE_FAILED, "TTS manifest identity mismatch")
        }
        if (
            sampleRate != 16_000 ||
            speakerCount <= 0 ||
            defaultSpeakerId !in 0 until speakerCount ||
            defaultLanguage != "zh-en" ||
            vocoderType != "hifigan" ||
            !supportedLanguages.containsString("zh-en") ||
            !supportedLanguages.containsString("en-US")
        ) {
            throw illegalState(TtsErrorCode.CREATE_ENGINE_FAILED, "TTS manifest core fields are invalid")
        }
        if (
            acousticFile != LitsTtsAssetRegistry.ACOUSTIC_MODEL ||
            vocoderFile != LitsTtsAssetRegistry.VOCODER_MODEL
        ) {
            throw illegalState(TtsErrorCode.CREATE_ENGINE_FAILED, "TTS manifest model files are invalid")
        }
        return ManifestInfo(
            sampleRate = sampleRate,
            speakerCount = speakerCount,
            defaultSpeakerId = defaultSpeakerId,
            acousticModelFile = acousticFile,
            vocoderModelFile = vocoderFile,
        )
    }

    private fun installRoot(context: Context, workPath: String?): File {
        val base = workPath?.takeIf { it.isNotBlank() }?.let(::File)
            ?: File(context.filesDir, "lits-tts-runtime")
        return base.resolve("tts")
    }

    private fun readAssetSignature(context: Context): String {
        val assetPath =
            "${LitsTtsAssetRegistry.ASSET_ROOT}/${LitsTtsAssetRegistry.assetSubPath}/${LitsTtsAssetRegistry.MANIFEST}"
        return context.assets.open(assetPath).use { input ->
            input.bufferedReader().use { it.readText() }
        }
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
        val acousticModel: File,
        val vocoderModel: File,
        val frontendGolden: File,
        val chineseLexicon: File,
        val cmudict: File,
        val symbols: File,
        val pinyinToTokens: File,
        val arpabetToTokens: File,
        val polychar: File,
    ) {
        companion object {
            fun of(rootDir: File, manifest: ManifestInfo): InstalledLayout = InstalledLayout(
                rootDir = rootDir,
                manifest = manifest,
                acousticModel = rootDir.resolve(manifest.acousticModelFile),
                vocoderModel = rootDir.resolve(manifest.vocoderModelFile),
                frontendGolden = rootDir.resolve(LitsTtsAssetRegistry.FRONTEND_GOLDEN),
                chineseLexicon = rootDir.resolve(LitsTtsAssetRegistry.CHINESE_LEXICON),
                cmudict = rootDir.resolve(LitsTtsAssetRegistry.CMUDICT),
                symbols = rootDir.resolve(LitsTtsAssetRegistry.SYMBOLS),
                pinyinToTokens = rootDir.resolve(LitsTtsAssetRegistry.PINYIN_TO_TOKENS),
                arpabetToTokens = rootDir.resolve(LitsTtsAssetRegistry.ARPABET_TO_TOKENS),
                polychar = rootDir.resolve(LitsTtsAssetRegistry.POLYCHAR),
            )
        }
    }

    internal data class ManifestInfo(
        val sampleRate: Int,
        val speakerCount: Int,
        val defaultSpeakerId: Int,
        val acousticModelFile: String,
        val vocoderModelFile: String,
    )
}
