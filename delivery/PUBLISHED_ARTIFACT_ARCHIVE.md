# 交付包对象存储归档规范

交付包按明确状态保存在公司对象存储；本机只保留轻量归档索引，使用时按需下载。归档不重建、不重压缩、不改变已验收的 ZIP，也不改变发布结论。

## 1. 范围与已发布认定

- ASR SDK 以 canonical `main` 的 `delivery/asr-sdk-release-history.json` 为依据。候选文件必须同时匹配台账的附件名、字节数、SHA-256，并保留平台、版本、交付日期、源码 commit 与包内 provenance 的绑定。
- 版本号相同但日期、源码或哈希不同的工作区产物不得沿用主线记录。`FORMAL`、文件名、构建成功、staged 目录或个人分支台账都不能独立证明已发布；历史包冲突或缺少发布依据时，记录文件哈希与原因后直接删除，不另建历史包归档。当前正在验收、身份明确的未发布包默认留在规定暂存目录；用户明确要求归档时，按下述未发布路径执行。
- 完整交付包须有绑定外层 ZIP SHA-256 的已发布记录和最终 ZIP 验收报告；仅内部 Release SDK 在台账中，不足以认定整个外层包已发布。完整 ZIP、外置 SHA-256、最终验收报告和实际交付说明作为一个归档集合，逐个登记大小与 SHA-256，全部验证后才能移除该集合的本地副本。不得用 SDK-only 包替代完整交付。
- 历史 SDK-only 交付按当时台账原样归档，不重新组装为当前默认结构。其他产品（包括 TTS）正式归档须有同等可核对的发布记录；没有依据的历史交付包按已授权清理范围处理。
- 原始 PCM、实验快照、失败现场、授权私钥、签名密钥和构建环境不属于交付包清理；不能整目录上传或清除 `build/`、`.secure/`、诊断目录或工作区。已发布包原有的授权内容不在归档时改写。

### 未发布包的明确授权归档

用户明确要求保存当前身份清楚的未发布包时，可以归档原包和真实报告，索引必须标记 `published: false` 并记录依据；不得创建正式发布记录或将验收状态改成 PASS。本次授权不推广成自动保存所有历史失败包。2026-09-28 的此类归档见 `archive-migrations/20260928-asr-*`。

`published-artifact-archives.json` 沿用历史文件名，同时保存已发布与明确授权的未发布归档；读取时必须检查 `published`。历史已发布条目没有此字段时，以其主线发布台账为依据，不凭文件名推断状态。

## 2. 本地与对象存储固定位置

本地交付文件统一暂存于以下目录，不再长期散落在仓库 `build/`、`asr/delivery/`、桌面、下载目录或 `~/delivery/`：

```text
~/.cache/amphion-runtime/delivery-staging/<product>/<platform>/<version>/<source-commit>/
├── packages/       # 待交付的原始 ZIP 与外置校验文件
├── acceptance/     # 该 ZIP 的最终验收报告及交付说明
└── scratch/        # 临时解包、独立构建与回下载校验副本
```

`source-commit` 使用完整 40 位提交号。`product`（如 `asr`、`tts`）与平台明确分隔；同版本不同构建不得混放。现有打包脚本必须显式传入此处的输出目录，不依赖脚本历史默认位置；仅底层编译中间文件可继续留在构建工具自身目录。使用脚本支持的 `output-root` / `--stage-release` 参数指定位置，未支持自定义输出的工具先完成输出目录适配再用于新交付。

本地只保留正在进行的交付暂存。已发布包在交付完成、归档回下载验证和远端索引保存后立即清理；取消或被否决的候选在保存必要的独立失败报告后清理 ZIP 和确认对应的解包副本。不按“留最近 N 版”建立本地镜像，不通过复制旧目录开始新交付。身份不清的历史交付包记录哈希后直接删除，不上传为历史包袱。独立诊断证据按其自身保留规范处理。

传输使用 AmphionBucket `ab`；先执行 `ab remotes` 确认别名。当前归档位置使用已有公司交付桶 `cos-amphion-delivery`，不修改 ACL、不生成公开链接，也不作为端侧 SDK 在线依赖。

