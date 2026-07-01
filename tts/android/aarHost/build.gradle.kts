plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
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
}

dependencies {
    implementation(files("../sdk/build/outputs/aar/sdk-debug.aar"))
    androidTestImplementation(libs.junit)
    androidTestImplementation(libs.androidx.test.core)
    androidTestImplementation("androidx.test:runner:1.6.2")
}
