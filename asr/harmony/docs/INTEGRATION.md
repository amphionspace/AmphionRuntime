# Amphion Runtime HarmonyOS 集成指南

适用范围：HarmonyOS NEXT / OpenHarmony 原生应用，不适用于 Android APK 兼容层。本版本以 Android ASR SDK 0.2.x 的公开 API 和运行语义为对齐基准。

## 环境要求

| 项目 | 要求 |
| --- | --- |
| DevEco Studio | 5.x |
| HarmonyOS SDK | 5.x，Stage 模型 |
| Native | OHOS NDK arm64-v8a |
| 设备 | HarmonyOS 6.0+ / NEXT 或 API 不低于工程 `compatibleSdkVersion` 的纯血鸿蒙真机，arm64 |
| 权限 | `ohos.permission.MICROPHONE` |

验收 HAP 当前配置见 `delivery/harmony-dingqiao/build-profile.json5`，`compatibleSdkVersion` 为 `5.0.0(12)`。如果 USB 设备是 HarmonyOS 4.3，需要先确认系统 API：

```bash
hdc shell param get const.ohos.apiversion
hdc shell getprop persist.sys.ohc.apiversion
```

若设备 API 低于 12，用当前 HAP 安装失败属于系统 API 不匹配；这与 USB、签名或 `hdc install` 命令无关。6.0+ / NEXT 与 4.3 表面都使用 HAP/`hdc`，但可安装性由设备系统 API、工程 `compatibleSdkVersion`、签名和 ABI 共同决定，不能视为完全相同。

## 模块

| 模块 | 作用 |
| --- | --- |
| `amphion_asr` | 核心 ASR HAR |
| `amphion_police` | 警务增强 HAR |
| `amphion_dingqiao` | 鼎桥接口 HAR |

验收 HAP（`dingqiao_demo`，同时演示 ASR + TTS）位于 `delivery/harmony-dingqiao/samples/dingqiao-demo`。

## 准备 native 与模型

```bash
bash asr/tools/04_build_harmony_so.sh
bash asr/tools/05_package_har_libs.sh
bash asr/tools/08_pack_harmony_assets.sh
```

## 通用 ASR API

```ts
import { AmphionRuntime, AsrConfig, AsrLanguage, AmphionLogLevel } from 'amphion_asr';

AmphionRuntime.init(context, {
  logLevel: AmphionLogLevel.INFO
});

const config = AsrConfig.builder()
  .numThreads(2)
  .punctuation(true)
  .itn(true)
  .vad(true)
  .endpoint(true)
  .hotwords(['接警', '处警'], 2.0)
  .build();

const engine = AmphionRuntime.create(context, AsrLanguage.ZH_EN, config);
const session = engine.newSession({
  onPartial: (text: string) => {},
  onFinal: (text: string, confidence: number) => {},
  onFinalResult: (result) => {},
  onEndpoint: () => {},
  onMetrics: (metrics) => {},
  onError: (error) => {}
});
session.acceptPcmShort(pcm16kMono);
session.stop();
session.close();
engine.close();
```

SDK 不接管录音，业务方需自行使用 `AudioCapturer` 获取 16 kHz、16-bit、mono PCM。

## 预加载与释放

`AmphionRuntime.preInstall` 会检查 Harmony rawfile 模型布局并返回可取消句柄；Harmony 当前不需要像 Android 那样先把 assets 解包到 `filesDir`。

`AmphionRuntime.preload(context, languages, config, onProgress)` 会提前创建对应语言的 `OnlineRecognizer` 并放入进程内池。后续 `create` 在 `numThreads`、endpoint 规则、热词和热词分数兼容时复用池内 recognizer；不兼容时创建专用 recognizer。`AmphionRuntime.release()` 会清空预加载池并重置 license 状态。

## 指标与日志

指标 schema 与 Android 版一致，通过 `AsrCallback.onMetrics` 和控制台日志输出，tag 文本为 `AmphionMetrics`。

| kind | 派发时机 | 主要字段 |
| --- | --- | --- |
| `UTTERANCE` | 每段 final 同帧派发 | `utteranceDurationMs`、`decodeDurationMs`、`postProcessMs`、`firstPartialLatencyMs`、`rtf`、`pcmBytesAccepted` |
| `SESSION` | session close 时派发 | `totalUtterances`、`totalPcmBytes`、`avgRtf`、`p95Rtf` |

