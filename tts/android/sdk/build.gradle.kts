plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
}

// 离线 license 公钥（X.509 SubjectPublicKeyInfo DER 的 base64，单行）。来自 gradle.properties /
// -P 参数；空 = SDK 不武装 license（开发 / 内部构建，init/createEngine 不做校验）。
val amphionLicensePublicKey: String =
    (project.findProperty("AMPHION_LICENSE_PUBLIC_KEY") as String?)?.trim().orEmpty()
val sdkMajor: String = providers.gradleProperty("AMPHION_SDK_MAJOR").orElse("1").get()
val sdkReleaseDate: String = providers.gradleProperty("AMPHION_SDK_RELEASE_DATE").orElse("2026-06-23").get()

android {
    namespace = "com.lits.tts.sdk"
    compileSdk = 34
    ndkVersion = "27.2.12479018"

    defaultConfig {
        minSdk = 24
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        consumerProguardFiles("consumer-rules.pro")
        buildConfigField("int", "SDK_MAJOR", sdkMajor)
        buildConfigField("String", "SDK_RELEASE_DATE", "\"$sdkReleaseDate\"")
        buildConfigField("String", "LICENSE_PUBLIC_KEY_B64", "\"$amphionLicensePublicKey\"")
        ndk {
            abiFilters += listOf("arm64-v8a")
        }
        externalNativeBuild {
            ndkBuild {
                arguments += listOf("APP_STL=c++_static")
            }
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
        freeCompilerArgs += listOf("-Xjvm-default=all")
    }

    testOptions {
        unitTests.isIncludeAndroidResources = true
    }

    androidResources {
        noCompress += listOf("onnx")
    }

    externalNativeBuild {
        ndkBuild {
            path = file("src/main/jni/Android.mk")
        }
    }

    sourceSets["main"].jniLibs.srcDirs("src/main/jniLibs")
}

dependencies {
    implementation(files("libs/onnxruntime-android-1.24.3-classes.jar"))

    testImplementation(libs.junit)
    testImplementation("org.json:json:20240303")
}
