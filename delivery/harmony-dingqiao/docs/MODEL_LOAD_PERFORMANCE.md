# HarmonyOS ASR 模型加载性能

本文固定鼎桥 `zhen` 模型的构建、加载和验收边界。性能结论只适用于 comparison identity
完全一致的报告；设备、系统版本、模型源文件、线程数、预热样本数或标点配置任一变化时，
必须建立新基线，不能直接套用旧报告门槛。

## 当前交付配置

| 项目 | 值 |
| --- | --- |
| API | `SpeechRecognizeSdk.createEngineAsync` |
| ASR 模型 | `asr/tools/demo-model/zhen` |
| encoder | `encoder.int8.onnx` → `encoder.int8.ort` |
| decoder | `decoder.onnx` → `decoder.ort` |
| joiner | `joiner.int8.onnx` → `joiner.int8.ort` |
| punctuation | `model.int8.onnx` → `model.int8.ort` |
| ORT 转换 | ONNX Runtime 1.16.3、CPU EP、ARM、Fixed、全部图优化 |
| ORT worker | 4 |
| eager warmup | 0 samples |
| 进程内复用 | 相同语言和 recognizer 配置 single-flight + pool |

模型在构建期转换为 ORT 格式；运行时从 Harmony rawfile 映射模型字节，关闭重复图优化，
并行创建 recognizer 与 punctuation。encoder、decoder 和 joiner 的 Session 初始化采用多 lane，
但整体关键路径仍是约 155 MiB encoder 的 Session 创建和权重预打包。

`zhen` 使用 INT8 decoder。打包脚本仅在 `decoder.int8.onnx` 缺失时兼容回退到
`decoder.onnx`，正式交付不应依赖该回退。

`demo-model/zhen` 和 `yueen` 是不入 Git 的受控模型输入，干净检出后必须从内部制品库恢复；
公开 demo 下载脚本不能替代本次交付模型。当前 `zhen` 源文件身份如下，恢复后应由
`08_pack_harmony_assets.sh` 生成的 manifest v2 再次校验：

| 源文件 | SHA-256 |
| --- | --- |
| `encoder.int8.onnx` | `cbb44392d7c7ecbf16495dec7517c724b4717667b2bd7c591efd1282029dcc1a` |
| `decoder.int8.onnx` | `2b2eac6b42a78d7090d8eb5ea258a5e380ae3935acfb4b9737d8623109928fe5` |
| `joiner.int8.onnx` | `31ac778b0b43ba89c424ddfc25b4192cac571f39a950867dc1f571ea5257023e` |
| `tokens.txt` | `29a20d469f044011706d9720ff31770e5dcd6c30714943282e9563a55c6918f5` |
| `bbpe.vocab` | `aa7a1b34d6a10e666f32dd7bc34599f16bd7602a3ed67602873c603dae978514` |
| punctuation `model.int8.onnx` | `65a3fb9f5ad7bfb96bf69e0dc4481df97f6ee60513c1d94ce981ba6effd524b1` |

## 2026-07-12 真机结果

设备 `6CT9K26130017501`、相同系统构建和模型源文件下：

| 阶段 | 冷加载 p50 | 冷加载 p95 | pool hit p50/p95 |
| --- | ---: | ---: | ---: |
| 优化前 ONNX 串行路径 | 3884.5 ms | 4010.55 ms | 不适用 |
| ORT、mmap、异步并行与 pool | 864 ms | 893.4 ms | 0/1 ms |
| 4 worker | 859 ms | 899 ms | 0/1 ms |
| 跳过冗余 eager warmup | **774.5 ms** | **810.25 ms** | 0/1 ms |

最终相对初始 p50 降低约 80.1%。800 ms 静音预热只触发一次 decode，使 engine ready
增加约 93 ms，但首次真实音频只减少约 10 ms，因此当前 ORT 模型将 eager warmup 设为 0。

48 轮真实 WAV burst 回归：48/48 完成、空 final 4.1667%、首轮 120 ms、总耗时
21858 ms、峰值 RSS 571.863 MiB。该短跑的 RSS slope 只作观察，不作为泄漏结论。

### 2026-07-12 第二台设备单变量复核（9020）

