# Conv-TasNet Harmony 真机第一资源门（2026-08-04）

## 1. 问题与边界

本轮只回答：固定 2 秒 Conv-TasNet ONNX 能否在当前 Harmony 交付栈和 Mate 80 ARM CPU 上创建 session、
稳定推理，并且不破坏随后发生的 ASR session 生命周期。

本轮改变的是 demo 隐藏诊断载体；必须保持不变的是 SDK 公共 API、`isFinal/isLast/onComplete/cancel`
语义、现有 `ZH_EN` 模型和客户 C1～C3 PCM。明确未处理：端侧逐块 ERes2Net 选流、交叠拼接、分离后
重识别、target-absent 产品门和正式 SDK 接入。

## 2. 真机与构建身份

- 设备：Huawei Mate 80 `VYG-AL30`，12 GB，12 logical CPUs，`arm64-v8a`。
- 系统：`6.1.0.135(SP8C00E120R5P7)`。
- SDK/HAP：0.2.9、唯一 `ZH_EN` 诊断 HAP，SHA-256
  `d351b61ee4764ccff7982dc8342104eff5f0e6ca7134979f96a9f09c27c4a530`，大小 `354,318,840 bytes`。
- ONNX Runtime：交付自带 1.16.3 CPU EP；没有 NPU/GPU EP。
- Conv-TasNet：固定 `1×32000`、opset 17、`20,147,162 bytes`，SHA-256
  `f5b040d383007319c67bd2e1862cc6b6b2ac9bef5101581f30c0c00200b3b7ab`。
- 输入：与此前客户回归完全相同的 `101_C1.wav`、`102_C2.wav`、`103_C3.wav`，SHA-256 分别为
  `a687cb55710bb3ef1771717d74bdf3e974653bd004bf490200ed9a3c86ddab9b`、
  `e12589eb974e422349d26b4b3b1bb41735b2cbb60744ce5cfdb1b4ff7cc41b59`、
  `f556c1ca7226678bbd448156a724b0e372c8ec8fe1c758c0fc042afa44502b00`。

## 3. 实验方法

每条 case 在同一个已经加载 `ZH_EN` ASR 的 app 进程内执行：

1. 关闭 ORT CPU arena 和 memory pattern，4 个 intra-op thread、1 个 inter-op thread。
2. 创建一次 Conv-TasNet session；warmup 一次；对该条前 2 秒 PCM 连续推理 10 次。
3. 检查输出为 `[1,2,32000]` 且全部有限值。
4. 释放 separator session，立即用同一个 ASR engine 跑完整原始 PCM session。
5. 调用 `finish` 前要求 `isLast=0`；结束后要求恰好一次 `isLast`、一次 `onComplete`，无 error，下一 case
   继续复用同一 engine。
6. 宿主每 0.5 秒采样 `/proc/<pid>/status`，保留 RSS/HWM/线程与完整 hilog。

## 4. 结果

| Case | create | warmup | 中位 2 秒块 | p95 / 最大 | 中位 RTF | 生命周期 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| C1 | 147.3 ms | 295.3 ms | 287.7 ms | 328.2 ms | 0.144 | 1 start / 1 last / 1 complete / 0 error |
| C2 | 143.8 ms | 294.6 ms | 309.3 ms | 324.0 ms | 0.155 | 1 start / 1 last / 1 complete / 0 error |
| C3 | 181.1 ms | 321.5 ms | 324.5 ms | 589.6 ms | 0.162 | 1 start / 1 last / 1 complete / 0 error |

- 最差观测 p95 RTF：`589.6 / 2000 = 0.295`，通过 `<0.35` 的高端机应急门。
- 进程 RSS peak `519.359 MiB`，HWM peak `533.152 MiB`；稳定段 RSS head/tail
  `425.812/415.934 MiB`，线程 head/tail `53/48`。它没有超过此前同设备声纹客户回放的
  `552.414 MiB` peak，但两种模式的模型驻留与采样时序不同，不能据此宣称 separator 的独立增量为负数。
