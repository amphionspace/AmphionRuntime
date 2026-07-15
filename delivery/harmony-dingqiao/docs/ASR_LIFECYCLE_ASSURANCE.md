# Harmony ASR 生命周期问题闭环与防回归说明

## 1. 目的与结论

本文汇总历史缺陷记录中的三类问题、根因修复、公共接口契约和发布门禁，作为项目内部的统一验收依据：

1. `vadBegin=1000` 与声纹组合时，真实首句出现 `speakerSimilarity=undefined` 并提前 `isLast=true`。
2. 连续识别过程中，调用方尚未执行 `finish` 就偶发 `isLast=true`。
3. 首次冷加载后，调用方在 `onStart` 内同步写入缓存音频时收到 `1002200010 NOT_LISTENING`。

这些问题已经在状态产生的最内层状态机修复，并分别建立主机单测、Harmony 真机模式和发布检查。验收结论应表述为：

> 已知问题在明确复现条件和约定调用范围内完成闭环，并已建立持续回归门禁。

不得表述为“覆盖所有边界”或“未来绝不复现”。

## 2. 公共生命周期契约

| 场景 | 对外保证 |
| --- | --- |
| `onStart` | 对应 session 已发布且完成会话级配置；回调调用栈内可同步 `writeAudio`、`finish` 或 `cancel` |
| 连续识别 | 显式 `finish` 前不得出现 `isLast=true`，除非命中明确配置的 `vadBegin` 或 `maxAudioDuration` |
| 正常结束 | 每个 session 恰好一次 `isLast=true`，随后恰好一次 `onComplete` |
| endpoint | `isFinal=true` 仅表示一句话结束，不等于整个 session 结束 |
| cancel | cancel 生效后不得新增 final 或 complete；取消前已经产生的 non-last endpoint final 保留 |
| 声纹分数 | 有效语音达到 `TargetSpeakerConfig.minSegSec` 时 final 应携带 `speakerSimilarity`；不足门槛时可省略分数，但不得丢识别结果 |

## 3. 修复后的正常时序

```mermaid
sequenceDiagram
    participant App as 调用方
    participant Adapter as 鼎桥适配层
    participant Core as ASR Core

    App->>Adapter: startListening(sessionId)
    Adapter->>Core: 创建并启动 native session
    Core-->>Adapter: native started
    Adapter->>Adapter: 发布 session 并完成会话级配置
    Adapter-->>App: onStart(sessionId)

    Note over App,Adapter: onStart 进入时 session 已可同步使用

    loop 连续音频
        App->>Adapter: writeAudio(sessionId, PCM)
        Core-->>Adapter: endpoint final
        Adapter-->>App: onResult(isFinal=true, isLast=false)
    end

    App->>Adapter: finish(sessionId)
    Adapter->>Core: flush / finish
    Core-->>Adapter: session final
    Adapter-->>App: onResult(isFinal=true, isLast=true)
    Adapter-->>App: onComplete(sessionId)
```

`onStart` 的实现门禁同时等待 `native started` 和 `session published`。两个事件无论谁先发生，对外都只发送一次 `onStart`。

## 4. cancel 与跨 session 隔离

```mermaid
sequenceDiagram
    participant App as 调用方
    participant SDK as Harmony ASR SDK
    participant Core as ASR Core

    App->>SDK: startListening(oldSession)
    SDK-->>App: onStart(oldSession)
    App->>SDK: writeAudio(oldSession, PCM)
    App->>SDK: cancel(oldSession)
    SDK->>Core: cancel
    SDK->>SDK: 关闭并隔离 oldSession

    Note over App,SDK: cancel 后 oldSession 不再新增 final / complete

    App->>SDK: startListening(newSession)
    SDK-->>App: onStart(newSession)
    App-->>SDK: oldSession 的迟到 write / finish / cancel
    SDK-->>App: 返回旧 session 对应错误，不污染 newSession
```

所有压力用例按 `sessionId` 保存有序回调轨迹。聚合回调数量相等不能替代逐 session 归属检查。

## 5. `vadBegin` 与声纹组合决策

```mermaid
flowchart TD
    A[启动 session 与 vadBegin 计时] --> B{是否确认语音}
    B -->|VAD speech| C[永久解除初始静音计时]
    B -->|ASR 非空 text 或 token| C
    B -->|只有连续未决声学活动| D[允许一次有界确认窗]
    B -->|持续纯静音| E[vadBegin 到期并自动结束]
    D --> F{窗末仍有近期语音证据}
    F -->|是| C
    F -->|否| E
    C --> G[继续正常识别]
    G --> H{有效语音达到 minSegSec}
    H -->|是| I[final 携带 speakerSimilarity]
    H -->|否| J[保留识别结果并省略分数]
    I --> K[等待显式 finish]
    J --> K
```

声学 backstop 不能把固定高能直接当作 speech。它只允许触发一次确认窗，最终仍需近期语音型能量变化、合理过零率或 ASR 非空 text/token 才能解除初始静音计时。

## 6. 历史问题与防复发机制

| 历史症状 | 根因层 | 修复机制 | 永久门禁 |
| --- | --- | --- | --- |
| 首句无分数并提前 last | 初始静音 deadline 与声纹最短有效语音窗口竞争 | 多信号起音确认；一次有界确认窗；旧活动不能直接解除计时 | `test_harmony_initial_silence_tracker`、`voiceprint-vad-begin`、`voiceprint-vad-begin-idle` |
| 连续识别提前 last | 用全局 finish 状态推断较早异步 final 的结束属性 | 只依据当前结果携带的 `isLast` 完成 session | `test_harmony_rejected_final_lifecycle`、`burst`、`paced`、`reentrant`、`user-sequence` |
| 冷加载首次写入失败 | native started 同步回调早于适配层发布 session | started/published 双条件门禁，发布后才发送一次 `onStart` | `test_harmony_session_start_gate`、`start-write`、`start-write-reload` |

