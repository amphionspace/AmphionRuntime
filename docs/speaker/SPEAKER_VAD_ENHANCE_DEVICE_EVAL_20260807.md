# 【真机评测】Speaker VAD Enhance 真实表现（2026-08-07）

## 1. 结论

`enableTargetSpeakerEnhancement` 在 Mate 80 上已经具备可用的实时处理能力和稳定的 SDK 生命周期，
但它不是“开启后全面优于普通 ASR”的通用增强：

- 对固定客户重叠用例 C1/C2/C3，12 个连续 session 的最终文本逐例、逐轮稳定满足“包含上海、
  不包含你好”，回调和资源释放全部通过。
- 对新增的 12 个目标人在场样例，增强让 2 条明显改善、3 条基本不变，也让多条发生丢字或替换；
  其中 10、11 两条丢失大段内容。该组没有人工逐字标注，所以这里只报告与普通 ASR 及历史稳定
  输出的差异，不把它包装成准确率。
- 目标人不在、输入为 12 条其他人单独讲话时，增强最终文本 12/12 为空；但输入为其他人的多人重叠
  或交通噪声音频时，3/12 错误产生正式文本。三个失败样例各重复两次后 6/6 完全复现。
- 把后置 Speaker VAD 门槛从默认 0.35 提高到 0.45、0.50、0.60，只能把三个稳定误放行减少为
  一个，不能消除。剩余样例会产生一个没有 `speakerSimilarity` 的短 final，因此单纯调阈值不是修复。
- 普通 ASR 与增强的 12 条配对测试中，首个非空临时文本额外耗时中位数为 194 ms、平均 299 ms、
  最差 838 ms。快速临时文本消除了“必须等 2 秒分离块”的硬等待，但没有做到零额外延迟。
- 实时长稳压 88 个处理块最慢 1689 ms，低于 1750 ms 步长；12 个独立冷进程样例最慢 1727 ms，
  只剩 23 ms 余量。当前 Mate 80 没有积压失败，但在更慢设备或 CPU 争用下风险较高。
- 常规增强峰值内存约 691～800 MiB；12 轮目标存在长稳压峰值 891 MiB；推理中 cancel 后立即开始
  下一 session 的峰值达到 933 MiB。均能回落，不是持续泄漏，但瞬时资源成本高。

因此当前建议保持为**显式可选能力**：只在多人同时讲话且目标人预计在场时开启；安静、单人、目标人
可能缺席或资源紧张时关闭。它可以保留 C1/C2/C3 这类重点内容，但还不能作为正式包的全局默认路径，
也不能对客户承诺“目标人不在时绝不输出别人”。

## 2. 测试环境与投入

- 设备：Huawei Mate 80，设备序列号 `7GK0226326015655`。
- 系统：HarmonyOS `6.1.0.135`。
- 分支基线：`codex/speaker-vad-enhancement-debug`，生产代码提交
  `838c1edc60bc37a3c2194430c5e6fb78e613c931`。
- 只构建并安装 `ZH_EN` HAP。
- 正式分离模型：`convtasnet_16k.ort`，SHA-256
  `921dc579ae7fdff42b5b53d6d3408c520121c6292d2c69d5d8dc92908b05ad13`，
  大小 `20,500,600 bytes`。
- 当前最终测试 HAP：SHA-256
  `fe1521c4a9b7c5b8d425676c847cfba11c6f0841542ffd221c21e727e14b9b1b`，
  大小 `359,851,370 bytes`。
- 有效测试共 30 次设备运行、128 个 SDK session/cycle；应用内测试时长约 28.5 分钟，资源采样
  观察约 32 分钟。

完整 artifact 保留在
[`delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806`](../../delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806)。
每次运行分别保存 `report.json`、`result.txt`、`memory.csv`、`hilog.txt`、输入映射和输入 PCM，失败
结果没有被后续运行覆盖。

## 3. 内容效果

### 3.1 固定客户 C1/C2/C3

当前正式 ORT 资产的首次三例回归：
[`20260806-234938`](../../delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806/20260806-234938-target-speaker-enhancement-34511c8f/report.json)。

| 用例 | 增强最终文本 | 结果 |
|---|---|---|
| C1 | 帮我查收明天的警单。然后准备明天去上海。 | 含上海、无你好 |
| C2 | 我准备明天去北京，我看明去北京的机票。你帮我定一下。准备据上海。 | 含上海、无你好；仍有识别错误 |
| C3 | 我准备去上海，你帮我准备一下飞机票多少钱。 | 含上海、无你好 |

随后又在同一进程按 C1→C2→C3 连续运行 12 个 session：三例各四次文本完全一致；共 12 start、
36 final、12 complete、0 error。每轮调用 `finish` 前 `isLast=0`，结束后一次 last、一次 complete，
native stream 全部归零。证据见
[`20260807-003625`](../../delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806/20260807-003625-target-speaker-enhancement-a5868483/report.json)。

