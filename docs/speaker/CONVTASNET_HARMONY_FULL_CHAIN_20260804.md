# Conv-TasNet Harmony 真机全链路验证（2026-08-04）

## 1. 结论

在 Huawei Mate 80、Harmony `ZH_EN` 0.2.9 交付栈上，固定 2 秒 Conv-TasNet 已完成以下端侧闭环：

`客户混合 PCM -> 2 秒分块/0.5 秒交叠 -> 两路分离 -> ERes2Net 逐块选流 -> 淡入淡出拼接 -> 公共 ASR API 重识别`

- C1、C2、C3 均满足严格业务门：最终文本包含“上海”，不包含“你好”。
- 三轮正常 session 均为一次 start、显式 `finish` 前零次 `isLast`、结束后恰好一次 `isLast` 和一次
  `onComplete`，无 error、无串 session、无 `THREAD_BLOCK`。
- separator 的 2 秒块 p50/p95/max RTF 为 `0.171/0.179/0.185`，通过 `<0.35` 门。
- 与同一最终诊断 HAP 的声纹常驻基线相比，救援链路 peak RSS 增量约 `203.5 MiB`，通过
  `<250 MiB` 门；测试后 RSS 和线程数均回落。
- 单个完整 2 秒声纹嵌入替代两个重叠 1.5 秒嵌入后，C1～C3 的选流序列和文本完全不变，声纹耗时
  降低 `34.7%`，worker 总耗时降低 `13.1%`。
- 负向小样本通过：注册说话人单独输入 5/5 块被选中；一名非注册 AISHELL3 说话人单独输入 5/5
  块全部低于 `0.25` 并输出空 PCM。

这证明当前 12 GB/12 logical CPU 的 Mate 80 能承载内部、高端机、离线按需 rescue。它不证明
`0.25` 阈值已具备开放集泛化，也不证明 8 GB 或中端设备可交付。

## 2. 验证边界和不变量

本轮改变：只在隐藏诊断载体中加入异步 native worker、固定 Conv-TasNet 和结果采集。

必须保持：

- SDK 公共 ASR 生命周期与 `isFinal/isLast/onComplete/cancel` 契约；
- 现有 `ZH_EN` ASR、ERes2Net、客户 C1～C3 PCM 和三段 enrollment；
- 2 秒块、0.5 秒 overlap、按块重新选流、低置信块静音和 cosine crossfade；
- 同一轮只构建、安装一个中英 HAP。

明确未处理：模型训练、三人及以上重叠、开放集阈值标定、实时流式首包、8 GB/中端机、NPU、模型许可
和正式 SDK API 设计。

## 3. 设备、模型和输入身份

- 设备：Huawei Mate 80 `VYG-AL30`，12 GB，12 logical CPUs，`arm64-v8a`。
- 系统：`6.1.0.135(SP8C00E120R5P7)`。
- ORT：交付自带 1.16.3 CPU EP。
- Conv-TasNet：固定 `[1,32000] -> [1,2,32000]`，`20,147,162 bytes`，SHA-256
  `f5b040d383007319c67bd2e1862cc6b6b2ac9bef5101581f30c0c00200b3b7ab`。
- enrollment far/mid/near SHA-256：
  `a50064cd01bc16e9bbdb58b4cf5d21a6fb13d7346e8e1de48c4890334a9e456e`、
  `9d35c3ff1c404f6edc5b70b49197307c36fa645701ce71513e9520250a880969`、
  `5c3f33e6c7eb85fcf9277ac705da736108355a90a658b54c8c1716cf46733463`。
- C1/C2/C3 SHA-256：
  `a687cb55710bb3ef1771717d74bdf3e974653bd004bf490200ed9a3c86ddab9b`、
  `e12589eb974e422349d26b4b3b1bb41735b2cbb60744ce5cfdb1b4ff7cc41b59`、
  `f556c1ca7226678bbd448156a724b0e372c8ec8fe1c758c0fc042afa44502b00`。
- 非目标负例：AISHELL3 `SSB04340017.wav`，转为 16 kHz mono PCM16 后 SHA-256
  `4acf7dd3cf6a9e8b34dfb46aa626d17a35ab106e7b7a70251148560f1d38663f`。

## 4. 真机主结果

优化后 C1～C3 报告：
[`20260804-162951-rescue-full-chain-26303fa5/report.json`](../../delivery/harmony-dingqiao/build/device-stress/20260804-162951-rescue-full-chain-26303fa5/report.json)

