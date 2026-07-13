# 商用授权接入说明（HarmonyOS）

> 本 SDK、模型与文档仅限授权客户在授权项目中使用。未经书面许可，不得复制、转售、转授权或用于其他项目。

`amphion_dingqiao.har` 已内置生产验签公钥。集成方无需配置公钥，只需使用我方单独签发的
`amphion-license.lic`。授权校验完全离线，不发起网络请求；授权文件不包含在 SDK ZIP 中。

## 1. 签发所需信息

| 信息 | 说明 |
| --- | --- |
| 设备标识清单 | 通常为正式宿主可读取的硬件 SN；一行一个 |
| 授权能力 | 本交付需要 `ASR` |
| 有效期 / 维护期 | 按合同约定 |
| 宿主签名证书 SHA-256 | 可选；仅在需要限制指定宿主证书时提供 |
| applicationId / bundleName | 可选记录字段，除非合同另有约定，不作为授权限制 |

签发清单与运行时注入值必须使用同一种设备标识。按 SN 签发的 license 不能由 ODID 验证，
按 ODID 签发的 license 也不能由 SN 验证。

## 2. 接入示例

```ts
import deviceInfo from '@ohos.deviceInfo';
import { LicenseDeviceIdProvider, SpeechRecognizeSdk } from 'amphion_dingqiao';

class HostDeviceIdProvider implements LicenseDeviceIdProvider {
  getDeviceSerial(_context: Context): string | undefined {
    const sn = deviceInfo.serial;
    return sn.length > 0 ? sn : undefined;
  }
}

SpeechRecognizeSdk.init(context, new HostDeviceIdProvider());
SpeechRecognizeSdk.setWorkPath(`${context.filesDir}/dingqiao_asr`);
SpeechRecognizeSdk.setLicense(licenseAbsolutePath, {
  onResult: () => {
    // 此时只完成授权校验与缓存，Runtime 和模型尚未加载。
    SpeechRecognizeSdk.prepareRuntime({
      onReady: () => { /* 现在可以 createEngine/createEngineAsync */ },
      onError: (code, message) => {}
    });
  },
  onError: (code, message) => {}
});
```

SDK 会校验：JSON 信封、ECDSA 签名、ASR 能力、有效期、维护期、SDK 主版本、设备白名单，
以及 license 中可选的宿主签名证书 SHA-256。宿主证书摘要由 SDK 从当前应用签名信息读取；
license 已绑定证书但摘要缺失或不匹配时会失败，不会跳过该检查。

## 3. 设备标识权限

读取 `deviceInfo.serial` 需要 `ohos.permission.sec.ACCESS_UDID`，普通三方应用通常无法取得该
system_basic 权限。正式系统/预置宿主应通过自己的系统能力读取 SN 并由
`LicenseDeviceIdProvider` 注入。普通测试 App 可以读取 ODID，但只有专门按该 ODID 签发的
license 才能通过，不能拿它验证按 SN 签发的正式 license。

`getDeviceSerial` 是兼容既有接口的方法名，返回值可以是双方约定的稳定设备标识。不要把明文
设备标识、正式 license 或私钥写入源码、日志或公开仓库。

## 4. `LicenseInfo`

`SpeechRecognizeSdk.getLicenseInfo()` 在尚未发起过 `setLicense()` 时会抛出含 `1002200034`
的错误。首次校验失败后可查询对应失败状态；已有有效授权时，新授权失败不会覆盖旧授权信息。

| 字段 | 说明 |
| --- | --- |
| `status` | `0` 有效；`1` 已过期；`2` 无效；`3` 设备或宿主证书不匹配 |
| `expireTime` | 到期日当天 `00:00:00 UTC` 的 epoch 毫秒；未提供或不可用时为 `-1` |
| `remainingDays` | 以 UTC 日期计算的剩余整天数；未提供或不可用时为 `-1` |
| `authorizedFeatures` | 已授权能力列表，例如 `ASR` |

## 5. 授权错误码

| code | 含义 | 建议处理 |
| --- | --- | --- |
| `1002200030` | 授权文件不存在或不可读 | 检查绝对路径和应用私有目录权限 |
| `1002200031` | 格式、签名、能力、维护期或 SDK 主版本不合法 | 不要修改文件；联系我方重新签发 |
| `1002200032` | 授权已过期 | 联系续期 |
| `1002200033` | 设备标识或已绑定宿主证书不匹配 | 核对 SN/ODID 类型、白名单和宿主签名证书 |
| `1002200034` | 尚未成功设置授权 | 先调用 `setLicense()` |
| `1002200035` | 激活流程兜底失败 | 结合回调 message 和 hilog 排查 |

重新设置有效授权会使旧 Runtime 和模型状态失效，随后必须重新调用 `prepareRuntime()`。
新的授权校验失败时，不会覆盖当前仍有效的旧授权。