```text
cos-amphion-delivery:amphion-runtime/releases/<product>/<platform>/<version>/<artifact-sha256>/<artifact-name>
```

当前 `<product>` 为 `asr`。完整交付集合的外置报告与说明放在外层包哈希目录下的 `companions/`，独立记录哈希；平台为 `harmony` 或 `android`。不使用 `latest`，不覆盖不同内容，不以版本目录表示唯一构建。发现远端冲突即停止，不添加 `--overwrite` 绕过。

Git 内的 `delivery/published-artifact-archives.json` 只登记已经回下载验证通过的对象，记录发布依据、精确远端 URI、文件大小、SHA-256、验证日期及本次验证的本地副本数量（删除结果另记迁移报告）；不写用户绝对路径、凭证或客户音频。全量索引另存到同桶 `amphion-runtime/archive-index/<batch-id>.json`，批次 ID 唯一，后续批次不覆盖旧索引。原发布台账保持不变。

### 每次交付在 Git 中记录什么

新的完整交付或没有现成产品台账的交付，在 `delivery/published-deliveries/<product>-<platform>-<version>-<outer-sha256>.json` 保存一条发布记录，并随发布 PR 合入主线。记录至少包含：

| 字段 | 内容 |
| --- | --- |
| `product` / `platform` / `version` | 产品、平台、版本 |
| `source_commit` / `delivered_at` | 冻结源码的完整提交号、实际交付日期 |
| `artifact` / `size_bytes` / `sha256` | 原始最外层交付包的文件名、字节数、完整 SHA-256 |
| `release_sdk` | ASR 子包对应的现有台账身份；其他产品无子包时省略 |
| `acceptance_report` / `acceptance_sha256` | 已入库脱敏最终报告的相对路径与哈希，报告本身绑定外层包身份 |
| `companions` | 实际交付的外置校验文件、报告和说明的相对文件名、大小与哈希 |
| `result` / `limitations` | 最终验收结论及未覆盖条件，不把失败或不确定结论改成通过 |

此记录建立正式交付身份；`published-artifact-archives.json` 则追加该身份对应的精确对象地址与回下载校验记录，不替代原始发布记录。每批归档必须保留已有索引条目，只追加新条目；上传包含全部条目的新批次索引，不能用本次条目覆盖历史索引。索引中的每个对象（包括外置附件）分别登记文件名、大小、SHA-256、精确 URI 和回下载验证时间。旧批次远端索引仍保留。

## 3. 执行顺序与删除门禁

1. 列出待归档文件，按发布依据计算本地 SHA-256 和大小；记录不匹配项及 SHA-256，按历史包清理规则删除，不上传为正式归档。检查没有构建、验收、传输或其他任务正在使用这些文件。
2. 执行 `ab push <local-file> <exact-remote-uri> --dry-run`，确认目标与冲突，再执行相同命令去掉 `--dry-run`。每项检查退出码；部分成功不能视为整批成功。
3. 用 `ab pull <exact-remote-uri> <new-temporary-path>` 从远端完整回下载，重新计算 SHA-256 和字节数，与发布台账及上传前值比较。不能以文件存在、大小相同、ETag、历史上传记录或 push 的退出码替代内容验证。
4. 将已验证索引写入本地并上传独立批次索引；回读索引核对内容。原始包和归档集合成员在索引落盘、远端索引验证前不得删除。
5. 删除前再次确认本地文件内容、大小与记录一致，且没有活跃使用者。只删除清单中明确列出的已验证文件和本次回下载的临时文件，不使用通配符、`git clean` 或工作区目录删除。任何失败、源文件变化、远端冲突或回下载校验不符都保留原文件并记录原因。
6. 有额外解包副本时，先逐文件确认与已归档 ZIP 的成员一致；仅移除匹配且未使用的副本。含额外/修改文件的目录不得整目录删除。构建中间产物不自动视为交付包副本。
7. 提交规范和已验证索引的 PR。仅归档和文档变更不触发 SDK 重构建或真机重跑；用实际传输回下载、哈希及索引一致性检查验证。归档验证记录不替代发布验收证据。

