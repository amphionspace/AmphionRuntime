# 鸿蒙双包出包：基线包与「四川话 / 无警务后处理」包

两个部门各用一个包：

| | 包 A 基线 | 包 B 四川话 / 无警务后处理 |
|---|---|---|
| ASR 模型 | `amphion-zh-en-police-179m-1.4.0` | `chuan-179m-tsx-v1-1.0.0` |
| 警务后处理 | 开（术语→车牌→派出所→润色→人名 LAC） | **不随包发行** |
| 警务热词偏置 | 371 条预置 @1.0 + 用户热词 @3.0 | **保留，与包 A 一致** |
| HAP 体积 | 412.0 MB | 375.9 MB |
| 代码差异 | 无 | 无 —— 两个包是同一份代码，只差资产 |

最后一行是这套做法的要点：**包 B 不是一个代码分支，是一份资产裁剪**。
引擎在运行时读警务资产 manifest 的 `variant` 字段决定后处理是否可用，
所以同一份二进制逻辑既能当基线包也能当裁剪包，不存在「两个包的代码会漂移」的问题。

## 怎么出包

两个包共享一个前提：本机 `node-addon-api` 要走预置本地源，否则 CMake 在
`FetchContent` 阶段报 `GIT_VERSION_STRING=''`（交叉编译工具链把 `find_program`
限制在 find-root 里，探不到系统 git）。

```bash
export NODE_ADDON_API_PREPATCHED=$PWD/.cache/speaker-screen-repro-acf477c2/node-addon-api
SIGN=$PWD/.secure/harmony-signing-signing-project.json
```

### 包 A 基线

```bash
# 1) 资产回到生产模型（若上次出的是包 B）
bash asr/tools/08_pack_harmony_assets.sh --zh-en-only

# 2) 构建 + 签名 + 装机 + 冒烟
bash delivery/harmony-dingqiao/delivery/build_install_smoke.sh \
  --signing-config "$SIGN" --device <SERIAL>
```

### 包 B 四川话 / 无警务后处理

```bash
# 1) 候选模型转 ORT 并重算资产清单
ZH_EN_DIR=$PWD/asr/tools/demo-model/amphion-chuan-179m-tsx-v1-1.0.0-chunk32-lc256-edge-transducer \
  bash asr/tools/08_pack_harmony_assets.sh --zh-en-only

# 2) 构建：裁掉后处理资产 + 换固定 MD5 策略
DINGQIAO_POLICE_POSTPROCESS=off \
DINGQIAO_MODEL_MD5_POLICY=$PWD/delivery/harmony-dingqiao/delivery/dingqiao_chuan_model_md5.json \
  bash delivery/harmony-dingqiao/delivery/build_install_smoke.sh \
    --signing-config "$SIGN" --device <SERIAL>
```

两个包的资产目录是同一个（`asr/harmony/sdk/src/main/resources/rawfile/amphion-models`），
所以**不能并行出包**，必须先出完一个再换模型出另一个。

## 实现要点

### 1. 资产裁剪：`trim_police_postprocessing.py`

在隔离构建工作区里跑（不动仓库本体），删掉术语/车牌/派出所的 FST 与词典、
LAC 人名模型，只留 `hotwords.json`，并在 manifest 打 `variant=hotwords-only`。
共 27 个文件 / 36.1 MB。

**必须保留 `hotwords.json`** —— 它是 `PoliceEngineConfig.effectiveHotwords` 的唯一
数据源，而包 B 保留解码期热词偏置。这是裁剪里唯一不能一刀切的地方。

### 2. `hvigorfile.ts` 必须尊重裁剪标记

`asr/harmony/sdk-police/hvigorfile.ts` 在每次构建时把 30 MB 的 LAC 人名模型从
`shared/models/` 拷进 rawfile。第一版包 B 因此只省了 5.7 MB —— 裁剪删掉的文件
被构建期又拷回来了。现在它先查 manifest 的 `variant`，是裁剪态就跳过并清掉残留。

出包后务必核一遍 HAP 里到底有什么，别只看体积：

