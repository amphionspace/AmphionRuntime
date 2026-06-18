# meta.json 与 sentences.json Schema

本文档定义评估数据收集涉及的两个 JSON 文件 schema：客户端写入 / 服务端落盘 / 后台脚本消费三方按此对齐。

## 一、meta.json（每条录音一份）

### 1.1 完整字段

| 字段 | 类型 | 必选 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| schema_version | int | 是 | 客户端常量 | 当前 1；服务端按 SUPPORTED_SCHEMA_VERSIONS 校验 |
| finalized | bool | 是 | 客户端 | true 表示这条录音已完成；后台脚本应跳过 finalized=false |
| recording_id | string(UUIDv4) | 是 | 客户端生成 | 全局唯一，幂等键 |
| attempt_index | int | 是 | 客户端 | 同一 sentence 下当前 tester 的第几次尝试，从 1 起 |
| sentence_id | string | 是 | 测试集 | 引用 sentences.json 中的 sentence.id |
| category_id | string | 是 | 测试集 | 引用 sentences.json 中的 category.id，便于聚合 |
| reference_text | string | 是 | 测试集 | sentence.text 的副本，避免后台 WER 计算被测试集版本漂移影响 |
| tester_id | string | 是 | TesterPrefs | sha1(nickname)[:12]，匿名但跨设备稳定 |
| tester_nickname | string | 是 | TesterPrefs | UI 展示用，不参与聚合 |
| device.model | string | 是 | Build.MODEL | 设备型号 |
| device.manufacturer | string | 是 | Build.MANUFACTURER | 厂商 |
| device.android_sdk | int | 是 | Build.VERSION.SDK_INT | API level |
| device.abi | string | 是 | Build.SUPPORTED_ABIS[0] | 进程 ABI |
| app_version | string | 是 | PackageManager | sample app versionName |
| sdk_version | string | 是 | AmphionRuntime.version() | AmphionRuntime SDK 语义化版本（0.2.0 起统一从这里读，旧文档里的 AsrSdk.version() 已废弃） |
| model_id | string \| null | 否 | 引擎语种 | 0.2.0 起取自 AsrLanguage 枚举名（如 ZH_EN / YUE_EN）；无现场识别时 null |
| model_version | string \| null | 否 | SDK 版本 | 0.2.0 起取自 AmphionRuntime.version()（与 sdk_version 同值，保留独立字段以兼容老 schema） |
| recorded_at | string(ISO8601 Z) | 是 | 客户端时钟 | UTC，例如 2026-05-19T10:47:00Z |
| duration_ms | int | 是 | EvalRecorder | 实际录音时长（毫秒） |
| sample_rate | int | 是 | 客户端常量 | 16000 |
| gain_db | float | 是 | EvalRecorder.gainDb | 软增益（默认 10.0，与生产链路对齐） |
| audio_source | string | 是 | MediaRecorder source 常量名 | VOICE_RECOGNITION |
| env.location | string | 是 | 测试员填 | 自由文本，例如「办公室」「高铁」 |
| env.noise_level | string | 是 | NoiseLevel enum token | unspecified / silent / low / medium / high / very_high |
| env.noise_level_db_estimate | float \| null | 否 | 预留字段 | 当前客户端不填 |
| env.notes | string | 是 | 测试员填 | 自由文本，可空字符串 |
| on_device_hypothesis | string \| null | 否 | OnDeviceTranscriber | 设备端 ASR final 文本；引擎不可用时 null |
| on_device_wer_estimate | float \| null | 否 | DeviceWerEstimator | 字符级编辑距离 / 参考长度；非权威 |
| on_device_utterance_e2e_ms | int \| null | 否（仅 schema=1，未纳入 server schema） | AmphionMetrics.utteranceE2eLatencyMs | 第一帧 PCM accept → onFinal 派发的端到端延迟；schema 升 v2 时纳入 |
| on_device_first_partial_ms | int \| null | 否（同上） | AmphionMetrics.firstPartialLatencyMs | 第一帧 PCM → 第一个 partial；本段无 partial 时 null |
| on_device_rtf | float \| null | 否（同上） | AmphionMetrics.rtf | decodeMs / utteranceMs；< 1 才能流式跟上实时 |
| on_device_native_rss_mb | int \| null | 否（同上） | AmphionMetrics.nativeRssMb | 本段结束时刻读到的 native VmRSS |
| upload | object | 是 | 客户端状态机 | 详见 1.2 |

### 1.2 upload 子对象

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| state | string | pending / uploading / uploaded / retry / failed |
| uploaded_at | string \| null | uploaded 状态时填写 ISO8601 时间戳 |
| attempts | int | 累计尝试次数（含成功） |
| last_error | string \| null | 最近一次错误的人类可读 message |
| last_attempt_at | string \| null | 最近一次尝试的 ISO8601 时间戳 |
| server_url | string \| null | 上传成功时记录的 base URL，便于回溯 |

### 1.3 不变量

1. 客户端永远写完整 schema（所有 NULL 字段也要存在）；这是为了让服务端可以严格 schema check
2. reference_text 与 sentence_id 必须同时存在；后台优先按 reference_text 算 WER
3. on_device_wer_estimate 与 on_device_hypothesis 必须同时为 null 或同时非 null
4. recorded_at 必须 UTC（带 Z 后缀）；服务端不重新格式化
5. duration_ms ≥ 0；零值合法（罕见，表示用户秒开秒关）
6. on_device_utterance_e2e_ms / on_device_first_partial_ms / on_device_rtf / on_device_native_rss_mb 当前 schema=1 阶段为「客户端单边写入字段」：客户端永远输出（值为 SDK metrics 或 null），服务端不要求字段存在。schema 升 v2 时这 4 个字段升为 NORMATIVE，并同步更新 SERVER_SPEC.md 错误码表中的 SCHEMA_MISMATCH 行

