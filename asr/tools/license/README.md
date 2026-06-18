# Amphion 离线 License 签发工具

我方（供应商）用这套 CLI 生成密钥对、签发离线授权文件（`.lic`），交付给业务方放进 App。SDK 端用构建期内置的公钥离线验签，全程零网络。

适用 SDK 版本：0.2.x 起（SDK 端实现见 `asr/android/sdk/src/main/java/com/amphion/asr/internal/LicenseVerifier.kt`）。

## 0. 安装依赖

```bash
pip install -r requirements.txt   # 仅需 cryptography
```

## 1. 一次性：生成密钥对

```bash
python gen_keypair.py --out-private amphion-license-private.pem
# 生产环境建议加口令加密私钥：
python gen_keypair.py --out-private amphion-license-private.pem --password "<强口令>"
```

输出的公钥 base64 贴到 `asr/android/gradle.properties`：

```
AMPHION_LICENSE_PUBLIC_KEY=<这里粘贴公钥 base64>
```

注意：

- 私钥是整套授权体系的信任根，泄露 = 任何人都能签发有效 license。必须离线保管（密码管理器 / KMS / 保险库），严禁进 git、严禁外发。
- 公钥换新 = 已签发的所有旧 `.lic` 全部失效（需重签）。请把密钥对视为长期资产妥善备份。

## 2. 拿到业务方的绑定信息

签发前向业务方收集：

- applicationId（必填）：宿主 App 的包名。
- 签名证书 SHA-256（建议）：业务方用如下命令导出后给你，用于强绑定，防止改包名绕过。

```bash
keytool -list -v -keystore <release.keystore> -alias <alias> | grep "SHA256:"
# 形如 SHA256: AB:CD:...:EF
```

## 3. 签发 license

```bash
python issue_license.py \
    --private-key amphion-license-private.pem \
    --application-id com.acme.talkie \
    --customer "ACME Talkie Co." \
    --license-id AMP-2026-0001 \
    --expires 2027-06-03 \
    --install-tier LE_100K \
    --features ASR_ZH_EN,ASR_YUE_EN,TARGET_SPEAKER,HOTWORDS \
    --cert-sha256 AB:CD:...:EF \
    --out com.acme.talkie.lic
```

把产物 `com.acme.talkie.lic` 交付给业务方，让其放进 App 的 `assets/`，默认文件名 `amphion-license.lic`（可在 `AmphionOptions.licenseAssetName` 改）。

不带 `--expires` = 永久授权（买断）。`--install-tier` 是声明性档位（离线方案不实时计量，仅用于展示 / 审计）。

## 4. 自测校验

单份校验（复刻 SDK 端逻辑，可真实运行）：

```bash
python verify_license.py --license com.acme.talkie.lic \
    --public-key-b64 "<gradle.properties 里的公钥>" \
    --application-id com.acme.talkie \
    --cert-sha256 AB:CD:...:EF
```

端到端闭环自测（生成→签发→正确校验→错误用例拒绝）：

```bash
bash selftest.sh
```

## 5. `.lic` 文件结构

信封（与 SDK 端严格一致）：

```
{"payload_b64": "<base64(UTF-8 JSON of claims)>",
 "alg": "SHA256withECDSA",
 "sig_b64": "<base64(DER ECDSA-P256 signature over the decoded payload bytes)>"}
```

签名覆盖的是 payload 解码后的原始字节，SDK 端不重新序列化，从根上规避 canonical JSON 歧义。

payload claims 字段：

| 字段 | 含义 | 必填 |
| --- | --- | --- |
| applicationId | 绑定的宿主包名 | 是 |
| certSha256 | 绑定的签名证书 SHA-256，空=不绑 | 否 |
| customer | 客户名 | 否 |
| licenseId | 授权编号 | 否 |
| issuedAt | 签发日期 yyyy-MM-dd | 否 |
| expiresAt | 到期日期 yyyy-MM-dd，空=永久 | 否 |
| installTier | 装机量档位标识（声明性） | 否 |
| features | 授权功能模块列表 | 否 |
| sdkMajor | 兼容的 SDK 大版本 | 否 |

## 6. 校验失败错误码（与 SDK 端 AsrErrorCode 对齐）

| 错误码 | 含义 |
| --- | --- |
| 6001 | LICENSE_MISSING 未提供 license |
| 6002 | LICENSE_MALFORMED 格式损坏 / 缺必填字段 |
| 6003 | LICENSE_SIGNATURE_INVALID 验签未通过 |
| 6004 | LICENSE_APP_MISMATCH applicationId 不匹配 |
| 6005 | LICENSE_CERT_MISMATCH 签名证书不匹配 |
| 6006 | LICENSE_EXPIRED 已过期 |

## 7. 与交付流程的衔接

完整商业化交付 SOP 见 `asr/android/docs/DELIVERY.md`；授权方案与防破解边界见 `asr/android/docs/LICENSING.md`。

鼎桥 Demo Release（`com.amphion.dingqiao.demo`）专用脚本：

```bash
bash asr/tools/license/issue_dingqiao_demo.sh
# 默认自签发日起 2 个月试用（DINGQIAO_DEMO_TRIAL_MONTHS 可调）；绑定 demo release 证书 SHA-256
# 产物 → sample-dingqiao-demo/src/main/assets/amphion-license.lic
```

`asr/tools/delivery/pack_dingqiao_*.sh` 在构建 Demo Release 前会自动调用上述脚本。
