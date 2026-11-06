# Sortformer `npu-v1` 交付包在 Kirin 9020 NPU 上的探测（2026-11-06）

对象：模型方交付的 `nemo-66M-4spk-npu-v1.zip`（仓库根目录，gitignored；sha256 `762fee8d04dd74de…`，MANIFEST 34 项全部校验通过）。
与 `delivery-v1` 同一 checkpoint，专为 NPU 重导出：**全静态 shape**（`feats[1,501,512]` + 加性 `attn_mask[1,1,1,501]`）、
1522 节点、opset 只有 `"":17`、不含 ORT 动态量化算子，推荐用 `converter_lite WEIGHT_QUANT bit_num=8`。包自己声明目标是
**Kirin 8020 / nova 15**，且"没有任何 NPU 上的数据"。

设备：Mate 80 / Kirin 9020（`NPU_ohos.boot.hardware.kirin9020_v2_0`）/ HarmonyOS 7.0.0.109，诊断 Demo（debug 签名）里的 `MindirProbe`。
探测口径与 11-04 那轮相同：零值输入，只判"加速器是否接受该图"与延迟，**不含精度含义**。

## 结论

**不能。** 这个包把 11-04 那轮怀疑过的全部图级变量都换掉了（动态 shape → 静态、无 mask → 有 mask、ORT 动态量化 → converter
权重量化、opset 杂项 → 已剥除、体量 → 84.9 MB），`encoder_layers` 在 Kirin 9020 NPU 上**仍然撞同一道墙**：

```
dllite_service/DLSA: QueryCapabilityParam Results is empty
com.amphion.asr.harmony.demo/DLSA: Authentication failed, fail to authenticate model.
com.amphion.asr.harmony.demo/NNRt: Authentication failed, input model cannot run by npu.
NNRt: OH_NNCompilation_Build failed, fail to create compiler.
MS_LITE: [nnrt_delegate.cc:772] InitNNCompilation# Build NNCompilation failed, ret: 1
```

| 图 | `.ms` 体量 | NPU 结果 | build | 备注 |
|---|---:|---|---:|---|
| `pre_encode`（静态 mel 992） | 2.1 MB | **PASS** | 174 ms | 中位 0.51 ms（11-04 动态版 3.44 ms） |
| `speaker_head` | 4.1 MB | **PASS** | 213 ms | 中位 2.59 ms |
| `encoder_layers.npu`（WEIGHT_QUANT） | 84.9 MB | **FAIL** | 978 / 1260 ms | `DLSA: Authentication failed`，两次复现 |
| `encoder_layers.fp32`（对照） | 276.8 MB | FAIL | 207 ms | 体量超限的"直接拒绝"模式，无认证日志，与包 README 预判一致 |

主机侧：三张静态图对 `golden/` 逐级比对 max|Δ| = 2.3e-4 / 5.2e-6 / 1.9e-5（ORT 1.24.3 CPU），与包内自报一致；
`converter_lite` 2.7.0 四张图全部 `CONVERT RESULT SUCCESS`，秒级完成。

## 本轮新增的证据

完整 hilog（`hilog -r` 后冷启动探针、`hilog -x` 全量落盘）给出了 11-04 没抓到的前半段：

1. **直接 NNRt HDI 路径被 SELinux 拒绝**（三次重试）：
   `hdf_devmgr/Selinux: avc: denied { get } for service=nnrt_device_service scontext=o:r:debug_hap:…` →
   `hdi_servmgr_client: get hdi service nnrt_device_service failed, -19` → `NNRt: [BackendManager] RegisterBackend failed`。
   我们的 Demo 是 **debug 签名**（`appProvisionType: debug`），SELinux 域是 `debug_hap`。
2. MS_LITE 随后走 HiAI Foundation 路径（`CheckNPUPrefix … current device name prefix is not HIAI_F`），在 `dllite_service` 的
   模型认证处失败：`AuthInnerApi: check system ability Id: 65888 error`、IPC `*.accessToken` error 7、
   `DLSA: QueryCapabilityParam Results is empty` → `Authentication failed`。
3. **单层二分**：从静态 encoder 抽出第 1 个 transformer 层（51 节点，fp32 8.9 MB / WEIGHT_QUANT 2.7 MB）。
   CPU 后端 **PASS**（中位 36 ms），NPU 后端 **FAIL**（build 47~78 ms），且日志里**没有任何** NNRt / DLSA / HiAI BuildModel 行——
   在 delegate 分区阶段就被放弃；MS_LITE 的原因文本全部 `<private>` 脱敏，看不到。

