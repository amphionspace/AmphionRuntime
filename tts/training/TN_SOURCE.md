# TN 源码来源

TTS 的文本归一化模块已从私有 submodule 转为 AmphionRuntime 直接跟踪的普通目录。
协作者只需本仓库权限即可取得这部分源码。

| 项目 | 记录 |
| --- | --- |
| 原仓库 | `hhk1994/Transsion_Multilingual_Text_Normalization_for_TTS` |
| 原提交 | `9cf6411c919c203351724a05fbdcc5ace5346242` |
| 本仓库目录 | `tts/training/dingqiao_lits/Dingqiao_Multilingual_Text_Normalization_for_TTS/` |
| 迁入范围 | 原提交的全部 49 个已跟踪文件，约 24.6 MiB；包括源码、规则、测试、文档及原有 MorphoDiTa `.tagger` 模型 |

迁入时保留文件内容和可执行位，不导入原仓库的 Git 历史或本机构建缓存。
源码路径保持不变，Android、HarmonyOS 和训练工具继续使用该目录。
后续修改直接通过本仓库的提交与 PR 管理。

第三方来源和许可声明保留在原文件中：`third_party/nlohmann/json.hpp` 标注 MIT，
`original/morphodita/src_lib_only/` 保留 MorphoDiTa 的 MPL-2.0 声明。
本次迁入不重新声明这些文件的许可。

模型包、checkpoint 和训练数据仍按 [资产同步说明](../../tools/assets/README.md) 管理。
本次只解除 TN 私有仓库的访问依赖；完整 SDK 构建仍需准备对应平台工具链和构建资产。

## 迁入验证

- 全部 49 个文件在父仓库中以普通文件跟踪，Git blob 哈希和可执行位与原提交一致。
- 从 Git 暂存内容导出独立副本，无需访问原私有仓库；中英文 TN 编译成功，
  原有输入中的英文 13 行、中文 12 行均完成冒烟运行。这不代表发音精度验收。
- 仓库结构、可观测性材料检查及修改脚本的语法检查通过。
- 原文件的 CRLF 和尾随空格原样保留，完整 `git diff --check` 会报告上游已有格式问题；
  本次编写的迁移说明和脚本改动通过格式检查。未修改检查规则。
- 未执行 Android/HarmonyOS 完整 SDK 构建或真机验收。

## 源码仓库依赖检查（2026-09-15）

检查范围包括本仓库的 Git 子模块、源码获取脚本、CI actions、Python 依赖清单及
Gradle/ohpm/native 依赖声明。现有源码获取入口未发现其他私有仓库依赖：

- `.gitmodules` 和 Git 索引只保留公开的 `k2-fsa/sherpa-onnx`，该固定提交没有嵌套子模块。
- TTS 构建脚本使用的 `unicode-org/icu` 和可选 MorphoDiTa 重建来源 `ufal/morphodita`
  均支持匿名访问；原 TN 私有仓库名称仅作为本页的来源记录保留。
- ASR 源码下载和 CI actions 涉及的仓库同样通过匿名 GitHub API 验证，合计 20 个公开仓库。
- 未发现依赖清单使用其他私有 Git URL；模型和训练资产仍通过既有资产同步流程单独提供。

`tools/test_check_repository_layout.py` 已加入检查：只允许当前公开子模块配置，并要求
TN 编译输入、规则、测试输入及文档由父仓库直接跟踪。该测试由现有 Repository Layout CI 执行。
