# 鼎桥 HarmonyOS 语音识别 SDK 集成指南

交付前置资料清单见 [`../../docs/dingqiao-offline-license.md`](../../docs/dingqiao-offline-license.md)。组包前需确认鼎桥提供的设备 SN 清单、bundleName、签名证书指纹、授权功能范围、维护期和 license 固定路径。

## 交付文件

| 路径 | 说明 |
| --- | --- |
| `har/` | 鼎桥 fat HAR 或三个分层 HAR |
| `demo/dingqiao-demo.hap` | 验收 Demo |
| `models/eres2net.onnx` | 声纹模型，放入 `setWorkPath` 指定目录 |
| `docs/` | 接口、授权、NOTICE 与集成说明 |
| `amphion-license.lic` | 授权文件，单独签发 |

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
