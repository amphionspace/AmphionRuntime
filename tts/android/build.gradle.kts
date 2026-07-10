plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
    alias(libs.plugins.kotlin.android) apply false
}

val sdkVersion = "3.0"
val modelId = "transsion_lits_en_zh_vocos24k_streaming_proto_external_loop"
val modelVersion = "0.1.0"
val deliveryDirName = "lits-transsion-tts-android-sdk-vocos24k-$sdkVersion"
val deliveryAarName = "lits-transsion-tts-sdk-vocos24k-$sdkVersion.aar"
val litsModelDir = rootDir.resolve("../../tools/trial-export/$modelId/$modelVersion")
val litsAssetDir = rootDir.resolve(
    "sdk/src/main/assets/lits-models/tts/$modelId/$modelVersion",
)

val validateLitsTtsModelPackage = tasks.register("validateLitsTtsModelPackage") {
    group = "build"
    description = "Validate the exported LITS TTS model package before packing SDK assets."
    inputs.dir(litsModelDir)
    doLast {
        val requiredFiles = listOf(
            "manifest.json",
            "frontend_rules.json",
            "rules/zh.json",
            "rules/en.json",
            "rules/zh_pinyin.json",
            "rules_v2/zh.full.json",
            "rules_v2/en.full.json",
            "tn-bin/arm64-v8a/zh_tts",
            "tn-bin/arm64-v8a/en_tts",
            "lits_hidden_encoder.onnx",
            "lits_stream_condition_chunk.onnx",
            "lits_stream_condition_final.onnx",
            "lits_stream_decoder_step.onnx",
            "vocos_vocoder.onnx",
        )
        requiredFiles.forEach { relativePath ->
            val file = litsModelDir.resolve(relativePath)
            if (!file.isFile) {
                throw GradleException(
                    "Missing LITS TTS model package file: $file. " +
                        "Unpack the v3.0 model/frontend package into $litsModelDir before building.",
                )
            }
            if (file.length() == 0L) {
                throw GradleException("Empty LITS TTS model package file: $file")
            }
        }
    }
}

tasks.register("syncTranssionTnAssets") {
    group = "build"
    description = "Compatibility alias; validates TN assets already bundled in the model package."
    dependsOn(validateLitsTtsModelPackage)
}

tasks.register("syncTranssionTnBinaries") {
    group = "build"
    description = "Compatibility alias; validates Android TN binaries already bundled in the model package."
    dependsOn(validateLitsTtsModelPackage)
}

tasks.register("syncTranssionTnRules") {
    group = "build"
    description = "Compatibility alias; validates TN rules already bundled in the model package."
    dependsOn(validateLitsTtsModelPackage)
}

val packLitsTtsSdkAssets = tasks.register<Copy>("packLitsTtsSdkAssets") {
    group = "build"
    description = "Pack exported Transsion LITS TTS assets into the Android SDK AAR."
    dependsOn(validateLitsTtsModelPackage)
    from(litsModelDir)
    into(litsAssetDir)
    doFirst {
        delete(rootDir.resolve("sdk/src/main/assets/lits-models/tts"))
    }
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
        "tn-bin/arm64-v8a/**",
        "rules/zh.json",
        "rules/en.json",
        "rules/zh_pinyin.json",
        "rules_v2/zh.full.json",
        "rules_v2/en.full.json",
        "lits_hidden_encoder.onnx",
        "external_loop_export_report.json",
        "lits_stream_condition_chunk.onnx",
        "lits_stream_condition_final.onnx",
        "lits_stream_decoder_step.onnx",
        "vocos_vocoder.onnx",
    )
    inputs.dir(litsModelDir)
    outputs.dir(litsAssetDir)
}

subprojects {
    tasks.matching { it.name == "preBuild" }.configureEach {
        dependsOn(packLitsTtsSdkAssets)
    }
}

tasks.register<Sync>("stageSdkDelivery") {
    group = "distribution"
    description = "Stage the SDK-only delivery package."
    dependsOn(":sdk:assembleRelease")

    into(rootProject.layout.buildDirectory.dir("delivery/$deliveryDirName"))

    from(rootDir.resolve("sdk/build/outputs/aar/sdk-release.aar")) {
        rename { deliveryAarName }
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
