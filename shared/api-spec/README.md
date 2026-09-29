## 跨端 API 协议（Single Source of Truth）

本目录定义所有 ASR 端 / 服务端必须共用的不变量，三端 SDK 必须按这里给出的 schema / 错误码 / 协议实现。

| 文件 | 说明 |
| --- | --- |
| manifest.schema.json | 模型 manifest.json 的 JSON Schema (draft-2020-12)；规范定义；校验覆盖以各端实际 CI 为准 |
| errcodes.yaml | 错误码表；各端错误码需要与此对照；不表示已有统一自动生成器 |
| dingqiao-asr-parameters.json | 鼎桥 Android/HarmonyOS 客户可无平台分支使用的参数契约；`platform_extensions` 不属于通用配置 |
| README.md | 本文件 |

## 在三端的具体落地

### Android
- `AsrError.kt` 中的 `AsrErrorCode` 常量与本目录 errcodes.yaml 保持一致
- 现有 CI 入口见 [.github/workflows/android.yml](../../.github/workflows/android.yml)；不应假定所有错误码已由 YAML 自动生成或全量校验

### iOS
- `AsrError.swift` 中的 `AsrErrorCode` enum 与 errcodes.yaml 保持一致
- 鼎桥兼容层参数名由 `dingqiao-asr-parameters.json` 驱动；阶段性未实现能力必须显式失败，不能静默忽略
- `asr.tools.tests.test_ios_dingqiao_contract` 在无 Xcode 环境下检查参数覆盖和生命周期结构
- 当前 CI 的契约检查不等于完整 Xcode 构建与设备验证

### Server (Linux)
- `proto/asr.proto` 的 `AsrError.code` 字段值域必须 ⊆ errcodes.yaml
- 服务端需按规范维护错误码；当前没有由此 YAML 自动生成并在编译期完整校验的链路

## 治理流程

1. 添加 / 修改 错误码 / manifest 字段：先在本目录提 PR
2. PR 通过后，三端各自跟进 PR；三端 SDK 的同步 PR 必须在本 PR merge 后 14 天内合并
3. 已发布的 manifest_version=1 的 schema 不能变；新版本必须递增 `$id` + 升 `manifest_version`
4. 错误码不能删除；废弃用 `deprecated_at` 标记，三端继续保留常量

## 校验实现示意（不是已接入的 CI 门禁）

```kotlin
@Test fun `errcodes.yaml is in sync with AsrErrorCode constants`() {
    val yaml = readResource("/shared/errcodes.yaml")  // 通过 sourceSets 引入
    val expected = parseErrcodesYaml(yaml).associateBy { it.code }
    val actual = AsrErrorCode::class.java.fields
        .filter { it.type == Int::class.javaPrimitiveType }
        .associate { it.name to it.getInt(null) }
    expected.forEach { (code, info) ->
        val constName = info.name.toScreamingSnake()
        assertEquals(code, actual[constName],
            "AsrErrorCode.$constName should be $code (per errcodes.yaml)")
    }
}
```
