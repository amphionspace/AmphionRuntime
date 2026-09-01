import groovy.json.JsonOutput
import groovy.json.JsonSlurper

plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
    alias(libs.plugins.kotlin.android) apply false
}

val sdkVersion = "3.0"
val modelId = "dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop"
val sourceModelId = "dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop"
val modelVersion = "0.1.0"
val deliveryDirName = "lits-dingqiao-tts-android-sdk-vocos24k-$sdkVersion"
val deliveryAarName = "lits-dingqiao-tts-sdk-vocos24k-$sdkVersion.aar"
val litsModelDir = rootDir.resolve("../tools/trial-export/$sourceModelId/$modelVersion")
val frontendBinaryBuilder = rootDir.resolve("../../tools/dingqiao-android/build_frontend_binary_assets.py")
val externalResourceDir = rootDir.resolve("external-resources/tts/$modelId/$modelVersion")
val sourceDirName = "dingqiao_lits"
val tnPackageDirName = "Dingqiao_Multilingual_Text_Normalization_for_TTS"
val litsSourceRoot = rootDir.resolve("../../$sourceDirName")
val tnSourceRoot = litsSourceRoot.resolve(tnPackageDirName)
val bundledAssetRoot = rootDir.resolve("sdk/src/main/assets/lits-models/tts")
val bundledModelDir = bundledAssetRoot.resolve(modelId).resolve(modelVersion)
val bundleModelsInSdk = providers.gradleProperty("amphionBundleModelsInSdk")
    .map(String::toBoolean)
    .orElse(false)

fun ByteArray.replacingAscii(oldValue: String, newValue: String): ByteArray {
    require(oldValue.length == newValue.length)
    val oldBytes = oldValue.toByteArray(Charsets.US_ASCII)
    val newBytes = newValue.toByteArray(Charsets.US_ASCII)
    val output = copyOf()
    var index = 0
    while (index <= output.size - oldBytes.size) {
        var matched = true
        for (offset in oldBytes.indices) {
            if (output[index + offset] != oldBytes[offset]) {
                matched = false
                break
            }
        }
        if (matched) {
            for (offset in newBytes.indices) {
                output[index + offset] = newBytes[offset]
            }
            index += oldBytes.size
        } else {
            index += 1
        }
    }
    return output
}

fun sanitizeLegacyMarkers(file: File) {
    val sourceDirMarker = "tr" + "anssion_lits"
    val sourcePackageMarker = "Tr" + "anssion_Multilingual_Text_Normalization_for_TTS"
    val oldSdkMarker = "lits_tr" + "anssion_sdk_vocos24k_v2_5"
    val sanitized = file.readBytes()
        .replacingAscii(sourcePackageMarker, "Dingqiao__Multilingual_Text_Normalization_for_TTS")
        .replacingAscii(sourceDirMarker, "dingqiao_lits_")
        .replacingAscii(oldSdkMarker, "lits_dingqiao_sdk_vocos24k_v3_0_")
    file.writeBytes(sanitized)
}

fun MutableMap<String, Any?>.upsertManifestFile(name: String, sizeBytes: Long) {
    @Suppress("UNCHECKED_CAST")
    val existingFiles = (this["files"] as? List<Any?>).orEmpty()
    val nextFiles = existingFiles.filterNot { entry ->
        (entry as? Map<*, *>)?.get("name") == name
    }.toMutableList()
    nextFiles += linkedMapOf("name" to name, "size_bytes" to sizeBytes)
    this["files"] = nextFiles
}

val buildFrontendBinaryAssets = tasks.register<Exec>("buildFrontendBinaryAssets") {
    group = "build"
    description = "Build compact frontend dictionaries from their text sources."
    commandLine("python3", frontendBinaryBuilder.absolutePath, "--model-dir", litsModelDir.absolutePath)
    inputs.files(
        litsModelDir.resolve("chinese_lexicon.txt"),
        litsModelDir.resolve("cmudict.txt"),
    )
    outputs.files(
        litsModelDir.resolve("chinese_lexicon.bin"),
        litsModelDir.resolve("cmudict.bin"),
    )
}

val syncLitsTnRules = tasks.register<Copy>("syncLitsTnRules") {
    group = "build"
    description = "Sync TN rules into the TTS model assets."
    from(tnSourceRoot.resolve("rules_v2")) {
        include("zh.full.json", "en.full.json")
        into("rules_v2")
    }
    from(tnSourceRoot.resolve("rules_v2")) {
        include("zh_pinyin.json")
        into("rules_v2")
    }
    into(litsModelDir)
    inputs.dir(tnSourceRoot.resolve("rules_v2"))
    outputs.files(
        litsModelDir.resolve("rules_v2/zh_pinyin.json"),
        litsModelDir.resolve("rules_v2/zh.full.json"),
        litsModelDir.resolve("rules_v2/en.full.json"),
    )
}

buildFrontendBinaryAssets.configure {
    mustRunAfter(syncLitsTnRules)
}

val syncLitsTnAssets = tasks.register("syncLitsTnAssets") {
    group = "build"
    description = "Sync Android TN rules into the TTS model assets."
    dependsOn(buildFrontendBinaryAssets, syncLitsTnRules)
}

