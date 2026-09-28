# 双端 ASR 待验收候选（2026-09-28）

状态：PREPARING / NOT ACCEPTED。用户已确认先制作双端候选包，角色问题保留为正式发布阻断。不得分发或登记为已发布。

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
