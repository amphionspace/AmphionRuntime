plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
    alias(libs.plugins.kotlin.android) apply false
}

val litsModelDir = providers.gradleProperty("LITS_TTS_MODEL_DIR")
    .orElse(providers.environmentVariable("LITS_TTS_MODEL_DIR"))
    .map { file(it) }
    .getOrElse(rootDir.resolve("../../tts/tools/trial-export/lits_delivery_16k_hifigan/1.0.0"))
val litsAssetDir = rootDir.resolve(
    "sdk/src/main/assets/lits-models/tts/lits_delivery_16k_hifigan/1.0.0",
)

val packLitsTtsSdkAssets = tasks.register<Copy>("packLitsTtsSdkAssets") {
    group = "build"
    description = "Pack exported Lits_delivery 16k TTS assets into the Android SDK AAR."
    from(litsModelDir)
    into(litsAssetDir)
    include(
        "manifest.json",
        "export_report.json",
        "smoke_tokens.json",
        "frontend_golden.json",
        "chinese_lexicon.txt",
        "cmudict.txt",
        "pinyin_2_bpmf.txt",
        "polychar.txt",
        "zh_en_symbols.json",
        "pinyin_to_tokens.json",
        "arpabet_to_tokens.json",
        "lits_acoustic.onnx",
        "hifigan_vocoder.onnx",
    )
    inputs.dir(litsModelDir)
    outputs.dir(litsAssetDir)
}

subprojects {
    tasks.matching { it.name == "preBuild" }.configureEach {
        dependsOn(packLitsTtsSdkAssets)
    }
}

tasks.register("clean", Delete::class) {
    delete(rootProject.layout.buildDirectory)
}
