# Android ASR SDK 0.3.5 最终 ZIP 验收报告

验收结论：**所列 SDK 功能、生命周期和前台 Demo 通过**。四人重叠精度及锁屏／后台角色处理尚未通过本次验收。

## 交付身份

| 项目 | 冻结值 |
|---|---|
| 完整 ZIP | `Amphion-Android-ASR-Complete-0.3.5.zip` |
| SHA-256 | `0b52b99b8f8f89919f269cbcdd0adee54bce56516bbbfd0e3c3b90dff8c3499a` |
| 字节数 | 1801707979 |
| SDK / Demo | 0.3.5 / 0.3.5（305） |
| 源码提交 | `1bdb516e708d0c939fe199dddee554af4fb9a6f8` |
| 交付分支 | `build/asr-delivery-20260916` |
| 能力及架构 | 中英 ZH_EN、ASR、arm64-v8a，模型内置 |
| 真机 | TECNO KI8，Android 13 |
| Demo 签名 | 既有评估用 debug keystore；Release APK 启用 R8 优化 |
| Demo 授权 | 到期 2026-11-14，绑定 Demo 包名和签名；不是客户正式应用授权 |

完整包包含 Release fat AAR 子包、Diagnostics fat AAR、两种可安装 Demo、独立 Demo 源码、文档与哈希清单。源码默认依赖包内 Release AAR；可指定 Diagnostics AAR，不能同时依赖两个版本。源码不含私钥；客户运行自编译 App 需使用与自身包名、签名匹配的授权。

## 已执行验证

| 验证 | 结果 | 实际覆盖 |
|---|---|---|
| 最终 ZIP 内容校验 | PASS | 校验 131 个条目；五个 APK/AAR 负载与已验收输入逐项同哈希 |
| SDK 来源和模型 | PASS | Release / Diagnostics 区分编译变体，来源绑定冻结提交；ITN 按固定 SHA 校验，不以放宽大小下限替代 |
| SDK 本地回归 | PASS | sdk Debug 60、Release 59；sdk-dingqiao Debug / Release 各 110，共 339 项，失败/错误/跳过均 0 |
| 公共 SDK 真机契约 | PASS（修正测试前置条件后） | 39 个不同用例，原 34 PASS 加定向修正后 5 PASS；包含 onStart 同步写入/finish、卸载重载、取消、迟到旧会话调用、超时、声纹和非有限参数 |
| 连续真实操作 | PASS | 300 轮，600 个正常会话、300 个取消会话；每轮核对 last/complete 顺序及取消无新增 final/complete，旧会话调用不得污染替换会话；耗时 669.1 秒 |
| 独立 Demo 源码构建 | PASS | 脱离仓库，只依赖包内公开 AAR，构建 App 及测试 APK；仅配置本地 Android SDK、现有授权和测试语料路径 |
| 包内 Diagnostics Demo | PASS | 180 秒四人音频：finish 前 last=0、唯一 last 后 complete、角色窗口文字完整、时间轴不倒退；另验证 UI final 标记由角色窗口决定，共 2 项 |
| Diagnostics 导出 | PASS | 自动导出实际 180 秒 16 kHz 单声道输入、回调、事件、有效配置与构建身份；原始录音保留于私有诊断目录 |
| 包内 Release Demo | PASS（前台亮屏） | R8 版本完整文件输入，观察中间→最终角色标记，结束后退出录音态，无角色降级；耗时 213.47 秒 |
| 离线运行 | PASS（上述真机流程） | Wi-Fi 关闭、无 SIM；App 未申请 INTERNET 权限，使用包内模型。未做逐系统调用网络抓取 |

Release AAR SHA-256：`9507f0a298d7d16530972d47f1579ee1fa89754f2f65ce44e722f080025a5a53`。
Diagnostics AAR SHA-256：`8909d0f2e941cf92058dfab67b0f0513579b91abf691c3b09139344f3ab3eb5f`。
Release APK SHA-256：`010940840798b95db4ba57d5c276cf3d669abb996b2a540dabcb33f65ae3562f`。

180 秒输入 SHA-256：`ca8dabf80f0471bb5967557f8f05669e30ca893880f34eb4df83bc77165cfbd2`，AISHELL-4 `L_R003S01C02` 的 690–870 秒，16 kHz 单声道，有四人标注。本轮是功能验收，不重新声明角色精度通过。

## 首次失败及处理

- 原 39 项中 5 项失败。两项声纹错误测试仍按异常取码，已改为核对公共返回 `VoiceprintRegisterResult.status` 并通过；该改动仅为测试断言，不修改 SDK。
- 另三项使用了不满足前置条件的语料：期望单段 speech begin 却输入两段语音、目标声纹注册与测试说话人不同、缺少重叠样本。分别使用对应语料后定向验证。重叠样本来自 AISHELL-4 的真实 RTTM 重叠区域。
- 声纹 + 1000 ms 初始静音用例，低能量文件前导与额外静音叠加后，首个语音确认超出 deadline；保留失败现场。只移除源文件 400 ms 前导，保持参数及调用时序后通过。此结果不能推导所有接近 deadline 的起音均可保留。
- 初次 Release Demo 文件输入在 30 秒自动锁屏后观察超时，继续原会话时出现 `INFERENCE_TIMEOUT` 降级。保持前台亮屏、同一 PCM 和参数的对照通过。**锁屏／后台角色可靠性仍为 OPEN**；尚未完成修复前后差分归因，不把它归为本次版本引入的回归，也不把原失败改写成 PASS。
- 测试源码整理时遗漏了仍有其他断言引用的辅助方法，首次独立构建失败；恢复方法后编译通过。最终源码与通过构建的源码逐文件相同，SDK/APK 哈希没有变化，复用对应真机证据。

## 接入迁移与边界

1. `AsrResult.timestamps`（秒）和鼎桥 `beginTime/endTime`（毫秒）现在统一使用 session 输入时间轴。业务侧自行累加前句时长的补偿必须移除。
2. 角色最终结果按窗口多批返回，按 `windowIndex` 累积，用 `sourceUtteranceId` 关联转写，`isSessionFinal` 表示角色末批。ASR final/last 不代表角色定稿。
3. 未知角色 `speakerIndex=-1`；中间角色可修正，已定稿窗口保持不变。默认最多 4 个角色，会议 Demo `vadEnd=800ms`。
4. **四人重叠精度 OPEN**。短暂新人、重叠语音仍可能未知或误认；本次不声称精度问题已经解决。
5. 300 轮压力属于所列调用序列的稳定性证据，不证明多小时会议无泄漏。资源采样保留，多机型、低内存强杀、权限撤销、来电和后台长录音未覆盖。
6. 不包含目标说话人增强模型；Diagnostics 会采集 PCM 和文字，正式业务应使用 Release AAR。

## 证据与复用

- 发布根报告：`delivery/android-dingqiao/evidence/release-gate/20260916-1bdb516e-0.3.5/report.json`。
- SDK 账本绑定 Release SDK 子 ZIP；本报告绑定最终完整 ZIP，二者用途不同。
- 逐会话回调、首次 FAIL、定向 PASS、内存采样、输入哈希与构建来源均保留；不提交原始 PCM、授权或密钥。
- SDK 和 Demo 冻结于 `1bdb516e708d0c939fe199dddee554af4fb9a6f8`。之后仅补测试、账本、脱敏证据和外置报告，不改变交付二进制。
