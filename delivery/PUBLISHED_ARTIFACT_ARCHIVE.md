# 交付包对象存储归档

完整交付顺序见[双端流程](ASR_DELIVERY_WORKFLOW.md)。本文只定义包的归档、恢复和本地清理；上传不重建或重压缩 ZIP，不改变验收与发布结论。

## 状态与适用范围

| 包的状态 | 归档依据 | 索引中的状态 |
| --- | --- | --- |
| 已正式发布的完整包 | 主线外层发布记录，精确绑定 ZIP 与最终报告 | `published: true` |
| 身份明确、尚未发布的当前包 | 用户明确要求保存；版本、源码、大小、哈希及真实报告完整 | `published: false` |
| 历史 SDK-only 已发布包 | 主线 `asr-sdk-release-history.json` 中的原始子包身份 | 保留历史发布依据，不重新组装 |
| 身份不清或与历史发布记录冲突的包 | 记录哈希和冲突原因，在用户已授权的范围内清理 | 不作为历史发布包上传 |

相同版本号、FORMAL 文件名、构建成功或个人分支台账均不能独立证明已发布。内层 SDK 的正式记录不能证明外层完整 ZIP 已发布。未发布包的明确授权不推广为自动保留所有历史失败产物。

归档集合包含原包、外置 SHA-256、验收报告及实际交付说明，附件逐个登记身份。TTS 等产品遵守同样的身份原则。源码、原始 PCM、实验快照、失败现场、授权私钥、签名私钥和构建环境不属于交付包清理；不得整目录上传或删除 `build/`、`.secure/` 或工作区。

## 位置与索引

