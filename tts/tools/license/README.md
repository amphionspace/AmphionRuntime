# TTS 授权工具入口

新签发统一使用仓库 [tools/license](../../../tools/license/README.md) 的申请、签发、验证和登记流程。本目录旧脚本仅保留兼容，不维护第二套正式操作步骤。

ASR 与 TTS 可使用同一签名信封，但必须同时满足各 SDK 的授权能力和绑定条件：

- Android ASR 不校验应用包名。
- Android TTS 会校验非空 `applicationId`；为空时回退到非空 `bundleName`。不匹配返回 `1002300015`。
- 不绑定应用的共用授权必须将两个 claims 字段都留空。业务应用标识保留在签发登记中。
- 证书、SN 白名单、运行期限、主版本和维护期以授权声明为准，不把某一批的试用策略写成通用规则。

业务接入与可选 SN provider 见 [Android TTS 接入说明](../../android/docs/INTEGRATION.md)。私钥、原始 SN 清单与实际授权文件不进源码仓库。
