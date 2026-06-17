# Lits TTS 离线 License 工具链

纯离线（零网络）的 To B 授权方案：ECDSA P-256 + SHA256 签名，绑定 applicationId（必）、
签名证书 SHA-256（可选）、设备指纹（可选单机），可选到期日。SDK 端验签逻辑见
`android/TtsRuntime/sdk/src/main/java/com/lits/tts/sdk/internal/LicenseVerifier.kt`。

## 角色与产物

| 角色 | 动作 | 产物 | 去向 |
|---|---|---|---|
| 我方（一次性） | gen_keypair.py | 私钥 PEM + 公钥 base64 | 私钥离线保管；公钥进 gradle.properties |
| 我方（每客户） | issue_license.py | 客户的 .lic | 交付给业务方放进 app assets |
| 业务方 | 放置 .lic + 集成 SDK | 武装后的 release 包 | 终端设备 |
| 任意方 | verify_license.py | 校验结论 | 本地自测，确认链路对称 |

## 准备

```bash
pip install -r requirements.txt
```

## 1. 生成密钥对（一次性，全产品线复用一把即可）

```bash
python gen_keypair.py --out-private lits-tts-license-private.pem
```

- 私钥 lits-tts-license-private.pem：严禁进库、严禁外发，离线保管（建议加 --password 口令）。
- 打印出的公钥 base64：填到 android/TtsRuntime/gradle.properties 的
  LITS_TTS_LICENSE_PUBLIC_KEY（或构建时 -PLITS_TTS_LICENSE_PUBLIC_KEY=...）。
- 公钥为空时 SDK 不武装 license（开发 / 内部构建，不做任何校验）。

## 2. 签发客户 license

绑定 applicationId（必），可选叠加证书 / 设备 / 到期：

```bash
python issue_license.py \
    --private-key lits-tts-license-private.pem \
    --application-id com.acme.reader \
    --customer "ACME Reader Co." \
    --license-id LITS-TTS-2026-0001 \
    --expires 2027-06-03 \
    --install-tier LE_100K \
    --features TTS_ZH_EN \
    --out com.acme.reader.lic
```

单机绑定：先在目标真机 release 包上取设备指纹，再签发：

```kotlin
val fp = TextToSpeechSdk.deviceLicenseFingerprint(context) // SHA-256("{pkg}|{ANDROID_ID}")
```

```bash
python issue_license.py ... --device-sha256 <上一步的指纹> --out com.acme.reader.lic
```

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
