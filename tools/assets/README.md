# Git 外资产同步

模型、测试语料等不适合进入 Git 的协作输入统一存放在对象存储。清单固定对象路径、大小、
整包 SHA-256 和逐文件 SHA-256；干净检出可以恢复出与发布构建机相同的输入。

2026-11-16 起默认存储是腾讯云 COS（`amphion-assets-1373259071`，`ap-guangzhou`，前缀
`amphion-runtime/assets/v1`）。华为云 OBS 桶 `cuhk-anfeiweng-benchmark` 以具名存储 `obs-legacy`
只读保留。2026-11-22 起测试语料清单（`asr/test-data/manifest.json`）与 catalog 归档也已迁到 COS；
2026-11-24 起受限 bundle 改为客户端 AES-256-GCM 加密后放 COS（见下文），清单不再引用 OBS 上的对象。

## 首次配置

凭据只通过本机环境变量提供，禁止写入仓库。团队成员可从 `amphionbucket` 仓库的共享配置取值：

```bash
export COS_SecretId=...
export COS_SecretKey=...
python3 -m pip install cos-python-sdk-v5
# 只在需要受限 bundle（team-secure-state-v6、harmony-demo-license-v2）时才需要团队资产密钥：
export AMPHION_ASSET_KEY_B64=...   # 32 字节 AES-256 密钥的 base64，来自 amphionkeys 仓库的 amphion-assets.env
python3 -m pip install cryptography  # 仓库 .venv 已带；受限 bundle 的命令用 .venv/bin/python 运行
```

团队密钥统一放在私有仓库 `amphionkeys`（git.amphiondev.com/amphion/amphionkeys，一个服务一个 `.env`），
有权限的人 clone 后用它的 `load.sh` 注入，例如：

```bash
~/amphionkeys/load.sh tencent-cos amphion-assets -- .venv/bin/python tools/assets/sync.py fetch team-secure-state-v6
```

`tencent-cos.env` 里的变量名是 `COS_SecretID`（大写 ID），本工具读的是 `COS_SecretId`，用 `load.sh` 时先
`export COS_SecretId="$COS_SecretID"` 或在 shell 里做一次映射。

## 跨机恢复

```bash
python3 tools/assets/sync.py list
python3 tools/assets/sync.py remote-verify all
python3 tools/assets/sync.py fetch all
python3 tools/assets/sync.py verify all
```

`list` 显示逻辑名称、状态、恢复范围、大小、许可、用途和旧名称别名。
`current` 表示当前受维护的输入，`historical` 表示仅供追溯的旧快照。
`all` 在下载、校验和上传命令中只选择 `current`；需要追溯时可显式指定历史名称。
状态不代表模型在所有场景都通过精度验收，仍须查看各资产的用途和限制。
`catalog-only` 是已登记位置、需要手动下载的语料，不参与 `all`；详见
[测试语料目录](../../asr/test-data/README.md)。

仓库模型恢复到清单声明的 Git 忽略目录。测试语料默认恢复到
`~/.cache/amphion-runtime/test-data/v1`；可用 `AMPHION_TEST_DATA_DIR` 指定共享磁盘。
中断的分片下载保存在 `~/.cache/amphion-runtime/assets`，可用
`AMPHION_ASSET_CACHE_DIR` 改位置。

当前中英打包默认模型为 Police 1.4.0 上游 encoder INT8、decoder/joiner FP32 包，tar.gz 按
[模型恢复说明](../../asr/tools/demo-model/README.md) 手动下载并校验；`fetch all` 不包含该模型。
`asr-zhen-police-179m-v1-1-v1.1.0` 保留为历史 A/B 基线，不再是当前鼎桥模型。

中文 ITN 当前使用 `asr-itn-zh-v2`，保留识别出的“啊、呃”；两端打包默认读取
`asr/tools/weitn-fsts-v2`。`asr-itn-zh-v1` 仅保留为旧规则记录，不用于新构建。

当前 canonical 受限资产是 `team-secure-state-v6`（2026-11-24，内容 = v5 + 扩充后的测试机 SN 清单），
包含团队授权根、可跨机签名配置、DevEco 解密材料、完整签名材料和设备清单。新机器按需执行
`.venv/bin/python tools/assets/sync.py fetch team-secure-state-v6`。v2~v5 的 OBS 快照已从清单移除，
OBS 账号只读、不再作为来源。