| Case | 块数 | 选流序列 | separator RTF | 声纹 RTF | worker RTF | 加 ASR 的离线 RTF | 最终文本 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | --- |
| C1 | 7 | `1,1,1,1,-1,-1,-1` | 0.216 | 0.196 | 0.637 | 0.843 | 帮我查收明天的景单。准备明天去上海。 |
| C2 | 10 | `1,1,1,1,1,1,1,-1,-1,-1` | 0.241 | 0.208 | 0.621 | 0.817 | 我准备明天去北京，我看明去北京的机票。帮我定一下。准备去上海。 |
| C3 | 8 | `-1,1,1,0,0,-1,-1,-1` | 0.226 | 0.202 | 0.638 | 0.840 | 我准备去上海，你帮我准备一下飞机票多少钱？ |

三个 case 的 separator 25 个块合计 p50/p95/max RTF `0.171/0.179/0.185`。整条链路仍是离线处理，
加入 ASR 后约为音频时长的 `0.82～0.84` 倍；不能把它描述成低延迟流式能力。

### 生命周期

| Case | start | final | `finish` 前 last | 总 last | complete | error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 1 | 3 | 0 | 1 | 1 | 0 |
| C2 | 1 | 4 | 0 | 1 | 1 | 0 |
| C3 | 1 | 2 | 0 | 1 | 1 | 0 |

每条 trace 都以 `start` 开始、以 `final-last > complete` 结束；完整 hilog 未发现诊断 worker 相关
`THREAD_BLOCK`、fatal 或 signal。

## 5. 资源基线

最终诊断 HAP 的声纹常驻基线：
[`20260804-163425-voiceprint-b873db7a/report.json`](../../delivery/harmony-dingqiao/build/device-stress/20260804-163425-voiceprint-b873db7a/report.json)

最终诊断 HAP 的 target-only/other-only 运行：
[`20260804-163256-rescue-negative-10c983ef/report.json`](../../delivery/harmony-dingqiao/build/device-stress/20260804-163256-rescue-negative-10c983ef/report.json)

两者 HAP SHA-256 均为
`05ef3a06d7d5721ed92646d2870c6ab44dd47b2667358f591db2154f8aac5c0d`。

| 同产物指标 | 声纹常驻基线 | rescue 负向链路 | 增量/回落 |
| --- | ---: | ---: | ---: |
| peak RSS | 449.137 MiB | 652.652 MiB | **+203.515 MiB** |
| rescue RSS head/tail | — | 504.242 / 371.098 MiB | -133.145 MiB |
| rescue thread head/tail | — | 50 / 44.5 | -5.5 |

该配对证明 `peak RSS < baseline + 250 MiB`。观察窗口不足 60 秒，所以内存斜率仍是
`INCONCLUSIVE`；这轮只能证明有界单次调用和释放，不能证明 30～100 轮无缓慢泄漏。

## 6. 评分策略 A/B

原方案对每个 2 秒输出流计算两个重叠 1.5 秒 ERes2Net embedding；优化方案每路只计算一个完整 2 秒
embedding。A/B 除评分采样外保持模型、阈值、拼接、输入和 ASR 相同。

原方案报告：
[`20260804-162536-rescue-full-chain-f8a47011/report.json`](../../delivery/harmony-dingqiao/build/device-stress/20260804-162536-rescue-full-chain-f8a47011/report.json)

| 指标 | 两个 1.5 秒窗口 | 一个 2 秒窗口 | 变化 |
| --- | ---: | ---: | ---: |
| 三例声纹耗时合计 | 11.399 s | 7.440 s | **-34.7%** |
| 三例 worker 耗时合计 | 26.668 s | 23.178 s | **-13.1%** |
| 平均完整离线 RTF | 0.928 | 0.833 | -10.2% |
| C1～C3 选流序列 | 基线 | 完全相同 | 无退化 |
| C1～C3 最终文本 | 基线 | 完全相同 | 无退化 |

因此短期配置采用一个完整 2 秒 embedding。两个 1.5 秒窗口只作为以后遇到块内说话人快速切换时的
回退实验，不作为当前默认。

## 7. 负向门禁

| 输入 | 结果 | 分数范围 | 生命周期 |
| --- | --- | --- | --- |
| 注册说话人单独输入 | 5/5 块选中，文本非空 | 每块最优 `0.611～0.867` | 1 last / 1 complete |
| 非注册 AISHELL3 说话人单独输入 | 5/5 块拒绝，增强结果为空 | 两路 `0.026～0.159` | 1 last / 1 complete |

