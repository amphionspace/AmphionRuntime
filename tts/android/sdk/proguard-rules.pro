# proguard-rules.pro：本 SDK release 自身开启 minify（isMinifyEnabled=true）时使用。
#
# 与 consumer-rules.pro 完全一致（直接 include），便于本地复现客户启用混淆时的行为，
# 同时让 com.lits.tts.sdk.internal.*（含离线 license 验签逻辑）在 release 被混淆。

# 直接 include consumer-rules.pro（AGP 8 支持）
-include consumer-rules.pro