### 3.2 新增 12 组目标人在场音频

测试音频包括 6 条 2～3 人重叠和 6 条交通背景音频；每条都使用对应的 3～5 秒目标人参考录音注册。
参考录音内容与测试音频不同，因此不存在把注册音频文本当答案的问题。

| 编号 | 普通 ASR | 增强 final | 对照判断 |
|---|---|---|---|
| 01 | 与此同时，欧美、澳等国众多华侨应征入股开阔。欧亚各战场同德意日法西斯浴血奋战。 | 与此同时，欧美、澳等国众多华侨应征入。欧亚各战场从德意日法西斯浴血奋战。 | 丢失部分内容 |
| 02 | 农业农村信息化十二五规划。 | 农业农村信息化十二五规划。 | 不变 |
| 03 | 木心灵日是当太太和天王位见时发生的一个罕见的天文现象。 | 木心凌日是当木星运行到太阳和天王星之间时发生的一种罕见的天文现象。 | 明显改善 |
| 04 | 一般可用雨伞遮住，或把相机装在塑料袋里。 | 一般遮住，或把相机扔在塑料袋里。 | 丢字、替换 |
| 05 | 目前市场上保卫更换芯片的智能手机不超过10款。 | 目前市场上搭载冰块芯片的智能手机不超过10款。 | 两边均有错，不能判优 |
| 06 | 来个新长征路上的摇滚。 | 来个新长征路上的摇滚。 | 不变 |
| 07 | 我当时有点昏头，想纠河边分手，他登个报纸，征婚也行，我连稿子都准备好了。 | 我当时有点昏头，想就和他分手算了，哪怕登个报纸征婚也行，我连稿子都准备好了。 | 明显改善 |
| 08 | 还要求具备大型赛会或日常从事社会志愿服务的经验。 | 还要求具备大型赛桂或日常从事社会志愿服务的经验。 | 一字替换 |
| 09 | 导致信号衰落的信道被称作衰落信道。 | 导致信号衰的信道被称作衰落信道。 | 丢一字 |
| 10 | 具体内容详见上海证券交易所网站。 | 券交易所网站。 | 严重截断 |
| 11 | 本价值的不确定，早上去机场。 | 岛上地机场。 | 严重截断 |
| 12 | 这不失为中国自主品牌车企实现追赶的一种好路径。 | 这不失为中国自主品牌车企实现追赶的一种好路径。 | 不变 |

普通 ASR 汇总证据见
[`20260806-235257`](../../delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806/20260806-235257-paced-db0c429a/report.json)；
增强的 12 个独立冷进程报告位于同一 artifact 根目录的 `20260806-235806` 至 `20260807-000403`。
历史 Android 多版本结果也支持 02、06、08、09、12 的普通文本具有较高稳定性，但该语料没有人工
逐字标注，不能从本表计算 CER 或宣称“2/12 提升率”。

### 3.3 目标人单独讲话

使用客户目标人的 far 录音注册，mid、near 两段独立录音做测试：

| 输入 | 普通 ASR | 增强 final | 首字变化 |
|---|---|---|---:|
| mid | 街道指令前方路口发生事故，请立即前往处置，注意观察，保持通讯畅通。 | 接到指令前方路口发生事故，请立即前往处置，注意观察，保持通讯畅通。 | +97 ms |
| near | 接到指令前方路口发生事故，请立即前往处置，注意观察，保持通讯。 | 接到指令前方路口发生事故，请立即前往处置，注意观察，保持通讯。 | -7 ms |

两条没有内容退化，但样本量只有一个人、两段录音。普通/增强峰值内存分别约 382/759 MiB，设备平均
计算占用分别约 9.5%/15.7%。证据：
[`普通`](../../delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806/20260807-002758-paced-ba287b64/report.json)、
[`增强`](../../delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806/20260807-002830-target-speaker-enhancement-6031a06f/report.json)。

## 4. 目标人缺席安全性

### 4.1 其他人单独讲话

固定注册 C1 目标声纹，输入 12 条其他人的单人录音。12/12 增强 final 为空；12 次正常 session 均
恰好一次 last、一次 complete、0 error。130 秒观察内峰值 RSS 760 MiB，RSS 和线程均无增长。

证据：
[`20260807-000535`](../../delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806/20260807-000535-target-speaker-enhancement-fd19a329/report.json)。

### 4.2 其他人的多人重叠或交通噪声

保持同一个错误注册声纹，输入 12 条主测试音频。9 条为空，3 条错误输出正式文本：

| 输入 | 错误 final |
|---|---|
| 02 两人重叠 | 素卫电视的转换及。 |
| 03 两人重叠 | 而后陆。 |
| 10 交通背景 | 食肉模糊与生活。 |

