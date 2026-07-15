# 鼎桥 HarmonyOS 离线 ASR SDK 0.2.4

本包为 SDK-only 交付，包含一个自包含 HAR 和客户文档；不包含 Demo HAP、License 或 TTS。
本交付内置 `zh-en` 中英识别模型，不包含粤语模型；声纹和警务术语能力保留。

| 路径 | 内容 |
| --- | --- |
| `har/amphion_dingqiao.har` | HarmonyOS API 12+、`arm64-v8a` 离线 ASR SDK |
| `docs/DINGQIAO_INTEGRATION.md` | 集成入口与调用顺序 |
| `docs/ASR_SDK_API_HARMONY.md` | 完整公开 API 契约 |
| `docs/LICENSE.md` | 商用授权接入 |
| `docs/TROUBLESHOOTING.md` | 故障排查与日志采集 |
| `docs/SDK_LIFECYCLE_PERFORMANCE_SUMMARY_20260713.md` | 生命周期性能摘要 |
| `docs/third-party/` | 第三方开源许可证 |
| `docs/checksum.txt` | 全部交付文件 SHA-256 清单 |

开始集成前请在本目录执行：

```bash
shasum -a 256 -c docs/checksum.txt
```

授权文件 `amphion-license.lic` 通过安全渠道单独下发。按硬件 SN 签发的 license 必须在能读取
同一 SN 的正式系统/预置宿主中验证，普通 Demo 的 ODID 不能替代硬件 SN。
