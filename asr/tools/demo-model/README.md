# asr/tools/demo-model/

这个目录的所有内容（包括 manifest.json / tokens.txt / export_meta.json 等元数据）都不入库。

## 当前中英模型：Police 1.4.0（仅 encoder INT8）

Android/Harmony 打包默认使用
`amphion-zh-en-police-179m-1.4.0-chunk32-lc256-transducer-encoder-int8/`。
源包位置和身份固定在
[模型策略](../../../delivery/harmony-dingqiao/delivery/dingqiao_zh_en_model_md5.json)。
这个上游 tar.gz 使用以下命令手动恢复；`tools/assets/sync.py fetch all` 不包含它。

```bash
ab remotes  # 确认 obs-cuhk-anfeiweng-benchmark 对应 cuhk-anfeiweng-benchmark
mkdir -p .cache/asr-police-v1.4
ab pull 'obs-cuhk-anfeiweng-benchmark:icefall/amphion/zh_en/checkpoints/candidates/police-179m-v1.4/onnx/chunk32-lc256/1.4.0/dist/transducer-fp32-chunk32-lc256-1.4.0.tar.gz' \
  .cache/asr-police-v1.4/transducer-fp32-chunk32-lc256-1.4.0.tar.gz
printf '%s  %s\n' \
  58e6620604f528df997a13c71c12550a586f644e15228397728c977310a4991f \
  .cache/asr-police-v1.4/transducer-fp32-chunk32-lc256-1.4.0.tar.gz | shasum -a 256 -c -
# 仅在校验成功后解压到新的版本目录。
tar -xzf .cache/asr-police-v1.4/transducer-fp32-chunk32-lc256-1.4.0.tar.gz -C asr/tools/demo-model
# 使用 requirements-harmony-ort.txt 对应的 Python 环境，仅量化 encoder。
.venv-harmony-ort-1.16.3/bin/python asr/tools/prepare_police_1_4_int8.py
bash asr/tools/08_pack_harmony_assets.sh --zh-en-only
bash asr/tools/08_pack_sdk_assets.sh --zh-en-only
```

上游 FP32 源包及其 SHA-256 不变。使用固定 ONNX Runtime 1.16.3 / ONNX 1.15.0 / NumPy
1.26.4，对 encoder 的常量权重 MatMul 做逐张量动态 QInt8 量化；decoder、joiner 和
词表逐字节保留源包内容。脚本验证源 encoder 及派生 encoder 的 SHA-256，并写入独立
`transducer-encoder-int8` 目录；不会覆盖 FP32 源模型。两端再分别转换为匹配各自 ORT 版本的产物。

运行期资源名 `encoder.int8.ort` / `joiner.int8.ort`（Android 加 `.mp3`）沿用历史名称。
encoder 为 INT8，joiner 仍为 FP32，实际身份以打包 manifest 的 `source_name`、源哈希及
[模型策略](../../../delivery/harmony-dingqiao/delivery/dingqiao_zh_en_model_md5.json)为准。

FP32 encoder 单文件最高级 ZIP 压缩仍达 545.8 MiB，无法满足现有 SDK-only ZIP 的
320 MiB 门禁。encoder INT8 候选约 153.7 MiB；门禁不变，仍须以最终 ZIP 验证。
精度对照和 Android/Harmony 真机验收均通过后才允许交付，转换或加载成功不能替代验收。

## 为什么

第一性原理：

1. 元数据必须与权重严格配对（sha256 一致）。如果元数据走 git、权重走 CDN，任一侧 bump 都会让另一侧立刻失配 —— 这种"git 已更新但权重还没刷"的中间态没有任何降级方案，调用方只能崩。
2. `manifest.files[].url` 在产线里通常是 `file:///` 私人路径或内部 CDN 域名，留在 git 历史里会泄露内部目录结构与服务发现信息。
3. 模型每次重训都会 bump 全量 sha256，元数据持续写入 git 历史会让 clone / blame 都越来越慢，且这部分历史的"可读价值"为零。

## 怎么填充

### 方式一：拉官方 sherpa-onnx 中英 demo 模型

```bash
bash asr/tools/00_fetch_demo_model.sh           # 仅 prepare
bash asr/tools/00_fetch_demo_model.sh push      # prepare + push 到设备
```

产物落到 `demo-model/zipformer_L_zh_en/`，manifest.json 带 `"lang": "zh-en"`，与 `decode_offline.py` / `decode_streaming.py` 默认 `--model-dir` 以及 sample app MainActivity 的 lang 路由一致。

粤英 (yue-en) 上游没有公开 demo，需自有训练后用方式二填到 `demo-model/zipformer_L_yue_en/`。

### 方式二：用自己训练的 ONNX 模型

把训练流水线导出的 `encoder.onnx` / `decoder.onnx` / `joiner.onnx` / `tokens.txt` 放到 `demo-model/<model_id>/` 下，然后跑：

```bash
bash asr/tools/00_push_my_model.sh
```

该脚本会自动构造 `manifest.json`（计算 sha256、填 `model_type` / `lang` / `sample_rate` 等）并按 ModelImporter 约定的路径 push 到设备。

### 方式三：从内部 CDN 拉

工程师内部使用，参见 `docs/eval/WORKFLOW.md`「工程师手册」section。

## 目录命名约定

`demo-model/<model_id>/` 中的 `<model_id>` 字面进 `manifest.json` 的 `model_id` 字段；与 SDK 的 `ModelManager.listLocal()` 强耦合。下游代码默认认这两个名字（与 `manifest.lang` 字段一一对应）：

| 目录 | manifest.lang |
| --- | --- |
| zipformer_L_zh_en | zh-en |
| zipformer_L_yue_en | yue-en |

如果你换了 model_id，需要同步改 `asr/android/samples/public-demo/src/main/java/com/amphion/asr/sample/MainActivity.kt` 里的 lang 路由逻辑。
