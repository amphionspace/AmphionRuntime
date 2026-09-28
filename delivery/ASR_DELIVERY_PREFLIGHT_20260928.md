# 双端 ASR 待验收候选（2026-09-28）

状态：NOT ACCEPTED。用户已确认先制作双端完整候选包，角色问题保留为正式发布阻断。不得分发或登记为已发布。

- 分支：`chore/asr-delivery-20260928`。PR #235、#236 已合入，当前基于 `7f41e794675b92baae2a0c0e74a8c2a56744ef0c`。
- 候选版本：Harmony 0.3.18、Android 0.3.9；上一发布基线为 2026-09-18 的 Harmony 0.3.17 / Android 0.3.8，源码 `5f622c6d390e2088570c5f9bbdc212f2f702f3a4`。
- 本次只调整交付版本、说明和组包输入；不改变识别、角色算法、生命周期或验收阈值。
- 用户已接受 PR #235 所记录 RSS 增长，旧 FAIL 仍保留，不再作为本次候选制作阻断；不代表长会议内存 PASS。
- 角色漏人、误认、客户短段 UNKNOWN、完整实录与最终展示仍未全部解决。Android 整窗 clustering 与 Harmony run 路径不能宣称精度等价。
- 已有 15 项公共契约测试通过对应旧主线 e107e171，不能冒充当前最终候选结果。PR #235 的同产物生命周期证据按原身份复用，不能改写成新包验收。

## 待完成

1. 校验模型、native、授权和签名输入，冻结新提交。
2. 双端生成 Release、Diagnostics、签名 Demo、Demo 源码及说明。所有候选保持 NOT ACCEPTED；Harmony 保留默认五目录，不伪造正式组包门禁所需 PASS 报告。
3. 保存最外层 ZIP SHA-256、构建身份和外置未验收报告。没有最终包真机、断网观测和角色精度证据时不得发布。

合入验收及资源决定见 [PR #235 验收](../docs/speaker/DIARIZATION_PR235_MERGE_ACCEPTANCE_20260928.md)。当前未向客户发送消息或上传正式发布物。

## 已定位的组包缺陷

Android Release AAR 首次已构建成功，但旧 AAR/APK 校验器仍强制要求运行时不再调用的 campplus.onnx，导致候选组包失败。当前运行时使用 ensureCommunityInstalled，构建清单已包含 encoder、pool、feature 与 PLDA。校验同步为这四项 Community 输入，并保护每项缺失或截断时必须拒绝；保留 eres2net、segmentation、LAC 检查。这是组包契约修复，不是角色身份精度修复。旧尝试日志留在 22e1dc72 对应暂存目录，新候选重新绑定修复后的提交。

## 最终候选决定

- 二进制冻结提交：`74e94a27cc90f033d3f8e5aa18ac0b3b9518e352`。后续仅补交付文档、包校验规则和候选报告，不改变 SDK/HAP/HAR。
- 用户明确本次没有体积大小门禁，已移除旧 320 MiB 限制；23 项包校验测试通过，包括超过原上限的有效 ZIP。旧大小失败日志保留为历史规则结果，不再作为本次阻断。
- 完整候选包含 SDK、Diagnostics SDK、已签名 Demo、独立 Demo 源码和文档。Harmony 外层保留默认五目录；Android Release Demo 位于 release-sdk 内层包，Diagnostics Demo 单列于外层。
- Harmony 普通 SDK 使用仓库 debug 载体、诊断关闭；Diagnostics 为独立构建模式。Android Demo 使用本机 Debug 签名证书，仅用于候选。均未登记发布或向客户发送。
- Harmony 模型软链接已实体化，内容哈希不变。普通与 Diagnostics HAP 均完成签名、模型/构建身份及 Mate80 安装加载检查；普通公共 HAR 的独立宿主构建通过。
- 最终 ZIP 的 SDK 生命周期、断网网络观测、角色精度与最终呈现尚未完成验收；不能将构建或模型就绪等同于这些项目通过。已知漏人、误认、短段 UNKNOWN 继续阻断正式发布。
- 精确产物大小与 SHA-256 记录于 `delivery/candidate-reports/asr-20260928/`，仅为候选记录，不是发布台账。
