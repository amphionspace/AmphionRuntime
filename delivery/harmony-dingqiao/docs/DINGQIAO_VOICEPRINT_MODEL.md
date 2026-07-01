# 声纹模型说明（eres2net.onnx）— 纯血鸿蒙

面向鼎桥集成与 Demo 验收。声纹（说话人）能力使用单个模型文件 `eres2net.onnx`（约 38 MB）。

> **与 Android 的差异**：Android 版把 `eres2net.onnx` 内置在 AAR 中、运行时自动解包；**纯血鸿蒙版当前不内置**该模型，需由**宿主 / Demo 将 `eres2net.onnx` 放入 `SpeechRecognizeSdk.setWorkPath(...)` 指定目录**后方可使用声纹。ASR 识别本身不依赖此模型，缺失不影响识别。

---

## 1. 与 ASR 模型的区别

| 类型 | 是否随 HAR 内置 | 是否需要放置 |
|------|-----------------|--------------|
| ASR 声学模型（识别用） | 是（内置于 `amphion_asr.har`） | 否 |
| 声纹模型 `eres2net.onnx` | 否 | **是**，需放入 `{setWorkPath}/eres2net.onnx` |

交付包内已随附 `eres2net.onnx`（见交付包 `models/eres2net.onnx`），供集成方放置。

---

## 2. 文件要求

- 类型：`eres2net.onnx`，单个模型文件（约 38 MB）。
- 目标位置：`{SpeechRecognizeSdk.setWorkPath}/eres2net.onnx`。
- native 声纹模块按该文件路径加载；集成方只需确保该目录可读写且文件存在。

---

## 3. 参考 Demo（`com.amphion.dingqiao.harmony.demo`）

Demo 工作目录（由 EntryAbility 设置）：

```
{filesDir}/dingqiao_work/
```

Demo 提供「导入声纹模型」入口（右上角菜单 → 导入声纹模型），通过系统文件选择器选中 `eres2net.onnx`（约 38 MB）后自动复制到工作目录。导入成功后主界面不再提示「未找到声纹模型」，声纹注册页可录制样本并注册。

也可用 `hdc file send` 直接推送：

```
hdc file send eres2net.onnx /data/app/el2/100/base/com.amphion.dingqiao.harmony.demo/files/dingqiao_work/eres2net.onnx
```

---

## 4. 正式 App（`com.tdtech.tiassistant`）

路径取决于贵司 `SpeechRecognizeSdk.setWorkPath(...)` 的配置。集成方需确保该目录可写，并把交付包内的 `eres2net.onnx` 放入其下（打包进 rawfile 后自行复制，或随首启流程拷贝）。

---

## 5. 声纹接口要点

- `registerVoiceprint(params)`：传入声纹样本（16 kHz / 16 bit / mono PCM 或可读 wav），返回声纹 ID；调用前需保证 `{workPath}/eres2net.onnx` 存在，否则返回 `1002200020`（注册失败）。
- 识别会话通过 `StartParams.extraParams.enableVoiceprintVerification=true` + `voiceprintIds=[...]` 启用；`isFinal=true` 的结果携带 `speakerSimilarity`（0~1，典型判决阈值 0.4，由调用方判断）。

---

## 6. 常见错误

| 现象 | 可能原因 |
|------|----------|
| 提示声纹模型未就绪 | `{workPath}/eres2net.onnx` 不存在；请先导入或推送 |
| 注册失败 `1002200020` | 模型缺失或 `setWorkPath` 目录不可写 |
| 启动识别报 `1002200024` | 传入的 voiceprintId 未注册 |

---

## 7. 验收建议

1. 将 `eres2net.onnx` 放入工作目录（Demo 用「导入声纹模型」）
2. 声纹注册页 → 录制至少 1 段 → 注册成功
3. 主界面开启「声纹校验」后识别，final 结果带 `speakerSimilarity`

更多集成说明见 `DINGQIAO_INTEGRATION.md`；平台差异见 `HARMONY_DIFFERENCES.md`。
