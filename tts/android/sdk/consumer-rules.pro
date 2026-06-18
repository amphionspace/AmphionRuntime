# Lits TTS SDK consumer rules.
# 这份规则在两处生效：
#   1) 客户 app 开启 R8/minify 时自动合并，保证 AAR 公开 API 仍可用；
#   2) 本 SDK release 自身 minify 时由 proguard-rules.pro include，决定哪些保留 / 哪些混淆。
#
# 关键：只保留公开包 com.lits.tts.sdk.*（单层，不含 .internal 子包），这样
# com.lits.tts.sdk.internal.*（含离线 license 验签 LicenseVerifier / LicenseGuard 等）在
# release 会被 R8 混淆，抬高逆向 / 打补丁门槛。被公开 API 引用到的 internal 类仍会被 R8
# 按可达性保留并改名，不影响运行。

# 公开 SDK API（含其嵌套 enum，如 TtsLicenseStatus$State）：保留类与全部成员，供
# Java/Kotlin 调用、data class 字段稳定、回调分发与可读崩溃栈。
-keep class com.lits.tts.sdk.* { *; }

# ONNX Runtime Java 类跨 JNI/native 边界。客户 minify release 时保持稳定。
-keep class ai.onnxruntime.** { *; }

# Native 方法名不能改名。
-keepclasseswithmembernames class * {
    native <methods>;
}

# 保留公开包内 enum 的 values()/valueOf()，供 Java/Kotlin 调用与可能的序列化/日志。
-keepclassmembers enum com.lits.tts.sdk.* {
    public static **[] values();
    public static ** valueOf(java.lang.String);
}
-keepclassmembers enum ai.onnxruntime.** {
    public static **[] values();
    public static ** valueOf(java.lang.String);
}

# 保留有用的崩溃栈信息，便于客户上报。
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile

# Java 17/Kotlin 构建在 desugaring 时可能引用 StringConcatFactory。
-dontwarn java.lang.invoke.StringConcatFactory
