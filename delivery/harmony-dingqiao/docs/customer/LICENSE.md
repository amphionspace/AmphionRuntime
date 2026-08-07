# 四个月体验授权接入说明（HarmonyOS）

> 本 SDK、模型与文档仅限授权客户在授权项目中使用。未经书面许可，不得复制、转售、转授权或用于其他项目。

本发行包内的 `amphion_dingqiao.har` 已启用离线授权校验，并内置**生产验签公钥（与 Android SDK 同一把）**。集成方**无需**也**不应**自行配置验签公钥；只需按本章放置我方签发的授权文件。同一份 `amphion-license.lic` 在 Android 与鸿蒙上验签一致。

## 1. 授权范围

授权文件由签发方另行提供，不在 SDK-only ZIP 内；获得授权后将其放入宿主可读路径。
本体验授权仅授予 ASR 能力，从签发日起四个自然月有效。
它不绑定 applicationId、bundleName、签名证书、设备、装机量、SDK 主版本或维护期，同一份文件可用于不同包名和设备。

## 2. 集成方式（ArkTS）

将 `amphion-license.lic` 放入宿主可读路径（如打包进 rawfile 后复制到 `setWorkPath` 目录，或应用私有可读目录），随后：

```typescript
import { SpeechRecognizeSdk } from 'amphion_dingqiao';

SpeechRecognizeSdk.init(context);
SpeechRecognizeSdk.setWorkPath(workPath);
SpeechRecognizeSdk.setLicense(licenseAbsolutePath, {
  onResult: (r) => {
    if (r.errorCode !== 0) return;
    // setLicense 只完成授权校验与缓存，不会拉起 Runtime 或加载模型。
    SpeechRecognizeSdk.prepareRuntime({
      onReady: () => { /* Runtime 已就绪；现在可以 createEngine/createEngineAsync */ },
      onError: (code, msg) => { /* Runtime 拉起失败 */ }
    });
  },
  onError:  (code, msg) => { /* 激活失败 */ }
});
```

`setLicense` 为异步回调，鉴权为**离线本地完整校验，无网络请求**，覆盖授权格式、ECDSA 签名、ASR 能力和有效期。它只缓存已验证授权，不会拉起 Runtime，也不会加载模型。必须在授权成功后调用 `prepareRuntime()`；收到 `onReady()` 后，才可调用 `createEngine()` / `createEngineAsync()` 加载或复用模型。

生命周期与内存控制粒度如下：

| 层级 | 加载接口 | 卸载接口 | 说明 |
| --- | --- | --- | --- |
| License | `setLicense()` | 重新设置授权 | 只校验并缓存，不拉 Runtime、不加载模型 |
| Runtime | `prepareRuntime()` | `unloadRuntime()` | 只管理运行时框架；卸载时模型跟随释放，但保留已验证授权 |
| Model | `createEngineAsync()` / `createEngine()` | `unloadModel()` | 创建引擎时按需加载模型；同配置已加载则复用 |

调用 `unloadModel()` 或 `unloadRuntime()` 前，都应先结束或取消活跃会话，并对持有的 engine 调用 `shutdown()`。`unloadRuntime()` 后无需再次 `setLicense()`，可直接再次调用 `prepareRuntime()`；准备成功后再创建引擎即可。

## 3. 授权错误码（setLicense / getLicenseInfo）

| code | 含义 | 处理 |
|------|------|------|
| 1002200030 | 授权文件不存在 / 不可读 | 确认路径正确、文件可读 |
| 1002200031 | 授权格式无效 / 验签失败（被篡改或非我方签发） | 向我方重新获取 |
| 1002200032 | 授权已过期 | 联系续期 |
| 1002200033 | 设备或证书不匹配 | 本体验授权不应触发；确认使用的是签发方提供的有效授权文件 |
| 1002200034 | 尚未设置授权（getLicenseInfo 时） | 先调用 setLicense |
| 1002200035 | 激活失败（离线实现下作兜底语义，非"服务器不可达"） | 参考 message 排查 |

## 4. 注意事项

- 本体验授权只受 ASR 能力和四个自然月有效期限制。
- `getDeviceSerial` 是兼容既有接口的方法名；本授权不绑定设备，因此无需实现或申请设备标识权限。
- 请勿将授权文件提交到公开代码仓库；勿在交付包内查找或替换验签密钥。
