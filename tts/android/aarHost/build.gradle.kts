plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

val generatedAndroidTestAssets = layout.buildDirectory.dir("generated/androidTestAssets")
val stageAndroidTestAssets = tasks.register<Sync>("stageAndroidTestAssets") {
    from(rootProject.file("testdata/dingqiao_batch_cases")) {
        include(
            "android_v3_sdk_stability_100_cases_improved_v2.jsonl",
            "android_v3_sdk_stability_424_cases_improved_v3.jsonl",
            "android_v3_sdk_stability_1000_cases_improved.jsonl",
        )
    }
    into(generatedAndroidTestAssets)
}

android {
    namespace = "com.lits.tts.aarhost"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.lits.tts.aarhost"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "0.2.5.4-aar-host"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk {
            abiFilters += listOf("arm64-v8a")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    sourceSets["androidTest"].assets.srcDir(generatedAndroidTestAssets)
}

dependencies {
    implementation(files("../sdk/build/outputs/aar/sdk-release.aar"))
    androidTestImplementation(libs.junit)
    androidTestImplementation(libs.androidx.test.core)
    androidTestImplementation("androidx.test:runner:1.6.2")
}

tasks.named("preBuild") {
    dependsOn(":sdk:assembleRelease")
}

tasks.matching { it.name == "mergeDebugAndroidTestAssets" }.configureEach {
    dependsOn(stageAndroidTestAssets)
}
