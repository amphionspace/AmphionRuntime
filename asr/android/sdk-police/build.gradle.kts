plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
}

val generatedLacAssets = layout.buildDirectory.dir("generated/sharedLacAssets")
val syncSharedLacModel by tasks.registering(Sync::class) {
    from("../../../shared/models/asr/police/lac/v1") {
        include("lac_encoder.onnx")
    }
    into(generatedLacAssets.map { it.dir("lac/v1") })
}

android {
    namespace = "com.amphion.police"
    compileSdk = 34

    defaultConfig {
        minSdk = 24
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        consumerProguardFiles("consumer-rules.pro")
        ndk {
            abiFilters += listOf("arm64-v8a")
        }
        externalNativeBuild {
            cmake {
                cppFlags += listOf("-std=c++17", "-fexceptions", "-frtti")
            }
        }
    }
    ndkVersion = "26.3.11579264"

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
        }
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
    }

    androidResources {
        noCompress += listOf("fst")
    }

    sourceSets.getByName("main").assets.srcDir(generatedLacAssets)

    testOptions {
        unitTests.isIncludeAndroidResources = true
        // 透传 realmic.* 系统属性给单测 JVM（真机对比工装用：realmic.dir / realmic.home）。
        unitTests.all { testTask ->
            val evalRoot = project.layout.projectDirectory.dir("src/test/resources/evaluation").asFile
            if (!evalRoot.resolve("plate_number").exists()) {
                testTask.exclude(
                    "**/*ReplayTest.class",
                    "**/*CompareTest.class",
                    "**/*GateTest.class",
                    "**/*ExportTest.class",
                    "**/*RealAsrTest.class",
                )
            }
            for (key in listOf("realmic.dir", "realmic.home", "redteam.corpus")) {
                val value = System.getProperty(key)
                if (value != null) testTask.systemProperty(key, value)
            }
        }
    }
}

tasks.matching {
    it.name.endsWith("Assets") || it.name.contains("lint", ignoreCase = true)
}.configureEach {
    dependsOn(syncSharedLacModel)
}

dependencies {
    implementation(project(":sdk"))
    implementation(libs.androidx.core.ktx)

    testImplementation(libs.junit)
    testImplementation(libs.mockito.kotlin)
}
