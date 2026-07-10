# 鸿蒙 ASR SDK 差异说明（对接口文档 v1.1 / Android v3.0）

本文件列出纯血鸿蒙 ASR SDK 与《语音识别 SDK 接口文档 v1.1》及 Android v3.0 实现的**一致项**与**差异项**。
交付/联调请以本文件为准。

## 一、已对齐（与接口文档 / Android 一致）

- 接口契约 `SpeechRecognizeSdk` / `SpeechRecognitionEngine` / `RecognitionListener` 的 13 个方法 + 5 个回调 + 数据结构全部实现（非桩）。
- **错误码 `1002200001`~`1002200037` 已按接口文档对齐**（引擎块 002–012、声纹 020–024、License 030–037 语义一致；036/037 为签名绑定失败的扩展码，与 Android 一致）。
- **License 授权**：真 ECDSA-P256 签名验签 + 有效期 + 设备 SN 白名单；SN 指纹算法与 Android `DeviceLicenseFingerprint` 一致：`SHA-256( 大写去空(SN) + deviceIdSaltId )`，大写 hex。
- **授权文件与 Android 共用**：注入的验签公钥与 Android SDK 为同一把生产密钥，故同一份 `amphion-license.lic`（ASR/TTS 共用、SN 白名单）在 Android 与鸿蒙上验签一致。
- `SpeechRecognitionResult.beginTime` / `endTime` 已填（由 token 时间戳换算，单位 ms，仅 `isFinal=true` 保证有效）。
- `onStart(sessionId, eventMessage)` / `onComplete(sessionId, eventMessage)` 回调携带 `eventMessage`（`"startListening success."` / `"recognize complete"`），与接口文档一致。
- 音频：PCM 16 kHz / 16 bit / mono；每帧 **640 字节(20ms) 或 1280 字节(40ms)** 均接受。

## 二、已知差异 / 需注明

1. **License 为纯离线本地验签**：接口文档时序图画成联网鉴权（错误码 `1002200035` 描述为"鉴权服务器不可达"）。实际实现为**离线本地 ECDSA 验签，无任何网络请求**；`setLicense` 为异步回调形态但不依赖网络，错误码 35 在离线实现下仅作兜底语义。
2. **recognizerMode（short/long）**：统一按 `long`（长语音流式）处理，不单独区分短语音（与接口文档"安菲翁统一填长语音"一致）。
3. **会话级热词 `sessionGeneralLexicon`**：V1 暂不支持，仅支持系统级 `sysGeneralLexicon`（与接口文档一致）。
4. **ITN（逆文本规整）**：Amphion WeText NAPI 尚未打包进鸿蒙包，数字/单位/金额规整能力降级；SDK 不会把未处理文本伪装成已处理。
5. **TEN_VAD**：枚举保留但模型未打包，选择 `TEN_VAD` 会报错；当前统一使用 Silero VAD。
6. **createEngine 无 Promise 形态**：仅提供同步 `createEngine(params)` 与回调 `createEngineAsync(params, callback)`（与 Android 一致；接口文档允许 callback / Promise 二选一）。
7. **设备 SN 读取需宿主特权**（与 Android 相同）：读取设备序列号需 `ohos.permission.sn`（system_basic 级特权权限），普通三方 App / Demo 无法读取。因此**绑定 SN 的正式 license 需宿主为系统/预置应用，或由宿主通过 `deviceIdProvider` 注入设备 SN**；Demo 使用不绑定 SN 的授权文件。若宿主读不到 SN，绑 SN 的授权会激活失败（`1002200033`），属宿主权限/环境问题。
8. **线程模型（鸿蒙特有，建议注意）**：首次 `createEngine` 会**同步加载 ASR 模型（约数秒）**，此期间调用线程被阻塞。**建议调用方在非 UI 线程调用 `createEngine`，或在加载期间显示加载态**。Android 使用 JVM 工作线程无此问题；鸿蒙 ArkTS 的 TaskPool worker 无法跨线程传递 NAPI 对象，故暂未后台化，列为后续优化项。
9. **native 内存指标**：`nativeRssMb` / `peakNativeRssMb` 等字段保持 `-1`（鸿蒙端暂未接入 native RSS 读取），字段名与 sentinel 规则与 Android 一致。

## 三、Demo 与授权

- Demo HAP（`dingqiao-demo.hap`）内置**不绑定 SN 的试用授权**（有效期至 2026-09-01），任意鸿蒙设备可体验；不替代正式 App 授权验收。
- 正式 App 集成时放入宿主的授权文件为**与 Android 共用的 `amphion-license.lic`**（绑定 SN 白名单 + 有效期），需宿主可读取/注入设备 SN。
