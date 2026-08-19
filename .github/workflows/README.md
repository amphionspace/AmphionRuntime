# Android CI 路径决策

`android.yml` 始终运行 `changes`、`asr-contracts` 和 required 汇总检查
`Build AAR (arm64-v8a)`。汇总检查沿用原显示名，branch protection 无需同步改名。

| 变更或事件 | `asr-contracts` | `android-aar` | 汇总检查 |
| --- | --- | --- | --- |
| PR 只修改文档或 Harmony 模型身份文件 | 运行 | 跳过 | 合约通过时通过 |
| PR 修改 `asr/android/**`、`asr/native/**`、native 脚本、sherpa patch 或 submodule | 运行 | 完整运行 | 汇总两个 job |
| push 到 `main` 或 `release/*` | 运行 | 完整运行 | 汇总两个 job |
| `v*` tag | 运行 | 完整运行 | 汇总两个 job；Maven 发布消费其 AAR artifact |
| 手动触发 | 运行 | 完整运行 | 汇总两个 job |

对 PR，`changes` 比较 merge-base 到 head 的 PR 自身变更集；对非 PR 事件，
Android 判定强制为 `true`，从而保持现有发布行为。

第二阶段将用完整 source fingerprint 替换现有 native cache key，并且只在精确命中、
产物身份已绑定时跳过编译；不得通过宽泛 restore key 复用 native 二进制。
