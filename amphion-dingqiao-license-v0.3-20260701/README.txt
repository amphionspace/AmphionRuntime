鼎桥统一离线授权文件 v0.3
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
  package/bundle: 不限制
  signing cert: 不限制
  features: ASR,TTS
  issuedAt: 2026-07-01
  expiresAt: 2026-09-01
  authorizedDevices: 2

校验
----
  sha256(amphion-license.lic) = aae071915ff93f90a25dda8028c84c310fc55b952beeec2a65cdd32b758b11e3
