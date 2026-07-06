# 鼎桥 HarmonyOS 语音识别 SDK 集成指南

交付前置资料清单见 [`../../docs/dingqiao-offline-license.md`](../../docs/dingqiao-offline-license.md)。组包前需确认鼎桥提供的设备 SN 清单、授权功能范围、维护期和 license 固定路径；bundleName 和签名证书指纹仅作可选记录。

## 交付文件

| 路径 | 说明 |
| --- | --- |
| `har/amphion_dingqiao.har` | ASR SDK（**自包含**：已内置 amphion_asr / amphion_police / sherpa_onnx，客户只需集成这一个）|
| `har/amphion_tts.har` | TTS SDK（自包含，如需）|
| `demo/dingqiao-demo.hap` | 验收 Demo |
| `models/eres2net.onnx` | 声纹模型，放入 `setWorkPath` 指定目录 |
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
  SpeechRecognizeSdk,
  StartParams
} from 'amphion_dingqiao';

SpeechRecognizeSdk.init(context);
SpeechRecognizeSdk.setWorkPath(`${context.filesDir}/dingqiao_work`);

const engine = SpeechRecognizeSdk.createEngine(new CreateEngineParams());
engine.setListener({
  onResult: (sessionId, result) => {},
  onComplete: (sessionId) => {},
  onError: (sessionId, code, message) => {}
});

const start = new StartParams();
start.sessionId = 'session-1';
start.audioInfo = new AudioInfo();
engine.startListening(start);
engine.writeAudio(start.sessionId, pcmFrame640Bytes);
engine.finish(start.sessionId);
```

## 离线授权

授权文件固定为 `amphion-license.lic`。如果 license 启用了设备 SN 白名单，宿主或交付适配层需要通过 `deviceIdProvider` 注入本机 SN；该 SN 必须与交付给我方签发 license 的 SN 清单一致。

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

如果由鼎桥业务 App 自行读取 SN，只需按上面的接口注入；如果由我方交付适配层实现，需要鼎桥提供读取 SN 的系统 API、权限要求和失败行为。

## 音频要求

| 项目 | 值 |
| --- | --- |
| 格式 | PCM S16LE |
| 采样率 | 16000 Hz |
| 声道 | 1 |
| 帧长 | 640 字节，即 20 ms |

## final 文本

中间结果为 ASR 原文；最终结果会经过警务增强（术语、车牌、派出所）。如需关闭某类增强，可在 `CreateEngineParams.extraParams` 中设置：

```ts
params.extraParams['plateNormalizeEnabled'] = false;
params.extraParams['stationNormalizeEnabled'] = false;
params.extraParams['termsNormalizeEnabled'] = false;
```

## 声纹

```ts
SpeechRecognizeSdk.registerVoiceprint({
  voiceprintId: 'user-1',
  audioPaths: [path1, path2, path3]
});
```

首版接口已稳定；native 声纹 embedding 接入后无需修改客户调用代码。

## TTS

离线 TTS 为独立 SDK（模块名 `amphion_tts`），通过 `import { TextToSpeechSdk } from 'amphion_tts'` 使用，API 文档见 `tts/harmony/docs/INTEGRATION.md`。

TTS 模型按 `rawfile/amphion-tts/<voiceId>/` 打包，默认 voiceId 为 `kokoro-zh-en`，目录需包含 `model.onnx`、`voices.bin`、`tokens.txt`、`espeak-ng-data/`，中英混合还需要 `lexicon-us-en.txt`、`lexicon-zh.txt` 以及可选 `date-zh.fst`、`phone-zh.fst`、`number-zh.fst`。可用 `bash tts/tools/harmony/pack_harmony_tts_assets.sh` 同步。
