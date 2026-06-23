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
val sdkMajor: String = providers.gradleProperty("AMPHION_SDK_MAJOR").orElse("1").get()
val sdkReleaseDate: String = providers.gradleProperty("AMPHION_SDK_RELEASE_DATE").orElse("2026-06-23").get()

// 离线 license 公钥（base64 of X.509 SubjectPublicKeyInfo DER，单行）。
// 空 = 不武装 license（开发 / 内部构建）；正式交付构建必须注入真实公钥（见 gradle.properties）。
val licensePublicKeyB64: String =
    providers.gradleProperty("AMPHION_LICENSE_PUBLIC_KEY").orElse("").get()

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
        buildConfigField("int", "SDK_MAJOR", sdkMajor)
        buildConfigField("String", "SDK_RELEASE_DATE", "\"$sdkReleaseDate\"")
        // 离线 license 公钥（空字符串 = SDK 未武装 license，init 不做校验）
        buildConfigField("String", "LICENSE_PUBLIC_KEY_B64", "\"$licensePublicKeyB64\"")
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        release {
            // 开启 R8：让 internal 的 license 验签逻辑在交付 AAR 中被混淆，抬高逆向门槛。
            // 公开 API 由 proguard-rules.pro（include consumer-rules.pro）整体保留。
            // 注意：改这里后必须用 :samples:public-demo:assembleRelease + 真机跑一遍回归（见 docs/DELIVERY.md）。
            isMinifyEnabled = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
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

    // 模型文件 (onnx / fst) 不要被 aapt2 zip-deflate；
    // 原因：onnx int8 + sherpa fst 都已经是高熵二进制，再 deflate 通常 -1% ~ +5%；
    //       但运行期 AssetManager 解压会把整文件读进堆，给 ZH-EN 这种 ~120MB 的模型直接 OOM。
    //       禁用压缩后 first-run 的拷贝走 mmap streaming，常驻内存只有 IO 缓冲。
    androidResources {
        noCompress += listOf("onnx", "fst")
    }

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
