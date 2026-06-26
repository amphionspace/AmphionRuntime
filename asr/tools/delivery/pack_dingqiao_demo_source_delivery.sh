#!/usr/bin/env bash
# 鼎桥 Demo 参考工程源码交付（方案：纯 demo 模块 + fat AAR + 客户文档，脱敏）。
#
# 用法（AmphionRuntime 仓库根目录）:
#   bash asr/tools/delivery/pack_dingqiao_demo_source_delivery.sh [SDK版本号]
#
# 环境变量（可选，供 pack_dingqiao_customer_delivery.sh 嵌入调用）:
#   DINGQIAO_FAT_AAR           已构建的 fat AAR 路径（跳过 AAR 编译）
#   DINGQIAO_DEMO_APK          已构建的 Demo APK 路径（跳过 Demo APK 编译）
#   DINGQIAO_DEMO_LICENSE      与 DINGQIAO_DEMO_APK 同批次签发的 license 路径
#   DINGQIAO_DEMO_SRC_OUT_ROOT 输出目录（默认 ../delivery/amphion-dingqiao-demo-src-v<版本>/）
#   DINGQIAO_DEMO_SRC_SKIP_ZIP=1  不生成 zip
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
CUSTOMER_DOCS="$AR_ROOT/docs/customer"
BUILD_DATE="$(date +%Y%m%d)"
DEMO_SRC="$AR_ROOT/samples/dingqiao-demo"

VERSION="$(dingqiao_resolve_delivery_version "$AR_ROOT" "${1:-}")"
AAR_NAME="dingqiao-asr-v${VERSION}.aar"
FAT_AAR="${DINGQIAO_FAT_AAR:-$AR_ROOT/build/dingqiao-delivery/$AAR_NAME}"

PKG_NAME="amphion-dingqiao-demo-src-v${VERSION}"
OUT_ROOT="${DINGQIAO_DEMO_SRC_OUT_ROOT:-$DQ_ROOT/delivery/$PKG_NAME}"
ZIP_PATH="$DQ_ROOT/delivery/${PKG_NAME}-${BUILD_DATE}.zip"

if [[ -z "${DINGQIAO_FAT_AAR:-}" ]]; then
  echo "[0/5] build fat AAR (align demo-src with SDK delivery) ..."
  cd "$AR_ROOT"
  ./gradlew :sdk:assembleRelease :sdk-police:assembleRelease :sdk-dingqiao:assembleRelease
  dingqiao_assert_sdk_version_consistent "$AR_ROOT"
  bash "$REPO_ROOT/asr/tools/delivery/merge_dingqiao_fat_aar.sh" "$VERSION"
fi
[[ -f "$FAT_AAR" ]] || { echo "[ERROR] missing $FAT_AAR" >&2; exit 1; }

if [[ -n "${DINGQIAO_DEMO_APK:-}" || -n "${DINGQIAO_DEMO_LICENSE:-}" ]]; then
  echo "[0b/5] reuse Release Demo APK + license from parent delivery ..."
  [[ -n "${DINGQIAO_DEMO_APK:-}" && -n "${DINGQIAO_DEMO_LICENSE:-}" ]] || {
    echo "[ERROR] DINGQIAO_DEMO_APK and DINGQIAO_DEMO_LICENSE must be provided together" >&2
    exit 1
  }
  DEMO_APK_SRC="$DINGQIAO_DEMO_APK"
  DEMO_LIC_SRC="$DINGQIAO_DEMO_LICENSE"
else
  echo "[0b/5] issue demo license + build Release Demo APK (2-month trial, hotwords UI) ..."
  dingqiao_issue_demo_license "$REPO_ROOT"
  cd "$AR_ROOT"
  ./gradlew :samples:dingqiao-demo:assembleRelease \
    -PdingqiaoUseFatAar=true \
    -PdingqiaoFatAarPath="$FAT_AAR"
  DEMO_APK_SRC="$AR_ROOT/samples/dingqiao-demo/build/outputs/apk/release/dingqiao-demo-release.apk"
  DEMO_LIC_SRC="$AR_ROOT/samples/dingqiao-demo/src/main/assets/amphion-license.lic"
