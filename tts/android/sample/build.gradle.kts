plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.lits.tts.sample"
    compileSdk = 34
    buildFeatures { buildConfig = true }

    defaultConfig {
        applicationId = providers.gradleProperty("LITS_TTS_SAMPLE_APPLICATION_ID")
            .orElse("com.tdtech.tiassistant").get()
        manifestPlaceholders["ttsAppLabel"] = providers.gradleProperty("LITS_TTS_SAMPLE_LABEL")
            .orElse("@string/app_name").get()
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "3.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
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
    implementation(project(":sdk"))
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
}
