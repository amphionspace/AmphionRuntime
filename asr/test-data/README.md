# Versioned test data

Test corpora that are too large for Git live in Huawei Cloud OBS. The manifest
pins every object by byte size and SHA-256 so a test run on another machine uses
the same input.

The default local root is `~/.cache/amphion-runtime/test-data/v1`. Override it
with `AMPHION_TEST_DATA_DIR`.

## 按测试目的选择

权威索引为 [manifest.json](manifest.json)，下表资产均位于华为云 OBS 桶
`cuhk-anfeiweng-benchmark`。`bundles` 是工具可以自动恢复的语料；`catalog` 是需要手动下载的
外部归档索引，两类都会出现在 `test_data.py list` 和 `tools/assets/sync.py list` 中。
`catalog-only` 不参与 `fetch all`、`verify all` 或 `publish`。

| 逻辑名称 | 主要用途 | 获取方式与限制 |
| --- | --- | --- |
| `aishell3-500` | 生命周期、热词回归、说话人状态契约 | 自动恢复；不作为带身份真值的声纹精度集 |
| `dingqiao-meeting-20260918` | 五段客户会议及其标注、句子体验验收证据 | 自动恢复；MOSS 辅助标注不等于人工真值 |
| `police-asr-eval-20260914` | 警务术语、车牌、派出所名称及定向失败样例的识别精度评测 | 手动下载；18 个数据集，以合成音频为主，含客户音频 |
| `police-terminology-legacy-v1` | 单独存放的旧警务术语包 | 手动下载；尚未检查内容，不应当作上面的完整警务评测包 |

`aishell3-500` 使用中性名称；旧名称 `aishell3-hotwords-500` 仍作为别名，两个名称同时指定
只选中一次。OBS 对象键仍为
`amphion-runtime/test-data/v1/amphion-test-data-aishell3-hotwords-500-v1.zip`，本地目录仍为
`~/.cache/amphion-runtime/test-data/v1/aishell3_test_hotwords_500`，包内文件及 SHA-256 均不变。
这保留了现有命令、缓存和历史报告的可追溯性。`dataset_version=v1` 表示缓存命名空间，
不是各数据集的采集日期或内容版本。

```bash
python3 asr/tools/test_data.py fetch aishell3-500
python3 tools/assets/sync.py verify aishell3-500
```

生命周期测试用这些音频驱动 SDK 公共调用和回调断言；警务评测用音频及文本标注计算精度。
Linux 可以用于警务算法迭代，正式交付的平台生命周期和性能门禁仍按对应平台执行。
声纹回退的固定双文件样例见 `asr/test-fixtures/voiceprint-fallback/`；纯静音、噪声由测试生成，
不属于上述对象存储包。

## 警务评测归档的位置

完整警务包逻辑名称为 `police-asr-eval-20260914`，物理对象键保留历史命名：

| 内容 | OBS 对象键 |
| --- | --- |
| 完整包 | `asr_testsets/2026-09-14/asr_testsets_handoff_20260914.tar.zst` |
| 整包校验和 | `asr_testsets/2026-09-14/asr_testsets_handoff_20260914.tar.zst.sha256` |
| 来源、范围及目录说明 | `asr_testsets/2026-09-14/summary/README.md` |
| 分数据集统计 | `asr_testsets/2026-09-14/summary/DATASET_SUMMARY.tsv` |

远端说明记录 18 个数据集、14,281 对音频和文本，约 21.76 小时，另有 1 条无可靠标注的音频。
根目录的 `manifest.jsonl` / `manifest.tsv` 和 `datasets/<dataset_id>/pairs.tsv` 提供输入映射；
评测时记录具体子集，不能只把整包名称写成“警务测试数据”。本次仅核对远端大小、已发布校验和
和说明文件，未下载整包，也未验证其中的标注质量或模型精度。

可用已配置的 AmphionBucket 下载（先用 `ab remotes` 确认下面别名对应上述桶）：

```bash
ab remotes
mkdir -p "$HOME/.cache/amphion-runtime/test-data/external/police-asr-eval-20260914"
ab pull obs-cuhk-anfeiweng-benchmark:asr_testsets/2026-09-14/asr_testsets_handoff_20260914.tar.zst \
  "$HOME/.cache/amphion-runtime/test-data/external/police-asr-eval-20260914/asr_testsets_handoff_20260914.tar.zst"
```

下载后、解压前按清单核对大小 `2538939557` 字节及 SHA-256
`a63e272bcab9a0b4d63282080bf3c8eb961bf00d62de81b2cabc6558c8f21c15`；在 Linux 可用
`sha256sum`，macOS 可用 `shasum -a 256`。自动恢复工具目前不接管这个 `tar.zst` 归档。

另一个旧包位于 `datasets/police-terminology-testset-v1.tar.gz`，大小 `20176931` 字节；
其对象键和校验和单独登记在 `catalog.police-terminology-legacy-v1`。仅凭名称不能判断它覆盖
哪些子集，使用前须检查内容及授权，不与完整警务包混用。

## Configure OBS credentials

Export these variables without committing their values:

```bash
export OBS_AccesskeyID=...
export OBS_SecretAccesskey=...
export OBS_Endpoint=https://obs.cn-north-9.myhuaweicloud.com
```

Install Huawei Cloud's OBS Python SDK, then fetch and verify the data:

```bash
python3 -m pip install esdk-obs-python
python3 asr/tools/test_data.py list
python3 asr/tools/test_data.py fetch all
python3 asr/tools/test_data.py verify all
```

`fetch` downloads to a temporary file, checks SHA-256 before extraction, and
replaces only the selected versioned bundle. Interrupted multipart downloads
can resume from their checkpoint files.

## Publishing policy

- Never put credentials, SDK licenses, signing material, device logs, or
  voiceprint embeddings in a test-data bundle. Customer recordings and their
  annotation evidence require explicit user authorization and internal-only OBS
  access; they must not be committed to Git or redistributed publicly.
- Each bundle must record its origin and redistribution status in the manifest.
- `publish` refuses an object that already exists with a different size. A new
  payload requires a new dataset version or object key.
- AudioSet audio downloaded from YouTube is not publishable. Google's official
  AudioSet release contains labels and derived features, not raw audio.
- The withdrawn aidatatang corpus and derived subsets require an explicit data
  owner approval before they may be shared beyond the existing authorized team.

## Customer meeting acceptance, 2026-09-18

`dingqiao-meeting-20260918` contains the five explicitly authorized offline
customer recordings (1,010.64 seconds), original MOSS auxiliary annotations,
human adjudication history and final decisions, and source-bound comparison
evidence. The cloud-recognition recording is excluded. This bundle is internal
evaluation data, not an openly licensed corpus or fully labeled DER benchmark.

```bash
python3 asr/tools/test_data.py fetch dingqiao-meeting-20260918
python3 tools/assets/sync.py verify dingqiao-meeting-20260918
```

Read `SOURCE.md`, `samples.json` and `annotations/human-final.json` after fetching.
The manifest pins the archive and each file. Original WAV bytes are preserved;
MOSS labels are auxiliary and historical listening decisions can be superseded
by later user adjudication. Do not force four speakers in every recording.

The accepted scope is customer-audio improvement with intact sentence output;
minor measured performance cost is accepted. See the
[scoped wrap-up](../../delivery/harmony-dingqiao/docs/CUSTOMER_MEETING_SENTENCE_WRAPUP_20260918.md)
for benefits, remaining errors and evidence limits.
