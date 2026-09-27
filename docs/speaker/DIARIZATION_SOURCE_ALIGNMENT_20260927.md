# 标点与 ITN 后处理的原句角色对齐

本轮修复 SDK 的证据边界，不修改模型、聚类、窗口、hop、预览、定稿周期或 timeout。此前时间轴与完整 session 证据修复继续保留。声学身份与 overlap 的既有失败独立跟踪，本补丁不宣称角色分离整体精度通过。

## 第一个错误状态

原始录音长 47.82 秒；UNKNOWN 是“你好。”3 个字符，不是 3 秒。原生 u6 为“可以听见我说话吗？你好。”，末两字 token 在 20.660/20.860 秒，附近声学区间止于 20.65221875 秒。

生产 `sentenceUtterances` 先 `punctuationUnits`，再按展示分句进行角色关联及 UNKNOWN 补全。这一步错误地把问号当成证据边界。固定 tokens、时间、声学区间，仅去掉问号就改变归属的回归在修改前稳定失败。

修复后先在原始 utterance 内计算直接关联与有限推断，再把已计算结果按精确源偏移投影到展示分句。“你好”符合既有 2500 ms 同原句规则，标记 `speakerInferred=true`、`confidence=0`；原始 `speakerTurns` 不延长。展示合并或 UNKNOWN 汇总也不能丢失推断标记。

另外移除无覆盖 token 直接继承整句唯一角色的路径：缺少声学覆盖先保持 UNKNOWN，只能由已有有限规则补全。Android 原本没有按标点先分句，但同步移除这一路径并保留推断标记。

## 精确映射和不确定性

BBPE 到原文的逐字节核验与原生时间映射保留；插入标点、空白以及标点替换词间空格使用已有精确映射。原生 token 的关联及推断不依赖展示文字。

当前 Wetext ITN 与标点接口只返回字符串，没有转换来源区间。移除以最小编辑距离猜测词语改写后分句边界的路径。数字合并、展开、替换、重复删除等无法精确追溯时，转换后的整句保持 UNKNOWN、confidence=0，并保留 rawText 与 speakerTurns；不均匀分配时间，不复制邻句身份，不覆盖多数角色。

同一原句中的展示段可以因分句方式不同而汇总为不同粒度；这不重新运行原始 token 的归属。混合角色、真实短插话及 overlap 保留声学区间，不能用 UNKNOWN 减少证明身份正确。

## 验证

- Harmony 87 项相关回归中 86 项首次通过；剩余定稿测试夹具缺少必需 rawText，补齐原生输入后单项通过。公共 SDK 与真实 Demo 展示方法的附加回归通过，显示“说话人 1 · 含推断补全”。
- Android SDK / dingqiao Debug 与 Release 全部单测通过。新增标点同输入及无映射 ITN 测试修改前均失败，修改后通过。
- 相邻场景：真实换人、短插话、同角色未知空隙、不同角色间未知、2500/2501 ms、零时长尾字、已知/未知副角色、无来源 overlap、跨原始 utterance、数字合并/展开/替换、重复文本映射不明、冻结和回调生命周期。
- 复用同设备 600 秒原始事件顺序及真实 segmentation/embedding，按设备聚类返回时序回放生产 Session/Clock/Identity/Transcript。62 次聚类调用、6 次定稿；每批 speakerTurns 完全相同，5436 字符及 SHA-256 不变，冻结、文本守恒和唯一结束断言通过。没有重新做模型长跑，桌面回放耗时不作为手机性能证据。
- 长样本展示 UNKNOWN 从 113 增为 426 字符。原因包括无覆盖 token 不再被无标记继承，以及 u32 原生尾部 UH 被文字后处理删除、无法精确追溯，整句保留未知。含推断标记的展示段覆盖 1580 字符，这不是新增声学已知字符数。声学误认仍为原有 1.70 秒，参考 overlap 召回仍为 0%，不是本次对齐引入，也没有被修复。

本地证据：`~/.cache/amphion-runtime/diagnostics/single-speaker-unknown-20260927/punctuation-alignment/`，包含 protocol.json、u6-red.log、harmony-regressions.log、cadence-fixture-green.log、presentation-invariants.log、caller-result.log、android-red.log、android-green.log、replay-long.log、replay-120000-recorded.json、long-differential.json。失败现场保留，不将其覆盖为通过。

真机复验与当前 HEAD 合入门禁尚待运行，不能使用旧构建身份替代本补丁验收。
