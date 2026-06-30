# 商用授权接入说明

本 SDK 发行包内的 `dingqiao-asr-*.aar` 已启用离线授权校验。集成方**无需**也**不应**自行配置验签公钥；只需按本章放置我方签发的授权文件。

## 1. 获取授权文件

正式集成前，请向我方商务 / 技术支持提供：

| 信息 | 说明 |
|------|------|
| applicationId | 可选记录字段，不作为授权限制；本次宿主为 com.tdtech.tiassistant |
| Release 签名证书 SHA-256 | 可选记录字段；正式设备白名单 license 默认不绑定签名 |
| 设备 SN 清单 | 首批授权设备 SN，一行一个；用于生成设备白名单 |
| 授权能力 | 本次正式授权为 ASR,TTS，ASR 与 TTS 共用同一份 amphion-license.lic |

我方将签发 `amphion-license.lic` 并通过安全渠道单独下发，不进 SDK 压缩包。本次正式授权限制设备 SN 白名单和到期时间，不按 App 包名限制宿主应用。

Demo APK 内自带的授权文件仅用于体验：绑定 Demo 包名与 Demo 签名，只限制期限，不绑定设备 SN，不可用于贵司正式 App。

Demo APK 验收只证明 Demo 内置授权可用、SDK 能完成初始化和体验流程；它不会验证正式 `amphion-license.lic`。正式授权必须在贵司正式宿主中验证：设备 SN 在授权白名单内，且宿主能读取或注入该 SN。

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
| 6001 | 未找到授权文件 | 确认 assets/amphion-license.lic 已打入 APK |
| 6003 | 授权无效或被篡改 | 向我方重新获取 |
| 6004 | 保留错误码；当前正式设备白名单 license 不按包名触发 | 无需按包名重签 |
| 6005 | 签名证书与授权不一致 | 更换 keystore 后需重新申请 |
| 6006 | 授权已过期 | 联系续期 |
| 6007 | 设备 SN 不在授权白名单，或运行时无法读取设备 SN | 确认正式 App 为可读取 SN 的系统应用，并使用包含该 SN 的正式授权 |

校验通过后，日志中可见授权状态为已授权（具体 tag 因版本而异）。

## 4. 注意事项

- 正式授权文件不按包名限制宿主应用；授权边界是设备 SN 白名单、有效期和授权能力。
- 正式授权启用设备 SN 白名单；宿主 App 需要能在运行时向 SDK 提供本机 SN。普通三方 App 通常无法读取系统 SN，系统 / 特权应用需具备对应权限。
- Demo APK 为普通安装体验包，不绑定 SN；若把 Demo 授权换成正式 SN 绑定授权，普通安装时可能因无法读取 SN 而初始化失败。
- 独立下发的正式 license zip 不用于 Demo APK；不要用 Demo 通过来替代正式宿主的授权验收。
- 请勿将授权文件提交到公开代码仓库。
- 授权相关问题请联系我方对接人，勿在交付包内查找或替换验签密钥。
