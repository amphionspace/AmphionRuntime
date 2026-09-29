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
- 虽然 Harmony core 在构造 session 时同步产生 started 信号，鼎桥适配层只会在 session 已发布且会话级配置完成后发送 `onStart`；因此其公共语义与 Android 一致，回调内可立即调用该 session 的 `writeAudio`、`finish` 或 `cancel`。
- 音频：PCM 16 kHz / 16 bit / mono；交付接口每帧固定 **640 字节(20ms)**。
- `vadBegin` / `vadEnd` 均按会话级 VAD 状态生效，不依赖 partial 文本；未显式传入 `vadBegin` 时保持禁用。

## 二、已知差异 / 需注明

1. **License 为纯离线本地验签**：接口文档时序图画成联网鉴权（错误码 `1002200035` 描述为"鉴权服务器不可达"）。实际实现为**离线本地完整验权，无任何网络请求**；`setLicense` 为异步回调形态但不依赖网络，只校验并缓存授权，不拉起 Runtime 或加载模型。授权成功后必须显式调用 `prepareRuntime`，再创建引擎。`unloadRuntime` 保留已验证授权，可免重新 `setLicense` 再次 `prepareRuntime`。错误码 35 在离线实现下仅作兜底语义。
2. **recognizerMode（short/long）**：两种模式使用同一流式模型，但 endpoint 语义不同。`short` 使用 `endpointMaxUtteranceMs` 作为单句硬上限；`long` 不做周期性 Rule3 硬切，只由自然静音或显式 `finish` 公开分段。long 会在 native 内压缩所有活跃 beam 已共同确认的 token/frame 前缀，该动作不产生 endpoint/final。`StartParams.extraParams` 可覆盖 engine 缺省模式；`vadBegin` 在两种模式下均生效。
3. **会话级热词 `sessionGeneralLexicon`**：V1 暂不支持，仅支持系统级 `sysGeneralLexicon`（与接口文档一致）。
4. **ITN（逆文本规整）**：鸿蒙与 Android 共用 WeText 规则和 FST；`itn=true` 时 final 会执行数字、单位和金额规整。数字字段中的 ASR 变体“么”仅在可信号码上下文或标准标识符形态下按“幺”处理，普通“这么/什么”保持原义。
5. **TEN_VAD**：枚举保留但模型未打包，选择 `TEN_VAD` 会报错；当前统一使用 Silero VAD。
6. **createEngine 无 Promise 形态**：仅提供同步 `createEngine(params)` 与回调 `createEngineAsync(params, callback)`（与 Android 一致；接口文档允许 callback / Promise 二选一）。
7. **设备 SN 读取需宿主特权**（与 Android 相同）：`deviceInfo.serial` 需要 `ohos.permission.sec.ACCESS_UDID`（system_basic），普通三方 App / Demo 无法获得。因此绑定 SN 的正式 license 需宿主为系统/预置应用，并通过 `SpeechRecognizeSdk.init(context, deviceIdProvider)` 注入 SN。普通 Demo 可使用 `deviceInfo.ODID`，但签发清单必须同步改为该 ODID；两种标识不可混用。读不到标识或白名单不匹配会返回 `1002200033`。
8. **模型准备与线程**：授权成功后先调用 `prepareRuntime`，SDK 会异步准备默认中英模型；配置匹配时，后续 `createEngine` 复用已准备的模型。自定义配置或模型卸载后仍可能发生冷加载，建议使用回调式 `createEngineAsync`，并在成功回调前显示加载状态。同步 `createEngine` 不保证无耗时，调用方不应依赖它在 UI 线程立即返回。
9. **native 内存指标**：`nativeRssMb` / `peakNativeRssMb` 等字段保持 `-1`（鸿蒙端暂未接入 native RSS 读取），字段名与 sentinel 规则与 Android 一致。
10. **License 错误码（双端已对齐）**：Android 与 Harmony 当前都将设备、证书及兼容应用绑定失败映射为 `LICENSE_DEVICE_MISMATCH = 1002200033`，不单独回调 0036/0037。格式、签名、主版本或授权能力不满足返回 0031；运行期限或维护期不满足返回 0032。历史版本文档中的分平台映射不能用于当前接入。

## 三、Demo 与授权

- Demo HAP（`dingqiao-demo.hap`）只用于体验，不替代正式 App 授权验收。标准体验包可内置不绑定设备的试用授权；设备验收包可绑定 Demo ODID，具体以 HAP 内 license 声明为准。
- 正式 App 集成时放入宿主的授权文件为**与 Android 共用的 `amphion-license.lic`**（绑定 SN 白名单 + 有效期），需宿主可读取/注入设备 SN。
