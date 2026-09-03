# 股票代码逐位读法修复 — 2026-09-03

本轮股票代码门禁通过；**完整发音对照仍未通过**。675 条真机结果仅 `v3-parity-known-regression-001` 的 token 改变，其余 674 条逐 token 一致，没有新增不匹配。目标句的 `600519` 已由“六十万零五百一十九”改成“六零零五一九”，但句内“百分之一点二三”的 `yi4/yi1` 历史标注差异仍在，总计仍是 380 条匹配、295 条差异、0 条执行错误。

## 根因与范围

已有股票数字保护只识别“股票 600519”，漏掉“股票代码 600519”。第一次错误发生在原生 TN 前的输入准备阶段；下游按普通数值转换后已经无法恢复代码语义。无原生 TN 的前端入口也有同样的匹配遗漏。

运行代码仅修改这两处已有正则，允许股票后带“代码”；保留原有六位长度限制和后续数字边界。模型、golden、授权、版本、并发、生命周期及其他数字规则不变。未扩大到所有“代码”、标点分隔代码、股票数量或其他金融格式。

## 验证

- 本机最小红灯：原生 TN 前仍为 `股票代码 600519`，没有逐位保护；相邻数值用例通过。局部修复后两个针对性单测通过。
- 默认 SDK 单测 106 项：103 PASS、3 项原有 SKIP、0 失败。后续只补两个控制场景的 token 边界断言，针对性单测再次通过；运行代码未变，不重复其余已通过用例。
- vivo V2505A / Android 16：最终 SDK 测试 APK 的 7 个场景全部通过，原生 TN 确实执行；原始/已规范化入口分别比较完整 token。覆盖空格、前导零、原有股票简称、普通数值、七位边界及完整问题句。
- 独立宿主仅引用 Release AAR：授权 `LICENSED`；1 start → 25 个连续有序、非空 PCM 回调 → 1 complete，无 error/stop，shutdown 返回。24000 Hz、16-bit、mono，共 1,325,568 字节；输入保留负温度、日期和 URL。没有保存 PCM。
- 同机、同模型、同 675 条输入、同 `useTn=true` 前后对照。严格报告检查器仍返回 exit 1；不豁免未处理差异。
- 三个已安装 APK 与本机构建哈希一致；两个测试包各 25 个模型/前端文件与既有校验清单一致。

最终测试提交 `c1adf36b75b10859b17a80c47a7cf1812727a908`；根因修复提交 `5a7dcffb` 后 Release AAR 未变。后续提交只更正测试预期，最终构建重新确认同一源码与产物。运行保持应用前台，不证明后台冻结恢复、主观听感或长稳压。身份与证据哈希见 [report.json](report.json) 和 [build-identity.json](build-identity.json)。

## 两次非 canonical 测试预期错误

`non-canonical/` 保留完整失败记录，不作为最终验收。4 个股票代码场景两轮都通过，停止点均是新增普通数值控制用例：

1. 第一次误把原生 TN 的数值读法和绕过 TN 的逐位读法视为相同；错误在 prepared 入口的测试预期。
2. 第二次逐位汉字参考仍忽略了既有分块边界。诊断数组只差前缀与数字之间的 `_`；原有数字块不添加这个前导标记，连续汉字参考会添加。检查内部数字分支后，先在本机验证“前缀块 + 数字块”的精确参考，再上机通过。没有过滤实际 token、放宽断言或修改 SDK 边界行为。

## 复现

按[批测说明](../../docs/BATCH_TESTING.md)部署 APK、授权与外置模型，前台运行 `StockCodeDeviceTest`、`AarFrontendContractDeviceTest`，再运行原有 `PronunciationRound15FrontendDeviceTest`。

```bash
python3 tts/tools/android/check_pronunciation_report.py \
  --summary tts/android/reports/stock-code-20260903/corpus-summary.json \
  --expected-total 675
```

预期 FAIL。[corpus-diff.json](corpus-diff.json) 记录唯一变化行和前后检查；完整结果、原始 summary、SDK/前端报告与构建/测试日志均保留。后续另行处理音调标注、多音字及技术路径，不在本补丁扩大范围。