受限 bundle 的加密方式是 **客户端 AES-256-GCM**（`"encryption": "client-aes256-gcm"`）：
`publish` 先按清单确定性构造明文 ZIP，再用团队密钥加密成 `<sha256>.zip.enc` 上传，COS 上只有密文，
桶凭据泄露也拿不到明文；上传时再叠一层 SSE-COS（AES256），`remote-verify` 会同时核对密文大小、
密文 SHA-256 与该标记。nonce 由密钥和明文 SHA-256 派生，同一内容总得到同一密文，因此密文身份可以
登记在清单里。密钥不在本仓库、不在 CI，只在 `amphionkeys` 的 `amphion-assets.env`（GitLab 即备份）；
密钥丢失则远端密文不可恢复。

更新受限 bundle 的流程：改 `.secure` 内容 → 清单里更新逐文件身份与明文 `size/sha256`（新修订号）→
`sync.py seal <bundle>` 计算并写回 `object / encrypted_size / encrypted_sha256` → `publish` → `remote-verify`。
未 `seal` 的条目可以加载，但 `publish / fetch / remote-verify` 会报错提示先 `seal`。
恢复采用合并模式，不删除 `.secure` 下其他本地内容，也不会默认覆盖同名但内容不同的文件；确认要采用
远端版本时显式增加 `--replace-existing`。受限 ZIP 的本地明文与密文临时文件无论成功或失败都会清理，
并保留清单声明的 `0600`/`0644` 权限。

2026-11-16 起，此前仍跟踪在 Git 里的模型与原生二进制也全部外置，仓库只保留源码：

| bundle | 恢复到 | 内容 |
| --- | --- | --- |
| `asr-shared-models-v1` | `shared/models/asr` | eres2net / CAM++ / pyannote 分割 ONNX 与许可证、LAC 人名 encoder；鼎桥与警务 SDK 构建时复制进包 |
| `tts-harmony-icu-v1` | `tts/harmony/sdk/src/main/cpp/third_party/ohos-icu/lib` | 鸿蒙 arm64 ICU 静态库 |
| `tts-onnxruntime-android-v1` | `tts/android/sdk/src/main/jniLibs/arm64-v8a` | 安卓 ONNX Runtime `.so` 与 JNI 绑定 |
| `tts-onnxruntime-harmony-v1` | `tts/harmony/sdk/libs/arm64-v8a` | 鸿蒙 ONNX Runtime `.so` |
| `tts-runtime-imf170000-v2` | `tts/tools/trial-export/dingqiao_imf_step00170000_streaming_vocos24k/0.1.0` | 鼎桥 Android TTS 3.x 客户线的 IMF 170000 流式 Vocos 24k 运行时模型包（含前端资源与 `.bin`），3.3 起用的词典修复版；`-v1` 为 3.1/3.2 所用旧包（historical） |
| `tts-training-inputs-v1` | `tts/training/dingqiao_lits`（合并模式） | MorphoDiTa 俄语 tagger、训练 filelist、CMUdict 0.7b、中文词典源文件 |

`tts-runtime-zhen-v1` 的目标目录 `tts/tools/trial-export/.../0.1.0/` 此前还有 19 个文本文件留在 Git 里，
现已一并移除，整个目录只由该 bundle 恢复。各端构建对这些路径都有硬失败检查并提示 bundle 名称。

TTS 协作输入拆成三个用途明确的 bundle：`tts-checkpoints-v3-20260806` 恢复训练 checkpoint，
`tts-runtime-zhen-v1` 恢复 Android/Harmony 共用的 ONNX 与前端资源，`tts-harmony-tn-v1` 恢复
HarmonyOS arm64 TN 可执行文件。这样新机器可以按训练、导出或真机验证场景只取所需资产。

## 2026-11-16 历史改写

模型与原生二进制外置后，用 `git filter-repo` 把它们从全部历史里删除（打包体积 198 MiB → 19 MiB，
main 顶端目录树不变）。所有提交哈希随之改变：

- 旧 → 新提交映射：`delivery/archive-migrations/20261116-history-rewrite-commit-map.txt`；
  证据文件里记录的旧哈希按此表查新值（右侧全 0 的提交只改过被移除文件，已被剪掉）。
- 被移除的路径：`delivery/archive-migrations/20261116-history-rewrite-removed-paths.txt`。
- 已有克隆不要 `git pull`，重新克隆；本地未推送分支用 `git rebase --onto <新基点> <旧基点>` 迁移。
- 任何分支检出后都没有模型文件，按上文 `fetch all` 恢复。

