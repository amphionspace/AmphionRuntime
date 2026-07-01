# 鼎桥 ASR SDK v0.2.8 交付包 corner-case 测试报告

测试日期：2026-06-26
测试对象：交付包内的 fat AAR（dingqiao-asr-v0.2.8.aar，git 4cad59c，分支 fix/dingqiao-finish-flush）
测试方式：在 dingqiao-demo 上写 androidTest 仪器化用例，直接消费交付的 AAR，连真机执行（SN 4EE\*\*\*062，在白名单内）
音频语料：/Users/boxp/Downloads/audio/（24 个 16k 单声道 PCM16，12 主句 + 12 声纹注册句）

## 1. 交付与授权验收

| 项目 | 结果 |
| --- | --- |
| customer zip SHA-256 | 020f096ebb945404299df5abbb627f05ce18103850537be33038fda538063342 |
| license zip SHA-256 | 809f8afb1c96e0ed54336a030a247e7d3e3b883a60ad8e4530c602f032f8463f |
| VERSION 一致性 | delivery_version=0.2.8，git_commit=4cad59c，git_dirty=false |
| demo APK 签名 | debug-keystore，cert 1D:C0:85:F7:... |
| demo 内置 license | app=com.amphion.dingqiao.demo，features=ASR，device_hash_count=0，expiresAt=2026-08-25，签名有效，可 createEngine |
| 正式 license v0.2.7 | app=com.tdtech.tiassistant，features=ASR,TTS，16 台白名单，expiresAt=2026-08-25，签名有效，文件 sha256 与清单一致 |
| 正式 license 设备绑定 | 连接设备 SN 在白名单内（离线 verify 通过），bogus SN 正确报 6007 |

## 2. 关键发现（按严重度）

### F1（高）finish() 不排空解码 backlog：快于实时喂入会丢整句/尾字

这是本轮最重要的 corner case，也是尾部帧问题的残留更严重形态。

证据（隔离实验 f01，同一引擎、同一音频，仅改喂入速率与 finish 前 settle）：

| 文件 | 实时喂入(20ms)+settle300 | 快喂(0ms)+settle300 | 快喂(0ms)+settle3000 |
| --- | --- | --- | --- |
| 04 生活建议 | 一般可用雨伞遮住，或把相机装在塑料袋里。 | 空 | 一般可用雨伞遮住，或把相机装在塑料袋里。 |
| 06 流行歌曲口语 | 来个新长征路上的摇滚。 | 空 | 来个新长征路上的摇滚。 |
| 11 行程提醒 | 假如大后天早上去机场。 | 空 | 假如大后天早上去机场。 |
| 01 长句（对照） | 全文 40 字 | 全文 40 字 | 全文 40 字 |

另在 abrupt（零尾静音立即 finish）快喂下，10/12 主句全文，仅 2 句丢 1 个尾字：10（网→网站）、12（路→路径）；padded/实时路径 12/12 全文。

根因（按层定位）：解码在独立线程异步消费 writeAudio 入队的 PCM；finish()/stop() 用当前已解码状态产出 final，不阻塞等待 backlog 排空。喂入快于实时会积压，语音靠后的短句在 finish 时还没解码，于是 final 为空。给足 pre-finish settle（约 3s，量级正比于剩余 backlog）或按实时节拍喂入即可恢复，且与实时结果逐字一致。0.2.8 内置的 500ms 收尾静音只能补偿实时路径的微小 backlog，覆盖不了快喂产生的大 backlog。

影响：离线 SDK 最典型用法就是读文件循环快喂 + finish，会静默丢整句且无任何报错。

建议：finish() 改为阻塞直到输入 backlog 全部解码后再产出 final + onComplete（真正 flush），而非固定追加静音。临时规避：客户侧按 ~实时节拍喂入，或 finish 前 settle，或轮询 isBusy 直至空闲再 finish。

### F2（中）license 多种失配收敛为同一错误码 1002200033

applicationId 失配、证书失配、设备失配/SN 不可读对外都返回 LICENSE_DEVICE_MISMATCH(1002200033)，仅 message 文案不同。客户只看错误码无法区分根因。建议拆分错误码，或在文档写明该码需结合 message 判读。

