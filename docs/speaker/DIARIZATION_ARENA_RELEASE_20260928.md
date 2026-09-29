# XNNPACK 空闲 arena 回收修复（2026-09-28）

**短录音结束后的资源红灯已修复；角色分离整体交付仍阻断。** 生产候选 `f6aef3d4` 在最后一个使用者释放内存后回收进程级 XNNPACK arena。临时计数日志已删除。连续短会话和 124 秒锚点共 137 个窗口的声学张量、ASR 对齐、临时聚类、冻结身份及公开结果与 `ad16789a` 基线完全一致。没有修改模型、窗口、hop、timeout、UNKNOWN、文本合并、评分或资源门槛。

## 从现场到最早错误状态

前一轮[首窗内存实验](DIARIZATION_MEMORY_OWNERSHIP_20260928.md)已否定“每次 encoder Run 后释放就足够”的假设。本轮只增加 allocator 的 live/reserved、RSS 与生命周期观测；同一 19.58 秒 PCM 的 11 窗声学及公开结果与旧产物完全一致。

锁定的 ORT 1.16.3 使用进程级 `GetStoredAllocator()`。`DisableCpuMemArena()` 没有关闭 XNNPACK 的 arena。首窗前 reserved 为 63 MiB，第二窗后为 255 MiB；推理时仍有约 100 MiB live，因此 Run 返回并不代表全部工作区已空闲。**provider 销毁时 live 已归零，reserved 仍为 255 MiB**，这是本次直接观测到的未回收状态。

修复只在 provider 销毁且共享 arena 的 live 为 0 时调用现有 `BFCArena::Shrink()`。有其他会话在使用时不触发主动回收；`Shrink()` 自身持锁且只释放完全空闲的区域，即使检查后发生新的分配，也不会释放活跃块。保留 ORT 的初始 arena 区域与原有 allocator 归属，没有替换全局 allocator 或调整推理计算。

诊断候选销毁前后 reserved 从 255 MiB 降至 1 MiB，RSS 从 562.582 MiB 降至 429.730 MiB，回收耗时约 25 ms。释放的虚拟保留量不等同于物理 RSS 下降量。

| 同一短 PCM 单次诊断 | 原 allocator `6099d79c` | 销毁回收 `7aa22a31` |
| --- | ---: | ---: |
| 结束后 reserved | 255 MiB | 1 MiB |
| runner RSS 增长 | +131.518 MiB | −10.107 MiB |
| RSS 峰值 | 575.914 MiB | 574.012 MiB |
| 角色 RTF | 0.31566 | 0.31658 |
| 既有 64 MiB 资源门禁 | FAIL | PASS |
| 11 窗声学 / ASR / 公开结果 | 对照基线 | 逐项相同 |

这证明的是结束后回收；运行峰值未显著下降。两个诊断产物均为 non-canonical，不能替代下列无插桩候选。

## 同产物候选验收

Mate80 `7GK0226326015655`、`OpenHarmony-6.1.1.120`，运行提交 `f6aef3d4d17887c23b74f2c5436716007928264f`。ZH_EN diagnostics HAP SHA-256 为 `46e74a45e6057680087fb9261277e7ff902976fc3f9a6c74e3bc47f217e549fc`；ORT 为 `503ac466600ce4e75843684159f5903b653cf0406bbfd2a1558e49d04157fcbf`。五个 HAP/HAR、build identity、输入索引、报告、memory.csv、hilog、完整事件及诊断分叉均由[证据索引](evidence/DIARIZATION_ARENA_RELEASE_20260928.json)绑定。原始音频和含文本诊断留在私有缓存，不提交 Git。

| 用例 | 公开结果 / 生命周期 | 实时与资源 |
| --- | --- | --- |
| 19.58 秒四人，连续两 session | 22 窗及全部临时 / 冻结 / 公开结果与原基线相同；每 session 唯一 last 后接唯一 complete；stream=0 | RTF 0.3143 / 0.3189；pending=0、in-flight≤1、最大音频延迟720 ms；结束耗时805 / 729 ms；runner memory PASS；不足60秒，长期趋势 INCONCLUSIVE |
| 123.8 秒四人 | 115 窗与全部公开状态相同；last/complete 与 stream 回收 PASS | RTF 0.546，pending=0、in-flight≤1、最大延迟980 ms；调用方停止到完成1314 ms；实时 PASS，runner memory PASS，严格长期内存 INCONCLUSIVE |
| cancel-full，两轮 | 两轮均无 final / complete / error，stream=0，取消后下一轮可启动 | SDK PASS；观察较短，内存 INCONCLUSIVE |
| finish → shutdown → setLicense → prepareRuntime → recovery | finish前last=0；原会话和恢复会话均唯一last / complete、无error、stream=0 | SDK及runner memory PASS；不足60秒，长期趋势 INCONCLUSIVE |

长锚点的 RSS 三段中位数为619.191 / 629.516 / 648.920 MiB，虽回归斜率为负，末段中位数仍高于前段。按原规则保留 INCONCLUSIVE，不能用结束后的释放掩盖运行中趋势。重复短会话的采样头段已落入首轮推理阶段，其 RSS 增长值不能与单次冷会话直接相减。上表只能证明已覆盖的两条 PCM 在此调度下未出现身份、文本或时序回退，不能替代全部实录或人工身份准确性判定。

主机54项 Community、公共角色契约及证据 spool 测试通过。构建时直接提取生产 ORT completion 方法与 provider 析构函数，验证延迟任务完成、输出可见性、section 复用，以及最后一个 owner 释放、仍活跃的第二 owner、下一 provider 分配和非 arena 策略。旧析构函数稳定红灯，修复后绿灯。真实 BFCArena 的资源效果以上述设备计数为证；fixture 不冒充 allocator 的实现测试。

构建中保留了两项非行为故障现场：初次诊断打包因两个 HAR 的 ORT 不同而被现有检查拒绝；统一精确同一库后才构建。候选编译的日志宏缺少花括号也已修正。没有降低签名、来源、重复库或构建身份校验。

## 放行边界与后续问题

本次只修改 Harmony 的 ORT 补丁；Android 运行代码未变，未将旧 Android 结果写成新平台验收。没有再次发布公开集 DER 成绩，也没有把“输出相同”当作“已有身份错误已解决”。客户开场短段 UNKNOWN、短查询候选新增的公开集边界误认、长时内存、完整四锚点/16段实录、最终调用方体验和完整发布矩阵仍阻断交付。没有合入最终 PR 或生成正式发布 ZIP。

独立短 mask 归属审计发现：当 clean 仅1–2帧且同通道还含 overlap 时，native 的整窗 embedding 池化范围包含 overlap，现有短段建档却可能将其归给唯一 clean run。两个公开窗口触发该形态，但在已存提交中未实际获准建档；不能宣称它是当前公开误认的已证根因。隔离补丁已有最小红绿用例和五段已存张量的结果不变证据，尚未并入本内存提交。下一步应独立落地这项所有权修复，然后继续短段身份与运行中内存定位，不能复用本提交的产物身份冒充后续候选验收。
