# tools/asr/demo-model/

这个目录的所有内容（包括 manifest.json / tokens.txt / export_meta.json 等元数据）都不入库。

## 为什么

第一性原理：

1. 元数据必须与权重严格配对（sha256 一致）。如果元数据走 git、权重走 CDN，任一侧 bump 都会让另一侧立刻失配 —— 这种"git 已更新但权重还没刷"的中间态没有任何降级方案，调用方只能崩。
2. `manifest.files[].url` 在产线里通常是 `file:///` 私人路径或内部 CDN 域名，留在 git 历史里会泄露内部目录结构与服务发现信息。
3. 模型每次重训都会 bump 全量 sha256，元数据持续写入 git 历史会让 clone / blame 都越来越慢，且这部分历史的"可读价值"为零。

## 怎么填充

### 方式一：拉官方 sherpa-onnx 中英 demo 模型

```bash
bash tools/asr/00_fetch_demo_model.sh
```

注意当前 fetch 脚本默认产出路径是 `demo-model/sherpa-onnx-streaming-zh-en-demo/1.0.0/`，与 `decode_offline.py` / `decode_streaming.py` 默认 `--model-dir tools/asr/demo-model/zipformer_L_zh_en` 不一致 —— 跑脚本时显式覆盖 `--model-dir`，或先把 fetch 脚本里的 `MODEL_ID` 改成 `zipformer_L_zh_en`。

### 方式二：用自己训练的 ONNX 模型

把训练流水线导出的 `encoder.onnx` / `decoder.onnx` / `joiner.onnx` / `tokens.txt` 放到 `demo-model/<model_id>/` 下，然后跑：

```bash
bash tools/asr/00_push_my_model.sh
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

如果你换了 model_id，需要同步改 `android/AmphionRuntime/sample/src/main/java/com/amphion/asr/sample/MainActivity.kt` 里的 lang 路由逻辑。
