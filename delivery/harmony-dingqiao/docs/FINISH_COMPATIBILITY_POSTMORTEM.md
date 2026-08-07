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

统一发布入口不提供跳过构建/安装的选项：第一个模式必须构建、签名并安装当前 commit
的 HAP，第二个模式才复用该次安装。这避免本地 build identity 与设备旧 HAP 被误组合为发布证据。

## 证据与停止条件

结果保存在 `delivery/harmony-dingqiao/build/release-gates/finish-compat/<gate-id>/`：

- 根目录 `report.json`：总体 PASS/FAIL、source commit、设备和构建身份、两个子报告路径；
- `runs/<run-id>/`：原始 `report.json`、`result.txt`、`memory.csv`、`hilog.txt`、设备信息和输入映射。

任一契约失败、两模式设备/构建身份不一致、工作区不干净或构建 commit 不匹配时，
门禁必须失败。短轮次内存结论可为 `INCONCLUSIVE`；该门禁验证生命周期，不替代长时资源压测或
文本精度评测。
