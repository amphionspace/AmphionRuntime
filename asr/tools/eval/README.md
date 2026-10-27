# 端侧 ASR / 说话人 指标评测工具链

本目录是 2026-10 两轮评测（客户技术指标表逐项实测、四川话候选模型 `chuan-179m-tsx-V1`
提测）实际使用的宿主侧工具链。它解决一个具体问题：**在不依赖真机的前提下，用与
SDK 完全相同的解码器代码，对任意评测集批量测出业务口径的指标。**

## 为什么在宿主侧跑

真机只能一条一条试听，跑不了几千条的 A/B。所以把 SDK 用的那份 native 解码器
（`third_party/sherpa-onnx` + `third_party/patches/sherpa-amphion` 的 32 个补丁）
编成宿主 Python 扩展，再用 Python 复刻 SDK 的参数与喂数节奏。

关键前提：**扩展必须从打过补丁的源码编译**，不能用 pip 装的上游 sherpa-onnx ——
否则测的是上游行为，不是我们交付的行为（rule3 提交、ITN、beam 归一化、热词
UTF-8 缓冲等都在补丁里）。

```bash
asr/tools/eval/build_host_extension.sh
export PYTHONPATH=third_party/.derived/sherpa-onnx/pypkg
```

解码参数取自 SDK 源码，不自行发挥：

| 参数 | 值 | 来源 |
|---|---|---|
| `decoding_method` | `modified_beam_search` | `asr/android/sdk/.../EngineImpl.kt:377`（有热词即 beam） |
| `max_active_paths` | 8 | `EngineImpl.kt:386` |
| `modeling_unit` / `bpe_vocab` | `bbpe` / `bbpe.vocab` | `EngineImpl.kt:356` |
| 全局 `hotwords_score` | 1.0 | `PoliceEngineConfig.HOTWORDS_SCORE_DEFAULT` |
| 用户热词权重 | `词 :3.0` | `PoliceEngineConfig.USER_HOTWORDS_SCORE` |
| 预置热词池 | 约 370 条（警言警语 + 车牌 + 派出所/警种） | `PoliceEngineConfig.effectiveHotwords` |
| 喂数节奏 | 20 ms / 包 | 与 SDK 一致（时延类指标必须按实时节奏） |

> 警务 SDK 的预置热词池始终非空，所以**出厂默认就是 beam search**，
> 「不配热词」不是一个真实存在的部署形态 —— `--hotwords none` 只作为对照下限。

## 目录

```
storage/   对象存储客户端与取数（COS / 华为 OBS / SenseCore AOSS）
corpus/    测试集生成（SNR 分层加噪、数字串、长语音、角色分离、重叠讲话）
metrics/   指标评测（ASR / 时延功耗 / DER / 片段召回 / 声纹 / 说话人识别 / ITN 重打分）
```

### storage/

三个客户端都是**标准库手写签名**，不装 SDK —— 厂商 SDK（尤其 `obs`）不认
`https_proxy` 环境变量，在本机代理环境下会直接挂住。

| 文件 | 说明 |
|---|---|
| `cosmin.py` | 腾讯云 COS，Signature v5（HMAC-SHA1）。注意：**签名用未编码路径，请求用编码后 URL**，否则对象 GET 必 403 |
| `obsmin.py` | 华为云 OBS V2 签名 |
| `aossmin.py` | SenseCore AOSS（S3 兼容），AWS SigV4 |
| `_ini.py` | 凭证文件定位，见下 |
| `fetch_cos.py` / `fetch_cos_sets.py` | 并行下载 COS 评测集（manifest + 音频），支持续传与大小校验 |
| `fetch_aoss_set.py` | 从 AOSS 按 lhotse manifest 随机抽样下载。manifest 里 `source` 是 `/workspace/data/...`，AOSS 对象键是 `audio-data/...`，脚本按此前缀映射 |

