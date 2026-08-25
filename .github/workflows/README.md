# Android/ASR CI 运行规则

`android.yml` 始终保留 required check `Build AAR (arm64-v8a)`。这个 check 是汇总
job，branch protection 无需改名；它会核对每个下游 job 应当成功还是应当跳过，状态不符
即失败。

## 变更分类

PR 使用 GitHub changed-files API；`main` push checkout 当前提交后按事件中的
`before..sha` 计算 Git diff。重命名同时检查新旧路径。首次 push、无效 `before`、diff
失败、API 异常、changed-files 结果截断、未知文件状态、未知事件或 workflow 自身变化都
fail-closed，执行全量门禁。`release/*`、`v*` tag 和手动运行始终全量，不受文件类型影响。

| 输入或事件 | AGC static | Harmony contracts | delivery redaction | police parity / unit | host AGC | Android AAR |
| --- | --- | --- | --- | --- | --- | --- |
| 普通纯 Markdown | 跳过 | 跳过 | 跳过 | 跳过 | 跳过 | 跳过 |
| customer delivery Markdown | 跳过 | 跳过 | 运行 | 跳过 | 跳过 | 跳过 |
| `Runtime.ets` | 运行 | 运行 | 跳过 | 跳过 | 跳过 | 跳过 |
| AGC report JSON | 运行 | 跳过 | 跳过 | 跳过 | 跳过 | 跳过 |
| Android SDK Kotlin | AGC boundary 变化时运行 | 运行 | 跳过 | shared SDK 变化时运行 unit | 仅 AGC processor 变化时运行 | 运行 |
| AGC native 源码、测试或构建输入 | 运行 | 运行 | 跳过 | 跳过 | 运行 | 运行 |
| Harmony AGC processor / ingress / bridge | 运行 | 运行 | 跳过 | 跳过 | 运行 | 跳过 |
| police assets | 跳过 | 运行 | 跳过 | parity 与 unit 均运行 | 跳过 | 运行 |
| Android samples、docs、其他 reports | 跳过 | 跳过 | 跳过 | 跳过 | 跳过 | 跳过 |
| 非 ASR 输入 | 跳过 | 跳过 | 跳过 | 跳过 | 跳过 | 跳过 |
| workflow、分类失败、release、tag、手动 | 运行 | 运行 | 运行 | 运行 | 运行 | 运行 |

Android AAR 只监听实际被当前 job 消费的三个 module（`sdk`、`sdk-dingqiao`、
`sdk-police`）、Gradle 配置、native 源码与脚本、sherpa patch 和 submodule gitlink。
`reports`、`docs`、`samples` 不会再触发未使用它们的 Android 冷构建。

分类逻辑是无副作用的 `classify(changes)`，同时读取文件路径、重命名前路径和 API status。
workflow 内带最小用例矩阵，覆盖 Harmony、Android、AGC、police、报告、Markdown、
customer redaction、sample、rename 和未知 status。静态门禁还会用
Node.js 执行该矩阵，并检查 workflow 拓扑、缓存配置和 required 汇总关系。

## 并行拓扑

`changes` 完成后，各门禁只依赖分类结果并行启动：

```text
changes
  ├─ static-contracts
  ├─ harmony-contracts
  ├─ delivery-redaction
  ├─ police-parity
  ├─ host-agc
  └─ android-aar
          ↓
      ci-result: Build AAR (arm64-v8a)
```

- `static-contracts`：AGC 静态证据门禁。
- `harmony-contracts`：全部 `test_harmony_*.py`、Android native cache 单测、设备压力及
  发布脚本契约测试。
- `delivery-redaction`：只在客户交付目录或脱敏检查器变化时运行；客户 Markdown 不因
  文档快速路径而跳过。
- `police-parity`：只在 police 输入变化时拉取 metadata 指定的冻结 commit，安装固定
  TypeScript 版本并校验资产同步与跨端 parity。
- `host-agc`：只在 AGC 输入变化时构建并执行 native tests。
- `android-aar`：构建三个 Android SDK module 当前消费的 AAR 与 native 产物；shared
  `sdk` 或 `sdk-police` 变化时额外执行 `:sdk-police:testReleaseUnitTest`。

## Cache 与 artifact

### Android native cache

`android-aar` 继续使用 `android-native-*` cache。key 是 sherpa gitlink、patch、
`asr/native/**`、native 构建脚本、ABI/platform 和固定工具版本的完整 fingerprint。
submodule 初始化后始终先应用固定 patch series，避免 cache hit 跳过 patch 后拿未打补丁
的 upstream Kotlin 与 SDK bridge 对账。cache 不使用模糊 restore key；命中后必须用
manifest 校验 fingerprint、三份 `.so` 的 SHA-256 和大小，验证通过才跳过 native 编译。
Gradle assemble、unit test、AAR 内容检查和 bridge 对账始终执行。

### Gradle enhanced cache

Android job 使用 `gradle/actions/setup-gradle@v6` enhanced provider，不再按每个 commit
保存约 700 MB 的完整 Gradle User Home。PR、release branch、tag 和手动运行只读；只有
`main` 可以写入。成功构建后执行 cleanup，任何 cache 命中都不会跳过 assemble 或测试。

### Host AGC incremental cache

`host-agc-*` 保存 `build-host` 和 Meson `subprojects`。依赖描述、工具脚本变化会产生新
基线；仅 AGC 源码或测试变化时可从同一依赖基线恢复，再由 Meson 增量编译。无论命中
与否都执行 native tests。`build-host/meson-logs` 明确排除在 cache 外，避免测试日志中
记录的进程环境进入缓存。

AAR 和 `.so` 上传使用 `compression-level: 0`，避免对已压缩二进制重复耗时压缩。

## 一次性旧 cache 迁移

合入后先等待一次包含 Android job 的 `main` workflow 成功，确认 enhanced Gradle cache
已生成。随后通过 GitHub Actions cache 列表记录删除前的条目数和总大小，只删除旧 key
形态 `gradle-Linux-<64位配置哈希>-<40位提交SHA>`；不能按 `gradle-` 前缀删除，因为
setup-gradle 新 cache 同样使用该前缀。明确保留 `gradle-home-v2`、
`gradle-dependencies-v2`、`gradle-transforms-v2`、`android-native-*` 和 `host-agc-*`。
删除后再次记录条目数和总大小。

本次改造前的观测基线是 15 个旧 `gradle-*` 条目、约 9.83 GiB；这一步不能在首次成功
的 `main` 构建前执行，也不能用宽泛前缀删除其他 cache。

## 首次 CI 验收

首次合入后的 `main` run 记录为：static 21 秒、Harmony 39 秒、police 26 秒、首次 main
host AGC 基线 2 分 11 秒、Android 2 分 44 秒；Android native cache 命中，Gradle
assemble + unit test 约 2 分 02 秒。迁移后 cache 总量约 644 MiB，其中 enhanced Gradle
约 542 MiB。

Harmony-only 路径已达到约 40 秒。report-only 现在只运行 static，不再被同一个
`contracts` flag 牵连到 Harmony tests；首次真实 report-only PR 仍需记录最终耗时。