## 名称与版本含义

逻辑名称用于选择资产，OBS 对象键用于定位既有文件；二者不必相同。整包 SHA-256 才是
输入内容的身份。为保持已有缓存、脚本和历史证据有效，本轮整理不重命名云端对象或本地目录。

| 资产 | 版本含义 |
| --- | --- |
| `aishell3-500` | 共享的 500 条 AISHELL-3 语料；旧名称 `aishell3-hotwords-500` 仍可使用，热词只是用途之一 |
| `asr-zhen-police-179m-v1-1-v1.1.0` | `model_id=police-179m-v1-1`，`model_version=1.1.0`；名称中的两个版本片段属于不同字段 |
| `tts-runtime-zhen-v1` | bundle 修订 `v1`，训练流程代次 `v3`，导出模型版本 `0.1.0`；三个数字不能互相代替 |
| `tts-checkpoints-v3-20260806` | 训练流程代次 `v3`，checkpoint 快照日期 `2026-08-06` |
| `team-secure-state-v6` | 团队签名及授权材料的第 6 版快照，不是 SDK 或模型版本 |

上述模型版本、流程代次和 checkpoint 日期已在清单中分字段记录。`amphion-runtime/assets/v1` 和
`amphion-runtime/test-data/v1` 中的 `v1` 是存储命名空间版本，不代表所有资产内容都处于第 1 版。
后续新资产应分别记录模型版本、bundle 修订或快照日期，避免再把多种版本号拼在名称中。

## 上传与审计

```bash
python3 tools/assets/sync.py audit
python3 tools/assets/sync.py publish asr-zhen-v1
# 把旧存储上已有的归档原样搬到清单声明的默认存储（不需要本地解压文件；受限 bundle 不参与）：
python3 tools/assets/sync.py mirror --from obs-legacy all
```

`mirror` 从源存储下载 ZIP、按清单整包 SHA-256 校验后上传到目标，再做远端校验；目标已有同身份
对象时跳过。bundle 可用 `"storage": "<名称>"` 指定留在某个具名存储（当前没有 bundle 这样做）。
受限 bundle 不走 `mirror`，只能从本地明文 `publish`。

2026-11-22 迁移记录：非受限 bundle 全部 19 个中的 14 个已在 COS（含当日用 `mirror --from obs-legacy`
补齐的 `tts-checkpoints-v3-20260806`、`tts-harmony-tn-v1`、`asr-zhen-police-179m-v1-1-v1.1.0`、
`asr-itn-zh-v1`）；测试语料 `aishell3-500`、`dingqiao-meeting-20260918` 与两个 catalog 归档也已复制到 COS。
受限 bundle 当时仍在 `obs-legacy`（COS 侧 `cos/kms` 上传探测返回 500，账号未开通 KMS）。
2026-11-24 改为客户端加密后发布到 COS：`team-secure-state-v6`、`harmony-demo-license-v2`；
`team-secure-state-v2~v5` 不再迁移，条目已从清单删除（OBS 上的对象原样留存但不再被引用）。

`publish` 只接受清单中逐文件身份完全匹配的仓库资产，并使用固定顺序、时间戳和权限构造
可重复 ZIP。对象键包含整包 SHA-256，工具不会覆盖不同内容。受限 bundle 必须经对象级
SSE-KMS 上传，远端校验若看不到 `kms` 标记就失败。

`audit` 对每个 Git 忽略文件作三选一判定：已同步资产、明确排除项、未分类文件。未分类文件
会使命令失败，必须先决定是否新增 bundle；不能用扩大通配符绕过。当前明确排除：

- 构建、IDE、虚拟环境、派生 SDK 模型、报告与交付输出；
- 由 `tts-runtime-zhen-v1` 确定性生成的 Android 外置资源和 Harmony HAR 内置资源副本；
- 可由固定上游地址重建的依赖缓存；
- 未登记的客户数据、个人声纹数据，以及不属于受控 `.secure` bundle 的敏感输入。

新受限文件不会被通配符自动带入对象；必须显式加入清单，避免历史构建副本或个人数据混入。

现有 `asr/test-data/manifest.json` 仍是测试语料的权威清单，并被本工具包含；原有
`asr/tools/test_data.py` 命令保持兼容。
