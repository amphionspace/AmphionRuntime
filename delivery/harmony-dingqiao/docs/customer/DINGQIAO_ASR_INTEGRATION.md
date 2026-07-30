# Amphion HarmonyOS 离线 ASR SDK 集成指南

## 1. 交付范围

本 SDK-only 包只交付中英离线 ASR：

| 路径 | 内容 |
| --- | --- |
| `../har/amphion_dingqiao.har` | 自包含 ASR SDK，内置中英模型、声纹、标点、ITN 和 VAD |
| `../license/amphion-license.lic` | 四个自然月体验授权，不绑定包名、证书、设备或 SDK 主版本 |
| `ASR_SDK_API_HARMONY.md` | 公共 API、参数、错误码和回调契约 |
| `LICENSE.md` | 离线授权接入 |
| `ASR_LIFECYCLE_ASSURANCE_20260716.md` | 历史问题闭环、时序图和验证边界 |
| `checksum.txt` | 交付文件 SHA-256 |

包内不含 Demo HAP、粤英模型、独立 TTS SDK 或 TTS 模型。体验授权已随包提供。

## 2. 添加依赖

将 `amphion_dingqiao.har` 放入宿主模块的 `libs/`，并在该模块的 `oh-package.json5` 声明：

```json5
{
  "dependencies": {
    "amphion_dingqiao": "file:./libs/amphion_dingqiao.har"
  }
}
```

该 HAR 已包含所需的 ASR core 和 native runtime，不需要再声明其他 Amphion HAR。为保持既有接口兼容，模块名仍为 `amphion_dingqiao`；本交付不包含行业专用文本增强资源或后处理。

## 3. 初始化与授权

```typescript
import { CreateEngineParams, SpeechRecognizeSdk } from 'amphion_dingqiao';

SpeechRecognizeSdk.init(context);
SpeechRecognizeSdk.setWorkPath(`${context.filesDir}/amphion_asr_work`);
SpeechRecognizeSdk.setLicense(licenseAbsolutePath, {
  onResult: () => {
    SpeechRecognizeSdk.prepareRuntime({
      onReady: () => {
        SpeechRecognizeSdk.createEngineAsync(new CreateEngineParams(), {
          onSuccess: (engine) => { /* 保存并复用 engine */ },
          onError: (code, message) => { /* 记录 code 和 message */ }
        });
      },
      onError: (code, message) => { /* 记录 code 和 message */ }
    });
  },
  onError: (code, message) => { /* 记录 code 和 message */ }
});
```

顺序必须是 `init -> setWorkPath -> setLicense -> prepareRuntime -> createEngine`。`setLicense` 只做离线验权；`prepareRuntime` 不加载模型；首次 `createEngineAsync` 才加载模型。

## 4. 设置监听器

```typescript
engine.setListener({
  onStart: (sessionId) => {},
  onEvent: (sessionId, eventCode, message) => {},
  onResult: (sessionId, result) => {
    if (result.isFinal && result.isLast) {
      // 整个 session 的最后一条结果。
    }
  },
  onComplete: (sessionId) => {},
  onError: (sessionId, code, message) => {}
});
```

`onStart(sessionId)` 表示该 session 已发布且可以同步使用。业务可以在 `onStart` 调用栈内立即执行 `writeAudio`、`finish` 或 `cancel`。

## 5. 开始、写入与结束

```typescript
import { AudioInfo, StartParams } from 'amphion_dingqiao';

const start = new StartParams();
start.sessionId = createUniqueSessionId();
start.audioInfo = new AudioInfo();
start.audioInfo.sampleRate = 16000;
start.audioInfo.sampleBit = 16;
start.audioInfo.soundChannel = 1;
start.extraParams = {
  enablePartialResult: true,
  enablePoliceEnhancement: true,
  vadBegin: 1000,
  vadEnd: 1000
};

engine.startListening(start);
engine.writeAudio(start.sessionId, pcmFrame640Bytes);
engine.finish(start.sessionId);
```

音频格式固定为 16 kHz、16-bit、单声道 PCM，小端序。标准实时帧为 20 ms，即 640 字节。

`maxAudioDuration` 缺省、非正数、非有限或不可解析时不启用自动上限；显式正有限值按调用值
生效，并限制在不超过 28,800,000 ms。显式配置并命中 `vadBegin` 或 `maxAudioDuration`
时，SDK 才允许自动结束。

`enablePoliceEnhancement` 是会话级布尔参数，默认 `true`。显式传 `false` 时 final 返回原始
ASR 文本，不执行警务术语、车牌和派出所归一化；不会触发引擎重建，也不改变生命周期回调顺序。

## 6. 生命周期契约

- `isFinal=true` 表示一句话或 endpoint 的最终结果；`isLast=true` 才表示整个 session 的最后结果。
- 普通连续识别中，调用 `finish(sessionId)` 前不得出现 `isLast=true`。
- 正常 session 恰好一次 `isLast=true`，随后恰好一次 `onComplete`。
- `cancel(sessionId)` 生效后不得新增 final 或 complete。
- 每次启动使用唯一 `sessionId`。旧 session 的迟到调用或回调不会终止、污染或借用新 sessionId。
- 启用声纹校验后，SDK 优先使用严格筛选的有效语音评分。严格语音短于 `minSegSec`，但 final
  已有非空 ASR text/token 且当前句实际 PCM 达到门槛时，SDK 使用当前句真实 PCM 回退评分。
  没有 ASR 语音证据、实际 PCM 仍短于门槛或空 terminal final 时，`speakerSimilarity` 可以省略。

## 7. 释放与重新加载

结束或取消所有活跃 session 后：

1. 对持有的 engine 调用 `shutdown()`。
2. 仅释放模型时调用 `SpeechRecognizeSdk.unloadModel()`。
3. 同时释放 runtime 时调用 `SpeechRecognizeSdk.unloadRuntime()`。
4. 再次使用时执行 `prepareRuntime -> createEngine`；已验证授权仍保留。

不要在活跃 session 中卸载模型或 runtime。业务空闲卸载后的首次 `onStart` 仍具备与冷启动相同的同步可用性保证。

## 8. 验收建议

集成后至少验证：冷启动首轮、`onStart` 内同步写入缓存、连续多句、显式 finish、cancel 后立即重启、回调内重启、重复 finish、`vadBegin` 真实语音/纯静音、显式最大时长、声纹门槛上下和卸载后重载。生命周期验收只判断状态、顺序和归属；识别字错率与声纹相似度精度应使用独立标注集评测。
