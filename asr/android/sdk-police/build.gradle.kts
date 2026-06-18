plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.amphion.police"
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
    }

    androidResources {
        noCompress += listOf("fst")
    }

    testOptions {
        unitTests.isIncludeAndroidResources = true
        // 透传 realmic.* 系统属性给单测 JVM（真机对比工装用：realmic.dir / realmic.home）。
        unitTests.all { testTask ->
            for (key in listOf("realmic.dir", "realmic.home")) {
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
