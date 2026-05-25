plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

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
            // 与 SDK 一致；只打 arm64-v8a
            abiFilters += listOf("arm64-v8a")
        }
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

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    // 评估模块的 FileProvider authority 引用 BuildConfig.APPLICATION_ID 避免 flavor 失配
    buildFeatures {
        buildConfig = true
    }

    testOptions {
        unitTests {
            // 允许 android.* API（如 android.util.Log）在 JVM 单测中返回默认值
            // 而非抛 "Method X not mocked"。JSONObject 真实实现走 org.json 库依赖。
            isIncludeAndroidResources = false
            isReturnDefaultValues = true
        }
    }
}

dependencies {
    implementation(project(":sdk"))

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.activity)
    implementation(libs.androidx.constraintlayout)
    implementation(libs.androidx.recyclerview)
    implementation(libs.androidx.lifecycle.runtime)
    implementation(libs.androidx.lifecycle.common)
    implementation(libs.material)
    implementation(libs.okhttp)

    testImplementation(libs.junit)
    // 提供真实的 org.json.JSONObject 实现给 JVM 单测；运行时 Android 自带，不影响 apk
    testImplementation("org.json:json:20231013")
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
}
