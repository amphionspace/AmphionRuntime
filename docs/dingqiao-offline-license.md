# 鼎桥离线 License 交付前置清单

本文是鼎桥专网交付前的信息收集清单。实现细节以 Android/Harmony SDK 内的 `amphion-license.lic` 为准；ASR 与 TTS 共用同一份 license、公钥和设备白名单。

## 当前 Android v0.2.7 交付口径

| 对象 | applicationId / bundleName | features | SN 绑定 | 到期 |
| --- | --- | --- | --- | --- |
| Demo APK | `com.amphion.dingqiao.demo` | `ASR` | 不绑定 SN，只绑定 Demo 包名和签名 | `2026-08-25` |
| 正式 SDK license | `com.tdtech.tiassistant` | `ASR,TTS` | 绑定鼎桥 SN 清单，本次 16 台 | `2026-08-25` |

Demo APK 是普通安装体验包，必须能在没有系统 SN 读取权限的设备上完成 `createEngine`。正式 SDK license 单独下发给客户 App，才启用 SN 白名单；客户 App 需要能读取或注入本机 SN。

## 交付前鼎桥需要提供的信息

| 类别 | 鼎桥需提供 | 用途 |
| --- | --- | --- |
| App 标识 | Android `applicationId`、HarmonyOS `bundleName` | 防止授权被复制到其他 App |
| 签名信息 | 正式签名证书 SHA-256 指纹，建议大写十六进制 | 防止换包或重签名后复用授权 |
| 设备 SN | 首批授权设备 SN 清单，一行一个；说明 SN 字段名和样例 | 生成 `authorizedDeviceHashes` 白名单 |
| SN 稳定性 | SN 在系统升级、恢复出厂、主板维修、换机后的变化规则 | 评估换机和重签流程 |
| SN 读取方式 | Android 端使用 `Build.getSerial()`；宿主为系统应用，并申请 `android.permission.READ_PRIVILEGED_PHONE_STATE` | 运行时向 SDK 注入本机 SN |
| 授权能力 | 是否授权 ASR、是否授权 TTS | 写入 `features`，仅允许 `ASR` 和 `TTS` |
| 版本范围 | 授权 SDK 大版本 `sdkMajor`、维护期 `maintenanceUntil` | 控制大版本和维护期外升级 |
| 运行期限 | `expiresAt` 是否为空或固定日期；本次 Android v0.2.7 为 `2026-08-25` | 控制运行到期策略 |
| 组包责任 | 后装包或升级包由哪一方组包 | 确认 license、SDK/HAR、模型放置责任 |
| 固定路径 | App assets 或 rawfile 中 license 的固定路径 | SDK 初始化时读取 `amphion-license.lic` |
| 增量设备 | 后续新增设备 SN 的同步周期和交付方式 | 支持增量或全量重签 |

## License 结构

外层仍使用签名信封：

```json
{
  "payload_b64": "<base64(UTF-8 JSON claims)>",
  "alg": "SHA256withECDSA",
  "sig_b64": "<base64(ECDSA signature)>"
}
```

`payload_b64` 解码后的 claims 使用以下关键字段：

| 字段 | 含义 |
| --- | --- |
| customer | 客户名称，例如 Dingqiao |
| licenseId | 授权编号，用于交付和排障追踪 |
| applicationId | Android 宿主包名 |
| bundleName | HarmonyOS 应用 bundleName |
| signingCertDigest | 客户应用正式签名证书 SHA-256 |
| deviceIdHashAlg | 当前固定为 SHA-256 |
| deviceIdSaltId | 项目固定 SN 哈希盐编号，当前也作为哈希盐材料 |
| authorizedDeviceHashes | 授权 SN 哈希白名单 |
| features | 授权能力列表，仅允许 ASR、TTS |
| sdkMajor | 授权 SDK 大版本 |
| maintenanceUntil | 可升级维护期截止日 |
| issuedAt | 签发日期 |
| expiresAt | 运行到期日；空表示已授权版本不因时间停机 |

## SN 白名单规则

License 不写入明文 SN。签发端和 SDK 端使用同一规则：

```text
SHA-256(normalizedSn + deviceIdSaltId)
```

`normalizedSn` 是去除首尾空格并转大写后的 SN。`deviceIdSaltId` 由我方固定为 `DQ-TIASSISTANT-20260623-69CD375699165832C1D2E9EA77C8BE71`，并写入 license；SDK 会从 license 读取该值后计算本机 SN 哈希。哈希不是加密，不能替代资料管理；它的作用是避免 license 中直接暴露明文 SN 清单。

SDK 已提供 `DeviceIdProvider` 注入通道。Android ASR 鼎桥封装层和 Android TTS 交付路径默认通过 `Build.getSerial()` 读取 SN 并注入；宿主 App 需要作为系统应用获得 `android.permission.READ_PRIVILEGED_PHONE_STATE`。返回的 SN 必须与交付给我方签发 license 的 SN 清单一致。若 HarmonyOS 或后续 Android 版本改用其他 SN API，需要在交付适配层替换 `DeviceIdProvider` 实现。

## 后装和升级

后装或升级包进入专网前，应确认本次覆盖的 SN 范围、SDK/HAR 版本、模型版本、license 文件和校验清单。设备不需要访问公网，SDK 初始化时在本地完成验签、App 绑定、签名证书绑定、SN 白名单、`sdkMajor` 和 `maintenanceUntil` 校验。

建议策略：

- `expiresAt` 由商务策略决定；本次 Android v0.2.7 使用固定到期日 `2026-08-25`。
- `maintenanceUntil` 控制能否升级到某个发布时间的 SDK 或模型版本。
- `sdkMajor` 不一致或维护期外升级需要重新签发 license。
- 新增设备、换机或 SN 变化时，需要提供新 SN 并重新签发全量或增量授权包。

## 方案边界

纯离线环境无法实时吊销已经进入现场的旧授权。吊销、新增设备或白名单收缩只能随下一次升级包、运维包或离线介质进入现场。如需防止回退到旧授权包，需要额外实现授权包版本号和本地防回退记录。
