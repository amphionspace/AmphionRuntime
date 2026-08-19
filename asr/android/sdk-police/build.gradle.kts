plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
}

val runReplayTests = providers.gradleProperty("policeRunReplayTests")
    .orElse("false")
    .map(String::toBoolean)

val defaultHotwordProfile = providers.gradleProperty("policeDefaultHotwordProfile")
    .orElse("full")
    .get()
check(defaultHotwordProfile in setOf("full", "prune_ui28")) {
    "policeDefaultHotwordProfile must be full or prune_ui28, got $defaultHotwordProfile"
}

android {
    namespace = "com.amphion.police"
    compileSdk = 34

    defaultConfig {
        minSdk = 24
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        consumerProguardFiles("consumer-rules.pro")
        buildConfigField(
            "String",
            "DEFAULT_HOTWORD_PROFILE",
            "\"$defaultHotwordProfile\"",
        )
    }

    buildFeatures {
        buildConfig = true
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

    testOptions {
        unitTests.isIncludeAndroidResources = true
        // 透传 realmic.* 系统属性给单测 JVM（真机对比工装用：realmic.dir / realmic.home）。
        unitTests.all { testTask ->
            val evalRoot = project.layout.projectDirectory.dir("src/test/resources/evaluation").asFile
            if (!runReplayTests.get() && !evalRoot.resolve("plate_number").exists()) {
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

dependencies {
    implementation(project(":sdk"))
    implementation(libs.androidx.core.ktx)

    testImplementation(libs.junit)
    testImplementation(libs.mockito.kotlin)
}
