# 鼎桥 HarmonyOS 语音识别 SDK 集成指南

交付前置资料清单见 [`../../docs/dingqiao-offline-license.md`](../../docs/dingqiao-offline-license.md)。组包前需确认鼎桥提供的设备 SN 清单、授权功能范围、维护期和 license 固定路径；bundleName 和签名证书指纹仅作可选记录。

完整 API、回调、参数、错误码和新增生命周期控制契约见 [`语音识别SDK接口.md`](语音识别SDK接口.md)。历史生命周期问题的修复保证、时序图和脱敏真机验证摘要见交付包内 `ASR_LIFECYCLE_ASSURANCE_20260716.md`。

## 交付文件

| 路径 | 说明 |
| --- | --- |
| `har/amphion_dingqiao.har` | ASR SDK（**自包含**：已内置 amphion_asr / amphion_police / sherpa_onnx，客户只需集成这一个）|
| `har/amphion_tts.har` | TTS SDK（自包含，如需）|
| `demo/dingqiao-demo.hap` | 验收 Demo |
| `docs/` | 接口、授权、NOTICE 与集成说明 |
| `amphion-license.lic` | 授权文件，单独签发 |

## 依赖配置

ASR SDK 为**自包含 HAR**——ASR 核心、警务能力层与 sherpa_onnx 运行时依赖都已打进 `amphion_dingqiao.har` 内部（`file:./` 相对路径）。客户**只需声明这一个依赖**，无需再单独集成 amphion_asr / sherpa_onnx：

```json5
{
  "dependencies": {
    "amphion_dingqiao": "file:./libs/amphion_dingqiao.har"
  }
}
```

把交付包 `har/amphion_dingqiao.har` 放到宿主工程（例如 `./libs/`），路径按实际调整。为**纯本地 `file:` 依赖**，`ohpm install` 与后续 HAP 编译**全程无需联网、无需连 ohpm 公共仓库**，适配内网/隔离构建环境。

> 只用 TTS 时同理声明一个自包含依赖 `"amphion_tts": "file:./libs/amphion_tts.har"`（HAR 包名为 `sdk`，`import { TextToSpeechSdk } from 'sdk'`）。
> ASR 的授权、识别等能力统一通过 `amphion_dingqiao` 的 `SpeechRecognizeSdk` 使用（含 `setLicense`），无需从 amphion_asr 单独导入。

## 主流程

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
    return readStableDeviceIdFromHost();
  }
}

SpeechRecognizeSdk.init(context, new HostDeviceIdProvider());
SpeechRecognizeSdk.setWorkPath(`${context.filesDir}/amphion_asr_work`);

