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
| model_type | string | 必须是 sherpa-onnx 支持的字符串：`zipformer2` / `zipformer` / `paraformer` 等。流式 zipformer 用 `zipformer2`。SDK 加载时会读取并传给 native 层。Android SDK 在加载 zipformer transducer 之前会扫 encoder ONNX 的 metadata，校验该字段与模型实际结构一致，不一致直接抛 `MODEL_TYPE_MISMATCH (2005)`，避免 sherpa-onnx 走错路径 native abort |
| decoding_method | string | greedy_search 或 modified_beam_search。SDK 加载时会读取，作为 AsrConfig 默认值的覆盖（仅当调用方未显式调用 .decodingMethod 时生效） |
| max_active_paths | int (可选) | modified_beam_search 时的 beam size，范围 [1, 32]。SDK 加载时读取，覆盖逻辑同 decoding_method |
| lang | string (可选) | 模型语言标识，约定值如 zh-en / yue-en / en / zh。SDK 会原样回填到 ModelDescriptor.lang 与 LocalModel.lang，业务方可据此做多语言路由（例如 sample 中的中英 / 粤英 RadioGroup 切换）。缺失时为 null，不影响加载 |
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

## 6. 可选：WeText ITN（中文小数/单位/日期/货币）fst

WeText ITN 用我们 fork 的 sherpa-onnx 中 vendored 的 [WeTextProcessing](https://github.com/wenet-e2e/WeTextProcessing)（wenet-e2e，Apache-2.0）三段式 runtime：`tagger.fst → C++ token reorder → verbalizer.fst`，覆盖小数、单位、日期、时间、货币、百分比、电话号码、身份证号等常见中文 ITN 场景。两份 fst 与模型权重解耦，按"规则数据"对待：

| 项 | 说明 |
| --- | --- |
| 与模型解耦 | fst 作用在 ASR 解码后的字符串上，对模型权重 / tokens.txt 无依赖，可跨多套模型共用 |
| 不属于 modelDir | 不放进 `asr-streaming-zipformer-zh-en-1.0.0/` 内、不进 manifest.json 的 files 数组 |
| 文件清单 | `zh_itn_tagger.fst` + `zh_itn_verbalizer.fst`（中文 ITN，总和约 2-4 MB）；WeTextProcessing 也支持 zh_tn / en_tn / ja_tn 等更多对子 |
| 来源 | 推荐做法：业务方在 CI / 内部机器上 `pip install WeTextProcessing==<pinned>` 后跑 `tools/asr/00_push_weitn_fsts.sh` 触发 pynini build，把 fst 缓存到 `tools/asr/weitn-fsts/`（git 忽略）；或直接挂到自家 CDN（脚本支持 WEITN_TAGGER_URL / WEITN_VERBALIZER_URL 环境变量直接拉预编译产物） |
| 在 sample 内的位置 | external push 到 `/sdcard/Android/data/<pkg>/files/asr-weitn-import/{zh_itn_tagger.fst,zh_itn_verbalizer.fst}`；sample 启动时 `WeitnAssetInstaller` 搬到 `<filesDir>/asr-weitn/` |
| 为何不走 assets | 即使两份 fst 总和也 2-4 MB；其次 fst 与模型权重生命周期独立，pull 模式比 assets 更灵活，便于线上热更 fst 修 bug |
| 在 SDK API 中传入 | `WeitnConfig.Builder(taggerFst, verbalizerFst).build()` → `WeitnEngine(config)`，详见 INTEGRATION.md §12.4 |

业务方自己分发 WeText fst 时同样推荐独立走 CDN：

- 两份 fst 加起来 ~2-4 MB，与 ASR 模型完全独立，可跨多个 ASR 模型共享
- 推荐放在 `<your-cdn>/asr-weitn/<v>/{zh_itn_tagger.fst,zh_itn_verbalizer.fst}`，旁边带 sha256 方便客户端校验
- 客户端拿到 fst 路径后 `WeitnConfig.Builder(taggerFile, verbalizerFile).build()` 即可，无需修改 AsrConfig
