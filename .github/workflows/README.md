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

对 PR，`changes` 通过 GitHub changed-files API 读取 PR 自身变更集，不 checkout
仓库；重命名同时检查新旧路径。对非 PR 事件，Android 判定直接强制为 `true`，
从而保持现有发布行为。`asr-contracts` 不依赖路径判定，会与 `changes` 并行启动。
`android-aar` 只读取当前源码和 submodule gitlink，因此使用 shallow checkout；只有
需要读取 frozen historical assets 的 `asr-contracts` 保留完整历史。

## Android native cache

`android-aar` 根据以下输入生成确定性 source fingerprint：

- `third_party/sherpa-onnx` gitlink commit；
- `third_party/patches/sherpa-amphion/**`、`asr/native/**`；
- Android native 构建、patch、依赖预取和打包脚本；
- ABI、Android platform、NDK、ORT、CMake、Meson 和 Ninja 版本。

当前 workflow 只构建 `arm64-v8a`；cache identity 工具会拒绝其他 ABI，避免配置与
固定的 arm64 产物路径不一致。

缓存 key 只接受完整 fingerprint 的精确命中，不配置 `restore-keys`。命中后必须先用
manifest 校验 fingerprint 及三份 `.so` 的 SHA-256/大小，才会跳过 native 编译；校验
失败直接令 job 失败。未命中时重新编译并生成 identity manifest。无论是否命中，
Gradle assemble/unit test、AAR 内容与哈希校验、Kotlin bridge 对账和 artifact 上传均照常运行。
