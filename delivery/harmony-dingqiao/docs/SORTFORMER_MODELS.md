# Sortformer-66M-4spk（Harmony 角色分离，0.3.26 起）

0.3.26 起鸿蒙角色分离由 Sortformer-66M-4spk 流式模型承担，取代此前的
pyannote 分割 + WeSpeaker 嵌入 + PLDA/VBx 聚类（Community-1）链路。模型、运行时
格式与校验值以 `delivery/sortformer_diarization_v1.json` 为准，本文只说明来源、
恢复方式与链路事实。

## 来源与恢复

- 交付包：`sortformer-66M-4spk-delivery-v1（1）.zip`（第二版；第一版的 int8
  编码器声明了 ORT 1.16.3 不支持的 `ai.onnx.ml:5` 域，无法加载）。整包 SHA-256
  记录在清单 `deliveryPackage.sha256`。
- 运行时资产（不进 Git，恢复到 `shared/models/asr/dingqiao/sortformer-66M-4spk/`）：

| 文件 | 来源 | 转换 |
|---|---|---|
| `pre_encode.ort` | `models/pre_encode.onnx` | ORT 1.16.3 `convert_onnx_models_to_ort`，`optimization_style=Fixed`，`target_platform=arm` |
| `encoder_layers.int8.ort` | `models/int8/encoder_layers.int8.ort1163.onnx` | 同上 |
| `speaker_head.ort` | `models/speaker_head.onnx` | 同上 |
| `spkcache_update.ort` | `models/spkcache_update.onnx` | 同上 |
| `learnable_sil_emb.npy` | `models/learnable_sil_emb.npy` | 逐字节复制 |
| `mel_window_hann400_periodic_false.npy` | `golden/frontend/` | 逐字节复制 |
| `mel_filterbank_128x257_slaney.npy` | `golden/frontend/` | 逐字节复制 |

`asr/harmony/sdk-dingqiao/hvigorfile.ts` 构建时按清单核对大小与 SHA-256，
同步到 `rawfile/amphion-dingqiao/sortformer-66M-4spk/`；任一文件不符即构建失败。
`verify_demo_inputs.sh` 再对 HAP 内的同名条目做逐字节比对，`harmony_build_identity.py`
把七个文件的哈希记入构建身份。

## 链路事实（与清单 `streaming`/`melFrontend` 一致）

- 16 kHz 单声道；mel 前端 n_fft 512 / win 400 / hop 160 / 128 带 slaney /
  预加重 0.97 / `log(mel + 2^-24)`，不做归一化。前端在 native 流式实现
  （`asr/harmony/sdk/src/main/cpp/sortformer_diarization.cpp`），每帧左右各看
  256 个真实采样，仅会话开头与 flush 处补零，与交付方整段参考实现逐帧一致
  （端上黄金向量 max|Δ| 2.3e-5）。
- 分块：124 个编码器帧（992 个 mel 帧 = 9.92 s）+ 1 帧右上下文；speaker-cache 188、
  FIFO 188、`scores_boost_latest = 0`。上下文按有效长度紧凑拼接，不按容量补零。
- 预览：每块到达 `diarizationPreviewMs`（默认 5000 ms）时，对已到部分做一次不提交
  状态的推理，先给出临时角色；该块完成后由最终结果覆盖。
- 四个槽位即模型自带的按出场顺序的说话人身份，整场稳定；SDK 只在某槽位首次出现
  在**最终**块里时给它分配公开角色号（`S1..S4`，受 `maxSpeakers` 封顶，超出保持匿名），
  不再做跨窗聚类或身份投票。
- 执行：ORT 1.16.3 CPU EP，默认 2 个 intra-op 线程，role QoS 策略不变；XNNPACK EP 在
  该 int8 图上精度相同但慢 4 倍，不使用。

## 真机实测（VYG-AL30，HarmonyOS 7.0，2026-10-28）

| 语料 | 现网 Community 链路 | Sortformer |
|---|---:|---:|
| 丁桥现场 5 条（UEM 受限，openbench-der-v1） | 23.10% | **12.10%** |
| AliMeeting 20 窗（官方人工金标，B 口径） | 36.07%（宿主近似链路） | **12.74%** |

编码器每块中位 389 ms（4 线程）；整文件推理 RTF 0.045，加 5 s 预览后 0.075~0.080；
CPU 秒/音频秒 0.150（功耗代理，与 Community 估算 0.08~0.17 同量级）。
详细数据见仓库根 `Sortformer_66M_真机实测报告_20261028.md`。