let engine: SpeechRecognitionEngine | undefined;
SpeechRecognizeSdk.setLicense(licenseAbsolutePath, {
  onResult: () => {
    SpeechRecognizeSdk.prepareRuntime({
      onReady: () => {
        SpeechRecognizeSdk.createEngineAsync(new CreateEngineParams(), {
          onSuccess: (createdEngine) => {
            engine = createdEngine;
            createdEngine.setListener({
              onResult: (sessionId, result) => {},
              onComplete: (sessionId) => {},
              onError: (sessionId, code, message) => {}
            });

            const start = new StartParams();
            start.sessionId = 'session-1';
            start.audioInfo = new AudioInfo();
            createdEngine.startListening(start);
            createdEngine.writeAudio(start.sessionId, pcmFrame640Bytes);
            createdEngine.finish(start.sessionId);
          },
          onError: (errorCode, message) => {}
        });
      },
      onError: (errorCode, message) => {}
    });
  },
  onError: (errorCode, message) => {}
});
```

`onStart(sessionId)` 表示对应 session 已经可用。宿主若在模型冷加载期间缓存了录音数据，可以在
`onStart` 回调内直接同步写入这些 640 字节 PCM 帧，无需额外延时；收到 `onStart` 前不要写入。

`StartParams.extraParams['maxAudioDuration']` 缺省时不启用自动上限。只有显式传入正有限数字或
可解析为正有限数字的非空字符串才启用，按调用值生效且上限为 28800000 ms；非正数或非法值
按未启用处理。
`StartParams.extraParams['enablePoliceEnhancement']` 为会话级布尔参数，默认 `true`。显式传
`false` 时该会话的 final 返回原始 ASR 文本，不执行警务术语、车牌和派出所归一化；该参数
不触发引擎重建，也不改变 partial、`isFinal`、`isLast` 或 `onComplete` 时序。
每个底层回调绑定其创建时的 session，业务在回调内取消旧 session 并立即启动新 session 时，
旧 session 的迟到结果不会改用新 sessionId 发送。

三层状态彼此独立：

| 层级 | 加载接口 | 卸载接口 | 说明 |
| --- | --- | --- | --- |
| License | `setLicense()` | 重新设置授权 | 完整离线验权并缓存，不拉 Runtime、不加载模型 |
| Runtime | `prepareRuntime()` | `unloadRuntime()` | 管理运行时框架；卸载时模型跟随释放，授权保留 |
| Model | `createEngineAsync()` / `createEngine()` | `unloadModel()` | 模型未加载时加载，同配置已加载时复用 |

调用任一卸载接口前，都应先结束或取消活跃会话，并对持有的 engine 调用 `shutdown()`。随后二选一：调用 `unloadModel()` 保留 Runtime，或调用 `unloadRuntime()` 让模型跟随 Runtime 一并释放。`unloadRuntime()` 不清除已验证授权，后续可直接 `prepareRuntime()`，无需再次 `setLicense()`。

## 离线授权

授权文件固定为 `amphion-license.lic`。如果 license 启用了设备白名单，宿主或交付适配层需要通过 `deviceIdProvider` 注入稳定设备标识；该标识必须与交付给我方签发 license 的清单一致。系统/预置宿主通常注入硬件 SN；普通 Demo 可注入 ODID，但不能用 ODID 去匹配按 SN 签发的 license。

**交付入口（推荐）**：鼎桥侧先通过 `SpeechRecognizeSdk.setLicense(licensePath, callback)` 完成离线完整验权和缓存（需先 `init(context)`）；授权成功后调用 `prepareRuntime()`，收到 `onReady()` 后再调用 `createEngineAsync()`。`setLicense()` 本身不会拉 Runtime 或加载模型。语言、热词配置确定后可提前创建并长期持有 engine，以隐藏模型冷加载。重新设置有效授权会使旧 Runtime / 模型失效，需要再次 `prepareRuntime()`。`getLicenseInfo()` 返回授权状态 `LicenseInfo`（`status` / `expireTime` / `remainingDays` / `authorizedFeatures`）。

```ts
import deviceInfo from '@ohos.deviceInfo';
import { LicenseActivationResult, LicenseDeviceIdProvider, SpeechRecognizeSdk } from 'amphion_dingqiao';

class DeviceIdProvider implements LicenseDeviceIdProvider {
  getDeviceSerial(_context: Context): string | undefined {
    const sn = deviceInfo.serial;
    return sn.length > 0 ? sn : undefined;
  }
}

SpeechRecognizeSdk.init(context, new DeviceIdProvider());
SpeechRecognizeSdk.setLicense(`${context.filesDir}/amphion-license.lic`, {
  onResult: (result: LicenseActivationResult) => {
    // 授权成功：此时仅缓存授权，Runtime 和模型尚未加载。
    const info = SpeechRecognizeSdk.getLicenseInfo();
    // info.status / info.expireTime / info.remainingDays / info.authorizedFeatures
    SpeechRecognizeSdk.prepareRuntime({
      onReady: () => {
        // Runtime 就绪，可继续 createEngine/createEngineAsync。
      },
      onError: (errorCode, message) => {}
    });
  },
  onError: (errorCode, message) => {}
});
```

如需直接使用底层 `amphion_asr` 授权入口（例如自定义 `deviceIdProvider` 注入 SN）：

```ts
import { AmphionOptions, AmphionRuntime, LicenseEnforcement } from 'amphion_asr';

