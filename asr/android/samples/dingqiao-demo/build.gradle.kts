import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

val localProps = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

// -PdingqiaoUseFatAar=true 时用方案 A fat AAR 构建 Demo（与 dingqiao-asr-*.aar 对齐）
val useFatAar = providers.gradleProperty("dingqiaoUseFatAar").orElse("false").get() == "true"
val fatAarPath = providers.gradleProperty("dingqiaoFatAarPath").orElse(
    "${rootProject.projectDir}/build/dingqiao-delivery/dingqiao-asr-v0.1.0.aar",
).get()
val evalAudioDir = providers.gradleProperty("dingqiaoEvalAudioDir").orNull
val demoAssetDir = providers.gradleProperty("dingqiaoDemoAssetDir").orNull

android {
    namespace = "com.amphion.dingqiao.demo"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.amphion.dingqiao.demo"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        ndk {
            abiFilters += listOf("arm64-v8a")
        }
    }

    signingConfigs {
        create("release") {
            val storePath = localProps.getProperty("dingqiaoReleaseStoreFile")
            if (!storePath.isNullOrBlank()) {
                storeFile = rootProject.file(storePath)
                storePassword = localProps.getProperty("dingqiaoReleaseStorePassword")
                keyAlias = localProps.getProperty("dingqiaoReleaseKeyAlias")
                keyPassword = localProps.getProperty("dingqiaoReleaseKeyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            val storePath = localProps.getProperty("dingqiaoReleaseStoreFile")
            if (!storePath.isNullOrBlank()) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
        debug {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    sourceSets {
        getByName("androidTest").assets.srcDir(
            rootProject.file("../test-fixtures/voiceprint-fallback"),
        )
        demoAssetDir
            ?.takeIf { it.isNotBlank() }
            ?.let { getByName("main").assets.srcDir(it) }
        evalAudioDir
            ?.takeIf { it.isNotBlank() }
            ?.let { getByName("androidTest").assets.srcDir(it) }
    }
}

dependencies {
    if (useFatAar) {
        implementation(files(fatAarPath))
    } else {
        implementation(project(":sdk-dingqiao"))
    }

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.activity)
    implementation(libs.androidx.constraintlayout)
    implementation(libs.androidx.recyclerview)
    implementation(libs.material)

    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.test.runner)
    androidTestImplementation(project(":sdk-police"))
}
