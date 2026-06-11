# consumer-rules.pro：客户开 R8/混淆 时会自动应用这一份规则
# 这份规则的目标：让客户启用 minifyEnabled 后，AAR 仍然能正常工作。
#
# 如果你需要修改这份规则，请同步修改 proguard-rules.pro（开发态自验）。

# ---- 1. JNI 入口必须保留 ----
# sherpa-onnx 的 native 方法都是 instance method（不是 static）。
# 简单粗暴：保留这三个核心类的全部成员，避免任何字段/方法被混淆掉。
-keep class com.k2fsa.sherpa.onnx.OnlineRecognizer {
    <fields>;
    <methods>;
}
-keep class com.k2fsa.sherpa.onnx.OnlineStream {
    <fields>;
    <methods>;
}
-keep class com.k2fsa.sherpa.onnx.Vad {
    <fields>;
    <methods>;
}
-keep class com.k2fsa.sherpa.onnx.OfflinePunctuation {
    <fields>;
    <methods>;
}
-keep class com.k2fsa.sherpa.onnx.WetextItn {
    <fields>;
    <methods>;
}
-keep class com.k2fsa.sherpa.onnx.WetextItn$Companion { *; }
-keep class com.k2fsa.sherpa.onnx.TextRewriteFst {
    *;
}
-keep class com.k2fsa.sherpa.onnx.TextRewriteFst$Companion { *; }
-keep class com.k2fsa.sherpa.onnx.SpeakerEmbeddingExtractor {
    <fields>;
    <methods>;
}
-keep class com.k2fsa.sherpa.onnx.SpeakerEmbeddingManager {
    <fields>;
    <methods>;
}

# 兜底：所有 native 方法都不能改名（防止 R8 跨类裁剪）
-keepclasseswithmembernames class * {
    native <methods>;
}

# ---- 2. JNI 反射访问的 data class（字段名不能混淆） ----
-keep class com.k2fsa.sherpa.onnx.EndpointRule { *; }
-keep class com.k2fsa.sherpa.onnx.EndpointConfig { *; }
-keep class com.k2fsa.sherpa.onnx.OnlineTransducerModelConfig { *; }
-keep class com.k2fsa.sherpa.onnx.OnlineParaformerModelConfig { *; }
-keep class com.k2fsa.sherpa.onnx.OnlineZipformer2CtcModelConfig { *; }
-keep class com.k2fsa.sherpa.onnx.OnlineNeMoCtcModelConfig { *; }
-keep class com.k2fsa.sherpa.onnx.OnlineToneCtcModelConfig { *; }
-keep class com.k2fsa.sherpa.onnx.OnlineModelConfig { *; }
-keep class com.k2fsa.sherpa.onnx.OnlineLMConfig { *; }
-keep class com.k2fsa.sherpa.onnx.OnlineCtcFstDecoderConfig { *; }
-keep class com.k2fsa.sherpa.onnx.OnlineRecognizerConfig { *; }
-keep class com.k2fsa.sherpa.onnx.OnlineRecognizerResult { *; }
-keep class com.k2fsa.sherpa.onnx.FeatureConfig { *; }
-keep class com.k2fsa.sherpa.onnx.HomophoneReplacerConfig { *; }
-keep class com.k2fsa.sherpa.onnx.SileroVadModelConfig { *; }
-keep class com.k2fsa.sherpa.onnx.TenVadModelConfig { *; }
-keep class com.k2fsa.sherpa.onnx.VadModelConfig { *; }
-keep class com.k2fsa.sherpa.onnx.SpeechSegment { *; }
-keep class com.k2fsa.sherpa.onnx.OfflinePunctuationConfig { *; }
-keep class com.k2fsa.sherpa.onnx.OfflinePunctuationModelConfig { *; }
-keep class com.k2fsa.sherpa.onnx.WetextItnConfig { *; }
-keep class com.k2fsa.sherpa.onnx.SpeakerEmbeddingExtractorConfig { *; }

# ---- 3. SDK 公开 API 全保留 ----
# 公开类型不能被裁剪；data class 字段也要保留以便客户反序列化日志/序列化使用
-keep public class com.amphion.asr.AmphionRuntime { *; }
-keep public class com.amphion.asr.AmphionOptions { *; }
-keep public class com.amphion.asr.AmphionLogLevel { *; }
-keep public class com.amphion.asr.AsrLanguage { *; }
-keep public class com.amphion.asr.AsrConfig { *; }
-keep public class com.amphion.asr.AsrConfig$Builder { *; }
-keep public class com.amphion.asr.VadConfig { *; }
-keep public class com.amphion.asr.VadModelType { *; }
-keep public class com.amphion.asr.EndpointRules { *; }
-keep public class com.amphion.asr.AsrEngine { *; }
-keep public class com.amphion.asr.AsrSession { *; }
-keep public interface com.amphion.asr.AsrCallback { *; }
-keep public class com.amphion.asr.AsrResult { *; }
-keep public class com.amphion.asr.AsrError { *; }
-keep public class com.amphion.asr.AsrErrorCode { *; }
-keep public interface com.amphion.asr.Cancellable { *; }
-keep public class com.amphion.asr.AmphionMetrics { *; }
-keep public class com.amphion.asr.AmphionMetricsKind { *; }
-keep public class com.amphion.asr.TargetSpeakerConfig { *; }
-keep public class com.amphion.asr.SpeakerEnroller { *; }
-keep public class com.amphion.asr.AmphionLicenseStatus { *; }
-keep public class com.amphion.asr.AmphionLicenseStatus$State { *; }
-keep public class com.amphion.asr.LicenseEnforcement { *; }

# 保留所有 enum 内部 value/valueOf
-keepclassmembers enum com.amphion.asr.** {
    public static **[] values();
    public static ** valueOf(java.lang.String);
}
-keepclassmembers enum com.k2fsa.sherpa.onnx.** {
    public static **[] values();
    public static ** valueOf(java.lang.String);
}

# ---- 4. 行号 / SourceFile 保留，方便客户上报崩溃栈 ----
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile

# ---- 5. Java 17 字符串拼接（invokedynamic） ----
# Kotlin/Java 17+ 编译的 classes.jar 会引用 StringConcatFactory；客户 minSdk<26 且
# minifyEnabled=true（AGP 8 R8 full mode）时缺此条会致命失败。
-dontwarn java.lang.invoke.StringConcatFactory