### F3（中）SN 绑定 license 在非特权宿主下必然失败（平台约束，非 SDK 缺陷）

demo app 无 READ_PRIVILEGED_PHONE_STATE，Build.getSerial 返回 unknown、ro.serialno 为空，拿不到 SN，无法算 deviceHash，SN 白名单校验必失败。正式宿主 com.tdtech.tiassistant 为特权应用可读 SN。结论：正式 SN 绑定 license 只能在特权宿主上联调；本轮已用 verify_license.py 对连接设备 SN 离线反查通过。建议在文档明确这一前提。

### F4（低）getLicenseInfo 在仅靠 asset license 起效时抛 LICENSE_NOT_SET

引擎经内置 asset license 可正常 createEngine，但未显式 setLicense 时 getLicenseInfo 返回 1002200034。建议 getLicenseInfo 回落到实际生效的 asset license，或文档写明其仅反映 setLicense 状态。

### F5（低）speaker-VAD 在 3 人重叠片段上整句抑制（阈值偏严，待确认）

file01 不开 speaker-VAD 可全文转写、相似度 0.636；开启 speaker-VAD（目标声纹）后 3 个 VAD 事件但 final 为空。重叠/中等相似场景门限可能偏严，建议复核门限或开放可配。

## 3. 契约/错误码用例（全部符合预期）

| 用例 | 结果 |
| --- | --- |
| 尾部帧（实时/padded） | 12/12 全文，abrupt avg_len_ratio=0.991 |
| 非 640 字节帧 | 1002200011 RECOGNITION_ERROR |
| startListening 前 writeAudio | 1002200010 NOT_LISTENING |
| 会话进行中再 startListening | 1002200006 ENGINE_BUSY |
| 空闲时 finish | 1002200004 FINISH_FAILED |
| cancel 语义 | 无 onFinal、无 onComplete |
| 非法 sessionId | 1002200002 START_LISTENING_FAILED |
| writeAudio 串 sessionId | 1002200011 RECOGNITION_ERROR |
| maxAudioDuration 低于下限 | 被夹到 20000ms，正常出字 |
| maxAudioDuration 超限 | 1002200003 MAX_AUDIO_DURATION |
| 不支持语言 en-US | 抛 DingqiaoEngineException 1002200001 |
| shutdown 后调用 | 抛 DingqiaoEngineException（engine destroyed），不走回调 |
| 声纹注册 | 成功且持久化 |
| 声纹样本过长(>8s) | 1002200022 VOICEPRINT_SAMPLE_DURATION |
| 声纹样本路径不存在 | 1002200020 VOICEPRINT_REGISTER_FAILED |
| 开启核验返回相似度 | speakerSimilarity=0.636 |
| speaker-VAD 缺 voiceprintIds | 1002200002 START_LISTENING_FAILED |
| 删除声纹后再用 | 1002200024 VOICEPRINT_NOT_FOUND |
| license 有效 | code=0，features=[ASR]，剩余 61 天 |
| license 过期 | 1002200032 LICENSE_EXPIRED |
| license 仅 TTS 缺 ASR | 1002200035 LICENSE_ACTIVATION_FAILED |
| license ASR+TTS | code=0，features=[ASR,TTS] |
| license 损坏 | 1002200031 LICENSE_INVALID |
| license 文件缺失 | 1002200030 LICENSE_FILE_UNREADABLE |

## 4. 结论

尾部帧修复在实时/近实时路径已生效（padded/实时 12/12 全文）。但发现一个更值得关注的残留：快于实时喂入时 finish() 不排空解码 backlog，会静默丢尾字乃至整句（F1），这恰是离线 SDK 最常见的批量解码用法，建议优先修复。授权链路（demo 内置 license、正式 SN 绑定 license）签名与 claims 均验证通过；正式 SN 绑定只能在特权宿主验证（F3，平台约束）。其余 API 契约、生命周期、错误码、声纹相关用例全部符合预期。

证据文件：evidence/instrumented_report.jsonl（48 条仪器化记录）、evidence/realtime_corpus.tsv（24 文件实时转写）。