**凭证不入库。** 运行时从 ini 读取（段 `cos` / `obs` / `sensecore`，键
`access_key` / `secret_key`），路径解析顺序：`COS_INI`/`OBS_INI`/`AOSS_INI`
→ `AMPHION_STORAGE_INI` → `~/project/amphionbucket/storage.ini`。

本机需要代理才能出网，且 `no_proxy` 不能为 `*`：

```bash
unset no_proxy NO_PROXY
export https_proxy=http://127.0.0.1:7897 http_proxy=http://127.0.0.1:7897
```

### corpus/

客户表里按 SNR 分 5 档（安静 ≥20 / 轻度 10~20 / 中度 5~10 / 重度 0~5 / 极限 <0），
官方评测集没有这个分层，所以自己加噪生成。

| 文件 | 说明 |
|---|---|
| `make_snr_sets.py` | AISHELL-3 热词语料 → 分档加噪。44.1k→16k 用多相 windowed-sinc 重采样（不依赖 scipy）；噪声两类：`babble`（同语料其它说话人叠加，对应商圈/人群）、`traffic`（合成低频，对应车内/主干道） |
| `mix_official.py` | 把官方评测集按同一口径加噪，**用于取代系数外推**（见下文「教训」） |
| `gen_sets.py` | 数字串（车牌/身份证/手机号/计数）、长语音拼接、角色分离多人交替、重叠讲话、声纹试验对清单 |
| `gen_overlap.py` | 受控重叠度的重叠讲话集，每条产出 `mix.wav` / `target.wav`（oracle 对照）/ `enroll.wav` |
| `gen_noise_variants.py` | 给数字串、长语音两个新集合生成噪声变体 |

口径声明（写报告时必须一并给客户）：

- **SNR 按有效语音段 RMS 计算**，不含静音 —— 否则静音会把 SNR 估计拉高。
- `traffic` 是**合成噪声不是实录**，必须标注。
- **重叠度** = 重叠语音时长 / 机主语音总时长（本测试采用的定义，需与客户确认）。
- **片段召回** = 被识别输出覆盖的参考语音段数 / 参考段总数，「覆盖」= 段内（±collar）
  至少落入一个识别 token 时间戳（本测试采用的定义，需与客户确认）。

### metrics/

| 文件 | 指标 |
|---|---|
| `eval_asr.py` | 统一 ASR 评测器：字准确率/CER、整句全对、术语命中 KWR、车牌整串命中。按 `labels.condition`（工况）/`accent`（口音）/`scenario` 分组。`--sample N` 跨全集等距抽样（保分组覆盖），`--offset` 可分片并行 |
| `eval_digits_long.py` | 数字串与长语音。额外给**整串正确率** —— 11 位手机号错 1 位，CER 只掉 9% 但业务上完全不可用 |
| `eval_snr_arms.py` | SNR 分层四臂对照：`greedy_nohw`（通用下限）/ `pool_nohw`（出厂默认）/ `pool_oracle3`（出厂默认+配热词）/ `oracle3_only`（与已发布 96.12% 同口径）。评分口径沿用 `asr/tools/hotwords/01_eval_aishell3_hotwords.py` |
| `eval_perf.py` | RTF、首个非空 partial 时延、endpoint→final 时延、尾包时延、**CPU 秒/音频秒（功耗代理）**、峰值 RSS |
| `eval_diar.py` | 角色分离 DER。10 ms 栅格、250 ms collar、枚举全排列取最优标号映射，重叠帧单独统计并排除（标准 DER excluding overlap 口径） |
| `eval_segrecall.py` | 片段召回（段数召回 + 时长加权召回），参考段取 AliMeeting 官方说话人时间轴 |
| `eval_speaker_id.py` | 开集说话人识别：测试音频 × 注册音频全交叉，按 near/mid/far 拾音距离分档。`enrolled=False` 的条目只产生负例，用于估计误接受 |
| `eval_voiceprint.py` | 声纹 EER / FAR / FRR（生产 ERes2Net + cosine） |
| `eval_overlap.py` | 重叠场景下机主 ASR 准确率与机主声纹准确率，并跑 `target.wav` 作 oracle 上界，差值即重叠造成的损失 |
| `rescore_itn.py` | 对已有解码结果补 ITN 再打分，见下 |
| `itn_probe.cc` | 从生产源码**原样抽出**的数字折叠逻辑 |
| `report_snr.py` | 按客户 5 档汇总，对齐要求值出达标/不达标 |