在另一台设备 `3ZF0225520048151`（`PLR-AL00`、`OpenHarmony-6.1.0.115`，Kirin 9020，比
6CT9K 的 8020 新一代）上做**单变量对照**：只把模型格式在 ORT 与 ONNX 之间切换
（`AssetRegistry` 指向 `.ort` 或 `.onnx`），异步并行 lane、4 worker、eager warmup=0、
native `.so`、bench harness 与源模型全部保持一致。ORT 组 decoder 源 SHA `2b2eac6b…`
（真 INT8 `decoder.int8.onnx`），ONNX 组用 `decoder.onnx`（FP32）。

**以单次冷启（凉机、用户实际首启场景）为准**：

| 模型格式 | 冷加载（凉机单次） | 说明 |
| --- | ---: | --- |
| ORT（优化） | **约 730 ms**（p50 740.5、p95 774.1，20 轮 648–776 无漂移） | 见下方耗时归因 |
| ONNX（未优化） | **约 2.6 s**（20 轮 min 2740、10 轮 min 2605） | 与本机 2026-07-11 逐算子 profiling 的 2573 ms 一致 |

单次冷启提速约 **3.6×**。

**ORT 启动耗时归因**（SDK `kind=LOAD` 埋点，3 次冷启）：`recognizerReadyMs` 690–709 ms、
`punctuationReadyMs` 176–201 ms、`assetLayoutMs` 0、`engineReadyMs` 691–709 ms。即
`engineReadyMs ≈ recognizerReadyMs`——**关键路径几乎全部是 recognizer 的 ORT session 创建**
（约 154 MiB encoder 的 `.ort` 字节载入 + INT8 权重 prepack；图优化已离线做掉，运行时不再花）。
punctuation（约 190 ms）走并行 lane、被 recognizer 完全隐藏；asset layout 无拷贝为 0。
下一步只能动 encoder 权重的零拷贝 mmap / prepack 缓存。

> 单次观察（未复验，不作结论）：某次 ONNX 20 轮连测后段从约 2.8 s 升到约 3.1–3.2 s
> （该次 p50 3141 ms），疑似连续重算力图优化使 SoC 发热降频；但同日 10 轮与前一日 12 轮
> 均稳定在约 2.6–2.7 s 未出现，故仅记为观察。ORT 组 20 轮无此现象。

绝对值随设备/系统/热状态而变，只在 comparison identity 一致时可比；此 9020 单次冷启结论
与 6CT9K 的 80.1% 同向印证（6CT9K 的 3884.5 ms 是更慢机型上的全串行优化前路径）。

## 复现加载基准

先构建并安装当前 signed HAP，再从仓库根目录执行：

```bash
python3 delivery/harmony-dingqiao/delivery/run_model_load_bench.py \
  --device <HDC_TARGET> \
  --warmup-runs 2 \
  --iterations 10 \
  --output delivery/harmony-dingqiao/build/model-load-bench/zhen-current.json
```

已确认 HAP 是当前构建产物时可加 `--skip-build`。工具仍会检查并安装该 HAP，不会绕过
模型 manifest、native hash、签名和设备构建身份检查。

只有 comparison identity 完全一致时才能启用自动门槛：

```bash
python3 delivery/harmony-dingqiao/delivery/run_model_load_bench.py \
  --device <HDC_TARGET> \
  --baseline path/to/comparable-baseline.json \
  --output delivery/harmony-dingqiao/build/model-load-bench/zhen-candidate.json
```

默认门槛要求 p50 至少改善 20%，且 p95 回退不超过 3%。报告和设备压力测试 artifact
包含设备信息，不进入客户交付包；交付包通过 `docs/checksum.txt` 固定实际 HAR/HAP 与文档。

## 已验证但未采用的方案

- `session.disable_prepacking=1`：加载进一步缩短，但 48 轮真实音频处理慢约 24%。
- 继续拆分 decoder/joiner：两者 Session 创建仅约 4–11 ms，已被 encoder 关键路径覆盖。
- `session.use_device_allocator_for_initializers=1`：真机无显著收益。
- 隐式自动预加载：`setLicense` 只验权并缓存；语言、热词配置可能尚未确定，不应在该阶段自动加载模型。重新设置有效授权还会使旧 Runtime / 模型失效。

业务如需接近 0 ms 的点击响应，应在 license 激活成功后先调用 `prepareRuntime`，收到 `onReady`
且最终配置确定后显式调用 `createEngineAsync`，并长期持有返回的 engine；同配置后续 pool hit 为 0–1 ms。
