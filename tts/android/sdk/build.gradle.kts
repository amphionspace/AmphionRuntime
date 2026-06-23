plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
}

// 离线 license 公钥（X.509 SubjectPublicKeyInfo DER 的 base64，单行）。
// 与 ASR 共用 AMPHION_LICENSE_PUBLIC_KEY。空 = SDK 不武装 license（开发 / 内部构建不校验）。
val amphionLicensePublicKey: String =
    (project.findProperty("AMPHION_LICENSE_PUBLIC_KEY") as String?)?.trim().orEmpty()
val sdkMajor: String = providers.gradleProperty("AMPHION_SDK_MAJOR").orElse("1").get()
val sdkReleaseDate: String = providers.gradleProperty("AMPHION_SDK_RELEASE_DATE").orElse("2026-06-23").get()

android {
    namespace = "com.lits.tts.sdk"
    compileSdk = 34

    defaultConfig {
        minSdk = 24
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        consumerProguardFiles("consumer-rules.pro")
        buildConfigField("int", "SDK_MAJOR", sdkMajor)
        buildConfigField("String", "SDK_RELEASE_DATE", "\"$sdkReleaseDate\"")
        buildConfigField("String", "LICENSE_PUBLIC_KEY_B64", "\"$amphionLicensePublicKey\"")
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        release {
            // 开启 R8：混淆 com.lits.tts.sdk.internal.*（含离线 license 验签逻辑），抬高逆向 / 打补丁门槛。
            // 公开 API 由 consumer-rules.pro 保留；proguard-rules.pro 复用同一份规则做开发态自验。
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
        freeCompilerArgs += listOf("-Xjvm-default=all")
    }

    testOptions {
        unitTests.isIncludeAndroidResources = true
    }

    androidResources {
        noCompress += listOf("onnx")
        // 仅打包 TTS 的 lits-models;排除工作区里残留的非 TTS assets(如 ASR 的 amphion-models)
        ignoreAssetsPatterns += "amphion-models"
    }

    packaging {
        // 纯 TTS 运行时不需要 sherpa-onnx(ASR)的 JNI 库,排除其残留以免打入 AAR
        jniLibs {
            excludes += "**/libsherpa-onnx-jni.so"
        }
    }

    sourceSets["main"].jniLibs.srcDirs("src/main/jniLibs")
}

dependencies {
    implementation(files("libs/onnxruntime-android-1.24.3-classes.jar"))

    testImplementation(libs.junit)
    testImplementation("org.json:json:20240303")
}
