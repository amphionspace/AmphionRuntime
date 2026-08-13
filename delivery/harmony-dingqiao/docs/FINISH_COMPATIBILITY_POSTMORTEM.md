# Harmony 0.3.0 finish 兼容性回归复盘

## 结论

0.3.0 将 `writeAudio` 和 `finish` 改为异步 FIFO 后，单层队列顺序成立，但两条客户真实调用时序
没有被当作发布契约：

1. VAD 宿主在 `SPEECH_END` 回调栈内同步调用 `finish(sessionId)`。异步队列直到当前
   endpoint final 已透出后才处理 finish，因此先返回带文本 non-last，再返回空 last。
2. PTT 宿主在 `finish()` 返回后观察到 `isBusy()==true`，立即调用 `shutdown()`。旧释放路径
   抢在异步 finish 处理前销毁会话，导致 final 和 complete 丢失。

修复保持异步 PCM FIFO，仅补齐两个结束状态边界：回调内 finish 意图可被当前 endpoint
观测；已接受 finish 时，shutdown 延后到 last/complete 收敛后释放资源。

## 为什么会漏掉

- 旧测试分别覆盖“PCM 在 finish 前入队”、“最终出现 complete”和“结果中有过文本”，
  没有组合成客户的完整时序。
- `callback-api-reentrant` 只要有 final 且有 last 就可通过，没有要求 `SPEECH_END` 的唯一
  last 本身带文本。
- 没有模拟已上线宿主的 `finish -> isBusy -> shutdown` 补偿逻辑。
- CI 显式列出少数测试模块，新增的 Harmony 契约测试不会自动进入门禁。

## 永久门禁

### 主机 CI

`.github/workflows/android.yml` 通过 `test_harmony_*.py` 自动发现 Harmony 主机契约测试，不再维护
容易遗漏的模块白名单。本问题由以下用例直接锁定：

- `test_harmony_async_audio_dispatch.py`：回调内 finish 意图必须作用于当前 endpoint。
- `test_harmony_finish_shutdown_gate.py`：shutdown 不得抢断已接受的 finish。
- `test_run_finish_compat_release_gate.py`：校验真机报告中的非空 last、唯一 complete、回调顺序、
  同设备与同构建身份。

### USB 发布门禁

在干净工作区、当前发布 commit 上执行：

```bash
python3 delivery/harmony-dingqiao/delivery/run_finish_compat_release_gate.py \
  --data-dir "$HOME/Downloads/testdata"
```

默认只构建并安装一份 ZH_EN HAP，然后在同一设备、同一 HAP/HAR 上依次执行：

- `callback-api-reentrant` 3 轮，必须包含一条 `SPEECH_END -> finish` 且 last 文本非空；
- `finish-shutdown` 10 轮，每轮 finish 前 last 数为 0，结束后恰好一次 last 和一次 complete。

单独执行时，统一入口不提供跳过安装的选项：第一个模式必须构建、签名并安装当前 commit
的 HAP，第二个模式才复用该次安装。完整自动 AGC 发布入口可传入 `--reuse-verified-build`，但必须同时
提供并验证当前 build identity；该路径只跳过重复构建，仍会安装 HAP、执行 UI smoke，再运行两个模式。
这避免本地 build identity 与设备旧 HAP 被误组合为发布证据。

## 证据与停止条件

结果保存在 `delivery/harmony-dingqiao/build/release-gates/finish-compat/<gate-id>/`：

- 根目录 `report.json`：总体 PASS/FAIL、source commit、设备和构建身份、两个子报告路径；
- `runs/<run-id>/`：原始 `report.json`、`result.txt`、`memory.csv`、`hilog.txt`、设备信息和输入映射。

任一契约失败、两模式设备/构建身份不一致、工作区不干净或构建 commit 不匹配时，
门禁必须失败。短轮次内存结论可为 `INCONCLUSIVE`；该门禁验证生命周期，不替代长时资源压测或
文本精度评测。

## 0.3.1 交付复核补充

0.3.1 在提交 `9eaf3b8` 和同一构建 fingerprint 上完成 Android Debug/Release 168 个测试，
以及 24 个适用的 Harmony 真机模式。VAD 回调内 finish 3/3、PTT finish 后立即 shutdown
10/10 均通过。完整脱敏证据保存在
`delivery/harmony-dingqiao/evidence/release-gate/20260809-9eaf3b8-0.3.1/`，并由发布账本记录
根 `report.json` 的 SHA-256。

复核还暴露出旧 SDK-only 打包流程只检查 Git 输入是否脏，却没有验证四个已构建 HAR 是否来自
当前源码。这样旧 HAR 理论上可以被重新组装进新 ZIP。后续打包必须先通过
`harmony_build_identity.py --verify`，`ZH_EN` 也不得跳过警务增强 HAR；provenance v2 记录
source fingerprint 与四个 component HAR 的哈希，并在交付校验时与外部 build identity 逐字段
比对。

历史 0.3.1 的 ZIP、最终 HAR、HAP、输入 fingerprint 和真机报告可以证明已交付制品及运行结果，
但当时的 build identity 未记录 `amphion_police.har`，因此**不能追溯证明四个 component HAR
全部来自该 source commit**。归档报告必须保留这项历史限制，不得把它表述为已补足的四 HAR
审计链；已经交付的 ZIP 也不改写。0.3.1 之后由上述 provenance v2 + build identity 门禁封住该路径。
