#!/usr/bin/env bash
# 鼎桥 Demo 参考工程源码交付（仅 sample-dingqiao-demo，脱敏，不含 SDK 源码/私钥/license）。
#
# 用法（AmphionRuntime 仓库根目录）:
#   bash tools/android/pack_dingqiao_demo_source_delivery.sh [SDK版本号]
#
# 产物: ../delivery/amphion-dingqiao-demo-src-v<版本>/
#       ../delivery/amphion-dingqiao-demo-src-v<版本>-<date>.zip
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=dingqiao_build_provenance.sh
source "$SCRIPT_DIR/dingqiao_build_provenance.sh"

REPO_ROOT="$(dingqiao_repo_root_from_script)"
DQ_ROOT="$(cd "$REPO_ROOT/.." && pwd)"
AR_ROOT="$(dingqiao_ar_root_from_repo "$REPO_ROOT")"
BUILD_DATE="$(date +%Y%m%d)"
DEMO_SRC="$AR_ROOT/sample-dingqiao-demo"

VERSION="$(dingqiao_read_sdk_version "$AR_ROOT")"
if [[ -n "${1:-}" ]]; then
  VERSION="$1"
fi

PKG_NAME="amphion-dingqiao-demo-src-v${VERSION}"
OUT_ROOT="$DQ_ROOT/delivery/$PKG_NAME"
ZIP_PATH="$DQ_ROOT/delivery/${PKG_NAME}-${BUILD_DATE}.zip"

echo "[1/4] stage demo source tree ..."
rm -rf "$OUT_ROOT"
mkdir -p "$OUT_ROOT"/{libs,gradle/wrapper,sample-dingqiao-demo}

# Gradle wrapper + version catalog（可独立编译的最小工程）
cp "$AR_ROOT/gradlew" "$AR_ROOT/gradlew.bat" "$OUT_ROOT/"
cp "$AR_ROOT/gradle/wrapper/"* "$OUT_ROOT/gradle/wrapper/"
cp "$AR_ROOT/gradle/libs.versions.toml" "$OUT_ROOT/gradle/"

# Demo 模块源码（排除 license、构建产物、macOS 垃圾文件）
rsync -a \
  --exclude 'build/' \
  --exclude '.gradle/' \
  --exclude 'src/main/assets/amphion-license.lic' \
  --exclude '.DS_Store' \
  --exclude '._*' \
  "$DEMO_SRC/" "$OUT_ROOT/sample-dingqiao-demo/"

mkdir -p "$OUT_ROOT/sample-dingqiao-demo/src/main/assets"

cat > "$OUT_ROOT/settings.gradle.kts" <<'EOF'
pluginManagement {
    repositories {
        maven { url = uri("https://maven.aliyun.com/repository/google") }
        maven { url = uri("https://maven.aliyun.com/repository/central") }
        maven { url = uri("https://maven.aliyun.com/repository/gradle-plugin") }
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        maven { url = uri("https://maven.aliyun.com/repository/google") }
        maven { url = uri("https://maven.aliyun.com/repository/central") }
        google()
        mavenCentral()
    }
}

rootProject.name = "dingqiao-demo-reference"
include(":sample-dingqiao-demo")
EOF

cat > "$OUT_ROOT/build.gradle.kts" <<'EOF'
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
}

tasks.register("clean", Delete::class) {
    delete(rootProject.layout.buildDirectory)
}
EOF

cat > "$OUT_ROOT/gradle.properties" <<EOF
org.gradle.jvmargs=-Xmx4g -Dfile.encoding=UTF-8
android.useAndroidX=true
kotlin.code.style=official
android.nonTransitiveRClass=true
dingqiaoSdkAar=libs/dingqiao-asr-v${VERSION}.aar
EOF

cat > "$OUT_ROOT/sample-dingqiao-demo/build.gradle.kts" <<'EOF'
import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

val localProps = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

val sdkAar = providers.gradleProperty("dingqiaoSdkAar").get()

