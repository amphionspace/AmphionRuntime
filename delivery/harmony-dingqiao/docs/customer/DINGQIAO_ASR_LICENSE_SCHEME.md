# Amphion HarmonyOS 离线 ASR 授权方案

## 1. 方案

SDK 使用本地签名 License，不依赖公网激活：

1. 我方私钥对授权声明签名。
2. SDK 内置生产验签公钥，在设备本地验证签名。
3. 本次授权不绑定应用包名、签名证书或设备标识。
4. `sdkMajor=0` 且 `maintenanceUntil` 为空，不限制 SDK 主版本或升级维护期。
5. `expiresAt` 控制运行有效期；为空时表示已授权版本不按日期停机。

`amphion-license.lic` 由签发方另行提供，或继续使用既有有效授权；SDK-only ZIP 不包含授权文件，
签发私钥也不进入交付物。

## 2. 授权声明

License 为 UTF-8 JSON 信封，签名覆盖原始授权声明字节：

```json
{
  "payload_b64": "<base64 claims>",
  "alg": "SHA256withECDSA",
  "sig_b64": "<signature>"
}
```

本次授权声明包含客户标识、授权编号、`ASR` 能力、签发日期和运行到期日；SDK 主版本设为不限制，应用包名、签名证书、维护期和设备白名单均为空。

## 3. 应用与设备范围

`applicationId`、`bundleName`、`signingCertDigest` 和 `authorizedDeviceHashes` 均为空，因此同一份授权可用于不同包名和设备。宿主无需为本授权提供硬件 SN 或 ODID。

## 4. 版本规则

- License 的 `sdkMajor=0`，不限制 SDK 主版本。
- SDK 发布日期晚于 `maintenanceUntil` 时，升级权益失效，需要续期。
- 维护期到期不会自动改变已经安装版本的 `expiresAt` 语义。
- 四个月运行有效期到期后需重新签发。

## 5. 集成与错误处理

公共调用顺序和代码示例见 [INTEGRATION.md](INTEGRATION.md)，授权错误码见 [LICENSE.md](LICENSE.md)。

授权失败时应记录错误码和脱敏 message，不得把 License 原文、设备标识或私钥材料写入日志。纯离线环境无法实时吊销已经离线安装的旧授权；吊销清单需随下一次升级或运维介质进入现场。

## 6. 边界

离线验签可以阻止普通复制、篡改和设备误用，但端侧代码理论上仍可能被逆向或替换。需要更强保护时可增加 native 完整性校验和系统级可信执行环境，代价是适配、排障和升级复杂度上升。
