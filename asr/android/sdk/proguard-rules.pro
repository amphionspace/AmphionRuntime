# proguard-rules.pro：仅在开发态启用 minify 时使用
# release 默认 isMinifyEnabled = false（AAR 是不混淆的；客户启用混淆时由 consumer-rules.pro 接管）
#
# 这里的内容与 consumer-rules.pro 完全一致，便于本地 sample 启用 minify 时复现客户行为。

# 直接 include consumer-rules.pro（AGP 8 支持）
-include consumer-rules.pro

# Release unit tests instantiate this internal state tracker directly. Keep the class boundary in
# the minified test artifact instead of letting R8 inline it into SessionImpl and remove the class.
-keep class com.amphion.asr.internal.InitialAcousticActivityTracker { *; }
-keep class com.amphion.asr.internal.EffectiveSpeechBuffer { *; }
-keep class com.amphion.asr.internal.EffectiveSpeechFinalDecision { *; }
-keep class com.amphion.asr.internal.SpeakerScoreSelection { *; }
-keep class com.amphion.asr.internal.SpeakerScoreSource { *; }
-keep class com.amphion.asr.internal.EffectiveSpeechBufferKt { *; }
-keep class com.amphion.asr.internal.RecognizerResetGeneration { *; }
-keep class com.amphion.asr.internal.SpeakerPcmBuffers { *; }
-keep class com.amphion.asr.internal.SpeakerVadScoreScheduler { *; }
-keep class com.amphion.asr.internal.AssetRegistry { *; }
-keep class com.amphion.asr.internal.AssetRegistry$Bundle { *; }
-keep class com.amphion.asr.internal.LicenseVerifier { *; }
-keep class com.amphion.asr.internal.FinalCallbackOrderGate { *; }
-keep class com.amphion.asr.AsrConfig { *; }
-keep class com.amphion.asr.internal.StreamingAgcProcessor { *; }
-keep class com.amphion.asr.internal.ProcessedAudioFrame { *; }
-keep class com.amphion.asr.internal.AgcBackend { *; }
-keep class com.amphion.asr.internal.DecoderSubmissionFence { *; }
-keep class com.amphion.asr.internal.NativeGuard { *; }
-keep class com.amphion.asr.internal.NativeResult { *; }
-keep class com.amphion.asr.internal.NativeResult$Ok { *; }
-keep class com.amphion.asr.internal.NativeResult$Err { *; }
-keep class com.amphion.asr.internal.Logger { *; }
