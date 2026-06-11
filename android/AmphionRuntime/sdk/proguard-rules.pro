# proguard-rules.pro：仅在开发态启用 minify 时使用
# release 默认 isMinifyEnabled = false（AAR 是不混淆的；客户启用混淆时由 consumer-rules.pro 接管）
#
# 这里的内容与 consumer-rules.pro 完全一致，便于本地 sample 启用 minify 时复现客户行为。

# 直接 include consumer-rules.pro（AGP 8 支持）
-include consumer-rules.pro
