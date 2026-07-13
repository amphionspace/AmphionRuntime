# 鼎桥 HarmonyOS 语音识别 SDK 集成指南

交付前置资料清单见 [`../../docs/dingqiao-offline-license.md`](../../docs/dingqiao-offline-license.md)。组包前需确认鼎桥提供的设备 SN 清单、授权功能范围、维护期和 license 固定路径；bundleName 和签名证书指纹仅作可选记录。

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
SpeechRecognizeSdk.setWorkPath(`${context.filesDir}/dingqiao_work`);

let engine: SpeechRecognitionEngine | undefined;
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
```

## 离线授权

授权文件固定为 `amphion-license.lic`。如果 license 启用了设备白名单，宿主或交付适配层需要通过 `deviceIdProvider` 注入稳定设备标识；该标识必须与交付给我方签发 license 的清单一致。系统/预置宿主通常注入硬件 SN；普通 Demo 可注入 ODID，但不能用 ODID 去匹配按 SN 签发的 license。

**交付入口（推荐）**：鼎桥侧通过 `SpeechRecognizeSdk.setLicense(licensePath, callback)` 激活 license（异步 ECDSA 验签 + SN 白名单，需先 `init(context)`）；激活成功且语言、热词配置确定后立即调用 `createEngineAsync` 并长期持有 engine，可以把冷加载隐藏在业务首页初始化阶段。不要在 license 激活前预加载，因为重新设置 license 会释放 Runtime。`getLicenseInfo()` 返回授权状态 `LicenseInfo`（`status` / `expireTime` / `remainingDays` / `authorizedFeatures`）。

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
    // 授权成功，可继续 createEngine
    const info = SpeechRecognizeSdk.getLicenseInfo();
    // info.status / info.expireTime / info.remainingDays / info.authorizedFeatures
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

`eres2net.onnx` 已内置在 `amphion_dingqiao.har`。`prepareRuntime()` 会幂等准备工作目录文件；注册和启用声纹识别时也会重试，不需要宿主分发或导入模型。

普通 final 声纹校验会在 ASR 启动后后台加载 extractor，不阻塞音频写入和中间识别；如果加载尚未完成，只在 final 前等待。Speaker VAD 需要流式声纹打分，因此冷态启动会同步等 extractor。宿主无需为普通声纹校验调用 `preloadVoiceprintModel()`；该同步接口仅用于主动前置 final 等待或 Speaker VAD 冷启动成本。

```ts
SpeechRecognizeSdk.registerVoiceprint({
  voiceprintId: 'user-1',
  samplePaths: [path1]
});
```

至少需要 1 条 3~8 秒样本，不限制样本上限；多条样本仅用于提升 embedding 稳定性。模型文件和注册后的 embedding 是持久数据，`unloadModel()` 只卸载内存中的声纹 extractor，不删除它们。

## TTS

离线 TTS 为独立 SDK（依赖名 `amphion_tts`，HAR 包名 `sdk`），通过 `import { TextToSpeechSdk } from 'sdk'` 使用，API 文档见 [`tts/harmony/docs/API.md`](../../../tts/harmony/docs/API.md)。

TTS 模型打包在 rawfile 目录 `lits-models/tts/transsion_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0` 下；`manifest.json` 的 `model_id` 必须为 `transsion_lits_en_zh_vocos24k_streaming_proto_external_loop`。支持的 voiceId 为 `lits-female-01`、`lits-female-02`。目录需包含以下运行时文件：`manifest.json`、`lits_hidden_encoder.onnx`、`lits_stream_condition_chunk.onnx`、`lits_stream_condition_final.onnx`、`lits_stream_decoder_step.onnx`、`vocos_vocoder.onnx`、`chinese_lexicon.txt`（以及 `cmudict.txt`、`supplement_lexicon.json`、`frontend_rules.json`、`zh_en_symbols.json`、`pinyin_to_tokens.json`、`arpabet_to_tokens.json` 等前端资源）。SDK 已内置该模型，不传外部目录时会自动解包，无需额外同步脚本。
