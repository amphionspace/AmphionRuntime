# 商用授权接入说明（纯血鸿蒙）

> 本 SDK、模型与文档仅限授权客户在授权项目中使用。未经书面许可，不得复制、转售、转授权或用于其他项目。

本发行包内的 `amphion_asr.har` 已启用离线授权校验，并内置**生产验签公钥（与 Android SDK 同一把）**。集成方**无需**也**不应**自行配置验签公钥；只需按本章放置我方签发的授权文件。同一份 `amphion-license.lic` 在 Android 与鸿蒙上验签一致。

## 1. 获取授权文件

正式集成前，请向我方商务 / 技术支持提供：

| 信息 | 说明 |
|------|------|
| applicationId | 可选记录字段，不作为授权限制；本次宿主为 com.tdtech.tiassistant |
| 签名证书 SHA-256 | 可选记录字段；正式设备白名单 license 默认不绑定签名 |
| 设备标识清单 | 正式宿主优先提供设备 SN；普通应用可约定 ODID。一行一个，用于生成设备白名单 |
| 授权能力 | 本次正式授权为 ASR,TTS，ASR 与 TTS 共用同一份 amphion-license.lic |

我方将签发 `amphion-license.lic` 并通过安全渠道单独下发。本次正式授权仅限制**设备 SN 白名单和到期时间**，不按 App 包名 / 签名证书限制宿主应用。

Demo HAP 内自带的授权仅用于体验，不可用于贵司正式 App。Demo 是否绑定设备以 HAP 内实际 license 声明为准：标准体验包可使用不绑定设备的试用授权；设备验收包可绑定 Demo 的 ODID。正式授权必须在贵司正式宿主中验证，并确保签发清单与运行时注入的是同一种设备标识。

## 2. 集成方式（ArkTS）

将 `amphion-license.lic` 放入宿主可读路径（如打包进 rawfile 后复制到 `setWorkPath` 目录，或应用私有可读目录），随后：

```typescript
import deviceInfo from '@ohos.deviceInfo';
import { LicenseDeviceIdProvider, SpeechRecognizeSdk } from 'amphion_dingqiao';

class HostDeviceIdProvider implements LicenseDeviceIdProvider {
  getDeviceSerial(_context: Context): string | undefined {
    // 系统/预置宿主使用 deviceInfo.serial；普通 Demo 可改用 deviceInfo.ODID。
    const deviceId = deviceInfo.serial;
    return deviceId.length > 0 ? deviceId : undefined;
  }
}

SpeechRecognizeSdk.init(context, new HostDeviceIdProvider());
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

`setLicense` 为异步回调，鉴权为**离线本地完整校验，无网络请求**，覆盖授权格式、ECDSA 签名、ASR 能力、有效期、维护期、SDK 主版本和设备白名单。它只缓存已验证授权，不会拉起 Runtime，也不会加载模型。必须在授权成功后调用 `prepareRuntime()`；收到 `onReady()` 后，才可调用 `createEngine()` / `createEngineAsync()` 加载或复用模型。

生命周期与内存控制粒度如下：

| 层级 | 加载接口 | 卸载接口 | 说明 |
| --- | --- | --- | --- |
| License | `setLicense()` | 重新设置授权 | 只校验并缓存，不拉 Runtime、不加载模型 |
| Runtime | `prepareRuntime()` | `unloadRuntime()` | 只管理运行时框架；卸载时模型跟随释放，但保留已验证授权 |
| Model | `createEngineAsync()` / `createEngine()` | `unloadModel()` | 创建引擎时按需加载模型；同配置已加载则复用 |

调用 `unloadRuntime()` 后无需再次 `setLicense()`，可直接再次调用 `prepareRuntime()`。准备成功后再创建引擎即可。释放模型前应先结束会话并对持有的 engine 调用 `shutdown()`，再调用 `unloadModel()`。

## 3. 授权错误码（setLicense / getLicenseInfo）

| code | 含义 | 处理 |
|------|------|------|
| 1002200030 | 授权文件不存在 / 不可读 | 确认路径正确、文件可读 |
| 1002200031 | 授权格式无效 / 验签失败（被篡改或非我方签发） | 向我方重新获取 |
| 1002200032 | 授权已过期 | 联系续期 |
| 1002200033 | 设备不匹配（标识不在白名单，或运行时无法读取标识） | 确认签发清单与 `deviceIdProvider` 返回同一种标识 |
| 1002200034 | 尚未设置授权（getLicenseInfo 时） | 先调用 setLicense |
| 1002200035 | 激活失败（离线实现下作兜底语义，非"服务器不可达"） | 参考 message 排查 |

## 4. 注意事项

- 正式授权不按包名限制宿主应用；授权边界为**设备标识白名单、有效期、授权能力**。
- 读取 `deviceInfo.serial` 需 `ohos.permission.sec.ACCESS_UDID`（system_basic），普通三方 App 无法获得。系统 / 预置宿主可注入 SN；普通 Demo 可注入无需该权限的 `deviceInfo.ODID`，但签发清单也必须使用该 ODID。
- ODID 按开发者和设备隔离；恢复出厂、更换开发者签名，或卸载该开发者在设备上的全部应用后可能重置，届时需要重新签发。
- `getDeviceSerial` 是兼容既有接口的方法名，返回值可为双方约定的稳定设备标识，不应把明文标识硬编码进 HAP。
- 独立下发的正式 license 不用于 Demo；不要用 Demo 通过替代正式宿主的授权验收。
- 请勿将授权文件提交到公开代码仓库；勿在交付包内查找或替换验签密钥。
