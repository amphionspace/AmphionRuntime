# 隐私与合规说明

适用 SDK：`com.amphion:amphion-runtime` 0.3.9

版本以本批 AAR 的 SDK_VERSION 和交付清单为准。本文主体描述核心 `:sdk`，鼎桥适配层及 diagnostics 的差异另列。

本文件用于：
1. 让你（集成方）在自己的 App 隐私政策、上架材料里准确披露 SDK 的数据行为；
2. 让你的最终用户、合规与法务团队明白本 SDK 收集了什么、不收集什么。

集成方应按实际 SDK 变体、启用功能及宿主的数据行为完善披露，不能将核心 SDK 的说明直接覆盖 Demo 或 diagnostics 的全部行为。

## 1. SDK 名称与提供方

| 项 | 取值 |
| --- | --- |
| SDK 名称 | AmphionRuntime |
| 包名 | com.amphion.asr |
| 坐标 | com.amphion:amphion-runtime |
| 版本 | 本批 AAR 的 SDK_VERSION |
| 提供方 | Amphion（fork 用户请替换为自己公司的完整名称与联系方式） |
| 隐私政策链接 | https://your-domain.example.com/privacy/amphion-runtime |

## 2. SDK 处理的个人信息类型

| 类型 | 是否处理 | 说明 |
| --- | --- | --- |
| 录音音频（PCM） | 是 | 仅在内存中流式处理，识别完成立即丢弃；不写入磁盘、不上传 |
| 识别结果文本 | 是 | 仅通过回调返回给宿主 App；SDK 不持久化、不上传 |
| IMEI / Android ID / MAC | 否 | 核心 SDK 不主动读取 |
| 设备 SN 及其哈希 | 按授权条件 | 启用设备绑定时，处理宿主/provider 提供的 SN 并在本地计算哈希校验，不上传 |
| 位置信息 | 否 | 不读取 |
| 联系人 / 相册 / 通话记录 | 否 | 不读取 |
| 应用安装列表 | 否 | 不读取 |
| 网络流量统计 | 否 | 不读取 |
| 崩溃日志 | 否 | 不上报 |

## 3. 网络通信

当前核心 SDK 完全离线，全部模型（中英 ASR / 粤英 ASR / 标点 / 中文 ITN / VAD）已经打入 AAR 的 assets，无任何主动网络请求。

| 时机 | 是否发起请求 |
| --- | --- |
| AmphionRuntime.init | 否 |
| AmphionRuntime.preInstall | 否（仅本地 assets → filesDir 解包） |
| AmphionRuntime.create | 否 |
| AsrSession.acceptPcm* / stop / close | 否 |

SDK 不与任何第三方域名（包括但不限于 sherpa-onnx 官方仓库）通信。

## 4. 数据存储

核心 SDK 的模型安装使用 App 私有目录，以下列出默认路径；宿主指定工作目录及适配层数据另行核对：

| 路径 | 内容 | 生命周期 |
| --- | --- | --- |
| `<filesDir>/amphion-runtime/<bundle>/v<n>/` | 解包后的 ONNX / FST / tokens.txt 等模型文件 | 卸载 App 时随 App 私有数据清除；SDK 升级会自动覆盖 |
| `<filesDir>/amphion-runtime/install.flag` | 一段记录当前 SDK_VERSION 的小文本 | 同上 |

核心 SDK 不持久化识别音频或文本。授权状态可能包含用于校验的设备哈希，不应写入公开日志。

鼎桥适配层另有声纹模板存储；启用角色分离时，PCM 按块写入应用私有临时目录，处理且不再引用后回收。diagnostics 变体可采集并导出有界 PCM/WAV、回调与日志；普通 Release 不能据此宣称具有相同采集行为。宿主自行录音、保存结果或导出诊断文件的行为也需单独披露。

## 5. 权限申明

SDK 自身的 AndroidManifest.xml 不声明任何敏感权限。集成方仅需要：

| 权限 | 用途 | 是否必需 |
| --- | --- | --- |
| android.permission.RECORD_AUDIO | 录制麦克风音频 | 使用麦克风时需要；只传入已有 PCM 不需要（SDK 不调 AudioRecord） |

0.2.0 起 SDK 不再需要 `INTERNET` / `ACCESS_NETWORK_STATE`。

## 6. 第三方依赖

| 依赖 | 协议 | 来源 | 是否上网 |
| --- | --- | --- | --- |
| sherpa-onnx | Apache-2.0 | https://github.com/k2-fsa/sherpa-onnx | 否 |
| ONNX Runtime | MIT | https://github.com/microsoft/onnxruntime | 否 |
| silero-vad | MIT | https://github.com/snakers4/silero-vad | 否 |
| WeTextProcessing | Apache-2.0 | https://github.com/wenet-e2e/WeTextProcessing | 否 |
| AndroidX core-ktx | Apache-2.0 | Google | 否 |

完整声明见同目录 `NOTICE` 文件。

## 7. 合规建议（给集成方）

如果你需要在 App 上架时披露集成本 SDK，请在你的隐私政策中加入类似措辞（仅供参考）：

> 我们的 App 集成了 AmphionRuntime 用于离线语音识别。SDK 仅在用户主动开启录音时处理音频数据，识别完成即丢弃，不上传至任何服务器，不主动读取 IMEI、Android ID、MAC 或位置；启用设备授权时在本地处理宿主提供的 SN 及其哈希；不与任何第三方域名进行网络通信。模型已经预置在安装包内，无需额外下载。

如果你需要 SDK 厂商出具单独的"个人信息处理说明"用于合规归档，请联系 privacy@your-domain.example.com（替换为你的真实邮箱）。

## 8. 变更记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| 0.2.0 | 2026-05 | 移除模型 CDN 下载与 INTERNET / ACCESS_NETWORK_STATE 权限；改为 AAR 内置全部模型，完全离线运行 |
| 0.1.0 | 2026-05 | 仓库拆分首版 |
