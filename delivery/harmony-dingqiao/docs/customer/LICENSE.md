# 商用授权接入说明（纯血鸿蒙）

> 本 SDK、模型与文档仅限授权客户在授权项目中使用。未经书面许可，不得复制、转售、转授权或用于其他项目。

本发行包内的 `amphion_asr.har` 已启用离线授权校验，并内置**生产验签公钥（与 Android SDK 同一把）**。集成方**无需**也**不应**自行配置验签公钥；只需按本章放置我方签发的授权文件。同一份 `amphion-license.lic` 在 Android 与鸿蒙上验签一致。

## 1. 获取授权文件

正式集成前，请向我方商务 / 技术支持提供：

| 信息 | 说明 |
|------|------|
| applicationId | 可选记录字段，不作为授权限制；本次宿主为 com.tdtech.tiassistant |
| 签名证书 SHA-256 | 可选记录字段；正式设备白名单 license 默认不绑定签名 |
| 设备 SN 清单 | 首批授权设备 SN，一行一个；用于生成设备白名单 |
| 授权能力 | 本次正式授权为 ASR,TTS，ASR 与 TTS 共用同一份 amphion-license.lic |

我方将签发 `amphion-license.lic` 并通过安全渠道单独下发。本次正式授权仅限制**设备 SN 白名单和到期时间**，不按 App 包名 / 签名证书限制宿主应用。

Demo HAP 内自带的授权仅用于体验：只限制期限，不绑定设备 SN，不可用于贵司正式 App。Demo 验收只证明 SDK 能完成初始化和体验流程；它不会验证正式 `amphion-license.lic`。正式授权必须在贵司正式宿主中验证：设备 SN 在授权白名单内，且宿主能读取或注入该 SN。

## 2. 集成方式（ArkTS）

将 `amphion-license.lic` 放入宿主可读路径（如打包进 rawfile 后复制到 `setWorkPath` 目录，或应用私有可读目录），随后：

```typescript
SpeechRecognizeSdk.init(context);
SpeechRecognizeSdk.setWorkPath(workPath);
SpeechRecognizeSdk.setLicense(licenseAbsolutePath, {
  onResult: (r) => { if (r.errorCode === 0) { /* 激活成功，再 createEngine */ } },
  onError:  (code, msg) => { /* 激活失败 */ }
});
```

`setLicense` 为异步回调，鉴权为**离线本地验签，无网络请求**；应在 `createEngine` 之前调用，并在成功回调后再建引擎。

## 3. 授权错误码（setLicense / getLicenseInfo）

| code | 含义 | 处理 |
|------|------|------|
| 1002200030 | 授权文件不存在 / 不可读 | 确认路径正确、文件可读 |
| 1002200031 | 授权格式无效 / 验签失败（被篡改或非我方签发） | 向我方重新获取 |
| 1002200032 | 授权已过期 | 联系续期 |
| 1002200033 | 设备不匹配（SN 不在白名单，或运行时无法读取设备 SN） | 确认为可读取 SN 的系统/特权应用，并使用含该 SN 的正式授权 |
| 1002200034 | 尚未设置授权（getLicenseInfo 时） | 先调用 setLicense |
| 1002200035 | 激活失败（离线实现下作兜底语义，非"服务器不可达"） | 参考 message 排查 |

## 4. 注意事项

- 正式授权不按包名限制宿主应用；授权边界为**设备 SN 白名单、有效期、授权能力**。
- 正式授权启用设备 SN 白名单；宿主 App 需能在运行时向 SDK 提供本机 SN。**读取设备 SN 需 `ohos.permission.sn`（system_basic 特权权限）**，普通三方 App 无法读取，需系统 / 预置应用或由宿主通过 `deviceIdProvider` 注入。详见 `HARMONY_DIFFERENCES.md` 第 7 条。
- Demo HAP 不绑定 SN；若把 Demo 授权换成正式 SN 绑定授权，普通设备可能因无法读取 SN 而激活失败（`1002200033`）。
- 独立下发的正式 license 不用于 Demo；不要用 Demo 通过替代正式宿主的授权验收。
- 请勿将授权文件提交到公开代码仓库；勿在交付包内查找或替换验签密钥。