常用环境变量：`SP`（工作目录）、`DS_ROOT`/`DS_NAME`（数据集）、`MODELS`（ASR 模型目录）、
`VP_MODEL` / `SEG_MODEL` / `EMB_MODEL`、`THREADS`。

```bash
# 典型一次 A/B
export PYTHONPATH=third_party/.derived/sherpa-onnx/pypkg
python3 metrics/eval_asr.py --dataset <集名> --root $SP/evaldata \
    --models <模型目录> --presets <预置热词文件> \
    --hotwords pool+terms --sample 300 --out $SP/decodeout/<tag>.jsonl
DECODE_DIR=$SP/decodeout ITN_PROBE=$SP/itn_probe python3 metrics/rescore_itn.py
```

## ITN 重打分：必须两侧都归一化

生产 SDK 在 final 文本上做 ITN（中文数字 → 阿拉伯数字），宿主 CLI 默认不开，
于是和「阿拉伯数字参考」对不上 —— 车牌整串命中率会直接测成 0.00%。

`itn_probe.cc` 是 `third_party/.derived/sherpa-onnx/sherpa-onnx/csrc/wetext/processor/
wetext_processor.cc` 第 19–250 行（`CanonicalizeAmbiguousDigitOne` +
`CollapseSpokenDigitRuns`）原样抽出来单独编译的，保证宿主侧变换和端上逐字节一致：

```bash
c++ -std=c++17 -O2 -o $SP/itn_probe metrics/itn_probe.cc
```

它只含数字串折叠这一段，不含 Tag/Verbalize 的 FST 全量 ITN —— 对车牌/身份证/手机号
这类裸数字串是对位的，对日期/单位不生效。

**只归一化假设一侧是错的。** 各数据集参考文本的数字写法不统一（车牌集用阿拉伯数字，
真人集用中文数字），单侧归一化会造成系统性错配：第一次只改假设，车牌命中率修好了，
`longform_real` 的准确率却从 56% 掉到 16%。`rescore_itn.py` 对假设和参考**同时**
归一化，并同时输出 ITN 前/后两列，便于核对。

## 两条方法论教训

1. **CER 会严重低估术语损失。** 四川话候选模型的厂商 CER 只差 0.23pp，看着无关痛痒；
   同一批数据上警务术语 KWR 掉了 5.63pp —— 相差 24 倍。给客户的结论必须带业务口径
   指标（KWR、整串命中、整句全对），不能只给 CER。
2. **合成口音语料不能用来验证方言能力。** 用 TTS 合成的「四川话」测候选模型，只得到
   −0.33pp，几乎看不出差别；换真实 WenetSpeech-Chuan 后是 −2.99/−5.04pp。方言、口音
   这类指标只能用真人语料，合成集最多做冒烟。

另外两条执行上的经验：

- **不要过度分片。** 8 个分片 × 2 线程在 10 核机器上把 load 推到 179，整体更慢；
  抽样（`--sample`）比跑全集划算得多。
- **时延类指标要串行单独测。** 与其它评测并行时 RTF 被污染（0.07 vs 串行 0.05）。

## 相关产出

- `docs/asr/CHUAN_179M_TSX_V1_EVALUATION_20261026.md` —— 四川话候选模型提测对照报告
- `docs/asr/MODEL_DEPLOYMENT_PRECISION_AND_BENCH.md` —— 部署精度（INT8/FP32）、编译打包步骤、历次实测性能
- `docs/asr/AISHELL3_HOTWORDS_EVAL.md` —— 热词评测基线
