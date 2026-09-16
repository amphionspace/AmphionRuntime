# 单人录音结束后仍显示两个角色

## 定位与修复范围

用户确认只有一人朗读。已保存手机 09:58:35–09:59:22 会话的完整 47.26 秒 SDK 输入、元数据和原始页面布局；无截断、录音溢出或削波。录音 SHA-256：`d3c1a2c50c3f7d269a3743aae8f2031a5a98da801c73bcf4434efbc8da7dd3f2`。原始音频、文字和 embedding 只留在私有诊断目录，不提交。

页面在录音结束后仍显示说话人 1、2。同一输入的当前生产链路最终聚为一人；已安装版本的真机公共 API 核对同样返回一人，8 条最终 utterance 的 speakerIndex 均为 0，全部 speakerTurn 也为 0。

第一个显示错误发生在结果列表更新：`FinalSegment` 是普通对象，`ForEach` 原来仅用行号和文字作为 key。最终角色变了而文字不变时，旧行被复用，保留中途角色标签。回归用例在修改前稳定复现：数据已经是 `[0, 0, -1]`，显示仍为“说话人 1、说话人 2、空”；修改后显示与最终数据一致。

- 要改变：文字不变时，角色修正和最终 UNKNOWN 标签也能刷新。
- 保持：SDK 角色编号、最多 4 人、已提交窗口不可回写、真实第二人仍独立显示。
- 本次不处理：多人会议的声学分割、声纹取样、聚类、阈值和内存预算。

修复只让列表 key 包含完整行状态，没有将所有角色强制设为一人，也没有修改 SDK。

## 原始证据与验证

私有目录：`~/.cache/amphion-runtime/diagnostics/single-speaker-phone-20260916-t7u17bab`。

- 原会话现场：`last_sdk_input.wav/json`、`app-pid-hilog.txt`、`phone-layout.json`。
- 同输入宿主机状态：`current-state.json`，19 个推理窗口，最终 1 个聚类。10 秒窗口曾产生两个临时角色，因此页面留下的旧值有明确来源。
- 真机公共结果：`usb-before/20260916-100805-diarization-windows-faca2cfa/report.json`，SHA-256 `b570d506d4fdd2f22127341aeb4a8efbbd03d92f81b4e0aa1cfd31ce560ee850`。运行的是已有 `b38ed120` 构建，SDK 未改动。压力载体使用长语音配置，原操作使用 PTT，因此本核对仅证明相同短录音的分人最终结果，不声称 ASR 参数完全相同。
- 该真机核对 start=1、finish 前 last=0、last=1 后 complete=1、error=0、native stream=0、分人无降级。原始报告保留 FAIL：47 秒未覆盖该模式要求的 120 秒中途提交窗口；不通过放宽断言改成整体 PASS。内存检查 PASS，短时趋势 INCONCLUSIVE。
- 显示回归及相邻 Demo 检查 11 项通过：文字不变的角色修正、UNKNOWN 最终标签、已发布结果拒绝迟到更新、真实第二人保留，以及既有配置和布局检查。

本次显示缺陷和 SDK 身份精度分开记录。[带标注的 2–4 人会议验收](COS_OBS_MEETING_ACCEPTANCE_20260915.md)仍为 FAIL，不因本次单人最终结果正确而关闭。

构建与安装结果将在完成后追加；本记录不是完整发布门禁通过声明。
