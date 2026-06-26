plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
    alias(libs.plugins.kotlin.android) apply false
}

val sdkVersion = "0.2.5.2"
val modelId = "transsion_lits_en_zh_vocos24k_streaming_proto_external_loop"
val modelVersion = "0.1.0"
val deliveryDirName = "lits-transsion-tts-android-sdk-vocos24k-$sdkVersion"
val deliveryAarName = "lits-transsion-tts-sdk-vocos24k-$sdkVersion.aar"
val litsModelDir = rootDir.resolve("../../tools/trial-export/$modelId/$modelVersion")
val transsionLitsRoot = rootDir.resolve("../../../transsion_lits")
val transsionTnRoot = transsionLitsRoot.resolve("Transsion_Multilingual_Text_Normalization_for_TTS")
val transsionTnAndroidBinDir = transsionLitsRoot.resolve("e2e_infer/bin-android-arm64")
val litsAssetDir = rootDir.resolve(
    "sdk/src/main/assets/lits-models/tts/$modelId/$modelVersion",
)

val syncTranssionTnBinaries = tasks.register<Sync>("syncTranssionTnBinaries") {
    group = "build"
    description = "Sync Android TN binaries built from transsion_lits into the TTS model assets."
    from(transsionTnAndroidBinDir) {
        include("zh_tts", "en_tts")
    }
    into(litsModelDir.resolve("tn-bin/arm64-v8a"))
    inputs.dir(transsionTnAndroidBinDir)
    outputs.dir(litsModelDir.resolve("tn-bin/arm64-v8a"))
    doFirst {
        if (!transsionTnAndroidBinDir.isDirectory) {
            throw GradleException(
                "Missing Transsion TN Android binaries: $transsionTnAndroidBinDir. " +
                    "Build them from transsion_lits before assembling the SDK.",
            )
        }
    }
}

val syncTranssionTnRules = tasks.register<Copy>("syncTranssionTnRules") {
    group = "build"
    description = "Sync Transsion TN rules from transsion_lits into the TTS model assets."
    from(transsionTnRoot.resolve("rules")) {
        include("zh.json", "en.json", "zh_pinyin.json")
        into("rules")
    }
    from(transsionTnRoot.resolve("rules_v2")) {
        include("zh.full.json", "en.full.json")
        into("rules_v2")
    }
    into(litsModelDir)
    inputs.dir(transsionTnRoot.resolve("rules"))
    inputs.dir(transsionTnRoot.resolve("rules_v2"))
    outputs.files(
        litsModelDir.resolve("rules/zh.json"),
        litsModelDir.resolve("rules/en.json"),
        litsModelDir.resolve("rules/zh_pinyin.json"),
        litsModelDir.resolve("rules_v2/zh.full.json"),
        litsModelDir.resolve("rules_v2/en.full.json"),
    )
}

val syncTranssionTnAssets = tasks.register("syncTranssionTnAssets") {
    group = "build"
    description = "Sync Android TN binaries and rules built from transsion_lits into the TTS model assets."
    dependsOn(syncTranssionTnBinaries, syncTranssionTnRules)
}

val packLitsTtsSdkAssets = tasks.register<Copy>("packLitsTtsSdkAssets") {
    group = "build"
    description = "Pack exported Transsion LITS TTS assets into the Android SDK AAR."
    dependsOn(syncTranssionTnAssets)
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
