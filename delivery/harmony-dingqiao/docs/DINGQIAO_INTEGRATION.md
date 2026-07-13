# 鼎桥 HarmonyOS 离线语音识别 SDK 集成指南

本交付仅包含自包含 ASR SDK，不包含 Demo HAP、授权文件或 TTS SDK。完整接口契约见
`ASR_SDK_API_HARMONY.md`，授权说明见 `LICENSE.md`，现场排查见 `TROUBLESHOOTING.md`。

## 1. 交付内容

| 路径 | 说明 |
| --- | --- |
| `har/amphion_dingqiao.har` | 自包含 ASR SDK，已内置运行时、中文/粤语模型、标点、ITN、VAD、警务资源和声纹模型 |
| `docs/` | API、授权、集成、排障、性能摘要、隐私及第三方许可 |
| `docs/checksum.txt` | 交付文件 SHA-256 清单 |

授权文件 `amphion-license.lic` 由双方通过安全渠道单独流转，不在 SDK ZIP 中。

## 2. 环境要求

| 项目 | 要求 |
| --- | --- |
| DevEco Studio | 5.x |
| HarmonyOS SDK | 5.x，Stage 模型 |
| 设备 API | API 12 或更高版本 |
| ABI | 仅 `arm64-v8a` 真机，不提供 x86_64 模拟器 native 库 |
| 麦克风 | 宿主申请权限并使用 `AudioCapturer` 采集；SDK 本身不申请权限 |
| 设备 SN | 按 SN 签发时，宿主需具备系统权限或通过系统能力取得同一标识 |

## 3. 引入 HAR

将 `har/amphion_dingqiao.har` 复制到宿主工程（例如 `libs/`），只声明这一项依赖：

```json5
{
  "dependencies": {
    "amphion_dingqiao": "file:./libs/amphion_dingqiao.har"
  }
}
```

随后运行 `ohpm install`。该 HAR 内部依赖均使用包内相对路径，不需要再导入
`amphion_asr`、`amphion_police` 或 `sherpa_onnx`。

## 4. 最小调用流程

```ts
import {
  AudioInfo,
  CreateEngineParams,
  LicenseDeviceIdProvider,
  SpeechRecognitionEngine,
  SpeechRecognizeSdk,
  StartParams
} from 'amphion_dingqiao';

class HostDeviceIdProvider implements LicenseDeviceIdProvider {
  getDeviceSerial(_context: Context): string | undefined {
    return readStableDeviceSnFromHost();
  }
}

SpeechRecognizeSdk.init(context, new HostDeviceIdProvider());
SpeechRecognizeSdk.setWorkPath(`${context.filesDir}/dingqiao_asr`);

let engine: SpeechRecognitionEngine | undefined;
SpeechRecognizeSdk.setLicense(licenseAbsolutePath, {
  onResult: () => {
    SpeechRecognizeSdk.prepareRuntime({
      onReady: () => {
        SpeechRecognizeSdk.createEngineAsync(new CreateEngineParams(), {
          onSuccess: (createdEngine) => {
            engine = createdEngine;
            createdEngine.setListener(listener);

            const start = new StartParams();
            start.sessionId = 'session-1';
            start.audioInfo = new AudioInfo();
            createdEngine.startListening(start);
            // onStart 后，连续写入按时间顺序排列的 640 字节 PCM 帧。
            createdEngine.writeAudio(start.sessionId, pcmFrame640Bytes);
            createdEngine.finish(start.sessionId);
          },
          onError: (code, message) => {}
        });
      },
      onError: (code, message) => {}
    });
  },
  onError: (code, message) => {}
});
```

`setLicense()` 只完成本地验权与缓存，不拉起 Runtime；`prepareRuntime()` 不加载模型；
首次 `createEngineAsync()` 才加载识别模型。同配置再次创建时复用已加载模型。

## 5. 生命周期和内存控制

| 层级 | 加载接口 | 卸载接口 | 说明 |
| --- | --- | --- | --- |
| License | `setLicense()` | 重新设置授权 | 离线验权并缓存，不拉 Runtime、不加载模型 |
| Runtime | `prepareRuntime()` | `unloadRuntime()` | 管理运行时状态；卸载时模型跟随释放，已验证授权保留 |
| Model | `createEngineAsync()` / `createEngine()` | `unloadModel()` | 首次加载模型，同配置后续复用 |

卸载前应先 `finish()` 或 `cancel()` 活跃会话，再调用 `engine.shutdown()`。随后按需要调用：

```ts
engine?.shutdown();
engine = undefined;

SpeechRecognizeSdk.unloadModel();   // 保留 Runtime 与已验证授权
// 或
SpeechRecognizeSdk.unloadRuntime(); // 模型跟随释放，保留已验证授权
```

`unloadRuntime()` 后重新使用时，从 `prepareRuntime()` 开始即可。接口返回后操作系统回收物理页
可能延后，因此 RSS 不保证立即回到最低值。

## 6. 授权接入

SDK 在本地校验 ECDSA 签名、ASR 能力、有效期、维护期、SDK 主版本、设备白名单，以及
license 中可选的宿主签名证书 SHA-256。宿主证书摘要由 SDK 从当前应用签名信息读取；若 license
声明了证书绑定但运行时无法取得摘要，校验会失败，不会跳过。

设备白名单使用 `LicenseDeviceIdProvider` 返回值。正式系统宿主通常注入硬件 SN；普通三方 App
通常没有 `ohos.permission.sec.ACCESS_UDID`，不能用 ODID 去匹配按 SN 签发的 license。
签发清单和运行时必须使用同一种标识，否则返回 `1002200033`。

## 7. 音频输入

| 项目 | 要求 |
| --- | --- |
| 编码 | PCM S16LE |
| 采样率 | 16000 Hz |
| 位深 / 声道 | 16 bit / 单声道 |
| 帧长 | **严格 640 字节（20 ms）** |

音频帧必须连续、按时间顺序写入，不得重复、跳帧或并发乱序。SDK 不接受 1280 字节帧。
采集结束必须调用 `finish()`，以便模型处理尾部缓存并输出 final；取消时调用 `cancel()`。

## 8. 回调和并发约束

- 部分参数错误、缓存命中和状态回调可以在调用栈内同步发生；模型冷加载等路径为异步回调。
- 不要假设回调一定在 UI 线程；更新 UI 时由宿主切换到自己的 UI 调度器。
- 建议在同一个 ArkTS 事件执行器上串行调用同一 engine，回调代码应允许同步重入。
- 不要在 `createEngineAsync()` 或会话仍在执行时并发调用卸载接口。
- 一个 `SpeechRecognitionEngine` 同时只允许一个活跃会话。

## 9. 模型内容与体积

HAR 是自包含包，包含中英 `zh-en`、粤英 `yue-en`、中英标点、中文 ITN FST、Silero VAD、
警务热词/车牌/派出所增强资源、声纹模型以及 arm64 native 运行时。交付文件体积是这些资产
压缩后的文件大小，不等于加载后 RSS；模型权重还可能通过 mmap 形成文件映射和共享页。

当前中文模型使用 INT8 encoder、FP32 decoder、INT8 joiner；FP32 decoder 用于避免 INT8
decoder 的漏 token 问题。标点模型独立于 ASR transducer，用于为最终文本恢复标点。

## 10. 校验交付包

在解压后的交付根目录执行：

```bash
shasum -a 256 -c docs/checksum.txt
```

全部显示 `OK` 后再集成。常见错误及现场日志采集方式见 `TROUBLESHOOTING.md`。
