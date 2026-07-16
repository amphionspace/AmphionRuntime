# 鼎桥 HarmonyOS 离线 ASR 授权方案

## 1. 方案

SDK 使用本地签名 License，不依赖公网激活：

1. 我方私钥对授权声明签名。
2. SDK 内置生产验签公钥，在设备本地验证签名。
3. 可按双方约定的稳定设备标识建立哈希白名单。
4. `sdkMajor` 与 `maintenanceUntil` 控制版本升级权益。
5. `expiresAt` 控制运行有效期；为空时表示已授权版本不按日期停机。

实际 `amphion-license.lic` 不在 SDK ZIP 内，通过安全渠道单独下发。

## 2. 授权声明

License 为 UTF-8 JSON 信封，签名覆盖原始授权声明字节：

```json
{
  "payload_b64": "<base64 claims>",
  "alg": "SHA256withECDSA",
  "sig_b64": "<signature>"
}
```

授权声明包含客户标识、授权编号、设备标识哈希、`ASR` 能力、SDK 主版本、维护期、签发日期和可选运行到期日。设备白名单只保存哈希，不保存明文设备标识。

## 3. 设备标识

系统或预置宿主优先注入稳定硬件 SN；普通应用可以与我方另行约定 ODID。签发清单与运行时 `LicenseDeviceIdProvider` 必须使用同一种标识，不能用 ODID 验收按 SN 签发的授权。

设备标识不应硬编码进 HAP，也不应写入业务日志。恢复出厂、主板维修或签名变化可能改变部分标识，发生变化后需要重新签发。

## 4. 版本规则

- License 的 `sdkMajor` 必须与 SDK 授权主版本一致。
- SDK 发布日期晚于 `maintenanceUntil` 时，升级权益失效，需要续期。
- 维护期到期不会自动改变已经安装版本的 `expiresAt` 语义。
- 新增设备、换机或维护期外升级均通过重新签发完成。

## 5. 集成与错误处理

公共调用顺序和代码示例见 [DINGQIAO_INTEGRATION.md](DINGQIAO_INTEGRATION.md)，授权错误码见 [LICENSE.md](LICENSE.md)。

授权失败时应记录错误码和脱敏 message，不得把 License 原文、设备标识或私钥材料写入日志。纯离线环境无法实时吊销已经离线安装的旧授权；吊销清单需随下一次升级或运维介质进入现场。

## 6. 边界

离线验签可以阻止普通复制、篡改和设备误用，但端侧代码理论上仍可能被逆向或替换。需要更强保护时可增加 native 完整性校验和系统级可信执行环境，代价是适配、排障和升级复杂度上升。
