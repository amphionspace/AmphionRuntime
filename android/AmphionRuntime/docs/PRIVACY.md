# 隐私与合规说明

适用 SDK：`com.amphion:amphion-runtime` 0.1.0

本文件用于：
1. 让你（集成方）在自己的 App 隐私政策、上架材料里准确披露 SDK 的数据行为；
2. 让你的最终用户、合规与法务团队明白本 SDK 收集了什么、不收集什么。

如果你的产品销售对象是中国大陆用户，请按 GB/T 35273-2020 个人信息安全规范、《App 违法违规收集使用个人信息行为认定方法》的口径披露。

## 1. SDK 名称与提供方

| 项 | 取值 |
| --- | --- |
| SDK 名称 | AmphionRuntime |
| 包名 | `com.amphion:amphion-runtime` |
| 版本 | 0.1.0 |
| 提供方 | Amphion（如果你 fork 出去自用，请替换为你公司的完整名称与联系方式） |
| 隐私政策链接 | https://your-domain.example.com/privacy/amphion-runtime |

## 2. SDK 处理的个人信息类型

| 类型 | 是否处理 | 说明 |
| --- | --- | --- |
| 录音音频（PCM） | 是 | 仅在内存中流式处理，识别完成立即丢弃；不写入磁盘、不上传 |
| 识别结果文本 | 是 | 仅通过回调返回给宿主 App；SDK 不持久化、不上传 |
| 设备唯一标识符（IMEI/Android ID/MAC） | 否 | 不读取 |
| 位置信息 | 否 | 不读取 |
| 联系人/相册/通话记录 | 否 | 不读取 |
| 应用安装列表 | 否 | 不读取 |
| 网络流量统计 | 否 | 不读取 |
| 崩溃日志 | 否 | 不上报 |

## 3. 网络通信

SDK 主动发起网络请求的全部场景：

| 时机 | 目标地址 | 内容 | 频率 |
| --- | --- | --- | --- |
| 集成方调用 `ModelManager.ensure(manifestUrl)` 时 | 集成方提供的 HTTPS URL | 下载 manifest.json 与模型文件 | 仅在模型不存在 / 不一致时 |

SDK 不与任何第三方域名（包括但不限于 sherpa-onnx 官方仓库）通信。所有模型分发地址由集成方自行配置。

如果集成方将模型预置在 APK 内，或通过自有渠道分发到设备，则 SDK 完全离线，不发起任何网络请求。

## 4. 数据存储

SDK 仅在以下两个位置写入数据：

| 路径 | 内容 | 生命周期 |
| --- | --- | --- |
| `<context.filesDir>/asr-models/<id>/<v>/` | 模型文件（encoder/decoder/joiner ONNX、tokens.txt、manifest.json 副本） | 由 `ModelManager.delete` 或卸载 App 删除 |
| `<context.filesDir>/asr-models/.tmp/` | 下载临时文件 | 校验通过后立即原子删除 |

SDK 不向 SharedPreferences、外部存储、外部数据库、云端 写入任何用户数据。

## 5. 权限申明

SDK 自身的 AndroidManifest.xml 不声明任何敏感权限。集成方需要在自己 manifest 声明：

| 权限 | 用途 | 是否必需 |
| --- | --- | --- |
| `android.permission.RECORD_AUDIO` | 录制麦克风音频 | 必需（业务方负责申请，SDK 不调 AudioRecord） |
| `android.permission.INTERNET` | 模型下载 | 仅当使用 ModelManager.ensure 时 |
| `android.permission.ACCESS_NETWORK_STATE` | 模型下载错误诊断 | 仅当使用 ModelManager.ensure 时 |

## 6. 第三方依赖

| 依赖 | 协议 | 来源 | 是否上网 |
| --- | --- | --- | --- |
| sherpa-onnx | Apache-2.0 | https://github.com/k2-fsa/sherpa-onnx | 否 |
| ONNX Runtime | MIT | https://github.com/microsoft/onnxruntime | 否 |
| silero-vad（可选） | MIT | https://github.com/snakers4/silero-vad | 否 |
| AndroidX core-ktx | Apache-2.0 | Google | 否 |

完整声明见同目录 `NOTICE` 文件。

## 7. 合规建议（给集成方）

如果你需要在 App 上架时披露集成本 SDK，请在你的隐私政策中加入类似措辞（仅供参考）：

> 我们的 App 集成了 AmphionRuntime 用于 离线 语音识别。SDK 仅在用户主动开启录音时处理音频数据，识别完成即丢弃，不上传至任何服务器，不收集设备唯一标识符、位置等其他个人信息。当你需要更新本地识别模型时，App 会向 我方服务器（仅由 我方域名 提供） 下载模型文件；除此之外 SDK 不与任何第三方进行网络通信。

如果你需要 SDK 厂商出具单独的"个人信息处理说明"用于合规归档，请联系 privacy@your-domain.example.com（替换为你的真实邮箱）。

## 8. 变更记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| 0.1.0 | 2026-05 | 仓库拆分首版 |
