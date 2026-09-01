#!/usr/bin/env python3
"""Assemble the complete Android TTS delivery without handling signing keys."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import subprocess
import zipfile
from pathlib import Path


SDK_VERSION = "3.0"
MODEL_ID = "dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop"
MODEL_VERSION = "0.1.0"
DEMO_APPLICATION_ID = "com.amphion.lits.tts.demo"
DELIVERY_NAME_PREFIX = "Amphion-Dingqiao-TTS"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def copy_file(source: Path, target: Path) -> None:
    if not source.is_file():
        raise SystemExit(f"missing input file: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def verify_demo_apk_assets(apk: Path) -> None:
    """Refuse a delivery whose demo APK cannot cold-start without side-loaded files."""
    expected = {
        "assets/amphion-license.lic",
        "assets/lits-models/tts/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/lits_hidden_encoder.onnx",
        "assets/lits-models/tts/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/lits_stream_condition_chunk.onnx",
        "assets/lits-models/tts/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/lits_stream_decoder_step.onnx",
        "assets/lits-models/tts/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/vocos_vocoder.onnx",
    }
    with zipfile.ZipFile(apk) as archive:
        missing = expected.difference(archive.namelist())
    if missing:
        raise SystemExit(f"demo APK is not self-contained; missing assets: {', '.join(sorted(missing))}")


def verify_sdk_aar_assets(aar: Path) -> None:
    expected_prefix = "assets/lits-models/tts/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/"
    expected = {
        f"{expected_prefix}lits_hidden_encoder.onnx",
        f"{expected_prefix}lits_stream_condition_chunk.onnx",
        f"{expected_prefix}lits_stream_decoder_step.onnx",
        f"{expected_prefix}vocos_vocoder.onnx",
    }
    with zipfile.ZipFile(aar) as archive:
        missing = expected.difference(archive.namelist())
    if missing:
        raise SystemExit(f"SDK AAR is not self-contained; missing model assets: {', '.join(sorted(missing))}")


def zip_tree(source: Path, output: Path) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
            relative = path.relative_to(source.parent).as_posix()
            info = zipfile.ZipInfo(relative + ("/" if path.is_dir() else ""), (1980, 1, 1, 0, 0, 0))
            mode = path.stat().st_mode
            info.external_attr = (mode & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            if path.is_dir():
                archive.writestr(info, b"")
            else:
                archive.writestr(info, path.read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser(description="Package the complete Amphion Android TTS delivery")
    parser.add_argument("--aar", type=Path, required=True)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    verify_demo_apk_assets(args.apk)
    verify_sdk_aar_assets(args.aar)

    repo = Path(__file__).resolve().parents[3]
    android = repo / "tts/android"
    if args.output_dir.exists():
        raise SystemExit(f"output already exists: {args.output_dir}")

    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    diff = subprocess.check_output(
        ["git", "diff", "--", "tts/android", "scripts/build_dingqiao_android_native.sh"],
        cwd=repo,
    )
    diff_sha256 = hashlib.sha256(diff).hexdigest()
    package_name = f"{DELIVERY_NAME_PREFIX}-Android-{SDK_VERSION}"
    root = args.output_dir / package_name
    root.mkdir(parents=True)

    aar_name = f"amphion_dingqiao_tts_sdk-android-{SDK_VERSION}.aar"
    apk_name = f"amphion_dingqiao_tts_demo-android-{SDK_VERSION}-debug.apk"
    copy_file(args.aar, root / "aar" / aar_name)
    copy_file(args.apk, root / "demo" / apk_name)
    # Keep legal notices away from license/ because default macOS volumes are
    # case-insensitive (a root LICENSE file would collide with that directory).
    copy_file(android / "LICENSE", root / "legal/LICENSE")
    copy_file(android / "NOTICE", root / "legal/NOTICE")
    (root / "docs").mkdir(parents=True, exist_ok=True)

    demo_source = root / "demo-source"
    shutil.copytree(android / "sample/src", demo_source / "sample/src")
    copy_file(android / "sample/proguard-rules.pro", demo_source / "sample/proguard-rules.pro")
    copy_file(android / "gradlew", demo_source / "gradlew")
    copy_file(android / "gradlew.bat", demo_source / "gradlew.bat")
    shutil.copytree(android / "gradle/wrapper", demo_source / "gradle/wrapper")
    copy_file(args.aar, demo_source / "libs" / aar_name)
    (demo_source / "gradlew").chmod((demo_source / "gradlew").stat().st_mode | stat.S_IXUSR)

    write_text(
        demo_source / "settings.gradle.kts",
        """
