# 最终模型目录与清单文件

阶段 A 输出的最终模型目录，是 SDK 在端上加载的实际形态。本文件给出一份固定的目录布局、tokens.txt 与 manifest.json 的内容模板。Android SDK 端会按 manifest.json 下载、校验、装载。

如果你只想 把已经导出量化好的模型 push 到 测试设备 验证 demo（不走 CDN 远程下载），看 `QUICKSTART.md` 第 14 节"换成自己导出的模型"，那一节有现成的 push 脚本与故障排查表，本文是数据格式定义与字段语义的参考。

## 1. 目录布局

每个模型版本是一个 自包含目录，目录名格式：

```
asr-streaming-zipformer-zh-en-<MAJOR>.<MINOR>.<PATCH>/
```

例如 `asr-streaming-zipformer-zh-en-1.0.0/`。版本号语义按 SemVer：

- MAJOR：模型结构变更（chunk size、词表、网络拓扑变了）
- MINOR：训练数据 / 收敛后微调，端上接口不变
- PATCH：仅修复（重新量化、重新校准）

目录内文件清单：

```
asr-streaming-zipformer-zh-en-1.0.0/
├── encoder.int8.onnx          # INT8 量化的 encoder（sherpa-onnx 接受）
├── decoder.onnx               # FP32，体积小不量化
├── joiner.int8.onnx           # INT8 量化的 joiner
├── tokens.txt                 # token id -> str
├── bpe.model                  # 可选；调试用，端上不读
└── manifest.json              # SDK 下载/校验入口
```

注意：

1. 文件名固定，SDK 内部按这套名称查找。如果你的 icefall 导出脚本输出名带 `epoch-99-avg-1` 之类后缀，请在 `01_export_to_onnx.md` 的最后一步重命名为上面的固定名。
2. 不要把 `bpe.model` 删掉，端上虽然不需要它，但留一份对调试和未来更换 tokenizer 有用。

## 2. tokens.txt

icefall 自带导出脚本（`export-onnx-streaming.py`）会一并输出 `tokens.txt`。格式是 每行 `<token>\s<id>`，从 0 开始，前几行长这样：

```
<blk> 0
<sos/eos> 1
<unk> 2
▁ 3
▁A 4
▁B 5
...
你 4096
好 4097
...
```

约束：

- 第一行必须是 `<blk> 0`（CTC blank / RNN-T blank）。
- `<sos/eos>` 与 `<unk>` 是 BPE 的标准特殊符号，sherpa-onnx 会按它们做兜底。
- token 行必须按 id 升序、且 id 连续。
- BPE 子词的下划线前缀是 SentencePiece 的标记字符 `▁`（U+2581，不是 ASCII 下划线 `_`）。
- 中文字符直接出现在 token 列即可，不需要拼音化。

如果你的 tokens.txt 不符合上述任何一条，sherpa-onnx 加载时会失败或给出乱码，请先在阶段 A 验证脚本里发现并修正。

## 3. manifest.json

SDK 从你的服务器拉一份 manifest.json，按里面的 URL 下载文件、按 SHA256 校验、按 size 校对，全部通过后原子替换到 `<filesDir>/asr-models/<modelId>/<version>/`。

文件结构：

