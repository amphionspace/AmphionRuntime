# 首窗内存归属与 arena 释放对照（2026-09-28）

**已定位主要 RSS 台阶到首个 encoder 调用；释放 arena 的候选仍未过门禁，已撤回。** 当前运行代码恢复为 `ad16789a` 的容量修复版本。短录音资源失败、长时趋势和短段身份问题继续阻断交付。本轮没有修改评分、64 MiB 资源门槛、模型、窗口、hop 或结束超时。

证据及输入/产物哈希见[索引](evidence/DIARIZATION_MEMORY_OWNERSHIP_20260928.json)。这是一项分配归属诊断，两个插桩 HAP 都是 non-canonical，不能代替四锚点或发布矩阵。此前有效容量修复证据继续见[同产物四锚点报告](DIARIZATION_CAPACITY_FIX_20260928.md)。

## 假设与唯一变量

既有19.58秒四人录音在首个10秒角色窗口开始时出现主要 RSS 台阶。代码已调用 `DisableCpuMemArena()`，因此再次关闭 CPU arena 不是新实验。

锁定版本的 ORT 源码显示，XNNPACK 的 `GetStoredAllocator()` 返回进程级 allocator，`CreatePreferredAllocators()` 默认创建 arena；Session 按设备注册 allocator，先注册的 XNNPACK 优先于 CPU。这提供了需要实测的归属假设，但源码本身不能证明全部 RSS 都来自该 arena。

第一路 `615c6aa0` 仅加入只读 RSS / `mallinfo2()` 阶段观测：window start、segmentation、features、encoder、pooling、run pooling，以及 async Work 销毁后。保留正常 ASR、SDK 调用时序及诊断输出。

第二路 `9f9905f8` 保留同样插桩，只给 encoder 的 `RunOptions` 增加 `memory.enable_memory_arena_shrinkage=cpu:0`，验证现有推理边界能否释放已空闲的 arena 区域。没有改变推理算式、线程数量、聚类、身份冻结或公开接口。若没有解决资源红灯，或声学/公开结果发生差异，则不作为生产修复。

最初的独立 native executable 被设备执行策略拒绝，没有运行模型，也没有修改设备权限。随后使用正常 CLT 构建、签名的 ZH_EN HAP。两个版本分别通过签名、授权、模型和构建身份检查；每路只跑一次相同短录音，未扩展长会议或完整实录。

## 分阶段发现与对照

Mate80 `7GK0226326015655`，系统 `OpenHarmony-6.1.1.120`，相同16 kHz mono PCM16、20 ms paced 输入。运行库 SHA-256 均为 `e5f009eaefd1eb91ae79d672d279847d54fa2b56d9265378626438e2e921d591`；HAP/HAR 分别绑定各自诊断提交，没有混为同一产物证据。

第一路首窗的 encoder 阶段 RSS 增加 **76.184 MiB**，随后的 pooling 增加 **0.090 MiB**；async Work 释放后 RSS 仍保持较高水平。窗口起始 RSS 从442.15 MiB升到下一窗524.63 MiB，后续仍升至566.13 MiB。因此可将主要首窗台阶定位到 encoder 阶段，尚不能将后续全部增长归因为同一个对象，也不能证明长时间已经达到平台。

| 指标 | 插桩基线 | 仅释放 encoder arena |
| --- | ---: | ---: |
| RSS 头/尾中位数，MiB | 435.256 / 567.102 | 449.783 / 542.883 |
| RSS 增长，MiB | 131.846 | 93.100 |
| RSS 峰值，MiB | 568.930 | 559.309 |
| VmData 首尾增长，MiB | 361.812 | 28.438 |
| encoder + pooling 均值，ms | 407.745 | 413.945 |
| 全窗口推理均值，ms | 565.119 | 558.136 |
| SDK diarization RTF | 0.3184 | 0.3145 |
| 最大音频延迟，ms | 760 | 720 |
| pending / in-flight 最大值 | 0 / 1 | 0 / 1 |
| SDK 生命周期 / stream 归零 | PASS / PASS | PASS / PASS |
| 既有资源门禁 | FAIL | FAIL |

释放路径的尾部 RSS 降低24.219 MiB，峰值降低9.621 MiB。两个冷启动的头部 RSS 不同，因此不能把增长差38.746 MiB全算成候选节省。单轮短样本和插桩耗时也不足以确定性能优劣；没有放宽门槛，没有忽略冷启动阶段，也没有把不足60秒的观察判为长期稳定。

结束后的 `hidumper --mem` 快照显示大量驻留仍位于 native heap，但它取得时间晚于 runner 的固定观察窗，只用于区分 native / ArkTS / HAP 映射，不能替换门禁采样或用作降低 RSS 的新成绩。`mallinfo2()` 不是 ORT arena 内部的 live/reserved 明细；下一步必须进一步分开 XNNPACK arena 与 libc 缓存的实际持有关系。

## 输出与回退保护

插桩基线对 `ad16789a`，以及释放路径对插桩基线，分别比较了全部11窗：窗口坐标、分割、整窗/run embedding、run 范围和 RMS 均逐值相同。ASR 原句及时间信息、公共最终结果的文本/时间轴/身份/UNKNOWN/overlap 字段也全部相同。标准 session 均唯一 last 后唯一 complete，stream 归零。

这些等价检查只覆盖该短录音，不能外推完整公开集、四锚点、所有生命周期或调用方 UI。没有把4个人数正确或接口 PASS 当作身份精度和可读性全面通过；本轮没有重新计算公开集数字。

## 处理结果与后续定位

`26e91516` 移除了临时观测和 arena 释放试验，恢复后的 `community_diarization.cpp` 与 `ad16789a` 逐字节相同。原容量修复 HAP/HAR 已从不可覆盖归档恢复，失败 HAP/HAR、完整事件、memory.csv、hilog 和对照结果另行保留。没有为恢复相同源码与产物重复构建或重复真机验收，也未改变既有测试。

本次结果否定了“仅在现有 encoder Run 结束时释放空闲 arena 就足以解决短录音资源红灯”的方案。下一次实验应直接观测 encoder allocator 的 live/reserved 区域及窗口返回、模型关闭时的释放量，再选择改变分配归属或工作区复用的最小修复。不得以扩大超时、隐藏首次内存或增加观察等待来转绿。短段查询新增误认仍是独立身份阻断项，不能由本轮内存诊断结案。