这里只使用了一个非注册身份，能捕获明显误选，不能估计开放集 FAR。真正交付阈值至少需要多身份、性别、
设备、距离、噪声和 target-absent 混合数据；在完成前，rescue 必须是显式 opt-in 且保留失败回退。

## 8. 发现并修复的诊断根因

第一次异步全链路运行把 C1 错拆成 28 块，所有声纹分数为 `-1`。根因不在模型：Harmony N-API 的
`napi_get_typedarray_info` 对完整 `Float32Array` 返回字节长度，而 Node 语义是元素数。诊断代码把长度再
乘 4，越过真实 PCM 边界。

修复是在 native 输入边界同时读取 backing `ArrayBuffer` 字节数：当 typed-array length 等于可用字节数
时除以 `sizeof(float)`，否则按元素数处理，并始终检查不越界。修复后 C1 恢复为 7 块，逐块分数与桌面
基准一致。该兼容处理只属于本轮诊断实现；正式 API 若复用，必须补 Node/Harmony 双语义单测。

## 9. 推荐接入与主要代价

短期推荐：仅对 Mate 80 这类高端设备提供“录音结束后、显式开启、按需加载”的离线 rescue；固定
2 秒/0.5 秒交叠、4 个 separator thread、2 个 ERes2Net thread、每路一个 2 秒 embedding、阈值 `0.25`。

主要代价：

- 比纯 ASR 增加约 20 MB 模型包和约 204 MiB 峰值 RSS；
- 录音结束后还需约 `0.82～0.84 × 音频时长` 的处理时间；
- blind separation + 后验选流不是真正 target-conditioned extraction，三人、目标缺失和跨域误选仍是
  失败域；
- 当前 checkpoint 的许可和 8/16 kHz metadata 必须在外部交付前澄清。

## 10. 指定下一步

1. 保持默认 ASR/Speaker VAD 不变，把 rescue 放在 app/service 层 opt-in，不直接改变 SDK session 状态机。
2. 正式实现复用 SDK 已有 ERes2Net extractor，避免额外实例；separator 按需创建，完成后立即释放。
3. 在同一设备做 30 轮 C1/C2/C3 交替稳压，至少持续 60 秒，门禁 RSS 斜率、线程回收、旧 session 迟到
   调用和下一 session 恢复。
4. 用不少于 20 个非注册身份和 target-absent 混合做阈值标定；任何误选都不得通过放宽文本门掩盖。
5. 许可确认通过后才进入客户包；否则回退到 Apache-2.0 的固定 RE-SepFormer 资源路线，不训练新模型。

Linux 服务器上的同口径算法/资源复验入口已固化为
[`asr/tools/speaker/12_eval_overlap_rescue.py`](../../asr/tools/speaker/12_eval_overlap_rescue.py)，运行方法见
[`CONVTASNET_LINUX_REPRODUCTION.md`](CONVTASNET_LINUX_REPRODUCTION.md)。Linux 结果不得替代本报告的
Harmony 生命周期门。

## 11. 实验后恢复

异步诊断 N-API、临时 ORT 头文件和内嵌 Conv-TasNet 已从源码与测试载体移除，原许可证已恢复，临时
输入目录已移入废纸篓；`report.json`、逐轮结果、memory.csv、hilog 和输入映射仍保留在上述 artifact。

重新构建、校验并安装的唯一 `ZH_EN` 0.2.9 HAP 为 `334,008,492 bytes`，SHA-256
`bb3d3de64d29cdef0ba681a9f275ec0b6ed224e78cdf970a6b0c6d7540ffd18a`；归档清单没有
`convtasnet_2s.onnx` 或诊断头文件。设备 `bm dump` 确认 `versionCode=209`、`versionName=0.2.9`、
`cpuAbi=arm64-v8a`，进程保持存活。

清理后的同一 HAP 又完成 3 个公共 API `burst` session：SDK、内存和空 final 门均 PASS，peak RSS
`396.836 MiB`，报告为
[`20260804-164006-burst-c38e0ead/report.json`](../../delivery/harmony-dingqiao/build/device-stress/20260804-164006-burst-c38e0ead/report.json)。

当前工作树的原许可证与 5 台授权设备清单不一致，直接预检会报 device-hash mismatch。为只完成本轮 USB
安装，干净 HAP 构建期间临时使用了已验证的 5 设备测试许可证，随后源码文件恢复为原哈希
`579f75d3cc2d2f31685ec2244522c6c5a65af688a19b3de0f0e433c142e18cc2`。正式交付前必须统一许可证与
授权清单，不能依赖本次临时构建步骤。