证据：
[`20260807-000828`](../../delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806/20260807-000828-target-speaker-enhancement-1c0237fd/report.json)。

三条分别再运行两次，6/6 输出完全相同，排除了一次性调度抖动：
[`20260807-001215`](../../delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806/20260807-001215-target-speaker-enhancement-5113a807/report.json)。

逐块诊断显示，第一层分离后选流门槛为 0.25，误放行块的最高相似度分别约为 0.397、0.382、0.319；
它们被当成目标音频送入第二层 Speaker VAD。默认 Speaker VAD 只要某个 1.5 秒窗口达到 0.35，便把
当前目标状态标记为“已出现”；最终整句评分配置为只记录分数，不再次拒绝。因此，一次错误确认足以让
分离伪影成为正式 final。

### 4.3 提高 Speaker VAD 门槛不能闭环

| `speakerVadThreshold` | 三条失败负例 | C1/C2/C3 正例 |
|---:|---|---|
| 0.35 默认 | 3/3 非空 | 3/3 内容门通过 |
| 0.45 | 1/3 非空；02 仍输出“规划。” | 3/3 内容门通过 |
| 0.50 | 1/3 非空；同一 02 | 未重复正例 |
| 0.60 | 1/3 非空；同一 02 | 未重复正例 |

02 剩余 final 没有 `speakerSimilarity`，说明它短到无法做严格整句评分，却仍在 Speaker VAD 曾确认目标
后公开。有效报告：
[`0.45`](../../delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806/20260807-002114-target-speaker-enhancement-3e3aad8a/report.json)、
[`0.50`](../../delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806/20260807-002326-target-speaker-enhancement-ac8c5cc8/report.json)、
[`0.60`](../../delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806/20260807-002449-target-speaker-enhancement-a62642ae/report.json)、
[`0.45 正例`](../../delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806/20260807-002555-target-speaker-enhancement-fb6d2c25/report.json)。

第一次 0.45 试验因测试载体把小数错误向下取整为 0 而作废，对应 `20260807-001839` artifact 只保留
排查记录，不进入任何结论。载体已改成保留小数，并补单测。

## 5. 延迟、计算与内存

### 5.1 首个临时文本

12 条目标人在场配对测试从第一帧 `writeAudio` 前计时，到第一个非空临时文本：

| 指标 | 普通 ASR | 增强快速临时文本 | 增量 |
|---|---:|---:|---:|
| 中位数 | 3020 ms | 3237 ms | 194 ms |
| 平均值 | 3130 ms | 3429 ms | 299 ms |
| 最差样例 | 5953 ms | 6791 ms | 838 ms |

这些绝对值包含音频自身起音和 ASR 出字条件，所以应以同文件增量理解。C1/C2/C3 旧 A/B 的增量中位数
为 85 ms；新增语料表明它不是普遍上限。

### 5.2 实时处理

| 场景 | 处理块 | 最慢块 | P95 | 最大排队 | 结论 |
|---|---:|---:|---:|---:|---|
| C1/C2/C3 当前正式基线 | 22 | 1706 ms | 1636 ms | 2 | 低于 1750 ms |
| 12 个独立冷进程目标在场样例 | 54 | 1727 ms | — | 1～2 | 最差只余 23 ms |
| C1/C2/C3 连续 12 session | 88 | 1689 ms | 1665 ms | 2 | 328 秒无累积 |
| 约 2 倍实时写入 | 22 | 1675 ms | 1666 ms | 2 | finish 正确等待 |
| 一次性突发写入 | 22 | 2299 ms | 1984 ms | 7 | 有积压，但结果完整 |

连续 12 session 的设备平均计算占用约 17.6%，P95 约 30.3%，峰值约 35.4%。这些是 12 核整机容量
占比；换成单核等价值，平均约 212%。当前只证明本台 Mate 80，不能外推到 8 GB 或中端设备。

### 5.3 内存与取消峰值

- 12 个独立冷进程目标在场样例：峰值约 691～773 MiB。
- C1/C2/C3 连续 12 session：峰值 891 MiB；RSS 三段中位数约 773/781/773 MiB，头尾变化
  `-13.4 MiB`，线程 `-1`，没有逐轮泄漏。
- 一次性突发：峰值 891 MiB。
- 推理中 cancel 后立即恢复：峰值 933 MiB；结束后回落，线程变化 `+1`，仍通过现有资源门。

取消不会等待已经开始的原生任务停止；旧任务完成后结果会被丢弃。下一 session 可以立即开始，但旧任务
和新任务的中间张量可能短时重叠，这是 cancel 场景峰值更高的最可能解释。

## 6. SDK 生命周期结果

