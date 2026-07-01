# Android SDK 交付邮件模板

各位好：

随信交付本次离线语音 Android SDK 更新包，请查收附件。本次共三个 zip：

1. ASR SDK 集成包：`<ASR_ZIP>`
2. TTS SDK 集成包：`<TTS_ZIP>`
3. License 授权包：`<LICENSE_ZIP>`

## 本次更新

TTS 更新：

- `<TTS_CHANGE_1>`
- `<TTS_CHANGE_2>`
- `<TTS_CHANGE_3>`

ASR 更新：

- `<ASR_CHANGE_1>`
- `<ASR_CHANGE_2>`
- `<ASR_CHANGE_3>`

License 更新：

- 本次正式 license 仅限制授权设备、授权能力和使用期限。
- 不限制应用包名 / applicationId；包名仅作为记录字段。
- 有效期：`<EXPIRES_AT>`。
- 授权能力：`<FEATURES>`。

## ASR 测试数据

| 域 | 命中率 |
| --- | --- |
| 派出所名称 | `<RATE>` |
| 车牌号 | `<RATE>` |
| 警务术语 | `<RATE>` |

## 验证结论

- ASR SDK：`<ASR_VERIFICATION_RESULT>`
- TTS SDK：`<TTS_VERIFICATION_RESULT>`
- License：`<LICENSE_VERIFICATION_RESULT>`
- 设备端回归：`<DEVICE_TEST_RESULT>`

## 复现说明

请以 zip 内文档为准完成集成和验证：

- ASR：`docs/DINGQIAO_INTEGRATION.md`、`docs/语音识别SDK接口.md`
- TTS：`docs/INTEGRATION.md`、`docs/API.md`
- License：`README.txt`、`checksum.txt`

如需核对文件完整性，请参考随包或邮件中的 `MANIFEST.md` / SHA-256。
