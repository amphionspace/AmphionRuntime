鼎桥统一离线授权文件 v0.2.7
================================

文件
----
  amphion-license.lic   ASR/TTS 共用授权文件
  VERSION.txt           授权元信息和 sha256

用途
----
  - Android ASR SDK 与 TTS SDK 共用同一份 amphion-license.lic。
  - 客户 App 需要把 amphion-license.lic 放入 app/src/main/assets/。
  - 默认文件名必须保持 amphion-license.lic，除非集成代码显式改 licenseAssetName。

授权摘要
--------
  applicationId: com.tdtech.tiassistant
  features: ASR,TTS
  issuedAt: 2026-06-25
  expiresAt: 2026-08-25
  authorizedDevices: 16

校验
----
  sha256(amphion-license.lic) = bda872951b762023f0be811b79781da252c1042078818522570a9e49a33cb503