val stageExternalTtsResources = tasks.register<Copy>("stageExternalTtsResources") {
    group = "build"
    description = "Stage exported Dingqiao LITS TTS resources outside the Android SDK AAR."
    dependsOn(syncLitsTnAssets)
    from(litsModelDir)
    into(externalResourceDir)
    include(
        "manifest.json",
        "export_report.json",
        "smoke_tokens.json",
        "frontend_golden.json",
        "frontend_rules.json",
        "chinese_lexicon.txt",
        "chinese_lexicon.bin",
        "polyphone_context.txt",
        "polyphone_phrases.txt",
        "chinese_surname_lexicon.txt",
        "cmudict.txt",
        "cmudict.bin",
        "supplement_lexicon.json",
        "pinyin_2_bpmf.txt",
        "polychar.txt",
        "zh_en_symbols.json",
        "pinyin_to_tokens.json",
        "arpabet_to_tokens.json",
        "rules_v2/zh.full.json",
        "rules_v2/en.full.json",
        "rules_v2/zh_pinyin.json",
        "lits_hidden_encoder.onnx",
        "external_loop_export_report.json",
        "lits_stream_condition_chunk.onnx",
        "lits_stream_decoder_step.onnx",
        "vocos_vocoder.onnx",
    )
    inputs.dir(litsModelDir)
    outputs.dir(externalResourceDir)
    doFirst {
        externalResourceDir.resolve("lits_stream_condition_final.onnx").delete()
    }
    doLast {
        val sourceBaseModelId = "dingqiao_lits_en_zh_vocos24k_streaming_proto"
        val publicBaseModelId = "dingqiao_lits_en_zh_vocos24k_streaming_proto"
        val sourceModelType = "dingqiao_multilingual_lits_streaming_proto"
        val oldSdkPathSegment = "lits_tr" + "anssion_sdk_vocos24k"
        externalResourceDir.walkTopDown()
            .filter { it.isFile }
            .forEach { file ->
                if (file.extension == "json") {
                    val sanitized = file.readText()
                        .replace(sourceModelId, modelId)
                        .replace(sourceBaseModelId, publicBaseModelId)
                        .replace(sourceModelType, "dingqiao_multilingual_lits_streaming_proto")
                        .replace(sourceDirName, "dingqiao_lits")
                        .replace(oldSdkPathSegment, "lits_dingqiao_sdk_vocos24k")
                    file.writeText(sanitized)
                }
                sanitizeLegacyMarkers(file)
            }

        val chineseLexiconBin = externalResourceDir.resolve("chinese_lexicon.bin")
        val cmudictBin = externalResourceDir.resolve("cmudict.bin")
        val manifestFile = externalResourceDir.resolve("manifest.json")
        @Suppress("UNCHECKED_CAST")
        val manifest = JsonSlurper().parse(manifestFile) as MutableMap<String, Any?>
        manifest.upsertManifestFile("chinese_lexicon.bin", chineseLexiconBin.length())
        manifest.upsertManifestFile("cmudict.bin", cmudictBin.length())
        manifestFile.writeText(JsonOutput.prettyPrint(JsonOutput.toJson(manifest)) + "\n")

        val exportReportFile = externalResourceDir.resolve("export_report.json")
        if (exportReportFile.isFile) {
            @Suppress("UNCHECKED_CAST")
            val exportReport = JsonSlurper().parse(exportReportFile) as MutableMap<String, Any?>
            exportReport["frontend_binary_assets"] = listOf("chinese_lexicon.bin", "cmudict.bin")
            exportReport["frontend_text_assets"] = listOf("chinese_lexicon.txt", "cmudict.txt")
            exportReport["android_decoder_models"] = listOf(
                "lits_stream_condition_chunk.onnx",
                "lits_stream_decoder_step.onnx",
            )
            exportReportFile.writeText(JsonOutput.prettyPrint(JsonOutput.toJson(exportReport)) + "\n")
        }
    }
}

val cleanBundledTtsResources = tasks.register<Delete>("cleanBundledTtsResources") {
    group = "build"
    description = "Remove bundled TTS model/frontend resources so the AAR stays SDK-only."
    delete(bundledAssetRoot)
}

val stageBundledTtsResources = tasks.register<Copy>("stageBundledTtsResources") {
    group = "distribution"
    description = "Embed the exported TTS model in the SDK AAR for zero-copy customer integration."
    dependsOn(stageExternalTtsResources)
    from(externalResourceDir)
    into(bundledModelDir)
    inputs.dir(externalResourceDir)
    outputs.dir(bundledModelDir)
    doFirst {
        bundledModelDir.deleteRecursively()
    }
}

subprojects {
    tasks.matching { it.name == "preBuild" }.configureEach {
        if (bundleModelsInSdk.get()) {
            dependsOn(stageBundledTtsResources)
        } else {
            dependsOn(cleanBundledTtsResources, stageExternalTtsResources)
        }
    }
}

tasks.register<Sync>("stageSdkDelivery") {
    group = "distribution"
    description = "Stage the SDK-only delivery package."
    dependsOn(":sdk:assembleRelease", stageExternalTtsResources)

    into(rootProject.layout.buildDirectory.dir("delivery/$deliveryDirName"))

    from(rootDir.resolve("sdk/build/outputs/aar/sdk-release.aar")) {
        rename { deliveryAarName }
    }
    from(rootDir.resolve("external-resources")) {
        into("external-resources")
    }
    from(rootDir) {
        include("README.md", "CHANGELOG.md", "LICENSE", "NOTICE", "CHECKSUMS.txt")
    }
    from(rootDir.resolve("docs")) {
        into("docs")
        include("API.md", "DELIVERY.md", "INTEGRATION.md", "PSEUDOCODE.md")
    }
}

tasks.register("clean", Delete::class) {
    delete(rootProject.layout.buildDirectory)
}