## 7. 2026-07-16 验证快照

验证对象为同一 commit、同一中英 `ZH_EN` HAP 和一台 HarmonyOS 6.1 arm64 真机。测试数据为 16 kHz、16-bit、单声道 WAV，按 30/60/120 秒和长音频分层选择。生命周期结果不以文本正确率判定 PASS。

| 模式 | cycle |
| --- | ---: |
| `burst` / `paced` | 3 / 3 |
| `vad-begin` / `vad-begin-silence` | 20 / 50 |
| `voiceprint` | 20 |
| `voiceprint-vad-begin` / `voiceprint-vad-begin-idle` | 40 / 40 |
| `max-duration` | 50 |
| `cancel` / `cancel-full` | 100 / 50 |
| `recreate` / `reconfigure` | 20 / 50 |
| `edge` / `numeric-edge` | 100 / 100 |
| `reentrant` | 100 |
| `start-cancel` / `start-write` / `start-write-reload` | 100 / 100 / 20 |
| `user-sequence` | 100 + 300 |

汇总结果：

- 1366/1366 cycle PASS，涉及 2266 次 session 启动。
- 0 个失败 cycle，0 个意外回调，0 次显式 `finish` 前提前 last。
- 所有正常结束轨迹满足一次 `final-last` 后一次 complete；cancel 轨迹无 last/complete。
- `voiceprint-vad-begin` 的 burst/paced、直接起音/前置静音四种组合各 10 轮；40/40 首个非空 final 带分数，40/40 在 `finish` 前 last 数为 0。
- hilog 未命中 `SIGSEGV`、`SIGABRT`、native crash、double free 或 heap corruption 等强崩溃特征。

`0.2.5` 最终候选构建完成了改动相关的定向复验：`start-write-reload` 20 轮、
`user-sequence` 300 轮、`voiceprint-vad-begin` 40 轮，共 360/360 cycle、960 次
session 启动通过。对应内部 run ID 为
`20260716-042448-start-write-reload-8b9b1a46`、
`20260716-042531-user-sequence-49e6ce1b` 和
`20260716-043652-voiceprint-vad-begin-97da11eb`。

另保留一次混合语种语料的失败 artifact
`20260716-043347-voiceprint-vad-begin-64c27f90`：14/14 失败均来自英语源被固定
`zh-CN` 模型切成短 endpoint，首个 endpoint 的有效语音不足声纹最短时长，按接口契约
可省略分数；同轮中文源 26/26 通过且 40 轮 finish 前 last 均为 0。该次结果归类为
测试语料不满足模式前置条件，不计入 SDK PASS，也未通过放宽断言处理。

关键内部 artifact：

| 证明目标 | run ID |
| --- | --- |
| 实时喂入与长时间资源观察 | `20260716-023241-paced-ba9a570a` |
| 声纹与 `vadBegin=1000` 四组合 | `20260716-024317-voiceprint-vad-begin-02f7fbe0` |
| 冷加载 `onStart` 内同步写入 | `20260716-032043-start-write-reload-234a201f` |
| 300 轮真实调用顺序 | `20260716-032413-user-sequence-63937379` |

每个 run 目录必须保留 `report.json`、`result.txt`、`memory.csv`、`hilog.txt`、`inventory.json` 和输入 payload 映射。

## 8. 资源稳定性

| 场景 | 观察时间 | RSS 净变化 | RSS 斜率 | 线程变化 |
| --- | ---: | ---: | ---: | ---: |
| paced | 313.9 秒 | +6.24 MiB | +1.58 MiB/min | 0 |
| cancel-full | 533.0 秒 | +0.52 MiB | +0.39 MiB/min | 0 |
| reconfigure | 541.9 秒 | +1.26 MiB | +0.30 MiB/min | 0 |
| user-sequence 300 | 437.3 秒 | +5.55 MiB | +1.40 MiB/min | 0 |

短场景的瞬时 RSS 变化可能包含模型逐步驻留，不能单独判定泄漏。资源结论以超过 60 秒的观察和 `shutdown -> unloadModel -> createEngine` 后的可回落性为准。

## 9. 发布与交付要求

1. 合入前运行状态机单测、Android 同名生命周期单测、Harmony 编译和同一构建产物的真机矩阵。
2. 正式交付至少运行 `voiceprint-vad-begin`、`voiceprint-vad-begin-idle`、`reentrant`、`start-write`、`start-write-reload` 和 `user-sequence`。
3. 客户材料使用 `docs/customer/ASR_LIFECYCLE_ASSURANCE_20260716.md` 和对应 JSON 摘要，不得复制本文件的内部 artifact ID。
4. 客户包组装时必须通过 `check_customer_delivery_redaction.py`，并由 `BUILD_PROVENANCE.json` 与 `checksum.txt` 绑定实际交付版本。

## 10. 未覆盖边界

当前门禁不替代以下独立验证：

- ASR WER/CER 和声纹目标/非目标相似度精度评测。
- 物理断连、系统强杀、麦克风权限动态撤销、音频路由切换和系统级极端内存压力。
- 其他硬件型号、系统补丁版本及宿主调度器差异。

这些边界应作为外部故障与兼容性矩阵单独报告，不能混入生命周期 PASS 结论。
