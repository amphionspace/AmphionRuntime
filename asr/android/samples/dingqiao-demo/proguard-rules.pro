# Sample 工程默认开启 minify，用来验证 SDK 的 consumer-rules.pro 是否覆盖完整。
# 这里不需要加额外规则——如果验证时发现问题，说明 sdk/consumer-rules.pro 漏了什么，
# 应该回到 sdk/consumer-rules.pro 补上，而不是在这里 patch。

-include ../../sdk/consumer-rules.pro

-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile
