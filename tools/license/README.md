# Amphion 统一离线 License 签发工具

我方用这套 CLI 生成密钥对、签发离线授权文件（`.lic`），交付给业务方放进 App。ASR 与 TTS 共享同一份 `amphion-license.lic`、同一套 claims 字段和同一套 SN 白名单哈希算法。

## 0. 安装依赖

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`openpyxl==3.1.5` 是正式 Excel 输入门禁的一部分：工具据此区分文本、数字、日期和公式单元格。没有该依赖时，正式流程不接受 `.xlsx`。

## 1. 正式商用交付入口

正式设备白名单交付统一使用 `license_delivery.py`，流程固定为 `plan -> issue -> verify -> record`。旧的 `issue_license.py` 保留兼容，但不提供 Excel 输入、风险确认、最终 ZIP 验收和 Git 台账门禁。

先复制并填写 [`license-request.example.json`](license-request.example.json)。申请必须显式声明永久/到期、无限/有限维护期、包名记录、证书绑定和完整源文件摘要；正式流程固定 `deviceBinding=required`。

```bash
.venv/bin/python license_delivery.py plan \
  --request /受控目录/license-request.json \
  --input-dir /受控目录/sn-input \
  --out /受控目录/plan.json

.venv/bin/python license_delivery.py issue \
  --repo "$(git rev-parse --show-toplevel)" \
  --request /受控目录/license-request.json \
  --plan /受控目录/plan.json \
  --input-dir /受控目录/sn-input \
  --operator "<操作者身份>" \
  --acknowledge DUPLICATE_SN \
  --out-dir /受控目录/output

.venv/bin/python license_delivery.py verify \
  --repo "$(git rev-parse --show-toplevel)" \
  --request /受控目录/license-request.json \
  --plan /受控目录/plan.json \
  --input-dir /受控目录/sn-input \
  --zip /受控目录/output/<deliveryId>.zip \
  --operator "<验收人身份>" \
  --out-prefix /受控目录/output/<deliveryId>.zip

.venv/bin/python license_delivery.py record \
  --repo "$(git rev-parse --show-toplevel)" \
  --zip /受控目录/output/<deliveryId>.zip \
  --issuance /受控目录/output/<deliveryId>.issuance.json \
  --verification /受控目录/output/<deliveryId>.zip.verification.json \
  --operator "<交付人身份>" \
  --delivered-at YYYY-MM-DD
```

有 `previousLicenseId` 时，四个涉及 SN 重算的阶段都必须提供旧版完整申请和旧版输入目录；不能用增量 SN 文件直接签发：

```text
--previous-request /受控目录/previous/license-request.json
--previous-input-dir /受控目录/previous/sn-input
```

计划中的每个 warning 都必须用独立的 `--acknowledge <code>` 确认。`--allow-dirty` 只生成 `production=false` 的排查产物，`record` 永远拒绝登记。

客户 ZIP 固定只含六个文件，不含明文 SN、设备哈希全集、源文件、私钥位置或本机绝对路径。验收回执在 ZIP 外生成，因为 ZIP 不能包含自身摘要。Git 台账只保存随机 `snSetId`、数量和产物摘要；原始申请、计划、签发回执、验收回执和正式 ZIP 应保存在组织批准的受控制品域。

## 2. 一次性生成密钥对

```bash
.venv/bin/python gen_keypair.py --out-private amphion-license-private.pem
```

生产环境建议加口令加密私钥：

```bash
.venv/bin/python gen_keypair.py --out-private amphion-license-private.pem --password "<强口令>"
```

输出的公钥 base64 填进各端构建配置的 `AMPHION_LICENSE_PUBLIC_KEY`。私钥是整套授权体系的信任根，泄露后任何人都能签发有效 license，必须离线保管，严禁进 git、严禁外发。

## 3. 兼容签发入口

```bash
.venv/bin/python issue_license.py \
  --private-key amphion-license-private.pem \
  --customer "ACME Co." \
  --license-id AMP-2026-0001 \
  --device-id-file devices.txt \
  --expires 2027-06-03 \
  --maintenance-until 2027-06-30 \
  --install-tier LE_100K \
  --features ASR,TTS \
  --out amphion-license.lic
```

`features` 只放产品级授权项：`ASR`、`TTS` 或两者。语言、警务增强、热词、声纹、模型名都不是 license feature。

`--application-id` 和 `--bundle-name` 可选，仅写入记录，不作为 Android 端授权边界。设备 SN 白名单使用：

```text
SHA-256(trim(upper(serial)) + deviceIdSaltId)
```

默认 `deviceIdSaltId` 为：

```text
DQ-TIASSISTANT-20260623-69CD375699165832C1D2E9EA77C8BE71
```

## 4. 本地校验

```bash
.venv/bin/python verify_license.py \
  --license amphion-license.lic \
  --public-key-b64 "<构建配置里的公钥>" \
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

## 5. `.lic` 文件结构

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
| applicationId | Android 宿主包名记录，不参与 Android 绑定校验 | 否 |
| bundleName | HarmonyOS bundleName 记录，不参与 Android 绑定校验 | 否 |
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

## 6. 旧入口兼容

`asr/tools/license/` 下的通用 Python 脚本保留为兼容包装器，实际执行这里的共享工具。TTS 交付分支应直接复用 `tools/license/`，不要再复制一套签发逻辑。