pluginManagement {
    repositories { google(); mavenCentral(); gradlePluginPortal() }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories { google(); mavenCentral() }
}
rootProject.name = "AmphionAndroidTtsDemo"
include(":sample")
""",
    )
    write_text(
        demo_source / "build.gradle.kts",
        """
plugins {
    id("com.android.application") version "8.4.0" apply false
    id("org.jetbrains.kotlin.android") version "1.9.22" apply false
}
""",
    )
    write_text(
        demo_source / "gradle.properties",
        """
org.gradle.jvmargs=-Xmx4096m -Dfile.encoding=UTF-8
android.useAndroidX=true
kotlin.code.style=official
""",
    )
    write_text(
        demo_source / "sample/build.gradle.kts",
        f"""
plugins {{
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}}

val deliveryLicenseFile = providers.gradleProperty("amphionDemoLicenseFile").orNull?.let(::file)
val prepareDeliveryAssets by tasks.registering(Sync::class) {{
    deliveryLicenseFile?.let {{ from(it) }}
    into(layout.buildDirectory.dir("generated/deliveryAssets"))
}}

android {{
    namespace = "com.lits.tts.sample"
    compileSdk = 34
    defaultConfig {{
        applicationId = "{DEMO_APPLICATION_ID}"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "{SDK_VERSION}"
    }}
    buildTypes {{
        release {{
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }}
    }}
    compileOptions {{
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }}
    kotlinOptions {{ jvmTarget = "17" }}
    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("generated/deliveryAssets"))
}}

tasks.named("preBuild").configure {{ dependsOn(prepareDeliveryAssets) }}

dependencies {{
    implementation(files("../libs/{aar_name}"))
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
}}
""",
    )
    write_text(
        demo_source / "README.md",
        f"""
# Demo 源码

使用 JDK 17 和 Android SDK 34，在本目录运行 `./gradlew :sample:assembleDebug`。
模型已随 SDK AAR 合并到最终 App，无需手工复制 assets；不会改写 SDK AAR。
如需运行自行编译的 Demo，须通过受控授权渠道取得 `.lic`，并以
`-PamphionDemoLicenseFile=/absolute/path/amphion-license.lic` 传入。Demo applicationId 固定为 `{DEMO_APPLICATION_ID}`。
""",
    )

    write_text(
        root / "README.md",
        f"""
# {DELIVERY_NAME_PREFIX} Android {SDK_VERSION}

本包包含 arm64-v8a Android TTS AAR、外置模型资源、自包含调试 Demo APK、Demo 源码、本地评估授权和接入文档。

## 目录

- `aar/{aar_name}`：已内置 24 kHz 中英双语模型的 SDK AAR；不内置授权。
- `demo/{apk_name}`：已内置模型与运行授权的调试 APK，可直接安装体验。
- `demo-source/`：基于随包 AAR 和模型可重建 Demo 的源码；运行时授权须独立受控提供。
- `docs/`：API、接入、平台差异、授权边界、验证与构建溯源。

先体验可直接安装 `demo/` APK；产品接入请从 `docs/INTEGRATION.md` 开始。
""",
    )
    shutil.copy2(android / "docs/API.md", root / "docs/TTS_SDK_API_ANDROID.md")
    write_text(
        root / "docs/INTEGRATION.md",
        f"""
# Android TTS 接入

## 环境

- Android 7.0 / API 24 及以上
- 当前仅交付 `arm64-v8a`
- JDK 17、compileSdk 34（重建 Demo 时）

## AAR 与模型

