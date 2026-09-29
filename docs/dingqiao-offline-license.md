# 鼎桥离线 License 交付前置清单（当前口径）

本文是鼎桥专网交付前的信息收集清单。实现细节以 Android/Harmony SDK 内的 `amphion-license.lic` 为准；ASR 与 TTS 可共用同一份 license、公钥和设备白名单。本文只记录当前规则，不写入某次历史交付的 zip 路径、固定到期日或 SN 数量。

## 每批授权范围

| 对象 | 能力与设备 | 有效期 |
| --- | --- | --- |
| Demo 体验授权 | 按本批声明；普通安装体验不应依赖宿主无法读取的系统 SN | 按本批约定，不固定两个月或四个月 |
| 正式设备白名单授权 | 只授予约定的 ASR/TTS 能力，并绑定已确认的 SN 清单 | 永久或指定期限须在申请中明确 |

Android ASR 不检查包名；Android TTS 对非空 `applicationId`（为空时回退 `bundleName`）仍执行匹配检查。不绑定应用的共用授权必须将这两个 claims 留空，应用标识只写签发登记。证书字段非空时执行证书校验。完整签发流程见[统一授权工具](../tools/license/README.md)。

## 交付前鼎桥需要提供的信息

| 类别 | 鼎桥需提供 | 用途 |
| --- | --- | --- |
| App 标识 | Android applicationId、HarmonyOS bundleName | 记录在申请/登记中；不绑定应用时不写入 claims |
| 签名信息 | 正式签名证书 SHA-256 指纹，建议大写十六进制 | 可选记录字段；正式设备白名单 license 默认不绑定签名 |
| 设备 SN | 首批授权设备 SN 清单，一行一个；说明 SN 字段名和样例 | 生成 authorizedDeviceHashes 白名单 |
| SN 稳定性 | SN 在系统升级、恢复出厂、主板维修、换机后的变化规则 | 评估换机和重签流程 |
| SN 读取方式 | Android 端使用 Build.getSerial()；宿主为系统应用，并申请 android.permission.READ_PRIVILEGED_PHONE_STATE | 运行时向 SDK 注入本机 SN |
| 授权能力 | 是否授权 ASR、是否授权 TTS | 写入 features，仅允许 ASR 和 TTS |
| 版本范围 | 授权 SDK 大版本 sdkMajor、维护期 maintenanceUntil | 控制大版本和维护期外升级 |
| 运行期限 | expiresAt 是否为空、固定日期或签发日起几个月 | 控制运行到期策略 |
| 组包责任 | 后装包或升级包由哪一方组包 | 确认 license、SDK/HAR、模型放置责任 |
| 固定路径 | App assets 或 rawfile 中 license 的固定路径 | SDK 初始化时读取 amphion-license.lic |
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
| applicationId | 不绑定应用时留空；Android TTS 对非空值校验 |
| bundleName | 不绑定应用时留空；Android TTS 可用作兼容回退 |
| signingCertDigest | 客户应用正式签名证书 SHA-256；正式设备白名单 license 默认为空 |
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

后装或升级包进入专网前，应确认本次覆盖的 SN 范围、SDK/HAR 版本、模型版本、license 文件和校验清单。设备不需要访问公网，SDK 初始化时在本地完成验签、SN 白名单、`sdkMajor` 和 `maintenanceUntil` 校验；应用绑定条件按上述平台差异及实际 claims 核对。

建议策略：

- `expiresAt` 由本批明确约定，不在通用文档中写死期限。
- `maintenanceUntil` 控制能否升级到某个发布时间的 SDK 或模型版本。
- `sdkMajor` 不一致或维护期外升级需要重新签发 license。
- 新增设备、换机或 SN 变化时，需要提供新 SN 并重新签发全量或增量授权包。

## 方案边界

纯离线环境无法实时吊销已经进入现场的旧授权。吊销、新增设备或白名单收缩只能随下一次升级包、运维包或离线介质进入现场。如需防止回退到旧授权包，需要额外实现授权包版本号和本地防回退记录。
