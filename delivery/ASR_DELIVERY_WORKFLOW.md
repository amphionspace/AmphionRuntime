# 双端 ASR 交付流程

本文是 Android/Harmony 鼎桥交付的顺序入口。平台文档只定义构建、包结构和平台检查；归档文档只定义对象存储操作。不要分别维护多份完整发布流程。

## 1. 确定范围和实际基线

- 从交付台账及实际附件确认上一版本的源码、外层 ZIP 哈希和平台版本，不能只取上一个 tag 或同名版本。客户实际收到的包与主线台账不一致时明确记录差异，不把已交付内容再次写为新增。
- 对照本次构建提交逐项检查已合入 PR 和非 PR 提交，填写[调用方变化核对表](CALLER_CHANGE_CHECKLIST.md)。产品变化与评测工具、归档、文档变更分开。
- 双端默认包含 SDK、Diagnostics SDK、签名 Demo、独立 Demo 源码和文档，外置校验及最终验收报告。没有统一包体积上限；特定客户限制必须单独记录。

## 2. 冻结和构建

冻结代码、版本、模型、授权、签名和组包规则。Release、Diagnostics、Demo、完整包和对应真机证据绑定同一构建提交。检查嵌套包版本与版本测试，不只改顶层版本号。

仅使用以下暂存目录：

```text
~/.cache/amphion-runtime/delivery-staging/asr/<platform>/<version>/<source-commit>/
  packages/      # 完整包、内层包及外置校验
  acceptance/    # 验收报告和实际交付说明
  scratch/       # 解包、独立构建及归档回下载
```

| 平台 | 构建与包结构入口 |
| --- | --- |
| Harmony | [默认完整交付](harmony-dingqiao/docs/DEFAULT_DELIVERY.md)；[构建操作](harmony-dingqiao/docs/DELIVERY.md) |
| Android | [鼎桥完整交付](android-dingqiao/DEFAULT_DELIVERY.md)；核心 AAR 操作另见 [Android 指南](../asr/android/docs/DELIVERY.md) |

脚本必须显式传入输出目录。改组包脚本先用小型输入验证，不反复生成大包。进入最终组包阶段后不加入无关修复。

## 3. 验证冻结产物

从最终 ZIP 解包安装 Demo，并用包内源码和公开 SDK 独立构建。按[SDK 验证矩阵](../docs/engineering/ASR_VALIDATION.md)运行约定门禁，分别记录接口契约、精度、用户体验和离线网络观测结论。

复用同提交、设备和二进制的有效证据。纯文档、外置说明及不影响二进制的组包调整不重跑真机；运行内容变化时先说明失效原因和最小重跑范围。保留失败现场、未覆盖项及 INCONCLUSIVE，不把构建或归档成功写成产品通过。

外置最终报告绑定外层 ZIP 哈希；不要将报告重新塞回已验收 ZIP。耗时验证开始前说明目标、预计时间、产物、失效条件和停止条件。

## 4. 记录状态并起草交付说明

- **未发布包**：在 `delivery/candidate-reports/` 保存外层身份和真实验收状态，明确 `published: false`。允许按用户明确授权归档，不获得正式发布资格。
- **正式发布**：使用[发布台账工具](ASR_SDK_RELEASE_TRACKING.md)登记子包及证据，再在 `delivery/published-deliveries/` 保存完整外层包的发布记录与最终报告。正式记录须合入主线，不能借用子包或其他构建的身份。
- 邮件根据核对表和[双端邮件模板](harmony-dingqiao/docs/customer/DELIVERY_EMAIL_TEMPLATE.md)填写，先写实际改进和对方要做的事，再给有明确样本/平台/基线的指标。邮件草稿不自动发送。

## 5. 归档、清理和 PR 收尾

使用[归档规范与命令](PUBLISHED_ARTIFACT_ARCHIVE.md)保存原包、校验、报告和实际交付说明，完整回下载验证每个对象及全量远端索引。保留历史索引条目，不覆盖旧批次。

只有用户已授权移除，且没有使用中的构建或验收任务时，才清理已验证本地包。归档脚本仅删除列明的原包和附件；展开副本须另行逐文件核对，原始录音、源码和独立诊断证据不在清理范围内。

提交归档索引、状态记录和清理报告。当前 PR HEAD 的适用 CI 通过，全部 review threads 已检查且有效问题处理完毕后，按用户授权合入。归档 PR 不替代正式发布批准。