- 三条共 3 start、6 final、3 last、3 complete、0 error；每条 `runRecognitionCycle` 均在 `finish` 前
  检查 `lastFinalsBeforeFinish=0` 后才判 PASS。
- HAP 相比此前约 339 MB 诊断包增加约 15.3 MB；ONNX 原始大小为 20.15 MB，差异来自 HAP 打包压缩，
  不能把 15.3 MB 当作运行时内存。

通过 artifact：
[`20260804-160039-separator-bench-598f17b0/report.json`](../../delivery/harmony-dingqiao/build/device-stress/20260804-160039-separator-bench-598f17b0/report.json)。
首次 20 次同步调用触发 6 秒看门狗并被杀的失败 artifact
`20260804-155758-separator-bench-98165589` 与随后输出回收问题 artifact
`20260804-155938-separator-bench-fe2c7a55` 均单独保留，没有覆盖。

## 5. 根因与产品约束

第一轮连续 20 次推理时，模型已经完成 C1/C2 推理和生命周期检查，但 app 被 Harmony 以
`THREAD_BLOCK_6S` 杀死。降为 10 次后三条完成，但 C3 仍出现 `THREAD_BLOCK_3S` 告警。模型单块只需
约 0.29～0.32 秒；卡顿来自诊断 NAPI 在 UIAbility 主线程同步循环，而不是模型 RTF 不足。

因此结论分两层：

- **ARM CPU 原始计算门：PASS。** 当前 Mate 80 能承载固定 2 秒 Conv-TasNet，且有充足实时系数余量。
- **产品接入门：尚未通过。** separator 必须在独立 worker/任务池运行；不得在 UI、音频采集或 ASR 回调
  线程同步推理。还需要完成端侧逐块选流、拼接、重识别和 target-absent 门。

## 6. 指定下一步

下一实现只做 app/demo 层异步 rescue，不改 SDK 默认状态机：

1. 在独立 worker 持有按需 separator session；主线程只提交 PCM 和接收完成消息。
2. 用 2 秒块、0.5 秒交叠；每块两路都由现有 ERes2Net 重新评分，不能固定输出流序号。
3. 只在 session 已有强目标滑窗证据、whole final 因混合被拒绝时触发；target-absent 默认不运行。
4. 用 C1～C3 完整波形验证端侧分离、选流、拼接和重识别文本；再补 target-only/other-only/
   target-absent。
5. 继续门：无 `THREAD_BLOCK`、最差 p95 RTF `<0.35`、相对基线增量 peak RSS `<250 MiB`、C1～C3
   “含上海、无你好”、生命周期不变。任何一项失败即停止正式 SDK 集成。

模型许可仍是独立阻断：checkpoint 当前标记 CC BY-SA 4.0，内部 pilot 可继续，闭源客户交付前必须完成
许可审查。

## 7. 实验后恢复

诊断 NAPI、临时 ORT 头文件和内嵌 Conv-TasNet 已从源码与交付载体移除；原 demo 许可证已恢复。
随后重新构建、校验并安装唯一 `ZH_EN` 0.2.9 HAP，设备侧 `bm dump` 确认 `versionCode=209`、
`versionName=0.2.9`、`cpuAbi=arm64-v8a`。完成全链路实验后的当前干净 HAP 大小为
`334,008,492 bytes`，SHA-256 为
`bb3d3de64d29cdef0ba681a9f275ec0b6ed224e78cdf970a6b0c6d7540ffd18a`，归档清单不再包含
`convtasnet_2s.onnx` 或诊断头文件。构建时使用当前 5 台设备清单对应的已验证测试许可证；安装后源码树已
恢复原许可证，SHA-256 `579f75d3cc2d2f31685ec2244522c6c5a65af688a19b3de0f0e433c142e18cc2`。
