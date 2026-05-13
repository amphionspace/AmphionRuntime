import org.jetbrains.dokka.gradle.DokkaTask

plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.dokka)
    `maven-publish`
}

val sdkGroupId: String = providers.gradleProperty("AMPHION_RUNTIME_GROUP_ID").get()
val sdkArtifactId: String = providers.gradleProperty("AMPHION_RUNTIME_ARTIFACT_ID").get()
val sdkVersion: String = providers.gradleProperty("AMPHION_RUNTIME_VERSION").get()

android {
    namespace = "com.amphion.asr"
    compileSdk = 34

    defaultConfig {
        minSdk = 24
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        consumerProguardFiles("consumer-rules.pro")

        // 仅打包目标 ABI：默认 arm64-v8a；如需双 ABI，把 armeabi-v7a 取消注释
        ndk {
            abiFilters += listOf("arm64-v8a")
            // abiFilters += listOf("arm64-v8a", "armeabi-v7a")
        }

        // SDK 版本号通过 BuildConfig 暴露给 Kotlin 代码
        buildConfigField("String", "SDK_VERSION", "\"$sdkVersion\"")
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            consumerProguardFiles("consumer-rules.pro")
        }
        debug {
            // 不混淆
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
        // 我们的公开 API 使用 @JvmStatic / @JvmOverloads / @Throws 保证 Java 互操作性
        // 注意：不开 -Xexplicit-api=strict，因为 com.k2fsa.sherpa.onnx.* 是上游复制过来的，
        // 不带显式 public/internal 标注；我们自己 com.amphion.asr.* 的可见性靠 KDoc + 代码审查保证。
        freeCompilerArgs += listOf(
            "-Xjvm-default=all",
        )
    }

    // 把 native .so 打到 AAR 里：jniLibs 目录是 SDK 工程内的 sdk/src/main/jniLibs/<abi>/
    sourceSets["main"].jniLibs.srcDirs("src/main/jniLibs")

    publishing {
        singleVariant("release") {
            withSourcesJar()
        }
    }

    testOptions {
        unitTests.isIncludeAndroidResources = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)

    testImplementation(libs.junit)
    testImplementation(libs.mockito.kotlin)

    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
}

// -------- Dokka 配置：生成 HTML API 文档 --------
tasks.withType<DokkaTask>().configureEach {
    moduleName.set("AmphionRuntime")
    dokkaSourceSets.named("main") {
        // 只把公开 API 编进文档；internal 包不出现在外部文档里
        perPackageOption {
            matchingRegex.set(".*\\.internal($|\\..*)")
            suppress.set(true)
        }
        // sherpa-onnx 内部 Kotlin 类不在文档里
        perPackageOption {
            matchingRegex.set("com\\.k2fsa\\.sherpa\\.onnx($|\\..*)")
            suppress.set(true)
        }
        documentedVisibilities.set(setOf(org.jetbrains.dokka.DokkaConfiguration.Visibility.PUBLIC))
        skipEmptyPackages.set(true)
        jdkVersion.set(17)
        suppressInheritedMembers.set(true)
    }
}

// -------- maven-publish 配置：发布到本地 maven 仓库 --------
afterEvaluate {
    publishing {
        publications {
            create<MavenPublication>("release") {
                from(components["release"])
                groupId = sdkGroupId
                artifactId = sdkArtifactId
                version = sdkVersion

                pom {
                    name.set("$sdkGroupId:$sdkArtifactId")
                    description.set("AmphionRuntime based on sherpa-onnx (streaming Zipformer Transducer)")
                    licenses {
                        license {
                            name.set("Apache-2.0")
                            url.set("https://www.apache.org/licenses/LICENSE-2.0.txt")
                        }
                    }
                }
            }
        }

        repositories {
            maven {
                name = "localFileRepo"
                url = uri("${rootProject.layout.buildDirectory.get()}/maven-repo")
            }
        }
    }
}