因此现有信息能排除的：体量（2.7 MB 也失败、134 MB Gemm 对照件曾通过）、动态 shape、mask、量化方式、opset。
当时剩下两条假设：(a) 签名/权限（`debug_hap` vs release 的 `normal_hap`、DLSA 认证资质）；(b) 算子类别。

## 华为侧答复（2026-11-06，经我方接口人转述）

两条假设都有了明确答案，与本文的实测逐条吻合：

1. **签名与 DLSA 解耦。** release 签名、`apl=normal` 只管 HAP 的安装分发身份，**不绕过**也不触发 DLSA；debug 包与 release 包
   走同一套 DLSA 判定与阈值。所以"做一个 release 签名的探针包"**没有验证价值**，假设 (a) 关闭。
2. **触发点是 Self-Attention 子图，不是单算子、不是体量。** DLSA 做的是**图连通子图识别**：只要存在完整的 SDPA 链路
   （QKV 投影 → 注意力打分 → softmax → 加权求和），哪怕只有 1 层、几 MB，就被归为 Transformer 类模型、进入强制模型认证；
   只含 Gemm/MatMul 的线性图归为普通计算模型直接放行；LayerNorm、GELU 单独出现不触发。
   —— 这正是"134 MB 纯 Gemm 通过、2.7 MB 单层 attention 失败"的解释，也解释了 SDK 的 ASR encoder（zipformer，同样含
   attention）两轮都卡在同一处。
3. **DLSA 模型认证是邀约准入，不是自助申请。** 需企业主体与营业执照、模型著作权/授权证明、权重与结构描述、输入输出样例、
   能力说明、风险评估报告；生成式模型另需内容安全与输出风控方案。须先经华为生态 / AI 侧接口人进入邀约白名单，
   才有提报入口；个人开发者无法直接提交。

## 对交付的含义

- **Sortformer encoder（31 层 attention）在 Kirin 9020 的 NPU 上，没有 DLSA 认证就不可能跑。** 这是平台准入策略，
  不是我们能靠改图、改量化、改签名解决的工程问题；两轮实验（11-04、本轮）到此为止，不再在 9020 上做图级变量实验。
- 鸿蒙 0.3.27 保持 CPU（ORT 1.16.3）路径不变；`npu-v1` 包不进入任何交付。`pre_encode` / `speaker_head` 虽能上 NPU，
  但两者合计占算力不到 2%，且 11-04 已实测小图 NPU 无延迟优势，单独上 NPU 没有意义。
- 若公司层面要走 NPU，路径只有一条：以企业主体通过华为接口人申请 DLSA 模型认证（材料见上）。认证对象是**模型**，
  Sortformer-66M-4spk 的权重与著作权归属需先与模型提供方理清。这是商务/合规动作，不是研发动作，需要公司决策。
- 包的目标机 Kirin 8020 / nova 15 我方没有；按上述答复，8020 上同样会进 DLSA 认证路径，README §0 的两道墙已不是首要问题。

## 复现

```bash
# 转换（Docker linux/amd64，MindSpore Lite 2.7.0）
docker run --rm --platform linux/amd64 \
  -v <mindspore-lite-2.7.0-linux-x64>:/ml:ro -v <解包目录>:/pkg ubuntu:22.04 \
  bash -c 'export LD_LIBRARY_PATH=/ml/tools/converter/lib PATH=/ml/tools/converter/converter:$PATH; cd /pkg; \
    converter_lite --fmk=ONNX --modelFile=models/fp32/encoder_layers.static.onnx --outputFile=models/ms/encoder_layers.npu \
      --inputShape="feats:1,501,512;attn_mask:1,1,1,501" --configFile=converter/quant8.cfg'
# 推文件：hdc file send -b 只在应用进程存活时可用 —— 先 aa start 普通拉起，再 send，再 force-stop
hdc shell aa start -a EntryAbility -b com.amphion.asr.harmony.demo; sleep 3
hdc file send -b com.amphion.asr.harmony.demo encoder_layers.npu.ms /data/storage/el2/base/files/encoder_layers.npu.ms
hdc shell aa force-stop com.amphion.asr.harmony.demo; hdc shell hilog -r
hdc shell aa start -a EntryAbility -b com.amphion.asr.harmony.demo --ps mindirProbe true --ps mindirProbeRunId <id> \
  --ps mindirProbeModel /data/storage/el2/base/files/encoder_layers.npu.ms --ps mindirProbeBackend npu --ps mindirProbeIterations 3
hdc shell "hilog -x" > full.log     # 立刻全量落盘；下一次 hilog -r 之前不要再探测
```

单层二分：`onnx.utils.extract_model(encoder, out, ['feats','attn_mask'], ['/layers.1/norm1/LayerNormalization_output_0'])`。
