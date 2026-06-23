# Amphion 离线 License 工具链

纯离线（零网络）的 To B 授权方案：ECDSA P-256 + SHA256 签名，绑定 applicationId / bundleName、
签名证书 SHA-256、设备 SN 白名单，可选到期日和维护期。SDK 端验签逻辑见
`tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/LicenseVerifier.kt`。

## 角色与产物

| 角色 | 动作 | 产物 | 去向 |
|---|---|---|---|
| 我方（一次性） | gen_keypair.py | 私钥 PEM + 公钥 base64 | 私钥离线保管；公钥进 ASR/TTS gradle.properties |
| 我方（每客户） | issue_license.py | 客户的 .lic | 交付给业务方放进 app assets |
| 业务方 | 放置 .lic + 集成 SDK | 武装后的 release 包 | 终端设备 |
| 任意方 | verify_license.py | 校验结论 | 本地自测，确认链路对称 |

## 准备

```bash
pip install -r requirements.txt
```

## 1. 生成密钥对（一次性，ASR/TTS 共用一把）

```bash
python gen_keypair.py --out-private amphion-license-private.pem
```

- 私钥 amphion-license-private.pem：严禁进库、严禁外发，离线保管（建议加 --password 口令）。
- 打印出的公钥 base64：填到 ASR/TTS Android gradle.properties 的
  AMPHION_LICENSE_PUBLIC_KEY（或构建时 -PAMPHION_LICENSE_PUBLIC_KEY=...）。
- 公钥为空时 SDK 不武装 license（开发 / 内部构建，不做任何校验）。

## 2. 签发客户 license

绑定 applicationId（必），可选叠加证书 / 设备 / 到期：

```bash
python issue_license.py \
    --private-key amphion-license-private.pem \
    --application-id com.acme.reader \
    --customer "ACME Reader Co." \
    --license-id AMP-2026-0001 \
    --device-id-file devices.txt \
    --device-id-salt-id DQ-TIASSISTANT-20260623-69CD375699165832C1D2E9EA77C8BE71 \
    --expires 2027-06-03 \
    --maintenance-until 2027-06-30 \
    --install-tier LE_100K \
    --features ASR,TTS \
    --out amphion-license.lic
```

设备白名单绑定：鼎桥提供授权 SN 清单后再签发：

```text
SN001
SN002
SN003
```

```bash
python issue_license.py ... --device-id-file devices.txt --out amphion-license.lic
```

本项目默认 `deviceIdSaltId` 固定为 `DQ-TIASSISTANT-20260623-69CD375699165832C1D2E9EA77C8BE71`，一般无需手工传 `--device-id-salt-id`。

## 3. 本地自测（无需 Android）

```bash
python verify_license.py \
    --license com.acme.reader.lic \
    --public-key-b64 "<gradle.properties 里的公钥>" \
    --application-id com.acme.reader
```

退出码 0 即通过；非 0 的错误码与 SDK 端 TtsErrorCode 的 LICENSE_* 段一致。

## .lic 信封格式

```json
{
  "payload_b64": "<base64(UTF-8 JSON of claims)>",
  "alg": "SHA256withECDSA",
  "sig_b64": "<base64(DER ECDSA-P256 signature over the decoded payload bytes)>"
}
```

签名覆盖的是 payload_b64 解码后的原始字节，不重新序列化，从根上规避 canonical JSON 歧义。
