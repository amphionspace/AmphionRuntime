# 鼎桥 Android v0.2.7 交付记录

## 问题复述

本次交付要同时满足两件事：客户拿到 Demo APK 后能普通安装并完成体验；正式 SDK 授权仍能限制到鼎桥 App、签名证书、SN 清单和到期时间。

## 关键假设

| 假设 | 风险 |
| --- | --- |
| Demo APK 是普通安装包，不具备系统应用读取 SN 的权限 | 高 |
| 正式 `com.tdtech.tiassistant` 可在量产环境读取或注入设备 SN | 中 |
| ASR 与 TTS 正式授权需要共用同一份 license | 中 |

## 结论

| 对象 | 交付策略 |
| --- | --- |
| Demo APK | 内置 Demo license，绑定 `com.amphion.dingqiao.demo` 和 Demo 签名，只限制期限，不绑定 SN |
| 正式 SDK license | 单独下发 `amphion-license.lic`，绑定 `com.tdtech.tiassistant`、Release 签名证书、SN 白名单和期限 |
| 授权能力 | Demo 为 `ASR`；正式 license 为 `ASR,TTS`，供 ASR 与 TTS 共用 |
| 到期时间 | Demo 和正式 license 均为 `2026-08-25` |
| 声纹模型 | `eres2net.onnx` 固定内置在 AAR / APK assets 中，运行时自动准备到 `setWorkPath` |

## 本次产物

| 产物 | 路径 | 关键状态 |
| --- | --- | --- |
| ASR 客户交付包 | `/Users/boxp/workspace/delivery/amphion-dingqiao-v0.2.7-customer-20260625.zip` | AAR/APK 均包含 `libsherpa-onnx-jni.so` 和 `libonnxruntime.so` |
| 独立 license 包 | `/Users/boxp/workspace/delivery/amphion-dingqiao-license-v0.2.7-20260625.zip` | `features=ASR,TTS`，SN 白名单 16 台，到期 `2026-08-25` |

## 验证结果

- Demo license：`applicationId=com.amphion.dingqiao.demo`，`features=ASR`，`device_hash_count=0`，`expiresAt=2026-08-25`。
- 正式 SDK license：`applicationId=com.tdtech.tiassistant`，`features=ASR,TTS`，`device_hash_count=16`，`expiresAt=2026-08-25`。
- 设备实测：Demo APK 普通安装后显示“引擎就绪，点击开始识别”，没有 `device SN unavailable`、`dlopen failed` 或崩溃日志。
- 声纹模型实测：安装后不需要手动导入 `eres2net.onnx`，SDK 可自动把模型准备到工作目录。

## 后续规则

- 不要给 Demo APK 内置 SN 绑定 license；普通三方 App 在 Android 上通常无法读取系统 SN，会导致 `createEngine` 失败。
- 正式客户 App 使用 SN 绑定 license 时，必须确认宿主能读取或注入稳定 SN；否则会返回设备不匹配或 SN 不可用。
- 每次重新交付前，必须从最终 zip 中反查 Demo license 和正式 license 的 claims，不能只相信脚本参数。
- 每次重新交付前，必须验证 AAR 和 Demo APK 都包含 `assets/amphion-dingqiao/eres2net.onnx`，客户包不再提供外置 `models/eres2net.onnx`。