fi
[[ -f "$DEMO_APK_SRC" ]] || { echo "[ERROR] missing $DEMO_APK_SRC" >&2; exit 1; }
[[ -f "$DEMO_LIC_SRC" ]] || { echo "[ERROR] missing $DEMO_LIC_SRC" >&2; exit 1; }

echo "[1/5] stage demo source tree ..."
rm -rf "$OUT_ROOT"
mkdir -p "$OUT_ROOT"/{libs,gradle/wrapper,sample-dingqiao-demo,docs,demo}

cp "$FAT_AAR" "$OUT_ROOT/libs/$AAR_NAME"
cp "$DEMO_APK_SRC" "$OUT_ROOT/demo/sample-dingqiao-demo-release.apk"
cp "$DEMO_LIC_SRC" "$OUT_ROOT/demo/amphion-license.lic"

DEMO_LIC_EXPIRES="$("$REPO_ROOT/tools/license/.venv/bin/python" -c "
import base64, json, sys
env = json.load(open(sys.argv[1], encoding='utf-8'))
payload = json.loads(base64.b64decode(env['payload_b64']).decode('utf-8'))
print(payload.get('expiresAt') or '永久')
" "$DEMO_LIC_SRC" 2>/dev/null || echo "见 amphion-license.lic")"

cat > "$OUT_ROOT/demo/README.txt" <<EOF
鼎桥 Demo 可安装包（com.amphion.dingqiao.demo）
============================================

  sample-dingqiao-demo-release.apk   可直接安装（内置 2 个月试用 license）
  amphion-license.lic                与 APK 同批次签发的 Demo 授权（绑定 Demo 包名+签名，不绑定 SN）

试用到期：${DEMO_LIC_EXPIRES}（到期后需联系我方重签 Demo 或更换正式授权）

安装后功能
----------
  - 离线 ASR + 警务增强（车牌/派出所/术语预设热词默认开启）
  - 菜单「自定义热词」：追加 sysGeneralLexicon
  - 声纹注册：声纹模型已内置于 SDK，首次运行自动准备

说明
----
  本 Demo 包名 com.amphion.dingqiao.demo，仅供集成参考。
  贵司正式 App（com.tdtech.tiassistant）请使用 SDK 交付包中的商用授权，勿混用本 license。正式授权可绑定设备 SN 清单。
EOF

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

dingqiao_stage_customer_docs "$OUT_ROOT/docs" "$CUSTOMER_DOCS" "$DQ_ROOT"

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
dingqiaoSdkAar=libs/${AAR_NAME}
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
val demoAssetDir = providers.gradleProperty("dingqiaoDemoAssetDir").orElse("demo").get()
val evalAudioDir = providers.gradleProperty("dingqiaoEvalAudioDir").orNull

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

    sourceSets {
        getByName("main").assets.srcDir(rootProject.file(demoAssetDir))
        evalAudioDir
            ?.takeIf { it.isNotBlank() }
            ?.let { getByName("androidTest").assets.srcDir(it) }
    }
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
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.test.runner)
}
EOF

cat > "$OUT_ROOT/sample-dingqiao-demo/proguard-rules.pro" <<'EOF'
# Demo Release 开启 R8；SDK 消费规则由 fat AAR 内 proguard.txt 自动合并。
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile
EOF

cat > "$OUT_ROOT/sample-dingqiao-demo/README.md" <<EOF
# 鼎桥语音识别 Demo（参考工程）

