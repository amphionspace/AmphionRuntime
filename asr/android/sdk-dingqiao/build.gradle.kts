plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.amphion.dingqiao"
    compileSdk = 34

    defaultConfig {
        minSdk = 24
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        consumerProguardFiles("consumer-rules.pro")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
        // 新接口方法必须是真正的 JVM default method，旧版只实现 onResult 的客户类
        // 才能在新版 SDK 调用 onSuccess 时安全继承默认桥接，避免 AbstractMethodError。
        // compatibility 同时保留旧 Kotlin 调用方引用的 *$DefaultImpls 类。
        freeCompilerArgs += listOf("-Xjvm-default=all-compatibility")
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }

    androidResources {
        noCompress += listOf("onnx")
    }
}

dependencies {
    implementation(project(":sdk"))
    implementation(project(":sdk-police"))
    implementation(libs.androidx.core.ktx)

    testImplementation(libs.junit)
    testImplementation(libs.mockito.kotlin)
}
