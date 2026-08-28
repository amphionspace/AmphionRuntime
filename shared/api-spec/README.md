## 跨端 API 协议（Single Source of Truth）

本目录定义所有 ASR 端 / 服务端必须共用的不变量，三端 SDK 必须按这里给出的 schema / 错误码 / 协议实现。

| 文件 | 说明 |
| --- | --- |
| manifest.schema.json | 模型 manifest.json 的 JSON Schema (draft-2020-12)；三端在 CI 中校验 |
| errcodes.yaml | 错误码表；三端 AsrErrorCode / proto AsrError.code 都派生自此 |
| dingqiao-asr-parameters.json | 鼎桥 Android/HarmonyOS 客户可无平台分支使用的参数契约；`platform_extensions` 不属于通用配置 |
| README.md | 本文件 |

## 在三端的具体落地

### Android
- `AsrError.kt` 中的 `AsrErrorCode` 常量与本目录 errcodes.yaml 保持一致
- CI（[ci/android.yml](../../ci/android.yml)）中跑单测校验

### iOS
- `AsrError.swift` 中的 `AsrErrorCode` enum 与 errcodes.yaml 保持一致
- xcodebuild test 阶段校验

### Server (Linux)
- `proto/asr.proto` 的 `AsrError.code` 字段值域必须 ⊆ errcodes.yaml
- C++ 服务端启动时把 errcodes.yaml 内嵌为常量（编译期检查）

## 治理流程

1. 添加 / 修改 错误码 / manifest 字段：先在本目录提 PR
2. PR 通过后，三端各自跟进 PR；三端 SDK 的同步 PR 必须在本 PR merge 后 14 天内合并
3. 已发布的 manifest_version=1 的 schema 不能变；新版本必须递增 `$id` + 升 `manifest_version`
4. 错误码不能删除；废弃用 `deprecated_at` 标记，三端继续保留常量

## CI 校验示例（Android Kotlin）

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
