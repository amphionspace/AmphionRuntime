# 鸿蒙 ASR SDK 差异说明（对接口文档 v1.1 / Android v3.0）

本文件列出纯血鸿蒙 ASR SDK 与《语音识别 SDK 接口文档 v1.1》及 Android v3.0 实现的**一致项**与**差异项**。
交付/联调请以本文件为准。

## 一、已对齐（与接口文档 / Android 一致）

- 接口契约 `SpeechRecognizeSdk` / `SpeechRecognitionEngine` / `RecognitionListener` 的 13 个方法 + 5 个回调 + 数据结构全部实现（非桩）。
- **错误码 `1002200001`~`1002200035` 已按接口文档对齐**（引擎块 002–012、声纹 020–024、License 030–035；`1002200012` 因不支持 SDK 内录音仅作兼容保留）。鸿蒙不单独发出 `1002200036` / `1002200037`，见"二、已知差异"第 10 条。
- **License 授权**：真 ECDSA-P256 签名验签 + 有效期 + 设备 SN 白名单；SN 指纹算法与 Android `DeviceLicenseFingerprint` 一致：`SHA-256( 大写去空(SN) + deviceIdSaltId )`，大写 hex。
- **授权文件与 Android 共用**：注入的验签公钥与 Android SDK 为同一把生产密钥，故同一份 `amphion-license.lic`（ASR/TTS 共用、SN 白名单）在 Android 与鸿蒙上验签一致。
- **警务增强与 Android 鼎桥 V2 对齐**：final 依次执行术语、全国车牌、派出所 V2；共用 Android 词表、同音表、GA36 车牌知识库和 235 条预设热词，包含电台数字归一与 GB28181 防误纠。`sync_harmony_police_assets.py --check` 校验资源同步，跨端共同执行 `police_v2_parity.tsv` 行为契约。
- `SpeechRecognitionResult.beginTime` / `endTime` 已填（由 token 时间戳换算，单位 ms，仅 `isFinal=true` 保证有效）。
- `onStart(sessionId, eventMessage)` / `onComplete(sessionId, eventMessage)` 回调携带 `eventMessage`（`"startListening success."` / `"recognize complete"`），与接口文档一致。
- 音频：PCM 16 kHz / 16 bit / mono；交付接口每帧固定 **640 字节(20ms)**。
- `vadBegin` / `vadEnd` 均按会话级 VAD 状态生效，不依赖 partial 文本；未显式传入 `vadBegin` 时保持禁用。

## 二、已知差异 / 需注明

1. **License 为纯离线本地验签**：接口文档时序图画成联网鉴权（错误码 `1002200035` 描述为"鉴权服务器不可达"）。实际实现为**离线本地完整验权，无任何网络请求**；`setLicense` 为异步回调形态但不依赖网络，只校验并缓存授权，不拉起 Runtime 或加载模型。授权成功后必须显式调用 `prepareRuntime`，再创建引擎。`unloadRuntime` 保留已验证授权，可免重新 `setLicense` 再次 `prepareRuntime`。错误码 35 在离线实现下仅作兜底语义。
2. **recognizerMode（short/long）**：两种值均接受，统一按 `long`（长语音流式）处理，不单独加载短语音模型；显式配置的 `vadBegin` 在两种值下均生效。
3. **会话级热词 `sessionGeneralLexicon`**：V1 暂不支持，仅支持系统级 `sysGeneralLexicon`（与接口文档一致）。
4. **ITN（逆文本规整）**：Amphion WeText NAPI 尚未打包进鸿蒙包，数字/单位/金额规整能力降级；SDK 不会把未处理文本伪装成已处理。
5. **TEN_VAD**：枚举保留但模型未打包，选择 `TEN_VAD` 会报错；当前统一使用 Silero VAD。
6. **createEngine 无 Promise 形态**：仅提供同步 `createEngine(params)` 与回调 `createEngineAsync(params, callback)`（与 Android 一致；接口文档允许 callback / Promise 二选一）。
7. **设备 SN 读取需宿主特权**（与 Android 相同）：`deviceInfo.serial` 需要 `ohos.permission.sec.ACCESS_UDID`（system_basic），普通三方 App / Demo 无法获得。因此绑定 SN 的正式 license 需宿主为系统/预置应用，并通过 `SpeechRecognizeSdk.init(context, deviceIdProvider)` 注入 SN。普通 Demo 可使用 `deviceInfo.ODID`，但签发清单必须同步改为该 ODID；两种标识不可混用。读不到标识或白名单不匹配会返回 `1002200033`。
8. **线程模型（鸿蒙特有，建议注意）**：首次 `createEngine` 会**同步加载 ASR 模型（约数秒）**，此期间调用线程被阻塞。**建议调用方在非 UI 线程调用 `createEngine`，或在加载期间显示加载态**。Android 使用 JVM 工作线程无此问题；鸿蒙 ArkTS 的 TaskPool worker 无法跨线程传递 NAPI 对象，故暂未后台化，列为后续优化项。
9. **native 内存指标**：`nativeRssMb` / `peakNativeRssMb` 等字段保持 `-1`（鸿蒙端暂未接入 native RSS 读取），字段名与 sentinel 规则与 Android 一致。
10. **License 错误码收敛（与 Android 的差异）**：鸿蒙 `DingqiaoErrorCode` 只定义到 `1002200035`，将「应用不匹配 / 证书指纹不匹配 / 设备不匹配」三类统一映射为 `LICENSE_DEVICE_MISMATCH = 1002200033`；Android 则拆分为 `1002200036`（`LICENSE_APP_MISMATCH`）/ `1002200037`（`LICENSE_CERT_MISMATCH`）/ `1002200033`。这与正式设备白名单授权**不按 applicationId 限制**（`6004 LicenseAppMismatch` 保留、默认不绑签名证书）的方案一致——鸿蒙有意不再单独发出 036/037。若鼎桥侧按 Android 文档预期 036/037 分支，请注意鸿蒙对应场景只返回 `1002200033`。

## 三、Demo 与授权

- Demo HAP（`dingqiao-demo.hap`）只用于体验，不替代正式 App 授权验收。标准体验包可内置不绑定设备的试用授权；设备验收包可绑定 Demo ODID，具体以 HAP 内 license 声明为准。
- 正式 App 集成时放入宿主的授权文件为**与 Android 共用的 `amphion-license.lic`**（绑定 SN 白名单 + 有效期），需宿主可读取/注入设备 SN。
