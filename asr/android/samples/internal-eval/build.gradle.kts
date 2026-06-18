plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    // namespace 故意与 :samples:public-demo 共用 com.amphion.asr.sample：
    // - internal-eval 的 Kotlin 文件继续用 com.amphion.asr.sample.eval.* 子 package（与 HEAD 一致）
    // - R / BuildConfig 由 namespace 决定，落在 com.amphion.asr.sample.R / .BuildConfig
    // - 两个模块互不依赖、不会同时打进同一个 APK，namespace 相同对运行期没有影响，
    //   反而让评测代码（其 import com.amphion.asr.sample.R）零修改
    namespace = "com.amphion.asr.sample"
    compileSdk = 34

    defaultConfig {
        // applicationId 必须与 :samples:public-demo 区分，否则两版 APK 不能同设备共存
        applicationId = "com.amphion.asr.sample.eval"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "0.2.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        ndk {
            abiFilters += listOf("arm64-v8a")
        }
    }

    buildTypes {
        release {
            // 对内评测包不对外发布，体积压缩动机弱；release 不开 minify，避免误删评测专用反射调用
            isMinifyEnabled = false
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

    // FileProvider authority 引用 BuildConfig.APPLICATION_ID，需要打开 buildConfig 生成
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
