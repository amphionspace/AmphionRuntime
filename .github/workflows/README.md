# Android CI 路径决策

`android.yml` 对 PR 始终运行 `changes` 和 required 汇总检查
`Build AAR (arm64-v8a)`。汇总检查沿用原显示名，branch protection 无需同步改名。

| 变更或事件 | `asr-contracts` | `android-aar` | 汇总检查 |
| --- | --- | --- | --- |
| PR 只修改 Markdown | 跳过 | 跳过 | 确认两个 job 均按预期跳过后通过 |
| PR 只修改非 Markdown 的非 Android 输入 | 运行 | 跳过 | 合约通过时通过 |
| PR 修改 `asr/android/**`、`asr/native/**`、native 脚本、sherpa patch 或 submodule | 运行 | 完整运行 | 汇总两个 job |
| push 到 `main` 或 `release/*`，且只修改 Markdown | workflow 不触发 | workflow 不触发 | 不运行 |
| push 到 `main` 或 `release/*`，且包含非 Markdown 变更 | 运行 | 完整运行 | 汇总两个 job |
| `v*` tag | 运行 | 完整运行 | 汇总两个 job；Maven 发布消费其 AAR artifact |
| 手动触发 | 运行 | 完整运行 | 汇总两个 job |

对 PR，`changes` 通过 GitHub changed-files API 读取 PR 自身变更集，不 checkout
仓库；重命名同时检查新旧路径。纯 Markdown PR 跳过 `asr-contracts` 和
`android-aar`，但仍运行 required 汇总检查，避免 branch protection 永久 pending。
纯 Markdown branch push 通过 trigger path filter 直接跳过整个 workflow；tag push
不受 path filter 影响。其余非 PR 事件仍强制完整运行，从而保持发布行为。

`android-aar` 只读取当前源码和 submodule gitlink，因此使用 shallow checkout。
`asr-contracts` 同样 shallow checkout，再从 police metadata 读取并校验冻结 commit，
只 fetch 该历史对象供 parity gate 使用，不下载完整仓库历史。

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
失败直接令 job 失败。命中后也不再下载仅供 native 编译使用的 NDK/CMake；未命中时
安装固定版本工具、重新编译并生成 identity manifest。无论是否命中，Gradle
assemble/unit test、AAR 内容与哈希校验、Kotlin bridge 对账和 artifact 上传均照常运行。

## Gradle cache

Gradle User Home cache 的 primary key 由 runner OS、Android Gradle 配置文件 hash 和
当前 commit SHA 组成。新 commit 先按相同配置 hash 恢复已有缓存，构建成功后再写入
自己的不可变 cache entry；这样既能复用依赖和 Gradle build cache，又不会让固定 key
长期停留在第一次保存的状态。任何缓存命中都不跳过 Gradle assemble 或 unit test。
