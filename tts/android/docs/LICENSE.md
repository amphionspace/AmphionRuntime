# Amphion 离线 License 机制

面向 To B 私有化交付的纯离线（零网络）授权。本文讲机制与设计取舍；签发 / 校验的操作步骤见
`tts/tools/license/README.md`，集成步骤见 `INTEGRATION.md` 第 11 节。

## 1. 目标与边界

- 离线：终端零联网即可校验；我方不运营任何在线授权服务。
- 防转移：license 与宿主 applicationId / bundleName 绑定，叠加签名证书和设备 SN 白名单。
- 防篡改：ECDSA 数字签名；客户拿到的是公钥，无法伪造 / 改写 license。
- 开发无摩擦：未注入公钥的构建（开发 / 内部）自动处于 DEV_UNLICENSED，不做任何校验。
- 鼎桥 Android v0.2.7 正式 license 面向 `com.tdtech.tiassistant`，`features=ASR,TTS`，绑定 SN 清单并与 ASR 共用；ASR Demo APK 的限期 license 不绑 SN，只用于 Demo 体验。

边界（诚实声明）：离线方案无法对抗「持有 root 的对手反编译 + 打补丁绕过校验」。本方案目标是
抬高门槛、约束正常商业客户的越权使用，不是 DRM 级强对抗。release 开启 R8 混淆 internal 验签
逻辑即是这一权衡下的硬化手段。

## 2. 密码学与信封

| 项 | 取值 | 理由 |
|---|---|---|
| 签名算法 | ECDSA P-256 + SHA256（SHA256withECDSA） | minSdk 24 全覆盖；Ed25519 需 API 33 |
| 公钥格式 | X.509 SubjectPublicKeyInfo(DER) 的 base64 | 构建期注入 BuildConfig.LICENSE_PUBLIC_KEY_B64 |
| 签名对象 | payload_b64 解码后的原始字节 | 规避 canonical JSON 歧义，签发端与 SDK 逐字节一致 |
| base64 | 标准字母表、无换行 | 与 Python base64.b64encode 对齐 |

.lic 文件（UTF-8 JSON）：

```json
{
  "payload_b64": "<base64(UTF-8 JSON of claims)>",
  "alg": "SHA256withECDSA",
  "sig_b64": "<base64(DER ECDSA-P256 signature over the decoded payload bytes)>"
}
```

payload（claims）字段：

| 字段 | 含义 | 空值语义 |
|---|---|---|
| applicationId | 绑定 Android 宿主包名 | 空=不用 Android 包名绑定 |
| bundleName | 绑定 HarmonyOS bundleName | 空=不用 Harmony 包名绑定 |
| signingCertDigest | 绑定签名证书 SHA-256 | 空=不绑证书 |
| deviceIdHashAlg / deviceIdSaltId / authorizedDeviceHashes | SN 白名单绑定 | 空=不绑设备 |
| expiresAt | 到期日 yyyy-MM-dd | 空=已授权版本不因时间停机 |
| maintenanceUntil | 可升级维护期 yyyy-MM-dd | 空=不限制维护期 |
| customer / licenseId / installTier / features / issuedAt / sdkMajor | 授权和审计信息 | 用于展示、排障和版本控制 |

设备白名单算法：SHA-256(normalizedSn + deviceIdSaltId)，大写 hex、无冒号。SN 由宿主或交付适配层通过 `TtsDeviceIdProvider` 注入。

## 3. SDK 端校验流程

入口 `LicenseVerifier.verify(ctx, ...)` 解析宿主 packageName / 签名证书 / 设备 SN 后委托
`verifyResolved(...)`（纯字符串、无 Android 依赖，可离设备单测）。顺序：

1. 公钥为空 → DEV_UNLICENSED，放行
2. license 缺失 → LICENSE_MISSING（1002300012）
3. 信封 / payload 解析失败 → LICENSE_MALFORMED（1002300013）
4. 验签失败 → LICENSE_SIGNATURE_INVALID（1002300014）
5. applicationId 不符 → LICENSE_APP_MISMATCH（1002300015）
6. certSha256 非空且不符 → LICENSE_CERT_MISMATCH（1002300016）
7. expiresAt 非空且超期（含宽限）→ LICENSE_EXPIRED（1002300017）
8. sdkMajor 不符 → LICENSE_SDK_MAJOR_MISMATCH（1002300019）
9. maintenanceUntil 早于当前 SDK 发布时间 → LICENSE_MAINTENANCE_EXPIRED（1002300020）
10. features 不包含 TTS → LICENSE_FEATURE_MISSING（1002300021）
11. authorizedDeviceHashes 非空且 SN 哈希未命中 → LICENSE_DEVICE_MISMATCH（1002300018）
12. 全部通过 → LICENSED

到期判定：到期日当天有效，deadline = expiresAt + (graceDays + 1) 天，now >= deadline 才算过期。

## 4. 接入点设计（与 police 参考分支的差异）

police 参考分支用强制的 `AmphionRuntime.init(context)` 拿 Context 并验签一次。TTS SDK 通过内部
`AndroidAppContext` 反射自动发现 ApplicationContext，因此不强制业务方先 init：

- `TextToSpeechSdk.init(context, options)`：police 风格显式入口，验签一次并缓存；ENFORCE 下失败抛异常。
- `createEngine` 门禁：若未显式 init，则用自动发现的 Context 懒校验一次并缓存。无 Context
  （纯 JVM 单测）或未武装（公钥为空）一律放行。
- 校验在 `createEngine`（模型加载、价值所在）处强制，`listVoices`（静态元数据）不拦。

这样既照搬了 police 的验签内核（claims / 签名 / 绑定 / 状态机 / DEV_UNLICENSED / ENFORCE-PERMISSIVE），
又适配了 TTS「直接 createEngine、纯 JVM 单测」的现有架构，不破坏既有调用方与测试。

## 5. 强制策略

| 策略 | 校验失败时行为 |
|---|---|
| ENFORCE（默认） | init / createEngine 抛 TextToSpeechException，licenseStatus = INVALID |
| PERMISSIVE | 不抛异常，licenseStatus = INVALID，由业务方决定提示 / 降级 |

仅在 SDK 被武装时策略才生效；未武装恒为 DEV_UNLICENSED。

## 6. 状态机

| state | 含义 |
|---|---|
| NOT_INITIALIZED | 尚未触发任何校验 |
| DEV_UNLICENSED | 未武装（公钥为空），不校验、功能可用 |
| LICENSED | 校验通过 |
| INVALID | 校验失败 |

## 7. 构建期注入

gradle 属性 `AMPHION_LICENSE_PUBLIC_KEY` → `BuildConfig.LICENSE_PUBLIC_KEY_B64`：

- 留空（默认）：开发 / 内部构建，不武装。
- 正式交付：填入 `tools/license/gen_keypair.py` 生成的公钥；私钥严禁进库。
- 可用 `-PAMPHION_LICENSE_PUBLIC_KEY=...` 注入，避免公钥进 VCS。
- 不再保留 TTS 独立公钥属性；ASR 与 TTS 共用同一份 `amphion-license.lic`。