android {
    namespace = "com.amphion.dingqiao.demo"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.amphion.dingqiao.demo"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk { abiFilters += listOf("arm64-v8a") }
    }

    signingConfigs {
        create("release") {
            val storePath = localProps.getProperty("dingqiaoReleaseStoreFile")
            if (!storePath.isNullOrBlank()) {
                storeFile = rootProject.file(storePath)
                storePassword = localProps.getProperty("dingqiaoReleaseStorePassword")
                keyAlias = localProps.getProperty("dingqiaoReleaseKeyAlias")
                keyPassword = localProps.getProperty("dingqiaoReleaseKeyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            val storePath = localProps.getProperty("dingqiaoReleaseStoreFile")
            if (!storePath.isNullOrBlank()) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
        debug { isMinifyEnabled = false }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation(files(rootProject.file(sdkAar)))
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.activity)
    implementation(libs.androidx.constraintlayout)
    implementation(libs.androidx.recyclerview)
    implementation(libs.material)
    testImplementation(libs.junit)
}
EOF

cat > "$OUT_ROOT/sample-dingqiao-demo/proguard-rules.pro" <<'EOF'
# Demo Release 开启 R8；SDK 消费规则由 fat AAR 内 proguard.txt 自动合并。
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile
EOF

cat > "$OUT_ROOT/sample-dingqiao-demo/README.md" <<EOF
# 鼎桥语音识别 Demo（参考工程）

本模块为交付 Demo APK 的参考源码，通过 \`libs/dingqiao-asr-v${VERSION}.aar\` 调用 \`SpeechRecognizeSdk\`。

构建说明见工程根目录 README.txt。
EOF

cat > "$OUT_ROOT/local.properties.example" <<'EOF'
# 复制为 local.properties 并填写本机 Android SDK 路径（Android Studio 通常会自动生成）
sdk.dir=/path/to/Android/sdk

# 可选：打 Release APK 时填写签名（Debug 联调可跳过）
# dingqiaoReleaseStoreFile=keystore/your-release.jks
# dingqiaoReleaseStorePassword=
# dingqiaoReleaseKeyAlias=
# dingqiaoReleaseKeyPassword=
EOF

cat > "$OUT_ROOT/libs/README.txt" <<EOF
请将 SDK 交付包 aar/ 目录下的 dingqiao-asr-v${VERSION}.aar 复制到本目录。

本 Demo 工程不包含 SDK 源码，仅依赖该 AAR 编译。
EOF

cat > "$OUT_ROOT/README.txt" <<EOF
鼎桥警务语音识别 SDK — Demo 参考工程源码 v${VERSION}
====================================================

本包仅含 sample-dingqiao-demo 参考工程，用于对照我方交付 Demo APK 的集成方式。
不含 SDK 核心源码、警务规则资产、打包脚本、私钥或授权文件。

保密：仅供贵司 com.tdtech.tiassistant 项目内部集成参考，请勿对外传播或二次分发。

目录
----
  sample-dingqiao-demo/     Demo App 源码（与交付包 demo/*.apk 对应）
  libs/                    放置 dingqiao-asr-v${VERSION}.aar（从 SDK 交付 zip 复制）
  gradle/ gradlew          独立 Gradle 工程，JDK 17

准备
----
  1. 将 SDK 交付包中 aar/dingqiao-asr-v${VERSION}.aar 复制到 libs/
  2. 复制 local.properties.example → local.properties，填写 sdk.dir
  3. 运行 Demo 需在 sample-dingqiao-demo/src/main/assets/ 放入我方签发的
     amphion-license.lic（Demo 包名专用，单独索取；本源码包故意不含该文件）
  4. 声纹：将 models/eres2net.onnx 推到设备工作目录（见 DingqiaoApp）

编译
----
  ./gradlew :sample-dingqiao-demo:assembleDebug
  ./gradlew :sample-dingqiao-demo:assembleRelease   # 需配置签名，见 local.properties

产物
----
  sample-dingqiao-demo/build/outputs/apk/

与正式 App 的区别
-----------------
  本 Demo 包名 com.amphion.dingqiao.demo，仅供参考 API 调用顺序（init / 640B 分帧 /
  识别 / 声纹）。贵司正式集成请使用 com.tdtech.tiassistant 及贵司签发的授权文件。

版本
----
  对齐 SDK 交付包 v${VERSION}；打包日期 ${BUILD_DATE}
EOF

echo "[2/4] sanity check ..."
[[ -f "$OUT_ROOT/sample-dingqiao-demo/src/main/java/com/amphion/dingqiao/demo/MainActivity.kt" ]]
[[ ! -f "$OUT_ROOT/sample-dingqiao-demo/src/main/assets/amphion-license.lic" ]]
grep -rq ":sdk-dingqiao\|:sdk-police" "$OUT_ROOT" && {
  echo "[ERROR] internal module reference leaked in demo-src package" >&2
  exit 1
}

echo "[3/4] zip ..."
rm -f "$ZIP_PATH"
dingqiao_zip_delivery "$OUT_ROOT" "$ZIP_PATH"

echo "[4/4] done"
echo "[OK] tree: $OUT_ROOT"
echo "[OK] zip:  $ZIP_PATH"
du -sh "$OUT_ROOT" "$ZIP_PATH"
