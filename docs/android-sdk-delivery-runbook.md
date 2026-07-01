# Android SDK 交付 Runbook

本文沉淀 ASR / TTS / License 三件套交付的标准流程。原则是：最终 zip 是唯一真相；交付前验证只从最终 zip 解压出的内容开始，不读取本地 `build/` 临时产物。

## 1. 交付前检查

1. 从最新 `main` 开交付分支，确认工作区 clean。
2. 确认版本号、交付日期和客户口径一致。
3. 确认 license 策略：
   - 正式 license 可同时授权 `ASR,TTS`。
   - v3.0 起不限制 applicationId / 证书，包名只作为记录字段。
   - 正式 license 仍限制设备白名单、授权能力和有效期。
   - 真实 SN、私钥、正式 license 和 `.secure/` 内容不得提交。
4. 确认测试音频口径：
   - ASR Android SDK `AudioInfo` 当前只支持 `16 kHz / 16 bit / mono PCM`。
   - `DingqiaoFinishFlushRegressionTest` 必须使用 16 kHz 音频。
   - 24 kHz 业务语料可用于业务评估流程，但不能直接喂给 16 kHz Android instrumentation 回归。

## 2. ASR 交付

在仓库根目录执行：

```bash
bash asr/tools/delivery/pack_dingqiao_customer_delivery.sh 3.0
```

基础校验：

```bash
bash asr/tools/delivery/verify_dingqiao_delivery.sh /path/to/amphion-dingqiao-v3.0-customer.zip
```

zip-only 校验：

```bash
export DELIVERY_VERIFY_REQUIRED_AAR_ENTRIES='jni/arm64-v8a/libsherpa-onnx-jni.so:1,jni/arm64-v8a/libonnxruntime.so:1,assets/amphion-dingqiao/eres2net.onnx:31457280'
export DELIVERY_VERIFY_REQUIRED_APK_ENTRIES='lib/arm64-v8a/libsherpa-onnx-jni.so:1,lib/arm64-v8a/libonnxruntime.so:1,assets/amphion-dingqiao/eres2net.onnx:31457280,assets/amphion-license.lic:1'
export DELIVERY_VERIFY_LICENSE_ENTRY='assets/amphion-license.lic'
export DELIVERY_VERIFY_LICENSE_FEATURES='ASR'
export DELIVERY_VERIFY_ANDROID_PACKAGE='com.amphion.dingqiao.demo'
bash tools/delivery/verify_delivery_zip_e2e.sh /path/to/amphion-dingqiao-v3.0-customer.zip
```

设备端回归：

```bash
cd asr/android

./gradlew :samples:dingqiao-demo:compileDebugAndroidTestSources

./gradlew :samples:dingqiao-demo:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=com.amphion.dingqiao.demo.DqLicenseTest

./gradlew :samples:dingqiao-demo:connectedDebugAndroidTest \
  -PdingqiaoEvalAudioDir=/path/to/16k-wav-dir \
  -Pandroid.testInstrumentationRunnerArguments.class=com.amphion.dingqiao.demo.DingqiaoFinishFlushRegressionTest
```

## 3. TTS 交付

在仓库根目录执行：

```bash
bash tts/tools/android/pack_lits_tts_android_delivery.sh 0.3.0
```

基础校验：

```bash
bash tts/tools/android/verify_lits_tts_android_delivery.sh /path/to/lits-tts-android-sdk-v0.3.0-YYYYMMDD.zip
```

如需要安装 demo 或跑源码链路，按 TTS 交付包里的 `docs/DELIVERY.md` 和 `android-src/TTS` 说明执行，并在交付结论里记录设备型号、Android 版本、license 来源和命令。

## 4. License 交付

正式 license 生成前必须确认：

| 字段 | 要求 |
| --- | --- |
| `features` | 正式三件套通常为 `ASR,TTS` |
| `authorizedDeviceHashes` | 必须来自客户确认的设备 SN |
| `expiresAt` | 必须为约定有效期；试用交付通常为 2 个月 |
| `applicationId` / `certificateSha256` | v3.0 起不作为限制条件 |

生成后必须运行 verifier，并在交付目录保留 verification 报告。正式 license zip 内只放客户需要的 `.lic`、说明和 checksum；不得放私钥、明文 SN 清单或 `.secure/`。

## 5. 交付目录整理

推荐目录：

```text
delivery/
├── current/
│   └── YYYYMMDD-vX.Y/
│       ├── asr/
│       ├── tts/
│       ├── license/
│       └── reports/
├── archive/
│   └── YYYYMMDD/
└── misc/
```

生成清单：

```bash
python3 tools/delivery/generate_delivery_manifest.py \
  /path/to/delivery/current/YYYYMMDD-vX.Y \
  --release-id YYYYMMDD-vX.Y \
  --output /path/to/delivery/current/YYYYMMDD-vX.Y/MANIFEST.md
```

清单应包含所有正式 zip 的路径、大小、SHA-256，以及相邻 verification 报告路径。

## 6. 交付邮件

交付邮件使用 `docs/delivery-email-template.md`。邮件必须写清：

- 三个 zip 名称。
- ASR / TTS / License 更新点。
- License 是否限制包名、设备和有效期。
- ASR 业务测试命中率或回归测试结果。
- 可复现命令或随包文档入口。
- SHA-256 或 `MANIFEST.md` 路径。

## 7. 交付结论门禁

只有同时满足以下条件，才能给出“可交付”结论：

1. 最终 ASR / TTS / License zip 均存在且 checksum 已记录。
2. ASR / TTS 专用 verifier 通过。
3. License verifier 通过，策略符合交付口径。
4. ASR license 和 finish/flush 设备端回归通过，或明确说明未跑原因。
5. 交付文档版本号、AAR 名称、zip 名称一致。
6. 对方可按 zip 内文档从源码或 demo 路径复现。
