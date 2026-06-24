plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
    alias(libs.plugins.kotlin.android) apply false
}

val sdkVersion = "0.1.0"
val deliveryDirName = "lits-tts-android-sdk-$sdkVersion"
val deliveryAarName = "lits-tts-sdk-$sdkVersion.aar"
val litsModelDir = rootDir.resolve("../../tools/trial-export/lits_delivery_16k_hifigan_streaming_proto/0.1.1")
val litsAssetDir = rootDir.resolve(
    "sdk/src/main/assets/lits-models/tts/lits_delivery_16k_hifigan_streaming_proto/0.1.1",
)

val packLitsTtsSdkAssets = tasks.register<Copy>("packLitsTtsSdkAssets") {
    group = "build"
    description = "Pack exported Lits_delivery 16k TTS assets into the Android SDK AAR."
    from(litsModelDir)
    into(litsAssetDir)
    doFirst {
        delete(rootDir.resolve("sdk/src/main/assets/lits-models/tts/lits_delivery_16k_hifigan"))
        delete(rootDir.resolve("sdk/src/main/assets/lits-models/tts/lits_delivery_16k_hifigan_streaming_proto"))
    }
    include(
        "manifest.json",
        "export_report.json",
        "smoke_tokens.json",
        "frontend_golden.json",
        "chinese_lexicon.txt",
        "chinese_lexicon.bin",
        "cmudict.txt",
        "cmudict.bin",
        "pinyin_2_bpmf.txt",
        "polychar.txt",
        "zh_en_symbols.json",
        "pinyin_to_tokens.json",
        "arpabet_to_tokens.json",
        "lits_hidden_encoder.onnx",
        "lits_stream_decoder_chunk.onnx",
        "hifigan_vocoder_int8.onnx",
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