本模块为交付 Demo APK 的参考源码，默认通过 \`libs/${AAR_NAME}\` 调用 \`SpeechRecognizeSdk\`（不含 SDK 源码）。

- 集成说明见 \`docs/DINGQIAO_INTEGRATION.md\`
- 声纹模型部署见 \`docs/DINGQIAO_VOICEPRINT_MODEL.md\`
- 默认读取根目录 \`demo/amphion-license.lic\` 作为 Demo 授权；如需替换，使用 \`-PdingqiaoDemoAssetDir=/path/to/assets\`
- 工程级说明见根目录 \`README.txt\`
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

cat > "$OUT_ROOT/README.txt" <<EOF
鼎桥警务语音识别 SDK — Demo 参考工程源码 v${VERSION}
====================================================

本包为「纯 Demo 模块源码 + fat AAR + 可安装 Demo APK + 客户文档」的独立 Gradle 工程。
不含 SDK 核心源码、警务规则资产、打包脚本或私钥。

保密：仅供贵司 com.tdtech.tiassistant 项目内部集成参考，请勿对外传播或二次分发。

目录
----
  demo/sample-dingqiao-demo-release.apk   可直接安装（内置 2 个月试用 license，到期 ${DEMO_LIC_EXPIRES}）
  demo/amphion-license.lic               与 APK 同批 Demo 授权（不绑定 SN；自编译 Release 需同签名，见 demo/README.txt）
  sample-dingqiao-demo/                  Demo App 源码（含自定义热词 UI）
  libs/${AAR_NAME}                       与 SDK 交付包同版本的 fat AAR
  docs/                                  集成说明、声纹说明、第三方声明
  gradle/ gradlew                        独立 Gradle 工程，JDK 17

快速体验（推荐）
----------------
  1. 安装 demo/sample-dingqiao-demo-release.apk
  2. 声纹：见 docs/DINGQIAO_VOICEPRINT_MODEL.md

自编译源码
----------
  1. 复制 local.properties.example → local.properties，填写 sdk.dir
  2. Debug 联调：./gradlew :sample-dingqiao-demo:assembleDebug（默认使用 demo/amphion-license.lic；如本机签名不匹配，请向我方索取匹配授权或自配签名+license）
  3. 声纹模型已内置于 libs/${AAR_NAME}，运行时自动准备，无需外置部署

与正式 App 的区别
-----------------
  Demo 包名 com.amphion.dingqiao.demo；正式集成请用 com.tdtech.tiassistant 及贵司商用授权。

版本
----
  对齐 SDK 交付包 v${VERSION}；AAR 与交付包 aar/ 目录一致；打包日期 ${BUILD_DATE}
EOF

echo "[2/5] sanity check ..."
[[ -f "$OUT_ROOT/sample-dingqiao-demo/src/main/java/com/amphion/dingqiao/demo/MainActivity.kt" ]]
[[ -f "$OUT_ROOT/libs/$AAR_NAME" ]]
[[ -f "$OUT_ROOT/docs/DINGQIAO_INTEGRATION.md" ]]
[[ -f "$OUT_ROOT/demo/sample-dingqiao-demo-release.apk" ]]
[[ -f "$OUT_ROOT/demo/amphion-license.lic" ]]
[[ ! -f "$OUT_ROOT/sample-dingqiao-demo/src/main/assets/amphion-license.lic" ]]
grep -rq ":sdk-dingqiao\|:sdk-police" "$OUT_ROOT" && {
  echo "[ERROR] internal module reference leaked in demo-src package" >&2
  exit 1
}

echo "[3/5] verify AAR in delivery tree ..."
bash "$REPO_ROOT/asr/tools/delivery/verify_dingqiao_delivery.sh" "$OUT_ROOT/libs/$AAR_NAME"

if [[ "${DINGQIAO_DEMO_SRC_SKIP_ZIP:-}" != "1" ]]; then
  echo "[4/5] zip ..."
  rm -f "$ZIP_PATH"
  dingqiao_zip_delivery "$OUT_ROOT" "$ZIP_PATH"
  echo "[5/5] done"
  echo "[OK] tree: $OUT_ROOT"
  echo "[OK] zip:  $ZIP_PATH"
  du -sh "$OUT_ROOT" "$ZIP_PATH"
else
  echo "[4/5] skip zip (embedded in customer delivery)"
  echo "[5/5] done"
  echo "[OK] tree: $OUT_ROOT"
  du -sh "$OUT_ROOT"
fi
