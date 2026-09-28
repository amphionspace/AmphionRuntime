# ASR SDK 交付台账操作

交付顺序见[双端流程](ASR_DELIVERY_WORKFLOW.md)。本文只说明 `tools/delivery/asr_release_tracker.py` 的使用，所有命令从仓库根目录执行。

## 三种记录各自表示什么

| 记录 | 作用 |
| --- | --- |
| `delivery/asr-sdk-release-history.json` | Android/Harmony SDK 子包的交付身份与验收证据 |
| `delivery/published-deliveries/` | 完整外层 ZIP 的正式发布身份，不能借用子包记录 |
| `delivery/published-artifact-archives.json` | 原包和附件的对象存储地址、回下载校验及发布状态，不代替发布台账 |

未发布完整包的身份与实际结论放在 `delivery/candidate-reports/`，不写入正式发布台账。正式外层记录格式见[归档规范](PUBLISHED_ARTIFACT_ARCHIVE.md#身份记录)。

## 新交付登记

先冻结构建源码并验证最终产物。台账中的 `source_commit` 是产物真正使用的提交，不是之后登记台账的文档提交。工具从 ZIP 内唯一 provenance 读取身份，不接受外置 provenance；同时检查 ZIP CRC、版本、完整源码提交、SHA-256 和字节数。

Android 用 `pack_dingqiao_customer_delivery.sh --stage-release <新暂存目录> <版本>` 生成待验收子包。目录中的 `NOT-ACCEPTED.txt` 以及包内 FORMAL 渠道标记都不能证明通过验收。完成约定的真机、独立源码构建和最终 ZIP 检查后，用以下命令同时登记包和已脱敏入库的证据。

将命令中的占位内容替换为本次冻结值；`--artifact` 指 SDK 子包，不能直接传入包含多个子包的完整外层 ZIP：

```bash
python3 tools/delivery/asr_release_tracker.py record-evidence \
  --platform android \
  --version '<sdk-version>' \
  --source-commit '<full-source-commit>' \
  --delivered-at '<YYYY-MM-DD>' \
  --artifact '/absolute/staging/path/sdk-package.zip' \
  --report 'delivery/path/to/sanitized/report.json'

python3 tools/delivery/asr_release_tracker.py verify-evidence
```

Harmony 使用同一命令，将 `--platform` 改为 `harmony` 并指定对应子包和报告。证据不符合平台约定时命令失败，不能通过删改报告断言登记。不同平台分开记录；重复的“平台 + 版本”会被拒绝。

包内更新日志由 `changelog` 子命令按上一同平台交付到本次源码提交生成。前一交付不是本次提交的祖先时，先明确分支或回移关系，不生成不完整日志。

## 已有记录维护

- `record` 只登记产物身份，不完成证据绑定，不作为新 staged 包的正式交付入口。
- 已有合法记录补充验收证据时，使用 `attach-evidence --platform <platform> --version <version> --report <report.json>`，随后执行 `verify-evidence`。不得借此把另一个构建的证据挂到旧包上。
- 正式记录及证据按[统一流程](ASR_DELIVERY_WORKFLOW.md)合入后，执行[对象存储归档](PUBLISHED_ARTIFACT_ARCHIVE.md)。归档不改变原验收结论或台账身份。
