plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.lits.tts.sample"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.lits.tts.sample"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    androidResources {
        noCompress += listOf("onnx")
    }
}

dependencies {
    implementation(project(":sdk"))
    implementation(libs.androidx.appcompat)
}