将 `aar/{aar_name}` 作为本地 AAR 依赖即可。AAR 已内置约 187 MB 的 24 kHz 中英双语模型；SDK 首次创建引擎时自动将资源安装到 `TextToSpeechSdk.setWorkPath(path)` 指定目录，无需业务方手工放置 assets 或模型目录。

## 初始化和合成

```kotlin
TextToSpeechSdk.init(applicationContext)
TextToSpeechSdk.setWorkPath(File(filesDir, "lits-tts-work").absolutePath)

TextToSpeechSdk.createEngine(
    CreateEngineParams("zh-en", RunMode.OFFLINE, "lits-female-02"),
    object : Callback<TextToSpeechEngine> {{
        override fun onSuccess(engine: TextToSpeechEngine) {{
            engine.setListener(listener)
            engine.speak(
                "你好，欢迎使用离线语音合成。",
                SpeakParams(
                    requestId = "tts-001",
                    languageContext = "zh-CN",
                    playType = PlayType.SYNTHESIZE_AND_PLAY,
                    streamingConfig = TtsStreamingConfig(chunkSize = 50, pcmQueueCapacity = 128),
                ),
            )
        }}
        override fun onError(errorCode: Int, errorMessage: String) {{ }}
    }},
)
```

中英前端可用 `zh-en` / `zh-CN`，英文用 `en-US`；英文示例音色为 `lits-female-01`。引擎创建和合成均应按异步接口使用，结束时调用 `shutdown()`。
""",
    )
    write_text(
        root / "docs/PLATFORM_DIFF.md",
        """
# Android 与 HarmonyOS TTS 差异

| 项目 | Android | HarmonyOS |
| --- | --- | --- |
| SDK 载体 | AAR | HAR |
| Demo 载体 | APK | HAP |
| 模型策略 | AAR 外置；Demo 可内置 | 当前 HAR/HAP 交付内置 rawfile |
| 原生 ABI | arm64-v8a | arm64-v8a |
| 文本归一化 | JNI + Android ICU + native TN | NAPI + native TN |
| 推理 | ONNX Runtime Android，external-loop decoder | ONNX Runtime OHOS，external-loop decoder |
| 授权宿主字段 | applicationId | bundleName |
| 性能观测 | `loadProfileInfo` / `profilingInfo` | Demo 分阶段耗时与 SDK profiling |

两端使用同一 24 kHz 模型拓扑和中英文能力，但 JNI/NAPI、资源安装、线程和播放层是独立实现。HarmonyOS 最近的 in-process TN、资源预热和内存优化不能直接视为 Android 已自动获得；Android 本包保持现有 external-loop 与 profiling 实现，没有夹带推理状态机重构。
""",
    )
    write_text(
        root / "docs/LICENSE.md",
        f"""
# 授权交付说明

本交付 ZIP 不包含独立 `.lic` 文件。`demo/` APK 已内嵌运行所需授权，可直接安装体验；SDK 集成及自行编译 Demo 所需授权须通过独立、受控渠道签发与提供。

正式授权应按客户 applicationId、签名证书和设备策略签发。包内不含签发私钥或可独立分发的授权文件。
""",
    )
    write_text(
        root / "docs/VALIDATION.md",
        """
# 验证结果

