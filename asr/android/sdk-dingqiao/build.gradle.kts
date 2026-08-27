plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
}

val generatedDingqiaoModelAssets = layout.buildDirectory.dir("generated/sharedDingqiaoModelAssets")
val syncSharedDingqiaoModels by tasks.registering(Sync::class) {
    from("../../../shared/models/asr/dingqiao") {
        include(
            "eres2net.onnx",
            "pyannote-segmentation-3.0.onnx",
            "pyannote-segmentation-3.0.LICENSE",
        )
    }
    into(generatedDingqiaoModelAssets.map { it.dir("amphion-dingqiao") })
}

android {
    namespace = "com.amphion.dingqiao"
    compileSdk = 34
    ndkVersion = "26.3.11579264"

    defaultConfig {
        minSdk = 24
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        consumerProguardFiles("consumer-rules.pro")
        buildConfigField("boolean", "DIAGNOSTICS_ENABLED", "false")
        ndk {
            abiFilters += listOf("arm64-v8a")
        }
        externalNativeBuild {
            cmake {
                cppFlags += listOf("-std=c++17", "-fexceptions", "-frtti")
            }
        }
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
        create("diagnostics") {
            initWith(getByName("debug"))
            matchingFallbacks += listOf("debug")
            buildConfigField("boolean", "DIAGNOSTICS_ENABLED", "true")
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

    sourceSets.getByName("main").assets.srcDir(generatedDingqiaoModelAssets)

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
        }
    }
}

tasks.matching { it.name.endsWith("Assets") }.configureEach {
    dependsOn(syncSharedDingqiaoModels)
}

dependencies {
    implementation(project(":sdk"))
    implementation(project(":sdk-police"))
    implementation(libs.androidx.core.ktx)

    testImplementation(libs.junit)
    testImplementation(libs.mockito.kotlin)
}
