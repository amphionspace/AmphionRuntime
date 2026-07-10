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

// Release 护栏：公钥为空会让 SDK 退化为「不校验 license」。禁止其进入 release 产物，
// 避免正式交付构建因公钥漏注入而静默关闭验签。
gradle.taskGraph.whenReady {
    val buildingRelease = allTasks.any {
        (it.name.startsWith("assemble") || it.name.startsWith("bundle")) && it.name.contains("Release")
    }
    if (buildingRelease && amphionLicensePublicKey.isBlank()) {
        throw GradleException(
            "AMPHION_LICENSE_PUBLIC_KEY 为空：release 构建将关闭 license 验签（SDK 未武装）。" +
                "打包前请在 gradle.properties 注入正式公钥。",
        )
    }
}

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

    androidTestImplementation(libs.junit)
    androidTestImplementation(libs.androidx.test.core)
    androidTestImplementation("androidx.test:runner:1.6.2")
}
