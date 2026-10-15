# 国内 Enterprise Android 授权接入

国内测试入口为 `https://test-console.amphion.top`，MCP 为 `/api/mcp`。企业身份用于申请审批；设备通过 `/activation/v1` 激活和续租，不使用企业管理员 Bearer。

## 工件与签发对齐

使用明确标记国内测试信任根的候选 AAR，不能用旧正式 SDK 验证新签名。候选通过 `AMPHION_LICENSE_PUBLIC_KEY` 构建属性追加国内测试公钥，正式默认公钥保持不变。ASR 需同时替换基础 SDK 与鼎桥适配 AAR；TTS 候选包含模型。arm64-v8a、Android API 24 起支持。

MCP 创建 `asr_tts_edge` 权益，选择 `offline_file`、`online_once` 或 `online_lease`，计量为 `device_seat`。能力为 `ASR`、`TTS` 或两者。设备标识必须由宿主提供稳定值，并与本次签发绑定一致；不要将模拟器验收标识用于客户。

## 端侧调用

ASR 离线文件调用顺序为：`SpeechRecognizeSdk.init`（配置设备标识提供器）→ `setLicense` 成功回调 → `prepareRuntime` 成功回调 → `createEngine`。TTS 使用 `TextToSpeechSdk.init` 与 `TtsLicenseOptions` 传入许可证文本、设备标识提供器，然后创建引擎。

需要联网激活时，在后台线程使用对应 SDK 的 `EnterpriseLicenseClient(origin)`，调用 `activate(code, fingerprint, destination)`。下载包含轮询、一次性票据、SHA-256 校验和原子文件替换。下载完成后仍需执行上述本地授权激活步骤；识别和合成本身离线运行。宿主声明 `INTERNET` 权限，文件放应用私有目录。

`activate` 返回 `Activation`，宿主使用基于 Android Keystore 的安全存储保存 `deviceId`、`token`。重启后通过 `Activation(deviceId, token)` 恢复，并调用 `renew(activation, fingerprint, destination)`。续租得到新代次后重新激活新文件，再建立引擎；不要记录 token 或许可证全文。初始化 SDK 不能替代授权激活。

## 参数行为

| 参数 | 执行行为 |
| --- | --- |
| 设备、能力、包名白名单、证书 | 不匹配时本地拒绝 |
| SDK 主版本、维护截止日 | 与构建信息比较，不满足时拒绝 |
| 运行有效期 | 秒级到期，已创建引擎和运行中的 ASR 喂音频也检查 |
| 租约与宽限 | 仅 `online_lease` 使用，显式零宽限生效；合同到期为硬上限 |
| 代次 | 激活成功时持久记录最高代次，旧代次拒绝；只读查询不提升代次 |
| 服务端撤销 | 拒绝续租和下载；已离线的设备只能依靠本地有效期终止 |

本轮 Android 模拟器验证覆盖实际 SDK 推理及授权控制，不替代鼎桥真机的硬件身份、防克隆、防回拨验证。iOS 正式授权能力仍待后续实现与验收。
