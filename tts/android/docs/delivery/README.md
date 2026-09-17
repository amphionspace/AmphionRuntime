# Android TTS 打包交付清单

本文是 Android TTS 交付的固定入口。后续打包沿用这里的目录、命名和接入示例；版本、模型或交付范围变更时同步更新。旧 `pack_lits_tts_android_delivery.sh` 的混合源码大包和早期 HiFi-GAN 说明不作为当前交付标准。

## 1. 每次交付两个独立包

| 交付物 | 命名 |
| --- | --- |
| SDK 包 | `lits-dingqiao-tts-android-sdk-vocos24k-<版本>.zip` |
| Demo 包 | `lits-dingqiao-tts-android-demo-vocos24k-<版本>.zip` |

两包使用同一版本、同一份 Release AAR、同一套运行资源。分别附同名 `.zip.sha256` 文件。
当前交付版本为 **3.1**；授权兼容字段 `sdkMajor=1`，与交付版本号分别管理，不因包名升版而改动。

## 2. SDK 包必须包含

```text
lits-dingqiao-tts-android-sdk-vocos24k-<版本>/
├── lits-dingqiao-tts-sdk-vocos24k-<版本>.aar
├── external-resources/
│   └── tts/<model_id>/<模型资源版本>/
│       ├── manifest.json
│       └── 模型、词典、音素表、TN 规则及其余必需运行资源
├── docs/
│   ├── API.md
│   ├── INTEGRATION.md
│   └── PSEUDOCODE.md
├── README.md
├── CHANGELOG.md
├── LICENSE
├── NOTICE
└── CHECKSUMS.txt
```

- AAR 包含 SDK 代码和必需原生库；模型使用 `external-resources` 外置交付。
- 接入示例沿用 `INTEGRATION.md` 和 `PSEUDOCODE.md`，不另加重复示例工程。
- 包根 README 使用 [SDK_README.md](../SDK_README.md)，只写接入方需要的内容。
- CHANGELOG 只放当前版本更新；完整历史保留在仓库。
- CHECKSUMS.txt 在组包时重新生成，覆盖包内全部文件（不包含自身）。
- LICENSE / NOTICE 是软件使用条件和第三方声明，必须保留；它们不是设备授权 `.lic` 文件。

### 组包入口

从仓库的 `tts/android` 目录执行，模型和授权公钥使用本次确认的构建配置：

```bash
./gradlew stageSdkDelivery \
  -PLITS_TTS_MODEL_ID=<model_id> \
  -PLITS_TTS_MODEL_DIR=/absolute/path/to/model/version \
  -PAMPHION_LICENSE_PUBLIC_KEY=<验签公钥>
```

任务调用 [pack_sdk_only.py](../../../tools/android/pack_sdk_only.py)，输出到 `tts/android/build/delivery/`。复用已经验收的 AAR 时，也可直接调用该脚本，传入 `--aar`、`--model-dir`、`--android-root`、`--output`、`--version`。

## 3. Demo 包必须包含

```text
lits-dingqiao-tts-android-demo-vocos24k-<版本>/
├── apk/
│   └── lits-dingqiao-tts-demo-vocos24k-<版本>.apk
├── android-demo/
│   ├── app/
│   │   ├── src/main/             # Demo 页面和 SDK 调用源码
│   │   ├── libs/<同版本SDK>.aar
│   │   ├── build.gradle.kts
│   │   └── proguard-rules.pro
│   ├── gradle/                  # Wrapper 和依赖版本清单
│   ├── gradlew / gradlew.bat
│   ├── settings.gradle.kts
│   ├── build.gradle.kts
│   ├── gradle.properties
│   └── .gitignore
├── external-resources/tts/      # 与 SDK 包相同的运行资源
├── tools/install_demo.py
├── README.md
├── LICENSE
├── NOTICE
└── CHECKSUMS.txt
```

- 源码来自现有 `sample`，保留大小屏布局、生命周期处理及内存显示。
- 独立工程直接依赖 `app/libs` 中的 Release AAR；不要求接入方取得 SDK 引擎或训练源码。
- APK 必须从随包源码构建；包名、显示名、版本号、ABI 和构建类型写清楚。当前 3.1 使用独立包名 `com.lits.tts.demo31`、显示名 `Lits TTS Demo 3.1`、Debug 构建。
- 安装脚本负责安装 APK、部署随包资源、配置使用方提供的 license 和真实 SN。不得内置本机测试授权或测试 SN。
- README 说明安装、授权配置、Android Studio / Gradle 编译、APK 输出位置及调试签名差异。
- 独立工程应能执行 `./gradlew :app:assembleDebug`；构建缓存与本机 Android SDK 路径不随包提供。

## 4. 两包都不交付的内容

- `.lic` 授权文件、私钥、签名密钥、设备 SN 清单；授权由使用方另行提供。
- `validation/`、内部 BUILD_INFO、测试日志、原始试听音频、测试 APK、验收报告。
- Gradle 缓存、`build/`、`local.properties`、IDE 本机配置。
- 训练 checkpoint、训练源码、未使用的旧模型或重复资源副本。
- 旧源码构建文档、历史交付过程、失效链接、与当前版本无关的说明和校验值。

资源按实际运行依赖清理，不能只看文件名：当前 `frontend_golden.json` 被 SDK 加载检查引用，必须保留；`export_report.json` 不参与运行，不进入客户包。删除资源时同步修改 manifest 清单，保持文件名和大小一致。

## 5. 兼容与准确性要求

- 保持之前公开 API、参数、回调及调用结果的兼容性；整理包和文档不能改变 SDK 行为。
- 已知模型分块边界差异：常规 `chunkSize` 正数覆盖值不得低于 **40**；`100` 等已支持值保持可用。句尾不足 40 帧由 SDK 处理。
- 原有能力限制如实说明，不把既有问题写成此次新增的不兼容，也不把未实现的能力写成已支持。
- 版本号、AAR 文件名、文档示例、资源路径和输出格式必须一致；当前为 24 kHz / PCM16 / mono。
- 不因为清理文件而删除授权说明、必需资源、使用条件或第三方声明。

## 6. 打包完成前核对

1. 两包的 AAR SHA-256 一致；相同运行资源逐文件一致；Demo APK 与随包源码对应。
2. 接入示例能编译，Demo 独立工程能构建。
3. 用最终资源验证实际 AAR 的关键调用、分块和播放；Demo 验证大小屏、页面重建及播放。
4. 没有授权/私钥/SN、构建垃圾、旧模型、内部报告或本地绝对路径。
5. 包内本地文档链接有效；manifest、CHECKSUMS.txt、ZIP CRC 和 ZIP SHA-256 正确。
6. 已有同一 AAR/资源的有效验证结果可以复用。只有文档或归档名称变化时，不重复运行音频测试；结果不能覆盖本次实际变化时再补相应验证。

## 7. 内部记录留在仓库

每次打包在 [releases](../releases/) 记录版本、日期、源码来源、模型身份、AAR/APK/ZIP 哈希、验证范围、未覆盖项和是否已上传。原始证据单独归档，不放客户包。不提交模型、ZIP、APK、私钥或授权文件到 Git。

当前实例：[SDK 3.1](../releases/3.1-20260917.md)、[Demo 3.1](../releases/demo-3.1-20260917.md)。上传地址须依据实际交付安排确认，不能把模型资产 OBS 路径当作 SDK 成品发布地址。