const licenseOptions = new AmphionOptions();
licenseOptions.licenseAssetName = 'amphion-license.lic';
licenseOptions.licenseEnforcement = LicenseEnforcement.ENFORCE;
licenseOptions.deviceIdProvider = {
  getDeviceSerial: (_context): string | undefined => {
    return 'DEVICE-SN-FROM-DINGQIAO';
  }
};

AmphionRuntime.init(context, licenseOptions);
```

如果由鼎桥业务 App 自行读取 SN，只需按上面的接口注入；读取 `deviceInfo.serial` 需要 `ohos.permission.sec.ACCESS_UDID`。如果由我方交付适配层实现，需要鼎桥提供读取 SN 的系统 API、权限要求和失败行为。

## 音频要求

| 项目 | 值 |
| --- | --- |
| 格式 | PCM S16LE |
| 采样率 | 16000 Hz |
| 声道 | 1 |
| 帧长 | 640 字节，即 20 ms |

## final 文本

中间结果为 ASR 原文；最终结果会经过与 Android 鼎桥一致的 V2 警务增强（术语 → 全国车牌 → 派出所），并默认注入同一套警务预设热词，热词分数为 `3.0`。如需关闭某类增强，可在 `CreateEngineParams.extraParams` 中设置：

```ts
params.extraParams['plateNormalizeEnabled'] = false;
params.extraParams['stationNormalizeEnabled'] = false;
params.extraParams['termsNormalizeEnabled'] = false;
```

## 声纹

`eres2net.onnx` 已内置在 `amphion_dingqiao.har`，SDK 直接从包内加载；`prepareRuntime()` 不复制或加载该模型，不需要宿主分发或导入。

普通 final 声纹校验会在 ASR 启动后后台加载 extractor，不阻塞音频写入和中间识别；如果加载尚未完成，只在 final 前等待。Speaker VAD 需要流式声纹打分，因此冷态启动会同步等 extractor。宿主无需为普通声纹校验调用 `preloadVoiceprintModel()`；该同步接口仅用于主动前置 final 等待或 Speaker VAD 冷启动成本。

```ts
SpeechRecognizeSdk.registerVoiceprint({
  voiceprintId: 'user-1',
  samplePaths: [path1]
});
```

至少需要 1 条 3~8 秒标准 WAV 样本，不限制样本上限；多条样本仅用于提升 embedding 稳定性。SDK 不限制已注册声纹条数，持久化数量只受工作目录可用空间约束。模型文件和注册后的 embedding 是持久数据，`unloadModel()` 只卸载内存中的声纹 extractor，不删除它们。

## TTS

离线 TTS 为独立 SDK（依赖名 `amphion_tts`，HAR 包名 `sdk`），通过 `import { TextToSpeechSdk } from 'sdk'` 使用，API 文档见 [`tts/harmony/docs/API.md`](../../../tts/harmony/docs/API.md)。

TTS 模型打包在 rawfile 目录 `lits-models/tts/transsion_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0` 下；`manifest.json` 的 `model_id` 必须为 `transsion_lits_en_zh_vocos24k_streaming_proto_external_loop`。支持的 voiceId 为 `lits-female-01`、`lits-female-02`。目录需包含以下运行时文件：`manifest.json`、`lits_hidden_encoder.onnx`、`lits_stream_condition_chunk.onnx`、`lits_stream_condition_final.onnx`、`lits_stream_decoder_step.onnx`、`vocos_vocoder.onnx`、`chinese_lexicon.txt`（以及 `cmudict.txt`、`supplement_lexicon.json`、`frontend_rules.json`、`zh_en_symbols.json`、`pinyin_to_tokens.json`、`arpabet_to_tokens.json` 等前端资源）。SDK 已内置该模型，不传外部目录时会自动解包，无需额外同步脚本。
