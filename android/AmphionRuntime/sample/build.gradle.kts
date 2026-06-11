import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

// 云端 ASR 的 API Key 从 local.properties 的 cloudAsrApiKey 读取（该文件已被 gitignore，
// 不会进入仓库），再经 BuildConfig 注入。缺省为空串：此时云端开关会因鉴权失败给出可读错误，
// 端侧 SDK 不受影响。正式产品应由服务端签发短期凭证，而非随 APK 分发长期 key。
val cloudAsrApiKey: String = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}.getProperty("cloudAsrApiKey", "")

android {
    namespace = "com.amphion.asr.sample"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.amphion.asr.sample"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        ndk {
            abiFilters += listOf("arm64-v8a")
        }

        buildConfigField("String", "CLOUD_ASR_API_KEY", "\"$cloudAsrApiKey\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
        debug {
            isMinifyEnabled = false
        }
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    testOptions {
        unitTests {
            isIncludeAndroidResources = false
            isReturnDefaultValues = true
        }
    }
}

dependencies {
    implementation(project(":sdk"))
    implementation(project(":sdk-police"))

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.activity)
    implementation(libs.androidx.constraintlayout)
    implementation(libs.androidx.recyclerview)
    implementation(libs.material)

    // 云端 ASR：WebSocket 流式（/clean-stream）。okhttp 自带 WebSocket + okio，无需额外库。
    implementation(libs.okhttp)

    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
}
