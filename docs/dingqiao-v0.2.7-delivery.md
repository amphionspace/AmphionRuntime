# 鼎桥 Android v0.2.7 历史交付记录

> 历史归档：本文只追溯 2026-06-25 的 v0.2.7 产物、假设和验证结果，不作为当前规则。当前入口见[统一交付流程](../delivery/ASR_DELIVERY_WORKFLOW.md)和[授权工具说明](../tools/license/README.md)；应用标识是否校验须区分 ASR/TTS 与实际 claims。

## 问题复述

本次历史交付要同时满足两件事：客户拿到 Demo APK 后能普通安装并完成体验；正式 SDK 授权限制到当时约定的客户 App 记录、签名证书、SN 清单和到期时间。该策略已被后续 v3.0 交付口径替换。

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
| 正式 SDK license | 单独下发 `amphion-license.lic`，当时记录为 `com.tdtech.tiassistant`、Release 签名证书、SN 白名单和期限 |
| 授权能力 | Demo 为 `ASR`；正式 license 为 `ASR,TTS`，供 ASR 与 TTS 共用 |
| 到期时间 | Demo 和正式 license 均为 `2026-08-25` |
| 声纹模型 | `eres2net.onnx` 固定内置在 AAR / APK assets 中，运行时自动准备到 `setWorkPath` |
| 验证口径 | Demo 验证使用 Demo APK 内置 license；正式 license zip 只在 `com.tdtech.tiassistant` 正式宿主中验证 |

## 本次产物

| 产物 | 路径 | 关键状态 |
| --- | --- | --- |
| ASR 客户交付包 | `amphion-dingqiao-v0.2.7-customer-20260625.zip` | AAR/APK 均包含 `libsherpa-onnx-jni.so` 和 `libonnxruntime.so` |
| 独立 license 包 | `amphion-dingqiao-license-v0.2.7-20260625.zip` | `features=ASR,TTS`，SN 白名单 16 台，到期 `2026-08-25` |

## 验证结果

- Demo license：`applicationId=com.amphion.dingqiao.demo`，`features=ASR`，`device_hash_count=0`，`expiresAt=2026-08-25`。
- 正式 SDK license：历史记录字段 `applicationId=com.tdtech.tiassistant`，`features=ASR,TTS`，`device_hash_count=16`，`expiresAt=2026-08-25`。
- 设备实测：从最终 zip 解压出的 Demo APK 普通安装后显示“引擎就绪，点击开始识别”，没有 `device SN unavailable`、`dlopen failed` 或崩溃日志。
- 声纹模型实测：安装后不需要手动导入 `eres2net.onnx`，SDK 可自动把模型准备到工作目录。
- 授权边界：Demo 通过不代表正式 license zip 已在正式宿主通过；当时正式 license 需要签名证书和设备 SN 匹配，并记录宿主包名。当前授权规则和平台差异见页首链接。

## 后续规则

- 不要给 Demo APK 内置 SN 绑定 license；普通三方 App 在 Android 上通常无法读取系统 SN，会导致 `createEngine` 失败。
- 正式客户 App 使用 SN 绑定 license 时，必须确认宿主能读取或注入稳定 SN；否则会返回设备不匹配或 SN 不可用。
- 每次重新交付前，必须从最终 zip 中反查 Demo license 和正式 license 的 claims，不能只相信脚本参数。
- 每次重新交付前，必须验证 AAR 和 Demo APK 都包含 `assets/amphion-dingqiao/eres2net.onnx`，客户包不再提供外置 `models/eres2net.onnx`。
- 每次设备验证必须安装最终 zip 解压出的 APK；如需验证源码工程，也必须从最终 zip 解压出的 `demo-src/` 运行。