- AAR Release 构建：PASS；仅包含 arm64 原生库、SDK classes 和 ONNX Runtime classes，不含模型与授权。
- Demo Debug APK 构建：PASS；包含完整 4 个 ONNX 模型、前端资源、评估授权和 arm64 原生库。
- APK v2 调试签名：PASS；这是本地 debug 签名，不是客户 release 签名。
- APK 内授权与签发输出逐字节一致，ECDSA、TTS feature、SDK major、有效期：PASS。
- 私钥标记与本机绝对路径扫描：PASS。
- 随包 Demo 源码 Gradle 工程解析（`:sample:tasks`）：PASS。
- JVM 定向门禁：`LitsTtsAssetRegistryTest` 3/3 PASS，覆盖当前资源清单、单 final-zero decoder 和旧 final condition 模型不再暴露。
- PCM 播放队列回归：`AndroidPcmPlayerQueueTest` 4/4 PASS；队列满时结束标记等待腾位，取消时清理队列，并验证中断结束路径不会使播放线程崩溃。
- 既有 JVM 全量基线：94 项中 86 PASS、5 FAIL、3 SKIP。5 项均为 6 月断言与 7/8 月 TN 规则的预期文本漂移（URL、车牌、时间、负数空格、技术符号）；未回滚模型规则，也未放宽断言。
- ADB 安装与运行：PASS；设备 vivo V2324A，Android 16 / API 36，arm64-v8a；applicationId=`com.amphion.lits.tts.demo`。
- APK 一致性：设备端 `base.apk` 与本包输入 APK SHA-256 均为 `41aef115463a1f845d4da33fc6c59a21b8d5946640824539a44550d4a3f703e3`。
- 清数据冷启动：PASS；模型从开始加载到完成约 2680 ms，未出现 `LICENSE_*`、`ORT_NO_SUCHFILE`、`onError` 或模型加载失败。加载期立即点击“仅合成”会在顶部和 Toast 明确反馈，不再静默无响应。
- 短文本仅合成：PASS；50 字符中英混合文本，7 个流式 chunk，首包 134 ms、合成 834 ms、音频 6368 ms、RTF 0.131，回调顺序为 `onStart -> onData* -> onComplete`。
- 长文本只合成：PASS；固定 1303 字符、36 个文本段，128 个流式 chunk，首包 105 ms、合成 14120 ms、音频 117504 ms、RTF 0.120，最大/平均 chunk 回调间隔 213/110 ms，无 ANR。
- 中文长文本仅合成：PASS；固定 1044 字符、35 个文本段，165 个流式 chunk，首包 206 ms、合成 44033 ms、音频 232560 ms、RTF 0.189，最大/平均 chunk 回调间隔 540/267 ms，无 ANR。
- 英文长文本边合成边播：PASS；播放启动 152 ms，合成在队列背压下 87125 ms 完成，117504 ms 音频完整播放后收到 `PLAYBACK_COMPLETE`；队列峰值 32/32、入队 128 个 chunk、AudioTrack underrun=0。此前队列满时结束标记可能丢失导致永久等待，本版已修复并由满队列真机路径验证。
- 内存快照：模型加载后 TOTAL PSS 396695 KB；中文长文本仅合成后 514906 KB（Demo 保留完整 PCM 供“播放/保存”）；英文边合成边播中段 492086 KB，完成回落至 444497 KB。均为单轮快照，不作为长稳压或泄漏结论。
""",
    )

    third_party = repo / "tts/harmony/build/delivery/complete-tts-0.1.0-5912f050" / "Amphion-Harmony-TTS-Complete-0.1.0/docs/third-party/ONNX-Runtime-MIT.txt"
    if third_party.is_file():
        copy_file(third_party, root / "docs/third-party/ONNX-Runtime-MIT.txt")

    artifacts = {
        "aar": root / "aar" / aar_name,
        "apk": root / "demo" / apk_name,
    }
    provenance = {
        "schemaVersion": 1,
        "platform": "Android",
        "sdkVersion": SDK_VERSION,
        "modelId": MODEL_ID,
        "modelVersion": MODEL_VERSION,
        "sourceCommit": commit,
        "sourceDirty": bool(diff),
        "androidDeliveryDiffSha256": diff_sha256,
        "abi": ["arm64-v8a"],
        "minSdk": 24,
        "compileSdk": 34,
        "licenseClass": "local-evaluation-not-formal-customer-license",
        "artifacts": {name: {"path": str(path.relative_to(root)), "sha256": sha256(path), "bytes": path.stat().st_size} for name, path in artifacts.items()},
    }
    write_text(root / "docs/BUILD_PROVENANCE.json", json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True))

    checksum_lines = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_file() and path.name != "checksum.txt":
            checksum_lines.append(f"{sha256(path)}  {path.relative_to(root).as_posix()}")
    write_text(root / "docs/checksum.txt", "\n".join(checksum_lines))

    archive = args.output_dir / f"{package_name}.zip"
    zip_tree(root, archive)
    print(json.dumps({"root": str(root), "zip": str(archive), "sha256": sha256(archive)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
