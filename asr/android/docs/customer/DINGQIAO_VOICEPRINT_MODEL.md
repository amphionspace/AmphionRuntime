# 声纹模型说明（eres2net.onnx）

面向鼎桥集成与 Demo 验收。自 Android v0.2.7 起，声纹模型已固定内置在 `dingqiao-asr-v*.aar` 中，运行时由 SDK 自动解包到 `SpeechRecognizeSdk.setWorkPath(...)` 指定目录。

---

## 1. 与 ASR 模型的区别

| 类型 | 是否在 AAR 内 | 是否需要手动下发 |
|------|----------------|----------------|
| ASR 声学模型（识别用） | 是 | 否，首次运行自动解包 |
| 声纹模型 `eres2net.onnx` | 是 | 否，首次运行自动解包 |

Demo 若提示声纹模型未就绪，一般表示首次解包未完成、应用数据异常或设备存储不足，不再需要手动导入模型文件。

---

## 2. 文件要求

- 类型：`eres2net.onnx` 是单个模型文件（约 38 MB）。
- 内置位置：AAR assets 内部路径由 SDK 管理，集成方无需访问。
- 运行位置：SDK 会自动复制到 `{setWorkPath}/eres2net.onnx`，供 native 声纹模块按文件路径加载。

---

## 3. 官方 Demo APK（`com.amphion.dingqiao.demo`）

Demo 默认工作目录：

```
/sdcard/Android/data/com.amphion.dingqiao.demo/files/dingqiao_work/
```

安装并首次打开 Demo 后，SDK 会自动准备声纹模型。正常情况下主界面不再提示“未找到声纹模型”，声纹注册页可直接录制样本并注册。

---

## 4. 正式 App（`com.tdtech.tiassistant`）

路径取决于贵司 `SpeechRecognizeSdk.setWorkPath(...)` 的配置。集成方只需确保该目录可写；SDK 会自动把内置模型准备到该目录下，无需从交付包单独拷贝 `eres2net.onnx`。

---

## 5. 常见错误

| 现象 | 可能原因 |
|------|----------|
| Demo 提示声纹模型未就绪 | 首次解包失败、存储不足或应用数据异常；重启 App 或清理应用数据后重试 |
| 注册失败 `speaker model not found` | `setWorkPath` 目录不可写，或模型自动解包失败 |
| 注册失败 `sample duration` | 每段样本须 3～8 秒 |

---

## 6. 验收建议

1. Demo 主界面不再显示「未找到声纹模型」
2. 声纹注册页 → 录制至少 1 段 → 注册成功
3. 主界面开启「声纹校验」后识别，final 结果应带相似度字段

更多集成说明见 `DINGQIAO_INTEGRATION.md`。
