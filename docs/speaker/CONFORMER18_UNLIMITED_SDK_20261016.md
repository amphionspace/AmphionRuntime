# Conformer18 无全局人数上限候选 SDK（2026-10-16）

本次将 SDK 默认 `maxSpeakers` 改为 0（不限制全局身份数）；正整数仍表示调用方显式设置的公开身份容量，负数/非整数非法。局部分割槽位仍为模型固有的 8 路，不等于会话全局最多 8 人。调用方如果显式传 4，必须删除该设置或改为 0。

## 当前推理流程

- 原 ASR 分支保留；角色分支为 conformer18 学生 checkpoint epoch 29，权重不变。
- 16 kHz，固定 320000 样本传输缓冲区及 validSamples；20 秒窗口、2 秒步长，最多一个尾窗，输出裁剪到真实结束。
- ECAPA 浮点 ONNX：与 pyannote.audio 3.4 的有效 mask 规则对齐。250 帧固定网格，活动阈值 0.5；非重叠帧数 > 1 时选非重叠，否则回退到该槽全部活动；至少 640 真实样本，不再重复短语音到 8000 样本。尾部 padding 不选入。
- 当前 chunk 内提取 embedding；历史代表 + 近期未压缩 embedding + 当前 embedding，单位向量 centroid AHC / 0.67 / min_cluster_size=1。
- 每 50 chunk 按历史 ID 压缩为向量和、计数；不是丢弃 50 chunk 之前的历史。历史 ID 投票按计数加权；代表在 AHC 几何中不作计数加权。
- 因果重叠平均、提交后冻结，不在结束时对全录音重聚类。N-API、JNI、主角色和副角色索引均支持超过四人的全局 ID。

## 与提供的 18.1782% 实验的边界

该数字来自 335 段冻结缓存回放，不能标注为本 SDK 的 DER。缓存提取按 32 个局部槽位跨窗口成批；本 SDK 按当前 chunk 成批，保持在线因果边界，padding/批次数值可能不同。ONNX/ARM 与 PyTorch/CUDA 也不是逐位等价。当前修复对齐算法与选样规则，不宣称复刻了冻结缓存的数值。恢复浮点 ECAPA 后旧 INT8 性能证据失效。

## 产物与验证

- `amphion_dingqiao-release.har`：自包含正式构建模式候选 SDK。
- `amphion_dingqiao-diagnostics.har`：自包含诊断 SDK。
- `amphion_asr_demo-release-signed.hap`：签名 release Demo 候选。
- `amphion_asr_demo-evaluation-signed.hap`：手机实际安装的诊断测试载体，修正了短录音必须至少两次公开窗口回调的错误断言。
- `evaluation-carrier-only-change.json`：测试载体修正前后的 15 个模型/native 条目哈希一致。旧 FAIL 原样保留，不改写为 PASS。
- `host-tests.log`：66 项相关 native/ArkTS/资源/场景检查通过；另有新增载体终态断言测试通过。
- Android 会话/客户端及新增无限人数索引测试通过。尚无本次 Android 真机证据，不能视为双端发布通过。
- `short-ecapa-parity.json`：640/1280/2560/8000/16000 样本的 float ONNX 与 SpeechBrain 单位向量方向一致（cosine > 0.99999）。
- `*-signature-verification-v2.log`：evaluation/release HAP 签名验证通过。

真机新结果位于 `diarization/conformer18/outputs/phone-unlimited-verified`，OpenBench collar=0、计入 overlap、逐完整录音一一映射。原 `phone-unlimited-smoke-v2` 的 RTTM 完整但载体断言 FAIL，不能当作 SDK 门禁通过。`phone-unlimited-smoke` 由于旧 Python 3.12 基础路径不存在未启动设备推理，保留错误现场。

本目录为本地候选构建，未宣称完整产品验收或发布。API 23 旧编译器门禁、Android 真机、完整断网/网络观测和长会议验收尚不具备本次全部证据。

## 真机定向结果

三段均 SDK PASS，全窗口覆盖、唯一 last 后唯一 complete，修正测试载体前后 RTTM 字节相同。

|录音|标注人数|预测身份数|DER|
|---|---:|---:|---:|
|voxconverse:fuzfh|3|3|13.1093%|
|voxconverse:gyomp|5|5|6.4204%|
|voxconverse:fpfvy|11|11|16.9506%|

三段加权 OpenBench DER 13.4321%。身份数量相等不证明身份逐段正确，仍以 DER/CONF 与片段检查为准。25 段新评测已启动于 `phone-unlimited-25`，尚未完成；失败停止，不混入旧四人限制版本结果。