本流程执行上传与本地移除须在用户授权的范围内。单次临时网络失败可按 `ab` 的断点续传能力重试一次；仍失败则保留文件并报告，不能自动无限重试或清除恢复检查点。

## 4. 仓库执行入口

完整交付顺序见[双端交付流程](ASR_DELIVERY_WORKFLOW.md)。归档使用 `tools/delivery/archive_delivery.py`，在 macOS/Linux 上运行，依赖 Python 3.10+、AmphionBucket 和清理时的 `lsof`；默认指定 `~/.local/bin/ab`，避免误用系统 ApacheBench。

```bash
# 从仓库根目录运行。先预览，无上传、索引写入或删除。
python3 tools/delivery/archive_delivery.py \
  --record delivery/candidate-reports/<batch>/android.json \
  --publication unpublished \
  --companion acceptance/complete-candidate-report.json \
  --companion acceptance/delivery-notes.md \
  --batch-id <unique-batch-id>

# 原命令追加 --apply 执行上传与完整回下载；
# 已获用户清理授权时再追加 --remove-local。
```

身份记录须包含 `platform`、`version`、完整 `source_commit`、外层 `artifact` 文件名、`size_bytes`、`sha256`；未发布记录必须包含 `published: false`。`product` 默认 asr。脚本从固定暂存目录读取原包，自动归档外置 `<artifact>.sha256` 和身份记录；其他附件通过重复 `--companion` 显式指定，路径相对该暂存目录。

正式包使用 `--publication published --record delivery/published-deliveries/<record>.json`。执行前 fetch 主线；脚本要求该记录与 `origin/main` 一致、`result` 为 PASS、最终报告哈希匹配，并核对记录中列出的全部 companions。历史 SDK-only 包仍按第 3 节人工核对原台账，不伪造完整包记录来适配此入口。

脚本保留旧索引，逐个对象完整下载校验，上传并回下载独立批次的全量索引，再原子保存本地索引；任何内容冲突都停止，不覆盖远端。删除前再次校验内容并检查使用状态，只删除本次列明的暂存文件，仓库内身份记录和报告不删除。清理结果写入 `delivery/archive-migrations/<batch-id>.json`。

失败保留原件和下载恢复目录。先处理报错再用新的唯一批次 ID 继续；已入索引的包不重复登记，按其 URI 恢复。脚本不自动清除展开副本、其他构建目录或云端对象，额外副本按第 3 节逐文件核对。

## 5. 按需恢复

从 Git 归档索引取得精确 `remote_uri`、`sha256` 和 `size_bytes`；本地索引不可用时，使用公司桶中的独立批次索引。恢复到新的临时位置，不覆盖已有文件：

```bash
ab pull '<remote_uri>' '/path/to/new-temporary-file.zip'
shasum -a 256 '/path/to/new-temporary-file.zip'
wc -c < '/path/to/new-temporary-file.zip'
```

哈希及字节数均与索引一致后才解包、使用或交付。核对发布台账中的同一身份；过期授权或当前能力限制仍按原发布记录处理，归档不赋予新的发布资格。使用结束后移除临时下载及已确认无修改的解包副本，不建立长期本地镜像。远端归档默认长期保留，不由本地清理流程删除。

## 6. 本次首次迁移

2026-09-27 按主线台账核对本机候选，匹配 Harmony 0.2.9 与 Android 0.3.3 两个历史交付 ZIP。归档结果见 [归档索引](published-artifact-archives.json)。

9 月 24 日交付工作区中的 Harmony 0.3.17 / Android 0.3.8 与主线同版本的 9 月 18 日记录存在身份冲突，按本次用户指令清理，不归档为已发布包；相关完整包、Diagnostics 包、staged 包及缺少发布依据的 TTS 历史包、SDK preview 包同样清理。只清除 ZIP 与可确认对应的解包内容，独立报告、源码与诊断证据保留。具体执行结果见 [迁移记录](archive-migrations/20260927.json)。