| 模式 | 轮数 | 结果 |
|---|---:|---|
| 快速临时文本回调内同步 `writeAudio + finish` | 6 | 6/6 PASS |
| `onStart` 内 continue / finish / cancel | 9 | 9/9 PASS |
| 推理中 cancel，立即启动恢复 session | 6 | 6/6 PASS |
| 首次加载 / 同进程复用 / `unloadModel` / `unloadRuntime` | 4 | 4/4 PASS |
| C1/C2/C3 实时长稳压 | 12 | 12/12 PASS |
| 2 倍实时与突发写入 | 6 | 6/6 PASS |

重载的 `startListening` 到 `onStart`：首次加载 1084 ms、同进程复用 727 ms、模型卸载后重载
1301 ms、Runtime 卸载后重载 1296 ms。所有正常 session 均在 `finish` 前没有 `isLast`，结束后一次
last、一次 complete；cancel 路径不产生 final/complete；结束后 native stream 为 0。

证据：
[`回调重入`](../../delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806/20260807-002938-target-speaker-preview-reentrant-5c3ece4d/report.json)、
[`onStart`](../../delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806/20260807-003014-target-speaker-enhancement-onstart-28a612f1/report.json)、
[`cancel 恢复`](../../delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806/20260807-003054-target-speaker-enhancement-cancel-4999707d/report.json)、
[`卸载重载`](../../delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806/20260807-003226-target-speaker-enhancement-reload-47fcd2b8/report.json)、
[`2 倍实时`](../../delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806/20260807-003348-target-speaker-enhancement-e5ce51bd/report.json)、
[`突发`](../../delivery/harmony-dingqiao/build/device-stress/speaker-vad-enhance-eval-20260806/20260807-003502-target-speaker-enhancement-f8dfa833/report.json)。

## 7. 已确认问题与建议

### P0：目标人缺席的多人/噪声场景会稳定误放行

现状是 3/12 样例非空，失败样例重复 6/6。正式对外说明必须明确：该接口不是身份安全边界，不能用来
保证“只记录注册警员”。

短期使用约束：只有业务已经知道目标人在场、且多人同时讲话价值足够高时才开启；不能因为界面临时文本
看起来合理就把它当最终身份结论。

代码修复方向：在公开非空 final 前增加真正的最终确认。短 final 没有分数时必须抑制，而不是继承此前
“目标已出现”的状态；有分数时也需要独立于 score-only 的正式拒绝规则。修复必须同时保护 C1/C2/C3、
目标单人、目标缺席单人和目标缺席混合，不能只在三条失败样例上调阈值。

### P1：增强会损伤本来已经可识别的音频

10、11 严重截断，其他多条也有丢字或替换。Conv-TasNet 是双人盲分离，交通噪声和三人输入都不是它的
强项。因此增强不能作为普通 ASR 的全局前置处理，现有显式开关必须保留。

### P1：实时余量和瞬时内存偏紧

独立冷进程最慢块 1727 ms，只比 1750 ms 步长少 23 ms；cancel 恢复峰值约 933 MiB。当前设备通过，
但商用支持范围不能扩大到未测设备。下一轮应至少增加目标中端机、后台 CPU 争用和 8 GB 设备；如果这些
设备失败，应按机型能力关闭增强，而不是放宽实时门。

### P2：快速临时文本仍有可见额外延迟

12 条配对中位数 +194 ms、最差 +838 ms。界面已不再等待首个 2 秒分离块，但“两条 ASR stream +
增强队列”的额外调度仍会影响首字。产品文案应写成“降低增强首字等待”，不要写成“与普通 ASR 零差异”。

## 8. 当前未覆盖范围

- 没有人工逐字标注，新增 12 条不能计算正式 CER/WER。
- 没有通过扬声器到手机麦克风重新采集；本轮是真机 SDK 公共 API 回放真实 WAV，不包含声学回放链路。
- 没有测试 8 GB、中端或低端 Harmony 设备，也没有后台高负载/温控降频。
- 没有覆盖三人及以上的正确逐人文字归属；文件名标记的三人样例只能观察输出，不能把双路模型写成支持
  三人分离。
- 12 个目标缺席身份和 12 个混合样例不足以估计正式误接受率，只能证明当前存在可复现问题。

## 9. 测试载体改动

为避免把 C1/C2/C3 的“上海/你好”断言错误套用到探索语料，设备测试脚本新增：

- `--skip-target-content-check`：只跳过 C1/C2/C3 特定文字门，生命周期、双流归属、实时积压和资源门仍
  全部执行；
- `--speaker-vad-threshold`：通过真实公共参数覆盖 Speaker VAD 门槛，并在报告中记录实际请求值；
- Harmony ability 使用保留小数的参数解析，避免 `0.45` 被向下取整为 `0`。

这些改动只属于 demo/测试载体，不修改 SDK 的生产默认值或公共会话状态机。