Harmony 端暂未接入 native RSS 读取，`nativeRssMb`、`peakNativeRssMb` 等字段保持 `-1`，字段名和 sentinel 规则与 Android 保持一致。

## License

ASR 与 TTS 共用离线 license 结构。Harmony ASR 读取同一类 `amphion-license.lic` 外层信封：

```json
{
  "payload_b64": "<base64(UTF-8 JSON claims)>",
  "alg": "SHA256withECDSA",
  "sig_b64": "<base64(ECDSA signature)>"
}
```

claims 字段与 Android 对齐，包括 `bundleName`、`signingCertDigest`、`authorizedDeviceHashes`、`features`、`sdkMajor`、`maintenanceUntil`。当前 Harmony 侧已解析 `payload_b64`、校验 bundleName、签名证书摘要、ASR feature、SDK 大版本、维护期和过期日；正式 ECDSA 验签仍需交付构建注入公钥后启用。未注入公钥且未传 license 时，状态为 `DEV_UNLICENSED`，用于开发和内部验证。

## 已知差异

| 能力 | 状态 |
| --- | --- |
| ASR | 走上游 `sherpa_onnx` Harmony HAR，支持中英和粤英流式识别 |
| VAD | 已接入 `sherpa_onnx.Vad`，当前支持 Silero VAD；`TEN_VAD` 枚举保留但模型未打包，选择会报错 |
| 标点 | 已接入 `OfflinePunctuation`，final 阶段单次加标点 |
| ITN | `AsrConfig.itn` 已保留并在回调中明确提示降级；需 Amphion WeText NAPI 打包后启用，不会伪装成已处理 |
| 声纹 | `SpeakerEnroller` 与目标说话人过滤已接入 `SpeakerEmbeddingExtractor`；注册输入需 16 kHz 单声道 PCM 或可读取的 16 kHz wav |
| 目标说话人 VAD | 已实现基础滑窗声纹打分与连续低分提前 endpoint；未确认目标说话人前会抑制 partial，避免非目标人文本泄露到 UI |
| license | 状态机、错误码和 claims 解析已对齐 Android；正式 ECDSA 验签仍需交付构建注入公钥 |

## 安装验收

可安装包位于 `delivery/harmony-dingqiao/samples/dingqiao-demo`，`asr/harmony/sdk` 本身是 HAR，不能直接安装。

常用命令：

```bash
cd delivery/harmony-dingqiao
ohpm install
hvigorw assembleHap --mode module -p module=dingqiao_demo@default -p product=default
hdc list targets
hdc install samples/dingqiao-demo/entry/build/default/outputs/default/dingqiao_demo-default-signed.hap
```

若安装失败，先按顺序检查设备 API、签名、ABI 和旧包签名是否一致。签名不一致时先卸载旧包；系统 API 低于 `compatibleSdkVersion` 时需要更换设备或另建低 API 兼容变体。

## main 分支复现说明

合入 `main` 后，源码、交付工程和 sherpa-onnx patch 序列都在仓库中；模型、签名证书、license、HAP/HAR 和 native 构建产物不入库。从干净 `main` 复现时需要：

```bash
git submodule update --init third_party/sherpa-onnx
bash asr/tools/04_build_harmony_so.sh
bash asr/tools/05_package_har_libs.sh
bash asr/tools/08_pack_harmony_assets.sh
```

`04_build_harmony_so.sh` 会自动调用 `apply_sherpa_patches.sh`，把 `third_party/patches/sherpa-amphion/` 的 patch 应用到 sherpa-onnx；不要提交 submodule 本体的本地改动。`08_pack_harmony_assets.sh` 需要本机已有 `asr/android/sdk/src/main/assets/amphion-models/` 模型源文件。构建 signed HAP 还需要 DevEco 签名配置；无签名配置时只能得到未签名或调试产物。

因此 `main` 可以编译出功能等价的鸿蒙应用，但 HAP 二进制不承诺字节级一致，签名、时间戳和构建元数据都会影响 hash。

## TTS

离线 TTS 已拆分为独立 SDK，见 `tts/harmony/`（模块名 `amphion_tts`）与 `tts/harmony/docs/INTEGRATION.md`。
