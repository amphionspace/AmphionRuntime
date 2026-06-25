# Amphion 统一离线 License 签发工具

我方用这套 CLI 生成密钥对、签发离线授权文件（`.lic`），交付给业务方放进 App。ASR 与 TTS 共享同一份 `amphion-license.lic`、同一套 claims 字段和同一套 SN 白名单哈希算法。

## 0. 安装依赖

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 1. 一次性生成密钥对

```bash
.venv/bin/python gen_keypair.py --out-private amphion-license-private.pem
```

生产环境建议加口令加密私钥：

```bash
.venv/bin/python gen_keypair.py --out-private amphion-license-private.pem --password "<强口令>"
```

输出的公钥 base64 填进各端构建配置的 `AMPHION_LICENSE_PUBLIC_KEY`。私钥是整套授权体系的信任根，泄露后任何人都能签发有效 license，必须离线保管，严禁进 git、严禁外发。

## 2. 签发统一 license

```bash
.venv/bin/python issue_license.py \
  --private-key amphion-license-private.pem \
  --application-id com.acme.app \
  --customer "ACME Co." \
  --license-id AMP-2026-0001 \
  --device-id-file devices.txt \
  --expires 2027-06-03 \
  --maintenance-until 2027-06-30 \
  --install-tier LE_100K \
  --features ASR,TTS \
  --cert-sha256 AB:CD:...:EF \
  --out amphion-license.lic
```

`features` 只放产品级授权项：`ASR`、`TTS` 或两者。语言、警务增强、热词、声纹、模型名都不是 license feature。

设备 SN 白名单使用：

```text
SHA-256(trim(upper(serial)) + deviceIdSaltId)
```

默认 `deviceIdSaltId` 为：

```text
DQ-TIASSISTANT-20260623-69CD375699165832C1D2E9EA77C8BE71
```

## 3. 本地校验

```bash
.venv/bin/python verify_license.py \
  --license amphion-license.lic \
  --public-key-b64 "<构建配置里的公钥>" \
  --application-id com.acme.app \
  --cert-sha256 AB:CD:...:EF \
  --device-id SN001 \
  --sdk-major 1 \
  --sdk-release-date 2026-06-23 \
  --required-feature ASR
```

TTS 包验收时把 `--required-feature` 改成 `TTS`。

端到端闭环自测：

```bash
bash selftest.sh
```

## 4. `.lic` 文件结构

信封：

```json
{
  "payload_b64": "<base64(UTF-8 JSON of claims)>",
  "alg": "SHA256withECDSA",
  "sig_b64": "<base64(DER ECDSA-P256 signature over decoded payload bytes)>"
}
```

签名覆盖 payload 解码后的原始字节，SDK 端不重新序列化，避免不同 JSON 序列化方式导致验签不一致。

payload claims 字段：

| 字段 | 含义 | 必填 |
| --- | --- | --- |
| applicationId | 绑定的 Android 宿主包名 | 是 |
| bundleName | HarmonyOS bundleName，默认同 applicationId | 否 |
| certSha256 | 兼容字段，绑定签名证书 SHA-256 | 否 |
| signingCertDigest | 绑定签名证书 SHA-256 | 否 |
| customer | 客户名 | 否 |
| deviceIdHashAlg | 设备哈希算法，目前固定 SHA-256 | 否 |
| deviceIdSaltId | 设备 SN 哈希盐编号 | 否 |
| authorizedDeviceHashes | 授权设备哈希列表 | 否 |
| licenseId | 授权编号 | 否 |
| issuedAt | 签发日期 yyyy-MM-dd | 否 |
| expiresAt | 到期日期 yyyy-MM-dd，空表示永久 | 否 |
| maintenanceUntil | 可升级维护期 yyyy-MM-dd，空表示不限制 | 否 |
| installTier | 装机量档位标识 | 否 |
| features | 产品级授权能力列表，仅允许 ASR、TTS | 否 |
| sdkMajor | 兼容 SDK 大版本 | 否 |

## 5. 旧入口兼容

`asr/tools/license/` 下的通用 Python 脚本保留为兼容包装器，实际执行这里的共享工具。TTS 交付分支应直接复用 `tools/license/`，不要再复制一套签发逻辑。
