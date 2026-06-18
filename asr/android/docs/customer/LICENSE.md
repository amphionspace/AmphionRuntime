# 商用授权接入说明

本 SDK 发行包内的 `dingqiao-asr-*.aar` 已启用离线授权校验。集成方**无需**也**不应**自行配置验签公钥；只需按本章放置我方签发的授权文件。

## 1. 获取授权文件

正式集成前，请向我方商务 / 技术支持提供：

| 信息 | 说明 |
|------|------|
| **applicationId** | 贵司 App 的包名（Release 构建） |
| **Release 签名证书 SHA-256** | 贵司用于上架 / 量产的 keystore 证书指纹 |

我方将签发 `amphion-license.lic` 并通过安全渠道单独下发（**不进 SDK 压缩包**）。

> Demo APK 内自带的授权文件仅绑定 Demo 包名与 Demo 签名，**不可**用于贵司正式 App。

## 2. 集成方式

将 `.lic` 放入 App 的 assets 目录，默认文件名：

```
app/src/main/assets/amphion-license.lic
```

初始化（与 `SpeechRecognizeSdk` 文档一致）：

```kotlin
SpeechRecognizeSdk.init(applicationContext)
```

若使用底层 `AmphionRuntime`，可通过 `AmphionOptions` 指定 assets 中的文件名；默认即为 `amphion-license.lic`。

## 3. 启动与错误码

Release 集成在 `init` 阶段校验授权。常见错误（`IllegalStateException`，message 含 `code=`）：

| code | 含义 | 处理 |
|------|------|------|
| 6001 | 未找到授权文件 | 确认 `assets/amphion-license.lic` 已打入 APK |
| 6003 | 授权无效或被篡改 | 向我方重新获取 |
| 6004 | 包名与授权不一致 | 提供正确 applicationId 申请重签 |
| 6005 | 签名证书与授权不一致 | 更换 keystore 后需重新申请 |
| 6006 | 授权已过期 | 联系续期 |

校验通过后，日志中可见授权状态为已授权（具体 tag 因版本而异）。

## 4. 注意事项

- 授权文件与 **包名 + Release 签名** 绑定；Debug 签名与 Release 不一致时，请使用 Debug 专用授权或先用 Release 包验证。
- 请勿将授权文件提交到公开代码仓库。
- 授权相关问题请联系我方对接人，勿在交付包内查找或替换验签密钥。
