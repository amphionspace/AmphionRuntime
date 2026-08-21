# 隐私说明

专用 Debug 交付默认开启公共 `writeAudio` 输入音频和识别文本，以便一次复现形成完整证据。
它仍不记录热词内容、完整 sessionId、voiceprintId、license 原文、私钥、签名材料和设备
序列号。若现场不允许携带音频或文本，必须在复现前通过配置或启动参数关闭对应采集。

音频来自通过校验后、进入异步/native 队列前的公共 `writeAudio` 输入，不包含 SDK 内部补静音
或跨 stream replay。单 session 默认最多保存 120 秒，达到上限只停止采集并标记截断，不影响识别。

诊断仅保存在应用沙箱，SDK 不自动上传。电脑端工具会再次检查禁止字段并脱敏 hilog。诊断 ZIP
仍可能包含业务敏感音频或文本，请只通过双方约定的安全渠道传输，并在问题结束后按数据策略删除。

预配置 Debug HAR 和随包应用默认使用 `CUSTOMER_SUPPORT`；`BASIC` 模式仍会强制关闭音频
和文本，`CUSTOMER_SUPPORT` 与 `FAILURE_ONLY` 则按独立开关采集。Debug 版后台 journal
也遵守相同开关与脱敏规则，Release HAR 中诊断硬关闭。
诊断目录默认总上限 200 MB、最多保留最近 3 个 run，SDK 不会访问或打包其他应用数据。

电脑收集工具默认只带出异常 session（无异常时只带出最新 session），不会默认包含同一 run
中的其他会话。可选 `--encrypt-password-file` 会在本机生成 AES-256 加密包并删除明文 ZIP；
密码必须经另一条安全渠道传递。
