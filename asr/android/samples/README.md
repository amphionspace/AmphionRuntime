# ASR Android Samples

本目录只放可安装的 ASR 示例 / 验证 App。它们都是独立 APK，可以单独构建和安装；但它们共享同一个 Gradle root、`:sdk` 体系和模型资产。

## 命名约定

| 目录 | Gradle 模块 | applicationId | 受众 | 说明 |
| --- | --- | --- | --- | --- |
| `public-demo/` | `:samples:public-demo` | `com.amphion.asr.sample` | 外部集成方 / 内部 smoke | 通用 ASR demo，覆盖端侧识别、热词、目标说话人等主流程。当前还包含云端 ASR 演示开关，因此 manifest 有 `INTERNET` 权限。 |
| `mini-demo/` | `:samples:mini-demo` | `com.amphion.asr.mini` | 小屏设备验收 | `public-demo` 的小屏版本，面向 240x320 等极小屏设备；保留核心端侧识别能力。 |
| `internal-eval/` | `:samples:internal-eval` | `com.amphion.asr.sample.eval` | 内部评测人员 | 评测数据采集、WER 估算、录音导出和上传工具。`eval` 是 evaluation（评测）的缩写；该模块不进入对外交付包。 |
| `dingqiao-demo/` | `:samples:dingqiao-demo` | `com.amphion.dingqiao.demo` | 鼎桥客户交付 / 验收 | 使用鼎桥适配层 `:sdk-dingqiao` 或 fat AAR 的定制 demo，只展示客户契约相关能力。 |

## 常用命令

```bash
cd asr/android

# 通用 demo
./gradlew :samples:public-demo:installDebug

# 小屏 demo
./gradlew :samples:mini-demo:installDebug

# 内部评测 App
./gradlew :samples:internal-eval:installDebug

# 鼎桥 demo
./gradlew :samples:dingqiao-demo:assembleDebug
```

## 交付边界

- 标准 ASR SDK 对外交付以 `:sdk` AAR 和 `public-demo/` 为主。
- `internal-eval/` 含网络上传、FileProvider、OkHttp 等评测链路，仅供内部使用。
- `dingqiao-demo/` 只用于鼎桥客户交付，不代表通用 SDK 的对外 API。
- `mini-demo/` 是屏幕形态变体，是否随包提供按项目需要决定。