本地暂存布局由[双端流程](ASR_DELIVERY_WORKFLOW.md#2-冻结和构建)定义。归档脚本按 `<product>/<platform>/<version>/<source-commit>` 查找 `packages/`、`acceptance/`、`scratch/`；源码提交使用完整 40 位 SHA，不依赖仓库 build 目录默认输出。

使用 AmphionBucket，先检查 `ab remotes` 中存在 `cos-amphion-delivery`。远端位置固定为：

```text
cos-amphion-delivery:amphion-runtime/releases/<product>/<platform>/<version>/<outer-sha256>/<artifact>
cos-amphion-delivery:amphion-runtime/releases/<product>/<platform>/<version>/<outer-sha256>/companions/<attachment>
cos-amphion-delivery:amphion-runtime/archive-index/<unique-batch-id>.json
```

不使用 latest，不覆盖不同内容，不修改 ACL 或创建公开下载链接。索引使用不可覆盖的批次 ID，保存包含历史条目的全量索引。

Git 中的 `delivery/published-artifact-archives.json` 沿用历史名称，包含正式和明确授权的未发布归档；读取时检查 `published`。旧条目无该字段时，依据其主线发布台账判断。每个原包和附件记录精确 URI、字节数、SHA-256 及完整回下载验证时间；不记录用户绝对路径、凭证或客户音频。删除结果另存 `delivery/archive-migrations/`。

## 身份记录

未发布包记录保存在 `delivery/candidate-reports/`，包括 `product`（默认 asr）、`platform`、`version`、完整 `source_commit`、外层 `artifact` 文件名、`size_bytes`、`sha256`、`published: false` 和真实验收结论。

正式完整包记录保存在 `delivery/published-deliveries/<product>-<platform>-<version>-<outer-sha256>.json`，在归档前随发布记录 PR 合入主线；后续归档索引和清理结果另行提交。除上述身份字段外，正式记录须包含：

| 字段 | 含义 |
| --- | --- |
| `published` / `delivered_at` | `true` 与实际交付日期 |
| `release_sdk` | ASR 子包的台账身份；没有子包的产品省略 |
| `acceptance_report` / `acceptance_sha256` | 仓库相对报告路径及哈希；报告绑定外层 ZIP |
| `companions` | 附件列表，每项有 `artifact`（文件名）、`size_bytes`、`sha256` |
| `result` / `limitations` | 最终结论及限制；脚本 published 模式只接受主线 `result: "PASS"` 的记录 |

身份记录、验收报告和外置校验文件由脚本自动纳入相应集合，其他实际交付附件必须显式列出。各附件文件名须唯一，不能靠同名覆盖。

## 执行归档

`tools/delivery/archive_delivery.py` 在 macOS/Linux 运行，依赖 Python 3.10+、AmphionBucket；删除时还需要 `lsof`。默认使用 `~/.local/bin/ab`，可用 `--ab` 指定安装路径，避免误用系统 ApacheBench。

从仓库根目录执行，先替换占位路径；以下命令只预览，不上传或删除：

```bash
python3 tools/delivery/archive_delivery.py \
  --record 'delivery/candidate-reports/<batch>/android.json' \
  --publication unpublished \
  --companion acceptance/complete-candidate-report.json \
  --companion acceptance/delivery-notes.md \
  --batch-id '<unique-batch-id>'
```

- `--record` 是仓库相对身份记录路径。脚本自动读取并归档 `packages/<artifact>`、`packages/<artifact>.sha256` 和记录本身；外置校验内容为 `<sha256>  <artifact>`。
- `--companion` 可重复，路径相对本次固定暂存目录。未发布包须列出真实报告和实际说明；脚本检查文件内容一致性，不替代人工判断附件是否齐全。
- 正式包使用 `--publication published`，`--record` 指向外层发布记录。执行前 fetch 主线；脚本核对记录与 `origin/main` 一致、报告哈希以及 `companions` 中每项身份，并自动归档仓库报告。不要再重复传入自动纳入的附件。
- 预览无冲突后，原命令追加 `--apply`。脚本逐项上传、完整回下载、重算哈希和字节数；随后上传并回下载全量批次索引，验证成功后原子保存本地索引。ETag、文件存在或 push 成功不能代替此验证。
- 本次上传及清理已获得用户授权时，同时追加 `--remove-local`。删除前再次检查哈希、大小和文件占用，只删除本次列明的暂存原包与附件，保留仓库身份记录和报告。逐项删除结果写入迁移记录。

历史 SDK-only 包不适用此完整包脚本：按主线台账核对身份，使用 `ab push --dry-run`、`ab push` 和 `ab pull` 完成同样的逐项回下载与索引验证，不伪造外层发布记录。仅在归档验证后移除本地包。

## 失败、额外副本与恢复

- 远端冲突、下载损坏、源文件变化或索引验证失败时停止，不加 `--overwrite`。未进入删除阶段的原件全部保留；若删除阶段中断，已删除项见迁移记录，剩余文件不继续清理。
- 保留下载恢复目录和 AmphionBucket 检查点。一次临时传输失败可重试一次，仍失败先诊断。重新执行脚本会使用新下载目录，不保证复用旧下载分块；不为恢复擅自清除旧检查点。
- 尚未入索引时，处理失败后用新的唯一批次 ID 继续；已入索引的包不得重复登记。若先前仅用 `--apply` 归档而未清理，后续按已有验证记录再次核对内容和占用后人工清理，不能靠重跑命令跳过重复登记保护。
- 额外内层包或展开副本不自动删除。逐文件与已归档 ZIP（必要时其内层 ZIP）比对，删除明确匹配且未使用的文件；有新增或修改内容的目录不得整目录删除。独立诊断证据保留。
- 恢复时从 Git 索引或远端批次索引获取精确 URI，用 `ab pull` 下载到新的临时位置，核对 SHA-256 和字节数后才使用。归档不续期授权，也不授予发布资格；使用后清理已核对的临时副本，不建立长期本地镜像。

历史迁移记录见 [2026-09-27](archive-migrations/20260927.json)；2026-09-28 双端当前包及重复副本的处理见同目录 `20260928-asr-*`。这些是具体批次事实，不作为其他任务的删除授权。