```bash
python3 - <<'PY'
import json, zipfile
z = zipfile.ZipFile("<HAP>")
for n in sorted(x for x in z.namelist() if "amphion-police/" in x):
    print(z.getinfo(n).file_size, n)
print(json.loads(z.read("resources/rawfile/amphion-police/manifest.json")).get("variant"))
PY
```

### 3. 运行时判定：`PoliceAssets.postprocessingAvailable`

读资产 manifest 的 `variant`。读不到或读不懂时返回 `true`，既有交付包的行为
不因这段新增代码改变。

- `SpeechRecognizeSdk`：不可用时不构造后处理流水线（资产不会被读到），
  调用方传 `enablePoliceEnhancement=true` 也不生效
- demo `Index.ets`：不可用时隐藏「警务增强」开关，显示「本包未集成警务后处理」

### 4. 模型身份策略可替换

`verify_dingqiao_model_md5.py` 原先把源包名写死在 `…-1.4.0.tar.gz` 上。现在改成
形状校验，仍强制 `enc-int8-dec-fp32-join-fp32-chunk32-lc256` 这个架构与精度不变量，
版本号由策略文件自己声明。`DINGQIAO_MODEL_MD5_POLICY` 切换策略文件。

候选模型的 `tokens.txt`（md5 `ff6d4c46…`）与 `bbpe.vocab`（`09638658…`）与生产模型
**逐字节一致**，所以换模型不影响热词与 bbpe 建模单元 —— 这是这次换模型风险低的根本原因。

## 端侧基线（真机实测）

设备 `7GK0226326015655`，语料 `aishell3_test_hotwords_500` 取 60 条，20 ms 实时节奏喂入，
`--asr-num-threads 4 --asr-qos user-initiated`。两个包跑同一批 60 条。

| 指标 | 包 A 基线 | 包 B 四川话/无后处理 |
|---|---|---|
| 会话完成 | 60/60 | 60/60 |
| 错误数 | 0 | 0 |
| 空 final 率 | 0.000 | 0.000 |
| 字准确率 | 94.25% | 93.34% |
| 整句全对 | 68.33% | 65.00% |
| 首结果时延 p50 | 1685 ms | 1695 ms |
| 首结果时延 p95 | 1740 ms | 1736 ms |
| CPU 单核等效 均值 / p95（功耗代理） | 128.2% / 167.8% | 128.7% / 167.3% |
| 峰值 RSS | 456.0 MB | 452.5 MB |
| RSS 增长 | +12.8 MB | +0.7 MB |
| 内存门禁 | PASS | PASS |

读法：

- **时延与功耗两个包没有差别**（p50 相差 10 ms、CPU 相差 0.5pp，都在噪声内）。
  换模型与裁剪后处理都不影响这两项。
- **精度差 −0.91pp 字准 / −3.33pp 整句**，方向与宿主侧一致：候选模型在普通话上
  略逊，增益在四川话上（宿主侧真实 WenetSpeech-Chuan 实测 −2.99/−5.04pp 的反向）。
  这批 60 条是地名/POI 密集的热词语料且未配对应热词，绝对值不代表通用场景。
- **裁掉 36 MB 资产不降峰值 RSS**（456.0 vs 452.5 MB）。省的是 HAP 体积，
  LAC 人名模型本来就是按需加载，不进常驻。别把体积收益当内存收益讲。

前置缺陷：这两个包的端侧会话原先全部失败，根因与修法见
`docs/asr/HARMONY_VAD_TYPEDARRAY_DEFECT.md`。**两个包都必须带该修复重出**，
修复前构建的产物不可交付。

## 还没做的事

- **设备 UDID 白名单**：profile 是 debug 类型 + `device-id-type: udid`，当前只白名单了
  4 台开发机。两个部门的设备装不上，需要在 AGC 把它们的 UDID 加进调试设备列表后重下 profile。
- **bundleName**：两个包都是 `com.amphion.asr.harmony.demo`，**不能装在同一台设备上**
  （互相覆盖）。要同机对比需另申请 bundleName，或改用现成的
  `com.amphion.asr.harmony.repro`。
- **按 SNR 分档的真机精度**：当前 60 条是安静工况。分档需要把加噪语料推到设备上跑，宿主侧已有分档数据。
