# Lits TTS SDK consumer rules.
# These rules are merged into the host app when the host enables R8/minify.

# Public SDK API is kept for Java/Kotlin callers, data-class field stability,
# callbacks, and predictable integration behavior. Internal implementation is
# intentionally not kept so release builds can obfuscate license/runtime code.
-keep class com.lits.tts.sdk.* { *; }

# ONNX Runtime Java classes cross JNI/native boundaries. Keep them stable when
# a host app minifies its release build.
-keep class ai.onnxruntime.** { *; }

# Native method names must not be renamed.
-keepclasseswithmembernames class * {
    native <methods>;
}

# Keep enum helpers used by Java/Kotlin callers and possible serialization/logging.
-keepclassmembers enum com.lits.tts.sdk.* {
    public static **[] values();
    public static ** valueOf(java.lang.String);
}
-keepclassmembers enum ai.onnxruntime.** {
    public static **[] values();
    public static ** valueOf(java.lang.String);
}

# Preserve useful stack traces for customer crash reports.
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile

# Java 17/Kotlin builds may reference StringConcatFactory during desugaring.
-dontwarn java.lang.invoke.StringConcatFactory