### 1.4 完整示例

```json
{
  "schema_version": 1,
  "finalized": true,
  "recording_id": "0bf8b3d8-44f3-4f15-8e60-7b1d2cd0b3aa",
  "attempt_index": 1,
  "sentence_id": "zh_en_mixed_005",
  "category_id": "zh_en_mixed",
  "reference_text": "我们的 deadline 是下周五五月二十二号。",
  "tester_id": "522b5a4b5c0a",
  "tester_nickname": "Alice (QA)",
  "device": {
    "model": "Pixel 7",
    "manufacturer": "Google",
    "android_sdk": 34,
    "abi": "arm64-v8a"
  },
  "app_version": "0.2.0",
  "sdk_version": "0.2.0",
  "model_id": "ZH_EN",
  "model_version": "0.2.0",
  "recorded_at": "2026-05-19T10:47:00Z",
  "duration_ms": 4321,
  "sample_rate": 16000,
  "gain_db": 10.0,
  "audio_source": "VOICE_RECOGNITION",
  "env": {
    "location": "办公室",
    "noise_level": "low",
    "noise_level_db_estimate": null,
    "notes": "空调风扇背景"
  },
  "on_device_hypothesis": "我们的 deadline 是下周五五月二十二号",
  "on_device_wer_estimate": 0.083,
  "on_device_utterance_e2e_ms": 320,
  "on_device_first_partial_ms": 180,
  "on_device_rtf": 0.42,
  "on_device_native_rss_mb": 168,
  "upload": {
    "state": "uploaded",
    "uploaded_at": "2026-05-19T10:47:05Z",
    "attempts": 1,
    "last_error": null,
    "last_attempt_at": "2026-05-19T10:47:05Z",
    "server_url": "https://eval.example.com"
  }
}
```

## 二、sentences.json（测试集 manifest，每个 APK / 推送包一份）

### 2.1 顶层结构

| 字段 | 类型 | 必选 | 说明 |
| --- | --- | --- | --- |
| schema_version | int | 是 | 当前 1 |
| manifest_version | string | 是 | 测试集自身的版本号，例如 1.0.0 |
| lang | string | 是 | 语言标识，与模型 manifest.lang 对齐：zh-en / yue-en / en / zh |
| description | string | 否 | 自由文本，便于人类辨认 |
| categories | array | 是 | 分类数组，详见 2.2 |

### 2.2 categories[i] 结构

| 字段 | 类型 | 必选 | 说明 |
| --- | --- | --- | --- |
| id | string | 是 | 分类 id，建议小写蛇形（daily / numbers / zh_en_mixed） |
| label | string | 是 | UI 展示标题 |
| description | string | 否 | UI 展示副标题 |
| sentences | array | 是 | 句子数组 |

### 2.3 sentences[i] 结构

| 字段 | 类型 | 必选 | 说明 |
| --- | --- | --- | --- |
| id | string | 是 | 句子 id，全局唯一；建议 <category>_<3 位序号>，如 zh_en_mixed_005 |
| text | string | 是 | 参考文本；中英混合 / 标点全保留 |

### 2.4 加载优先级

客户端 SentenceRepository 按以下顺序加载：

1. <externalFilesDir>/asr-eval-set/sentences.json（adb push 外部覆盖）
2. assets/eval-set/sentences.json（APK 内置 fallback）

外部 manifest 加载失败时自动 fallback 内置版本。

### 2.5 演进规则

- 新增 sentence：直接追加，sentence.id 必须保持唯一
- 删除 sentence：不要物理删除（否则历史录音会找不到对应 reference_text）；改用单独的「deprecated」标记字段（未来 schema_version=2 加）
- 改 sentence.text：禁止直接改；改 text 等于产生新 sentence，应分配新 id

### 2.6 自由文本（custom sentence）

测试员可在 app 内通过「+ 自由录音」入口录任意内容（先录后校对），reference 不在 sentences.json 中。约定如下：

| 字段 | 取值 | 说明 |
| --- | --- | --- |
| sentence_id | `custom_<sha1(normalize(text))[:12]>` | 同一 text 在不同设备 / tester 派生同一 id，便于跨人聚合 |
| category_id | `custom` | 与内置 6 类隔离，后台 by_category 报告天然分组 |
| reference_text | 用户输入的原 text（已 normalize） | 与 sentence_id 一一对应；改 text 即产生新 sentence |

normalize 规则：

1. 去首尾空白
2. 合并多个连续空格为单个

不做大小写折叠（英文大小写在 ASR 里可能有真实差异），也不去标点（中文标点会影响 ITN / WER）。

后台脚本对待 custom 与内置完全一致：reference_text 仍是唯一权威 ref；sentence_id 仅做聚合键。eval_wer.py 的 by_category 报告会单独列出 `custom` 一栏，可对比内置集与真实业务场景的 WER 差距。

## 三、文件路径约定

```
Android 客户端：
  <externalFilesDir>/asr-eval/
    _temp/<recording_id>/                 # 写入中
    <tester_id>/<sentence_id>/<recording_id>/
      audio.wav
      meta.json
      hypothesis.txt                       # 可选
  <externalFilesDir>/asr-eval-set/sentences.json     # 外部 manifest 覆盖
  <externalFilesDir>/asr-eval-export/eval_<tester>_<ts>.zip  # ZipExporter 输出

服务端（参考实现）：
  /var/lib/amphion-eval/
    <tester_id>/<sentence_id>/<recording_id>/
      audio.wav
      meta.json
      hypothesis.txt
      _received_at
```

两边的目录结构刻意保持镜像，让 asr/tools/eval_wer.py 用同一份遍历代码处理 zip 与服务端落盘。