```json
{
  "manifest_version": 1,
  "model_id": "asr-streaming-zipformer-zh-en",
  "version": "1.0.0",
  "min_sdk_version": "1.0.0",
  "max_sdk_version": "2.0.0",
  "model_type": "zipformer2",
  "decoding_method": "greedy_search",
  "sample_rate": 16000,
  "feature_dim": 80,
  "files": [
    {
      "name": "encoder.int8.onnx",
      "url": "https://your-cdn.example.com/asr/zh-en/1.0.0/encoder.int8.onnx",
      "size_bytes": 45123456,
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcd"
    },
    {
      "name": "decoder.onnx",
      "url": "https://your-cdn.example.com/asr/zh-en/1.0.0/decoder.onnx",
      "size_bytes": 1024000,
      "sha256": "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
    },
    {
      "name": "joiner.int8.onnx",
      "url": "https://your-cdn.example.com/asr/zh-en/1.0.0/joiner.int8.onnx",
      "size_bytes": 5242880,
      "sha256": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
    },
    {
      "name": "tokens.txt",
      "url": "https://your-cdn.example.com/asr/zh-en/1.0.0/tokens.txt",
      "size_bytes": 65536,
      "sha256": "1111111111111111111111111111111111111111111111111111111111111111"
    }
  ]
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| manifest_version | int | manifest 自身格式的版本号，当前固定 1 |
| model_id | string | 模型业务标识；同一 model_id 的不同 version 可热更 |
| version | string | SemVer 版本号 |
| min_sdk_version / max_sdk_version | string | 兼容的 SDK 版本范围；SDK 启动时会 reject 不兼容的模型 |
| model_type | string | 必须是 sherpa-onnx 支持的字符串：`zipformer2` / `zipformer` / `paraformer` 等。流式 zipformer 用 `zipformer2`。SDK 加载时会读取并传给 native 层 |
| decoding_method | string | greedy_search 或 modified_beam_search。SDK 加载时会读取，作为 AsrConfig 默认值的覆盖（仅当调用方未显式调用 .decodingMethod 时生效） |
| max_active_paths | int (可选) | modified_beam_search 时的 beam size，范围 [1, 32]。SDK 加载时读取，覆盖逻辑同 decoding_method |
| sample_rate | int | 训练时的采样率，端上 SDK 会按此值做重采样校验 |
| feature_dim | int | fbank 特征维度，与 icefall 训练一致；通常 80 |
| files | array | 每个文件的 url + size + sha256；name 必须与本地文件名一致 |

字段优先级（同名字段在多处出现时）：

1. 调用方 Builder 显式调用，例如 `.decodingMethod(MODIFIED_BEAM_SEARCH)` —— 最高
2. modelDir/manifest.json 的对应字段
3. AsrConfig.Builder 的默认值 —— 最低

这意味着算法/运营同学发布新模型时，可以通过修改 manifest.json 切换默认解码策略，而不需要 App 发版。详见 `android/AmphionRuntime/docs/INTEGRATION.md` 第 7 节。

## 4. 怎么生成 manifest.json

阶段 A 的 `03_verify_onnx.sh` 跑通之后，用下面的小脚本一次性生成 manifest.json（把它放在最终模型目录里，作为「待上传」资源的一部分）：

```bash
cd asr-streaming-zipformer-zh-en-1.0.0/

python3 - <<'PY'
import hashlib, json, os, pathlib

MODEL_ID = "asr-streaming-zipformer-zh-en"
VERSION  = "1.0.0"
BASE_URL = "https://your-cdn.example.com/asr/zh-en/1.0.0"

FILES = ["encoder.int8.onnx", "decoder.onnx", "joiner.int8.onnx", "tokens.txt"]

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

manifest = {
    "manifest_version": 1,
    "model_id": MODEL_ID,
    "version": VERSION,
    "min_sdk_version": "1.0.0",
    "max_sdk_version": "2.0.0",
    "model_type": "zipformer2",
    "decoding_method": "greedy_search",
    "sample_rate": 16000,
    "feature_dim": 80,
    "files": [
        {
            "name": name,
            "url": f"{BASE_URL}/{name}",
            "size_bytes": os.path.getsize(name),
            "sha256": sha256(name),
        }
        for name in FILES
    ],
}

pathlib.Path("manifest.json").write_text(
    json.dumps(manifest, indent=2, ensure_ascii=False)
)
print("manifest.json written")
PY
```

把整个目录上传到你的对象存储 / CDN，再把 manifest.json 的访问 URL 配进 SDK 初始化（`AsrConfig.modelManifestUrl`）就完成了模型分发。
